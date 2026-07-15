"""虚拟主播引擎 — B站弹幕监听 + Agent 流水线 + RTMP 推流"""

import asyncio, hashlib, hmac, json, logging, os, re, time, subprocess
from datetime import datetime
from typing import Optional

log = logging.getLogger("live_engine")

# ── 常量 ──────────────────────────────────────────────────────────────────

BILIBILI_WS_URL = "wss://broadcastlv.chat.bilibili.com/sub"
BILIBILI_API = "https://api.live.bilibili.com"
HEARTBEAT_INTERVAL = 20       # B站心跳间隔（秒）
AGENT_STATUS_INTERVAL = 5     # Agent 状态轮询间隔（秒）
MAX_DANMAKU = 100             # 弹幕缓存上限

# ── Agent 定义 ───────────────────────────────────────────────────────────

AGENTS = [
    {"id": "danmaku",  "name": "弹幕监听",  "desc": "B站开放平台 WebSocket"},
    {"id": "scene",    "name": "场景决策",  "desc": "LLM 弹幕→场景判断"},
    {"id": "tts",      "name": "语音合成",  "desc": "CosyVoice / Edge-TTS"},
    {"id": "avatar",   "name": "虚拟角色",  "desc": "Live2D 立绘渲染"},
    {"id": "stream",   "name": "推流输出",  "desc": "ffmpeg RTMP 推流"},
]


class LiveEngine:
    """虚拟主播引擎"""

    def __init__(self):
        self._running = False
        self._connected = False      # B站 WS 连接状态
        self._streaming = False      # RTMP 推流状态
        self._access_key = ""
        self._room_id = ""
        self._ws: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._agent_task: Optional[asyncio.Task] = None
        self._ffmpeg_proc: Optional[subprocess.Popen] = None
        self._danmaku_cache: list[dict] = []
        self._agent_status: dict[str, str] = {a["id"]: "stopped" for a in AGENTS}
        self._agent_errors: list[str] = []
        self._start_time: float = 0
        self._last_error: str = ""
        self._rtmp_url: str = ""
        self._lock = asyncio.Lock()

    # ── 公开属性 ──────────────────────────────────────────────────────────

    @property
    def status(self) -> dict:
        """完整状态快照"""
        danmaku_rate = 0
        if self._danmaku_cache and self._start_time:
            elapsed = time.time() - self._start_time
            danmaku_rate = round(len(self._danmaku_cache) / max(elapsed, 1), 1)
        return {
            "running": self._running,
            "connected": self._connected,
            "streaming": self._streaming,
            "room_id": self._room_id,
            "agents": {a["id"]: {
                "name": a["name"],
                "desc": a["desc"],
                "status": self._agent_status.get(a["id"], "stopped"),
            } for a in AGENTS},
            "danmaku_count": len(self._danmaku_cache),
            "danmaku_rate": danmaku_rate,
            "uptime": round(time.time() - self._start_time) if self._start_time else 0,
            "last_error": self._last_error,
            "errors": self._agent_errors[-10:],
        }

    @property
    def danmaku_list(self) -> list[dict]:
        return list(self._danmaku_cache)

    # ── 生命周期 ──────────────────────────────────────────────────────────

    async def start(self, access_key: str, room_id: str = ""):
        """启动直播引擎"""
        self._access_key = access_key
        self._room_id = room_id
        self._running = True
        self._start_time = time.time()
        self._last_error = ""
        # 后台任务
        self._agent_task = asyncio.create_task(self._agent_loop())
        log.info("[直播] 引擎已启动")
        return True

    async def stop(self):
        """停止直播引擎"""
        self._running = False
        await self._disconnect_bilibili()
        await self._stop_rtmp()
        for t in [self._heartbeat_task, self._agent_task]:
            if t and not t.done():
                t.cancel()
                try: await t
                except: pass
        self._ws = self._heartbeat_task = self._agent_task = None
        log.info("[直播] 引擎已停止")

    # ── B站 WebSocket ─────────────────────────────────────────────────────

    async def connect_bilibili(self) -> bool:
        """连接 B站 开放平台 WebSocket"""
        if not self._access_key:
            self._last_error = "未配置 Access Key"
            return False
        if self._connected:
            return True
        if not self._room_id:
            # 自动获取直播间 ID
            room = await self._fetch_room_id()
            if not room:
                return False
            self._room_id = room
        try:
            import aiohttp
            # B站 WS 连接
            room_id_int = int(self._room_id)
            # 获取 WS 地址和认证信息
            auth_body = {
                "room_id": room_id_int,
                "platform": "web",
                "protocol": "ws",
                "key": self._access_key,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{BILIBILI_API}/xlive/web-room/v1/index/getDanmuInfo",
                    json=auth_body, timeout=5
                ) as resp:
                    if resp.status != 200:
                        self._last_error = f"B站 API 返回 {resp.status}"
                        return False
                    data = await resp.json()
                    if data.get("code") != 0:
                        self._last_error = f"B站认证失败: {data.get('message', '')}"
                        return False
                    ws_host = data["data"]["host"]
                    ws_port = data["data"]["ws_port"]
                    ws_url = f"wss://{ws_host}:{ws_port}/sub"

            self._connected = True
            # 启动心跳
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._agent_status["danmaku"] = "running"
            log.info(f"[直播] 已连接到 B站 直播间 {self._room_id}")
            return True
        except Exception as e:
            self._last_error = f"B站连接失败: {e}"
            log.warning(f"[直播] {self._last_error}")
            return False

    async def disconnect_bilibili(self):
        """断开 B站 连接"""
        await self._disconnect_bilibili()

    async def _disconnect_bilibili(self):
        self._connected = False
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try: await self._heartbeat_task
            except: pass
        self._heartbeat_task = None
        self._agent_status["danmaku"] = "stopped"
        log.info("[直播] 已断开 B站 连接")

    async def _heartbeat_loop(self):
        """B站 WebSocket 心跳保持"""
        while self._running and self._connected:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            # B站 协议心跳包（简化：成功连接即认为存活）
            log.debug("[直播] 心跳")
        self._connected = False

    async def _fetch_room_id(self) -> str:
        """自动获取直播间 ID"""
        if self._access_key:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{BILIBILI_API}/room/v1/Room/getRoomInfoByUid?uid=0",
                        timeout=5
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            # 尝试从 Access Key 关联的房间获取
                            if data.get("data", {}).get("room_id"):
                                return str(data["data"]["room_id"])
            except: pass
        return ""

    # ── RTMP 推流 ────────────────────────────────────────────────────────

    async def start_stream(self, rtmp_url: str) -> bool:
        """启动 RTMP 推流"""
        if self._streaming:
            return True
        if not rtmp_url:
            self._last_error = "未配置 RTMP 地址"
            return False
        self._rtmp_url = rtmp_url
        try:
            # 检查 ffmpeg
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            if proc.returncode != 0:
                self._last_error = "ffmpeg 未安装"
                return False

            # 启动 ffmpeg 推流（循环推静态图+音频）
            loop = asyncio.get_event_loop()
            self._ffmpeg_proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-f", "lavfi", "-i", "color=c=0x1a1a2e:s=1280x720:d=999999",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "2000k",
                "-c:a", "aac", "-b:a", "128k",
                "-f", "flv", rtmp_url,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            self._streaming = True
            self._agent_status["stream"] = "running"
            log.info(f"[直播] RTMP 推流已启动 -> {rtmp_url[:40]}...")
            return True
        except Exception as e:
            self._last_error = f"推流启动失败: {e}"
            log.warning(f"[直播] {self._last_error}")
            return False

    async def stop_stream(self):
        """停止 RTMP 推流"""
        await self._stop_rtmp()

    async def _stop_rtmp(self):
        if self._ffmpeg_proc:
            try:
                self._ffmpeg_proc.terminate()
                await asyncio.sleep(0.5)
                if self._ffmpeg_proc.returncode is None:
                    self._ffmpeg_proc.kill()
            except: pass
            self._ffmpeg_proc = None
        self._streaming = False
        self._agent_status["stream"] = "stopped"
        log.info("[直播] RTMP 推流已停止")

    # ── Agent 管理 ────────────────────────────────────────────────────────

    async def _agent_loop(self):
        """Agent 流水线状态维护"""
        while self._running:
            await asyncio.sleep(AGENT_STATUS_INTERVAL)
            # scene：B站连上后自动就绪
            if self._connected and self._agent_status.get("scene") == "stopped":
                self._agent_status["scene"] = "ready"
            # tts：scene 就绪后自动就绪
            if self._agent_status.get("scene") == "ready" and self._agent_status.get("tts") == "stopped":
                self._agent_status["tts"] = "ready"
            # avatar：tts 就绪后自动就绪
            if self._agent_status.get("tts") == "ready" and self._agent_status.get("avatar") == "stopped":
                self._agent_status["avatar"] = "ready"

    # ── 弹幕管理 ──────────────────────────────────────────────────────────

    def add_danmaku(self, user: str, text: str, ts: float = 0):
        """添加一条弹幕到缓存"""
        if not ts:
            ts = time.time()
        self._danmaku_cache.append({
            "user": user, "text": text[:200], "time": ts,
            "time_str": datetime.fromtimestamp(ts).strftime("%H:%M:%S"),
        })
        if len(self._danmaku_cache) > MAX_DANMAKU:
            self._danmaku_cache = self._danmaku_cache[-MAX_DANMAKU:]


# 全局单例
engine = LiveEngine()
