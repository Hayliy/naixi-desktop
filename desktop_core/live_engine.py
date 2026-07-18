"""虚拟主播引擎 — 完整直播管道
架构：danmaku → scene → tts → avatar → stream (5 Agent asyncio.Queue 串联)
"""

import asyncio, hashlib, hmac, json, logging, os, re, subprocess, sys, tempfile, time
from datetime import datetime
from typing import Optional
from aiohttp import WSMsgType

DEFAULT_LIVE_PROMPT = """你是奶昔，一个虚拟主播。你正在B站直播，以下是你的设定：

性格：可爱、活泼、有点傲娇。语气自然口语化，像在和朋友聊天。
回复要求：简短（30字以内），偶尔带一点点语气词，不要说教或长篇大论。
互动规则：
- 观众发弹幕→根据内容自然回应
- 有人送礼物→感谢
- 有人进入直播间→简单欢迎
- 被问到敏感/不知道的问题→诚实说不知道，转移话题
- 保持直播氛围轻松愉快

注意：不要说"感谢xxx的弹幕"这种机械的回复，直接回应内容本身。"""

log = logging.getLogger("live_engine")

# ── 常量 ──────────────────────────────────────────────────────────────────

OPEN_LIVE_API = "https://api-live.bilibili.com"
HEARTBEAT_INTERVAL = 20       # B站心跳间隔（秒）
QUEUE_TIMEOUT = 2             # 队列等待超时（秒）
MAX_DANMAKU = 200             # 弹幕缓存上限
STREAM_WIDTH = 1280
STREAM_HEIGHT = 720
STREAM_FPS = 15
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
AVATARS_DIR = os.path.join(DATA_DIR, "avatars")

AGENT_DEFS = [
    {"id": "danmaku", "name": "弹幕监听",  "desc": "B站开放平台 WebSocket 弹幕接收"},
    {"id": "scene",   "name": "场景决策",  "desc": "LLM 弹幕→互动策略生成"},
    {"id": "tts",     "name": "语音合成",  "desc": "CosyVoice / Edge-TTS 语音生成"},
    {"id": "avatar",  "name": "虚拟角色",  "desc": "Live2D 立绘渲染与口型同步"},
    {"id": "stream",  "name": "推流输出",  "desc": "ffmpeg 音视频合成 RTMP 推流"},
]

# ── 工具函数 ──────────────────────────────────────────────────────────────

def _fmt_size(b):
    return f"{b/1024/1024:.1f}MB" if b >= 1048576 else f"{b/1024:.1f}KB" if b >= 1024 else f"{b}B"

def _fmt_time(ts):
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


class LiveEngine:
    """虚拟主播引擎 — 完整 5 Agent 管道"""

    def __init__(self):
        # 状态
        self._running = False
        self._start_time = 0.0
        self._access_key_id = ""
        self._access_key_secret = ""
        self._app_id = ""
        self._room_id = ""
        self._code = ""
        self._rtmp_url = ""
        self._game_id = ""
        self._dashscope_api_key = ""
        self._bili_config_saved = False

        # B站连接
        self._connected = False
        self._ws = None
        self._ws_session = None
        self._ws_task: Optional[asyncio.Task] = None
        self._hb_task: Optional[asyncio.Task] = None

        # Agent 状态: stopped/ready/running/error
        self._agent_status: dict[str, str] = {a["id"]: "stopped" for a in AGENT_DEFS}
        self._agent_tasks: dict[str, asyncio.Task] = {}
        self._agent_errors: list[str] = []

        # Agent 管道队列
        self._danmaku_queue: asyncio.Queue = asyncio.Queue()
        self._scene_queue: asyncio.Queue = asyncio.Queue()
        self._tts_queue: asyncio.Queue = asyncio.Queue()
        self._avatar_queue: asyncio.Queue = asyncio.Queue()

        # 数据
        self._danmaku_cache: list[dict] = []
        self._last_error = ""
        self._ffmpeg_proc: Optional[subprocess.Popen] = None
        self._current_text = ""
        self._current_emotion = "开心"
        self._audio_playlist: list[str] = []
        # VTube Studio 连接
        self._vts_ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._vts_authenticated: bool = False
        self._vts_host: str = "127.0.0.1"
        self._vts_port: int = 8001
        # 桌宠 WebSocket（前端 Live2D 窗口）
        self._live2d_ws: Optional[aiohttp.WebSocketResponse] = None
        # 桌宠子进程（PySide6 独立窗口）
        self._pet_proc: Optional[subprocess.Popen] = None
        # 场景历史（全部保留，过长时压缩）
        self._scene_history: list[dict] = []
        self._live_prompt: str = DEFAULT_LIVE_PROMPT
        # 高并发防护
        self._last_process_time: float = 0.0      # 上次处理弹幕时间
        self._process_interval: float = 2.0        # 最小处理间隔（秒）
        self._danmaku_batch: list[dict] = []       # 批量缓冲
        # LLM 聊天配置缓存
        self._chat_cfg: dict = {}
        self._chat_cfg_ts: float = 0
        # 音频设备
        self._audio_out_device: str = ""  # 输出设备名称（VB-Cable 或默认）
        self._audio_in_device: str = ""   # 输入设备名称
        self._sd_available: bool = False
        try:
            import sounddevice
            self._sd_available = True
        except:
            pass

    # ── 状态快照 ──────────────────────────────────────────────────────────

    @property
    def status(self) -> dict:
        elapsed = time.time() - self._start_time if self._start_time else 0
        danmaku_rate = round(len(self._danmaku_cache) / max(elapsed, 1), 1) if elapsed > 0 else 0
        return {
            "running": self._running,
            "connected": self._connected,
            "streaming": self._ffmpeg_proc is not None and self._ffmpeg_proc.returncode is None,
            "room_id": self._room_id,
            "game_id": self._game_id,
            "agents": {a["id"]: {"name": a["name"], "desc": a["desc"],
                       "status": self._agent_status.get(a["id"], "stopped")} for a in AGENT_DEFS},
            "danmaku_count": len(self._danmaku_cache),
            "danmaku_rate": danmaku_rate,
            "uptime": round(elapsed),
            "start_time": self._start_time,
            "last_error": self._last_error,
            "vts_connected": self._vts_ws is not None and not self._vts_ws.closed,
            "pet_running": self._pet_proc is not None and self._pet_proc.poll() is None,
            "errors": self._agent_errors[-10:],
        }

    @property
    def danmaku_list(self) -> list[dict]:
        return list(self._danmaku_cache)

    # ── 配置持久化 ────────────────────────────────────────────────────────

    def _load_config(self):
        """从 SQLite 加载直播配置"""
        try:
            from desktop_core.storage import meta_get
            raw = meta_get("live_config")
            if raw:
                cfg = json.loads(raw)
                self._access_key_id = cfg.get("access_key_id", "")
                self._access_key_secret = cfg.get("access_key_secret", "")
                self._app_id = cfg.get("app_id", "")
                self._code = cfg.get("code", "")
                self._room_id = cfg.get("room_id", "")
                self._rtmp_url = cfg.get("rtmp_url", "")
                self._dashscope_api_key = cfg.get("dashscope_api_key", "")
                self._live_prompt = cfg.get("live_prompt") or DEFAULT_LIVE_PROMPT
                self._audio_out_device = cfg.get("audio_out_device", "")
                self._audio_in_device = cfg.get("audio_in_device", "")
                self._bili_config_saved = bool(self._access_key_id and self._access_key_secret)
        except: pass

    def save_config(self, **kwargs) -> bool:
        """保存直播配置到 SQLite（自动合并旧配置，防止部分更新覆盖）"""
        try:
            # 先从 DB 加载已有配置作为基础
            base = {}
            try:
                from desktop_core.storage import meta_get
                raw = meta_get("live_config")
                if raw:
                    base = json.loads(raw)
            except:
                pass

            # 防止前端把遮罩后的密钥传回来覆盖真实密钥
            def _real(v, cur):
                if v is None or (isinstance(v, str) and "****" in v):
                    return cur
                return v

            cfg = {
                "access_key_id": _real(kwargs.get("access_key_id"), base.get("access_key_id", self._access_key_id)),
                "access_key_secret": _real(kwargs.get("access_key_secret"), base.get("access_key_secret", self._access_key_secret)),
                "app_id": _real(kwargs.get("app_id"), base.get("app_id", self._app_id)),
                "room_id": kwargs.get("room_id", base.get("room_id", self._room_id)),
                "code": _real(kwargs.get("code"), base.get("code", self._code)),
                "rtmp_url": kwargs.get("rtmp_url", base.get("rtmp_url", self._rtmp_url)),
                "dashscope_api_key": _real(kwargs.get("dashscope_api_key"), base.get("dashscope_api_key", self._dashscope_api_key)),
                "live_prompt": kwargs.get("live_prompt", base.get("live_prompt", self._live_prompt)),
                "audio_out_device": kwargs.get("audio_out_device", base.get("audio_out_device", self._audio_out_device)),
                "audio_in_device": kwargs.get("audio_in_device", base.get("audio_in_device", self._audio_in_device)),
            }
            from desktop_core.storage import meta_set
            meta_set("live_config", json.dumps(cfg))
            self._access_key_id = cfg["access_key_id"]
            self._access_key_secret = cfg["access_key_secret"]
            self._app_id = cfg["app_id"]
            self._room_id = cfg["room_id"]
            self._rtmp_url = cfg["rtmp_url"]
            self._dashscope_api_key = cfg["dashscope_api_key"]
            self._live_prompt = cfg["live_prompt"]
            self._audio_out_device = cfg.get("audio_out_device", "")
            self._audio_in_device = cfg.get("audio_in_device", "")
            self._bili_config_saved = bool(self._access_key_id and self._access_key_secret)
            log.info("[直播] 配置已保存")
            return True
        except Exception as e:
            self._last_error = f"配置保存失败: {e}"
            return False

    # ═══════════════════════════════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════════════════════════════

    def dict(self, **kwargs) -> bool:
        ...

    async def _close_old_session(self):
        """关闭上次残留的 B站 session（从数据库读取 game_id）"""
        try:
            from desktop_core.storage import meta_get
            old_id = meta_get("live_game_id")
            if not old_id or not self._access_key_id or not self._access_key_secret:
                return
            import aiohttp
            from uuid import uuid4
            end_body = json.dumps({"game_id": old_id, "app_id": int(self._app_id)}, separators=(",", ":"))
            md5 = self._bili_md5(end_body)
            ts, nonce = str(int(time.time())), uuid4().hex[:16]
            hdrs = {"Content-Type":"application/json","Accept":"application/json",
                "X-Bili-Timestamp":ts,"X-Bili-Signature-Method":"HMAC-SHA256",
                "X-Bili-Signature-Nonce":nonce,"X-Bili-Signature-Version":"1.0","X-Bili-AccessKeyId":self._access_key_id,
                "X-Bili-Content-MD5":md5}
            hdrs["Authorization"] = self._bili_sign(self._access_key_secret, hdrs, md5)
            async with aiohttp.ClientSession() as session:
                async with session.post("https://live-open.biliapi.com/v2/app/end", data=end_body, headers=hdrs, timeout=5) as r:
                    if r.status == 200:
                        log.info(f"[直播] 已关闭旧 session: {old_id[:16]}...")
            from desktop_core.storage import meta_set
            meta_set("live_game_id", "")
        except:
            pass

    async def start(self) -> bool:
        """启动直播引擎 — 配置加载 + Agent 启动 + 自动连接"""
        self._load_config()
        # 检查 B站 配置
        if not self._bili_config_saved:
            self._last_error = "B站 开放平台配置不完整（需 App ID + Token）"
            return False

        self._running = True
        self._start_time = time.time()
        self._last_error = ""
        self._agent_errors.clear()

        # 启动所有 Agent
        await self._start_agent("danmaku", self._agent_danmaku)
        await self._start_agent("scene", self._agent_scene)
        await self._start_agent("tts", self._agent_tts)
        await self._start_agent("avatar", self._agent_avatar)
        await self._start_agent("stream", self._agent_stream)

        # 尝试连接 VTube Studio（非阻塞，失败不影响直播）
        asyncio.create_task(self._vts_connect())

        # 先关闭上次残留的 session（防止"同一房间启动数量超过配置上限"）
        await self._close_old_session()

        # 自动连接 B站（失败则等 5 秒重试一次）
        for attempt in range(2):
            ok = await self.connect_bilibili()
            if ok:
                break
            if attempt == 0:
                log.info("[直播] 首次连接失败，等 5 秒重试...")
                await asyncio.sleep(5)
        if not ok:
            log.warning(f"[直播] B站 连接失败: {self._last_error}")

        log.info("[直播] 引擎已启动")
        return True

    async def stop(self):
        """停止所有 Agent 和连接，保存统计数据"""
        self._running = False
        await self.disconnect_bilibili()
        await self._vts_disconnect()
        self._stop_pet()
        await self._stop_ffmpeg()
        for aid in list(self._agent_tasks.keys()):
            t = self._agent_tasks.pop(aid, None)
            if t and not t.done():
                t.cancel()
                try: await t
                except: pass
            self._agent_status[aid] = "stopped"
        # 保存统计数据
        if self._start_time:
            self._save_stats()
        self._start_time = 0
        log.info("[直播] 引擎已停止")

    def _save_stats(self):
        """保存本次直播统计数据到 SQLite"""
        elapsed = time.time() - self._start_time
        try:
            from desktop_core.storage import meta_set
            stats = {
                "uptime": round(elapsed),
                "danmaku": len(self._danmaku_cache),
                "erros": len(self._agent_errors),
                "last_run": time.strftime("%Y-%m-%d %H:%M:%S"),
                "room_id": self._room_id,
            }
            from desktop_core.storage import meta_get
            old = meta_get("live_stats")
            if old:
                try:
                    import json
                    all_stats = json.loads(old)
                except: all_stats = []
            else:
                all_stats = []
            all_stats.append(stats)
            all_stats = all_stats[-30:]  # 保留最近 30 条
            meta_set("live_stats", json.dumps(all_stats))
            log.info(f"[直播] 统计数据已保存: {elapsed:.0f}s, {len(self._danmaku_cache)} 条弹幕")
        except Exception as e:
            log.warning(f"[直播] 统计保存失败: {e}")

    async def _start_agent(self, agent_id: str, coro_func):
        """启动一个 Agent 协程"""
        if agent_id in self._agent_tasks and not self._agent_tasks[agent_id].done():
            self._agent_tasks[agent_id].cancel()
        self._agent_status[agent_id] = "ready"
        task = asyncio.create_task(self._agent_wrapper(agent_id, coro_func()))
        self._agent_tasks[agent_id] = task

    async def _agent_wrapper(self, agent_id: str, coro):
        """Agent 包装器：捕获异常、自愈重启"""
        self._agent_status[agent_id] = "running"
        retries = 0
        while self._running and retries < 3:
            try:
                await coro
                break  # 正常退出
            except asyncio.CancelledError:
                break
            except Exception as e:
                retries += 1
                err = f"[{agent_id}] 异常(第{retries}次): {e}"
                self._agent_errors.append(err)
                self._last_error = err
                log.warning(f"[直播] {err}")
                if retries < 3:
                    await asyncio.sleep(retries * 3)
                    self._agent_status[agent_id] = "running"
                    # 重新创建协程
                    coro = self._restart_agent(agent_id)
                else:
                    self._agent_status[agent_id] = "error"
        if self._running and self._agent_status.get(agent_id) != "error":
            self._agent_status[agent_id] = "stopped"

    def _restart_agent(self, agent_id: str):
        """根据 agent_id 返回新的协程"""
        m = {"danmaku": self._agent_danmaku, "scene": self._agent_scene,
             "tts": self._agent_tts, "avatar": self._agent_avatar, "stream": self._agent_stream}
        return m.get(agent_id, self._agent_danmaku)()

    # ═══════════════════════════════════════════════════════════════════════
    # B站 Open Live API v2 连接（参考：github.com/VTB-LINK/bianka）
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _bili_md5(s: str) -> str:
        return hashlib.md5(s.encode()).hexdigest()

    @staticmethod
    def _bili_sign(secret: str, headers: dict, body_md5: str) -> str:
        """B站 Open Live API v2 签名
        X-Bili-* header 按小写 key 排序后 key:value\n 格式，HMAC-SHA256
        """
        # 构建小写 headers 映射
        lower_headers = {k.lower(): v for k, v in headers.items() if k.lower().startswith("x-bili-")}
        keys = sorted(lower_headers.keys())
        raw = "\n".join(f"{k}:{lower_headers[k]}" for k in keys)
        return hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()

    async def connect_bilibili(self) -> bool:
        """连接 B站 弹幕 WebSocket — Open Live API v2"""
        if self._connected:
            return True
        if not all([self._access_key_id, self._access_key_secret, self._app_id, self._code]):
            self._last_error = "B站 配置不完整（需 App ID + AccessKey ID + Secret + 主播身份码）"
            return False

        # 先关掉之前可能残留的 session
        await self._close_old_session()

        try:
            import aiohttp
            from uuid import uuid4

            api_host = "https://live-open.biliapi.com"
            body = json.dumps({"code": self._code, "app_id": int(self._app_id)}, separators=(",", ":"))
            body_md5 = self._bili_md5(body)
            ts = str(int(time.time()))
            nonce = uuid4().hex[:16]
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Bili-Timestamp": ts,
                "X-Bili-Signature-Method": "HMAC-SHA256",
                "X-Bili-Signature-Nonce": nonce,
                "X-Bili-Signature-Version": "1.0",
                "X-Bili-AccessKeyId": self._access_key_id,
                "X-Bili-Content-MD5": body_md5,
            }
            headers["Authorization"] = self._bili_sign(self._access_key_secret, headers, body_md5)

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{api_host}/v2/app/start", data=body, headers=headers, timeout=10) as r:
                    if r.status != 200:
                        txt = await r.text()
                        log.warning(f"[直播] B站 API {r.status}: {txt[:300]}")
                        self._last_error = f"B站 API {r.status}: {txt[:200]}"
                        return False
                    resp = await r.json()
                if resp.get("code") != 0:
                    msg = resp.get('message', '')
                    log.warning(f"[直播] B站 返回错误: code={resp.get('code')} msg={msg}")
                    self._last_error = f"B站 start 失败: {msg}"
                    # 如果 B站 说"超过配置上限"，等5秒清理旧 session 重试一次
                    if "超过配置上限" in msg:
                        log.info("[直播] 等待 5 秒后重试...")
                        await asyncio.sleep(5)
                        await self._close_old_session()
                        return False  # 让调用方可以检查 last_error 后重试
                    return False
                info = resp["data"]
                self._game_id = info["game_info"]["game_id"]
                # 保存 game_id 到数据库，下次启动时先关旧 session
                try:
                    from desktop_core.storage import meta_set
                    meta_set("live_game_id", self._game_id)
                except: pass
                auth_body_str = info["websocket_info"]["auth_body"]
                wss_links = info["websocket_info"]["wss_link"]

            # 心跳
            self._hb_task = asyncio.create_task(self._heartbeat_loop())

            # 连接 WS（B站二进制协议包: op=7认证, ver=0原始数据）
            auth_body = json.loads(auth_body_str) if isinstance(auth_body_str, str) else auth_body_str
            auth_str = json.dumps(auth_body, separators=(",", ":"))
            ws_session = aiohttp.ClientSession()
            try:
                wss_url = wss_links[0]
                ws = await ws_session.ws_connect(wss_url, heartbeat=30)
                self._ws = ws
                # 发送认证协议包（二进制, op=7, ver=0）
                await ws.send_bytes(self._build_ws_packet(7, auth_str.encode(), 0))
                self._connected = True
                self._ws_session = ws_session
                log.info(f"[直播] 已连接到 B站 直播间")
                self._ws_task = asyncio.create_task(self._ws_read_loop(ws))
            except:
                await ws_session.close()
                raise
            self._connected = True
            return True
        except Exception as e:
            self._last_error = f"B站连接失败: {e}"
            log.warning(f"[直播] {self._last_error}")
            return False

    async def _on_bili_json(self, raw: str):
        """处理 B站 WS JSON 消息（兼容新旧协议）"""
        try:
            data = json.loads(raw)
            cmd = data.get("cmd", "")
            is_v2 = cmd.startswith("LIVE_OPEN_PLATFORM_")

            if cmd in ("DANMU_MSG", "LIVE_OPEN_PLATFORM_DM"):
                if is_v2:
                    d = data.get("data", {})
                    txt, uid, uname = d.get("msg", ""), d.get("uid", 0), d.get("uname", "")
                else:
                    info = data["info"]
                    txt, uid, uname = info[1], info[2][0], info[2][1]
                self._cache_danmaku(uname, txt)
                await self._danmaku_queue.put({"type": "danmaku", "uid": uid, "user": uname, "text": txt, "time": time.time()})

            elif cmd in ("SEND_GIFT", "LIVE_OPEN_PLATFORM_SEND_GIFT"):
                d = data.get("data", data)
                uname = d.get("uname", "") or (data.get("data", {}) if is_v2 else {}).get("uname", "")
                gift = d.get("gift_name", "") or d.get("giftName", "")
                num = d.get("num", 1) or d.get("gift_num", 1)
                action = d.get("action", "赠送")
                if uname:
                    txt = f"{uname}{action}{gift}x{num}"
                    self._cache_danmaku(uname, f"[礼物]{gift}x{num}")
                    await self._danmaku_queue.put({"type": "gift", "user": uname, "text": txt, "gift": gift, "num": num, "time": time.time()})

            elif cmd in ("LIVE_OPEN_PLATFORM_GUARD", "GUARD_BUY"):
                d = data.get("data", data)
                uname = d.get("uname", "") or data.get("data", {}).get("uname", "")
                guard = d.get("guard_level", "") or d.get("gift_name", "")
                if uname:
                    txt = f"感谢{uname}上舰！"
                    await self._danmaku_queue.put({"type": "guard", "user": uname, "text": txt, "time": time.time()})

            elif cmd in ("INTERACT_WORD", "LIVE_OPEN_PLATFORM_LIVE_ROOM_ENTER"):
                d = data.get("data", data)
                uname = d.get("uname", "") or data.get("data", {}).get("uname", "")
                if uname:
                    await self._danmaku_queue.put({"type": "enter", "user": uname, "text": f"{uname}进入直播间", "time": time.time()})

            elif cmd in ("LIKE", "LIVE_OPEN_PLATFORM_LIKE"):
                d = data.get("data", data)
                uname = d.get("uname", "") or data.get("data", {}).get("uname", "")
                if uname:
                    await self._danmaku_queue.put({"type": "like", "user": uname, "text": f"{uname}点了赞", "time": time.time()})

            # 新增事件处理
            elif cmd in ("LIVE_OPEN_PLATFORM_SUPER_CHAT", "SUPER_CHAT"):
                # 醒目留言/SC
                d = data.get("data", data)
                uname = d.get("uname", "") or d.get("user", {}).get("uname", "")
                msg = d.get("message", "") or d.get("msg", "")
                rmb = d.get("rmb", 0) or d.get("price", 0)
                if uname:
                    txt = f"SC({rmb}元) {uname}: {msg}"
                    self._cache_danmaku(uname, f"[SC]{msg}")
                    await self._danmaku_queue.put({"type": "super_chat", "user": uname, "text": txt, "rmb": rmb, "time": time.time()})

            elif cmd == "LIVE_OPEN_PLATFORM_SUPER_CHAT_DEL":
                # SC 被删除
                log.info(f"[直播] SC 被删除: {data.get('data', {}).get('messageIds', '')}")

            elif cmd in ("LIVE_OPEN_PLATFORM_LIVE",):
                # 开播通知
                d = data.get("data", {})
                log.info(f"[直播] 直播已开始: room={d.get('roomId','')} title={d.get('title','')}")

            elif cmd in ("LIVE_OPEN_PLATFORM_LIVE_OFF",):
                # 下播通知
                d = data.get("data", {})
                log.info(f"[直播] 直播已结束: room={d.get('roomId','')}")

            elif cmd in ("LIVE_OPEN_PLATFORM_GAME_START",):
                # 场次开始
                d = data.get("data", {})
                log.info(f"[直播] 场次开始: game={d.get('gameId','')}")

            elif cmd in ("LIVE_OPEN_PLATFORM_GAME_END", "LIVE_OPEN_PLATFORM_INTERACTION_END"):
                # 场次结束 / 交互结束
                log.info(f"[直播] 场次/交互结束")

        except Exception as e:
            log.warning(f"[直播] 消息解析异常: {e}")

    async def _on_bili_binary(self, raw: bytes):
        """处理 B站 WS 二进制包"""
        try:
            if len(raw) < 16:
                return
            import struct, zlib
            
            # 可能一个 frame 包含多个包，循环解析
            offset = 0
            while offset + 16 <= len(raw):
                total_len = struct.unpack(">I", raw[offset:offset+4])[0]
                header_len = struct.unpack(">H", raw[offset+4:offset+6])[0]
                ver = struct.unpack(">H", raw[offset+6:offset+8])[0]
                op = struct.unpack(">I", raw[offset+8:offset+12])[0]
                
                if total_len < header_len or total_len > len(raw) - offset:
                    break
                
                body = raw[offset+header_len:offset+total_len]
                
                # 对 op=5（消息数据）或 op=8（认证回复）处理
                if op in (5, 8):
                    # 尝试解压
                    try:
                        body = zlib.decompress(body)
                    except:
                        pass
                    
                    text = body.decode("utf-8", errors="replace")
                    for line in text.split("\0"):
                        line = line.strip()
                        if line:
                            await self._on_bili_json(line)
                
                offset += total_len
        except:
            pass

    @staticmethod
    def _build_ws_packet(op: int, body: bytes, ver: int = 0) -> bytes:
        """构建 B站 WS 二进制协议包（官方文档: 大端对齐）
        ver=0 原始数据, ver=2 zlib压缩"""
        import struct
        header_len = 16
        total_len = header_len + len(body)
        return struct.pack(">IHHII", total_len, header_len, ver, op, 1) + body

    async def _ws_read_loop(self, ws):
        """WS 消息读取循环（后台任务），断开后自动重连"""
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    log.info(f"[直播] WS TEXT: {msg.data[:200]}")
                    await self._on_bili_json(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    log.info(f"[直播] WS BINARY: {len(msg.data)}B")
                    await self._on_bili_binary(msg.data)
                elif msg.type == WSMsgType.CLOSED:
                    break
        except Exception as e:
            log.warning(f"[直播] WS 读取异常: {e}")
        finally:
            self._connected = False
            log.info("[直播] WS 连接已断开")
            # 自动重连（引擎仍在运行）
            if self._running:
                log.info("[直播] 尝试自动重连...")
                asyncio.create_task(self._auto_reconnect())

    async def _auto_reconnect(self):
        """自动重连 B站，最多 3 次"""
        for i in range(3):
            await asyncio.sleep(5 * (i + 1))
            if not self._running or self._connected:
                return
            log.info(f"[直播] 重连第 {i+1} 次...")
            self._load_config()
            ok = await self.connect_bilibili()
            if ok:
                log.info("[直播] 重连成功")
                return
        log.warning("[直播] 自动重连失败")

    async def disconnect_bilibili(self):
        """断开 B站 连接"""
        self._connected = False
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try: await self._ws_task
            except: pass
        self._ws_task = None
        if self._hb_task and not self._hb_task.done():
            self._hb_task.cancel()
            try: await self._hb_task
            except: pass
        self._hb_task = None
        if self._ws:
            try: await self._ws.close()
            except: pass
            self._ws = None
        if self._ws_session:
            try: await self._ws_session.close()
            except: pass
            self._ws_session = None
        # 调用 /v2/app/end 关闭场次
        if self._game_id and self._app_id:
            try:
                import aiohttp
                from uuid import uuid4
                end_body = json.dumps({"game_id": self._game_id, "app_id": int(self._app_id)}, separators=(",", ":"))
                md5 = self._bili_md5(end_body)
                ts, nonce = str(int(time.time())), uuid4().hex[:16]
                hdrs = {"Content-Type":"application/json","Accept":"application/json",
                    "X-Bili-Timestamp":ts,"X-Bili-Signature-Method":"HMAC-SHA256",
                    "X-Bili-Signature-Nonce":nonce,"X-Bili-Signature-Version":"1.0","X-Bili-AccessKeyId":self._access_key_id,
                    "X-Bili-Content-MD5":md5}
                hdrs["Authorization"] = self._bili_sign(self._access_key_secret, hdrs, md5)
                async with aiohttp.ClientSession() as session:
                    await session.post("https://live-open.biliapi.com/v2/app/end", data=end_body, headers=hdrs, timeout=5)
            except: pass
        self._game_id = ""
        # 清理数据库中的 game_id
        try:
            from desktop_core.storage import meta_set
            meta_set("live_game_id", "")
        except: pass
        log.info("[直播] 已断开 B站 连接")

    async def _heartbeat_loop(self):
        """B站 心跳：HTTP 项目心跳(20s) + WS 协议心跳(30s)"""
        ws_hb_count = 0
        while self._running and self._game_id:
            await asyncio.sleep(20)

            # WS 协议心跳（op=2，每 30s 一次，但配合 20s 周期每 2 次发一次）
            ws_hb_count += 1
            if ws_hb_count % 2 == 1 and self._ws and not self._ws.closed:
                try:
                    await self._ws.send_bytes(self._build_ws_packet(2, b"", 0))
                except:
                    pass

            # HTTP 项目心跳（保持 game 存活）
            try:
                import aiohttp
                from uuid import uuid4
                hb = json.dumps({"game_id": self._game_id}, separators=(",", ":"))
                md5 = self._bili_md5(hb)
                ts, nonce = str(int(time.time())), uuid4().hex[:16]
                hdrs = {"Content-Type":"application/json","Accept":"application/json",
                    "X-Bili-Timestamp":ts,"X-Bili-Signature-Method":"HMAC-SHA256",
                    "X-Bili-Signature-Nonce":nonce,"X-Bili-Signature-Version":"1.0","X-Bili-AccessKeyId":self._access_key_id,
                    "X-Bili-Content-MD5":md5}
                hdrs["Authorization"] = self._bili_sign(self._access_key_secret, hdrs, md5)
                async with aiohttp.ClientSession() as session:
                    async with session.post("https://live-open.biliapi.com/v2/app/heartbeat", data=hb, headers=hdrs, timeout=5) as r:
                        if r.status != 200:
                            log.warning(f"[直播] 心跳失败: {r.status}")
            except Exception as e:
                log.warning(f"[直播] 心跳异常: {e}")

    def _cache_danmaku(self, user: str, text: str):
        self._danmaku_cache.append({"user": user, "text": text[:200], "time": time.time(), "time_str": _fmt_time(time.time())})
        if len(self._danmaku_cache) > MAX_DANMAKU:
            self._danmaku_cache = self._danmaku_cache[-MAX_DANMAKU:]

    # ── LLM 直播互动 ──────────────────────────────────────────────────────

    def _resolve_chat_config(self) -> dict:
        """获取聊天LLM配置（对话页的 chat 供应商）"""
        now = time.time()
        if self._chat_cfg and now - self._chat_cfg_ts < 60:
            return self._chat_cfg
        cfg = {"api_key": "", "api_url": "", "model": ""}
        try:
            from desktop_core.storage import meta_get, decrypt_config
            raw = meta_get("desktop_config")
            if raw:
                dc = json.loads(raw)
                decrypt_config(dc)
                for pid, pcfg in dc.get("api_providers", {}).items():
                    if pcfg.get("type", "chat") in ("chat", "default"):
                        cfg = {"api_key": pcfg.get("api_key", ""), "api_url": pcfg.get("api_url", ""), "model": pcfg.get("model", "")}
                        break
        except:
            pass
        self._chat_cfg = cfg
        self._chat_cfg_ts = now
        return cfg

    async def _call_llm(self, prompt: str) -> Optional[str]:
        """调用配置的聊天 LLM，返回回复文本"""
        cfg = self._resolve_chat_config()
        if not cfg["api_key"] or not cfg["api_url"]:
            return None
        try:
            from aiohttp import ClientSession
            import json as _json
            is_dashscope = "dashscope" in cfg["api_url"] or ("aliyuncs" in cfg["api_url"] and "compatible-mode" not in cfg["api_url"])
            messages = [{"role": "system", "content": self._live_prompt}]
            # 构造上下文：全部历史，超长时压缩
            ctx = list(self._scene_history)
            total_chars = sum(len(h.get("content","")) for h in ctx)
            if total_chars > 4000:
                # 压缩旧消息：保留最近 20 条，前面的合并为一段摘要
                recent = ctx[-20:]
                old = ctx[:-20]
                summary = "前面聊了: " + " | ".join(
                    h["content"].replace("的弹幕","").strip()[:60]
                    for h in old[-10:] if h["role"] == "user"
                )
                if len(summary) > 500:
                    summary = summary[:500] + "..."
                ctx = [{"role": "system", "content": f"[历史摘要] {summary}"}] + recent
            for h in ctx:
                messages.append({"role": h["role"], "content": h["content"]})
            messages.append({"role": "user", "content": prompt})

            if is_dashscope:
                url = cfg["api_url"].rstrip("chat/completions").rstrip("/") + "/chat/completions"
            else:
                url = cfg["api_url"].rstrip("/") + ("/chat/completions" if "/chat/completions" not in cfg["api_url"] else "")
            headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
            payload = {"model": cfg["model"] or "qwen-plus", "messages": messages,
                       "max_tokens": 100, "temperature": 0.8}

            async with ClientSession() as s:
                async with s.post(url, json=payload, headers=headers, timeout=10) as r:
                    if r.status != 200:
                        return None
                    data = await r.json()
                    reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if reply:
                        # 记录到上下文（不限量，_call_llm 内部会压缩）
                        self._scene_history.append({"role": "user", "content": prompt})
                        self._scene_history.append({"role": "assistant", "content": reply})
                        return reply.strip()
        except:
            pass
        return None

    # 动作标签 → Live2D motion 映射（通用）
    _ACTION_MOTION_MAP = {
        "wave": ("TapBody", 0), "bye": ("TapBody", 0),
        "nod": ("TapHead", 0), "think": ("TapHead", 0),
        "surprise": ("TapBody", 0), "shake": ("TapHead", 0),
        "kime": ("TapBody", 0), "sing": ("TapBody", 0),
        "angry": ("TapBody", 0), "cry": ("TapBody", 0),
        "smile": ("TapBody", 0), "sad": ("TapBody", 0),
    }
    _ACTION_NAMES = list(_ACTION_MOTION_MAP.keys())

    async def _decide_reply(self, text: str, user: str) -> tuple:
        """弹幕回复：LLM → 规则降级。返回 (回复文本, 情绪, 动作标签)"""
        llm_reply = await self._call_llm(
            f"[弹幕] {user}: {text[:100]}\n"
            "请用以下格式回复:\n"
            "[情绪] 回复内容 [动作标签]\n"
            "可用情绪: 开心、欢迎、惊讶、悲伤、害羞、生气、卖萌\n"
            f"可用动作标签: {' '.join(f'[{a}]' for a in self._ACTION_NAMES)}\n"
        )
        if llm_reply:
            return self._parse_reply(llm_reply)
        t = text.lower().strip()
        # (条件, 回复模板, 情绪, 动作)
        rules = [
            (lambda t: any(k in t for k in ["你好","hi","hello","在吗"]), f"欢迎{user}来到直播间～", "欢迎", "wave"),
            (lambda t: any(k in t for k in ["谢谢","感谢","thx"]), f"谢谢{user}的支持！", "开心", "smile"),
            (lambda t: any(k in t for k in ["666","哈哈","笑死","好活"]), f"嘻嘻～{user}开心就好！", "开心", "smile"),
            (lambda t: any(k in t for k in ["主播","奶昔","老婆","可爱"]), f"被{user}夸了，好害羞", "害羞", "wave"),
        ]
        for cond, reply, emotion, action in rules:
            if cond(t):
                return (reply, emotion, action)
        return (None, "开心", "")

    def _parse_reply(self, raw: str) -> tuple:
        """解析 LLM 回复中的情绪标记和动作标签。返回 (文本, 情绪, 动作)"""
        emotion = "开心"
        action = ""
        text = raw.strip()
        # 提取情绪 [情绪]
        if text.startswith("[") and "]" in text[:10]:
            bracket_end = text.index("]")
            emotion = text[1:bracket_end].strip()
            text = text[bracket_end+1:].strip()
        # 提取动作标签 [动作]（可能在末尾）
        import re
        for a in self._ACTION_NAMES:
            pat = re.compile(r'\[' + re.escape(a) + r'\]', re.IGNORECASE)
            m = pat.search(text)
            if m:
                action = a
                text = pat.sub('', text).strip()
                break
        valid_emo = {"开心","欢迎","惊讶","悲伤","害羞","生气","卖萌","无奈"}
        if emotion not in valid_emo:
            emotion = "开心"
        return (text, emotion, action)

    def _action_to_motion(self, action: str) -> tuple:
        """动作标签 → (motion_group, motion_index)"""
        return self._ACTION_MOTION_MAP.get(action, ("", -1))

    async def _agent_danmaku(self):
        """弹幕 Agent — B站 WS 回调本身已驱动，此协程保持运行"""
        while self._running:
            await asyncio.sleep(1)

    # ═══════════════════════════════════════════════════════════════════════
    # Agent: 场景决策（LLM 或规则）
    # ═══════════════════════════════════════════════════════════════════════

    async def _agent_scene(self):
        """场景 Agent — 弹幕/礼物/进入 → LLM → 回复（含高并发削峰）"""
        while self._running:
            try:
                msg = await asyncio.wait_for(self._danmaku_queue.get(), timeout=QUEUE_TIMEOUT)
            except asyncio.TimeoutError:
                # 超时：处理积压的批量缓冲
                if self._danmaku_batch:
                    await self._process_batch()
                continue

            msg_type = msg.get("type", "")

            # 高优：礼物/上舰/SC → 立即处理，不排队
            if msg_type in ("gift", "guard", "super_chat", "enter"):
                if msg_type in ("gift", "guard"):
                    reply = f"感谢{msg['user']}的{'礼物' if msg_type=='gift' else '大航海'}！"
                elif msg_type == "super_chat":
                    reply = f"感谢{msg['user']}的醒目留言！"
                else:
                    reply = f"欢迎{msg['user']}进入直播间～"
                emotion = "开心" if msg_type in ("gift", "guard") else "欢迎"
                action = "wave" if msg_type in ("gift", "guard") else "wave"
                await self._scene_queue.put({"type": "speak", "text": reply, "emotion": emotion, "action": action})
                continue

            # 弹幕：削峰 + 批量
            if msg_type != "danmaku" or not msg.get("text"):
                continue

            now = time.time()
            batch_window = 1.0  # 1 秒内的弹幕合并处理

            # 如果距离上次处理不足间隔，加入批量缓冲
            if now - self._last_process_time < self._process_interval:
                self._danmaku_batch.append(msg)
                if len(self._danmaku_batch) > 20:  # 缓冲上限，太多就丢最早的
                    self._danmaku_batch.pop(0)
                continue

            # 到了处理窗口：合并缓冲+当前弹幕
            batch = list(self._danmaku_batch)
            batch.append(msg)
            self._danmaku_batch.clear()
            self._last_process_time = now

            # 采样：弹幕太多时只取前 N 条 + 统计
            if len(batch) > 5:
                # 统计高频词
                from collections import Counter
                words = []
                for b in batch:
                    words.extend(b.get("text", "")[:20])
                top_words = Counter(words).most_common(3)
                # 取前 3 条代表性的 + 统计数据
                samples = batch[:3]
                summary = f"（共{len(batch)}条弹幕，高频词:{' '.join(w for w,_ in top_words)}）"
                prompt = summary + "\n".join(f"[弹幕] {b['user']}: {b['text'][:60]}" for b in samples)
            else:
                prompt = "\n".join(f"[弹幕] {b['user']}: {b['text'][:60]}" for b in batch)

                reply, emotion, action = await self._decide_reply(prompt, "")
                if reply:
                    await self._scene_queue.put({"type": "speak", "text": reply, "emotion": emotion, "action": action})

    async def _process_batch(self):
        """处理积压的批量缓冲"""
        batch = list(self._danmaku_batch)
        self._danmaku_batch.clear()
        if not batch:
            return
        samples = batch[:3]
        prompt = f"（共{len(batch)}条弹幕）\n" + "\n".join(f"[弹幕] {b['user']}: {b['text'][:60]}" for b in samples)
        reply, emotion, action = await self._decide_reply(prompt, "")
        if reply:
            await self._scene_queue.put({"type": "speak", "text": reply, "emotion": emotion, "action": action})

    # ── 音频设备管理（sounddevice + VB-Cable） ──────────────────────────

    def list_audio_devices(self) -> dict:
        """列出所有音频设备，标记输入/输出/VB-Cable"""
        result = {"outputs": [], "inputs": [], "vb_cable": None, "available": self._sd_available}
        if not self._sd_available:
            return result
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                info = {"index": i, "name": d["name"], "channels": d["max_output_channels"] if d["max_output_channels"] > 0 else d["max_input_channels"]}
                if "VB" in d["name"] or "Cable" in d["name"]:
                    result["vb_cable"] = info
                if d["max_output_channels"] > 0:
                    result["outputs"].append(info)
                if d["max_input_channels"] > 0:
                    result["inputs"].append(info)
        except:
            pass
        return result

    def _get_audio_devices(self) -> tuple:
        """获取实际使用的输出/输入设备ID"""
        out_id, in_id = None, None
        if not self._sd_available:
            return out_id, in_id
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            # 输出：仅当明确配置了输出设备才指定，否则用系统默认
            if self._audio_out_device:
                for i, d in enumerate(devices):
                    if self._audio_out_device in d["name"] and d["max_output_channels"] > 0:
                        out_id = i
                        break
            if out_id is None:
                out_id = sd.default.device[1]  # 系统默认输出
            # 输入：仅当明确配置了输入设备才指定，否则用系统默认
            if self._audio_in_device:
                for i, d in enumerate(devices):
                    if self._audio_in_device in d["name"] and d["max_input_channels"] > 0:
                        in_id = i
                        break
            if in_id is None:
                in_id = sd.default.device[0]  # 系统默认输入
        except:
            pass
        return out_id, in_id

    def play_audio(self, audio_bytes: bytes, sample_rate: int = 24000):
        """播放音频 bytes 到输出设备（用 ffmpeg 统一转 WAV）"""
        if not self._sd_available or not audio_bytes:
            return
        try:
            import sounddevice as sd
            import numpy as np
            import threading, io, wave, subprocess, tempfile, os

            # 写临时文件，用 ffmpeg 转成标准 WAV（支持任何输入格式）
            tmp_in = os.path.join(tempfile.gettempdir(), f"play_in_{int(time.time()*1000)}")
            tmp_out = os.path.join(tempfile.gettempdir(), f"play_out_{int(time.time()*1000)}.wav")
            with open(tmp_in, "wb") as f:
                f.write(audio_bytes)
            subprocess.run(
                ["ffmpeg", "-y", "-i", tmp_in, "-ar", "24000", "-ac", "1",
                 "-sample_fmt", "s16", "-f", "wav", tmp_out],
                capture_output=True, timeout=10
            )
            try: os.remove(tmp_in)
            except: pass

            if not os.path.exists(tmp_out):
                return

            with wave.open(tmp_out, 'rb') as wf:
                frames = wf.readframes(wf.getnframes())
                data = np.frombuffer(frames, dtype=np.int16)
                rate = wf.getframerate()
            try: os.remove(tmp_out)
            except: pass

            out_id, _ = self._get_audio_devices()
            if hasattr(self, '_play_thread') and self._play_thread and self._play_thread.is_alive():
                self._play_thread.join(timeout=3)
            self._play_thread = threading.Thread(
                target=lambda: (sd.wait(), sd.play(data, rate, device=out_id), sd.wait()),
                daemon=True
            )
            self._play_thread.start()
        except:
            pass

    # ── VTube Studio 控制（WebSocket API） ───────────────────────────────

    async def _vts_connect(self):
        """连接 VTube Studio WebSocket API"""
        if self._vts_ws and not self._vts_ws.closed:
            return True
        try:
            ws = await aiohttp.ClientSession().ws_connect(f"ws://{self._vts_host}:{self._vts_port}", heartbeat=10)
            self._vts_ws = ws
            # 认证
            auth_req = json.dumps({
                "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0",
                "messageType": "AuthenticationRequest",
                "data": {"pluginName": "奶昔直播", "pluginDeveloper": "Naixi", "authenticationToken": ""}
            })
            await ws.send_str(auth_req)
            resp = json.loads(await ws.receive_str())
            if resp.get("data", {}).get("authenticated"):
                self._vts_authenticated = True
                log.info("[VTS] 已连接并认证")
                return True
            log.info("[VTS] 已连接（未认证，需在 VTS 中点击确认）")
            return True
        except Exception as e:
            log.warning(f"[VTS] 连接失败: {e}")
            return False

    async def _vts_disconnect(self):
        """断开 VTube Studio 连接"""
        if self._vts_ws:
            try: await self._vts_ws.close()
            except: pass
            self._vts_ws = None
            self._vts_authenticated = False

    async def _vts_send_parameters(self, params: dict):
        """发送参数到 VTube Studio（如 MouthOpen, FaceAngleX 等）"""
        if not self._vts_ws or self._vts_ws.closed:
            return
        try:
            req = json.dumps({
                "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0",
                "messageType": "InjectParameterDataRequest",
                "data": {"parameterValues": [{"id": k, "value": v} for k, v in params.items()]}
            })
            await self._vts_ws.send_str(req)
        except:
            pass

    def _audio_to_mouth_data(self, audio_bytes: bytes, frame_ms: int = 80) -> list[float]:
        """分析音频 bytes 生成 MouthOpen 值序列（0.0~1.0）"""
        import numpy as np, io, wave
        try:
            with io.BytesIO(audio_bytes) as buf:
                with wave.open(buf, 'rb') as wf:
                    frames = wf.readframes(wf.getnframes())
                    data = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
                    rate = wf.getframerate()
            frame_size = int(rate * frame_ms / 1000)
            mouth_values = []
            for i in range(0, len(data), frame_size):
                chunk = data[i:i + frame_size]
                if len(chunk) == 0:
                    break
                rms = float(np.sqrt(np.mean(chunk ** 2)))
                # 映射到 0.0~1.0（阈值 500~8000）
                mouth = min(1.0, max(0.0, (rms - 500) / 8000))
                mouth_values.append(mouth)
            return mouth_values if mouth_values else [0.0]
        except:
            return [0.0]

    async def _vts_speak(self, audio_bytes: bytes, text: str = "", emotion: str = "", action: str = ""):
        """TTS 音频播放 + 口型同步（VTS + 桌宠双通道）"""
        mouth_data = self._audio_to_mouth_data(audio_bytes)
        if not mouth_data:
            return
        self.play_audio(audio_bytes)
        if self._live2d_ws and not self._live2d_ws.closed:
            try:
                await self._live2d_ws.send_json({
                    "type": "speak", "mouth": mouth_data,
                    "frame_ms": 80, "text": text, "emotion": emotion, "action": action,
                })
            except:
                pass
        # 逐帧发送口型参数到 VTube Studio（80ms/帧）
        frame_interval = 0.08
        for mouth in mouth_data:
            if not self._running:
                break
            await self._vts_send_parameters({"MouthOpen": mouth})
            await asyncio.sleep(frame_interval)

    # ═══════════════════════════════════════════════════════════════════════
    # Agent: TTS 语音合成
    # ═══════════════════════════════════════════════════════════════════════

    async def _agent_tts(self):
        """TTS Agent — 文本 → 语音合成 → 播放 + 推流"""
        while self._running:
            try:
                action = await asyncio.wait_for(self._scene_queue.get(), timeout=QUEUE_TIMEOUT)
            except asyncio.TimeoutError:
                continue

            if action.get("type") != "speak":
                continue

            text = action.get("text", "")
            if not text:
                continue

            audio_bytes = await self._synthesize(text)
            if audio_bytes:
                await self._vts_speak(audio_bytes, text, action.get("emotion", "开心"), action.get("action", ""))
                tmp = os.path.join(tempfile.gettempdir(), f"live_push_{int(time.time()*1000)}.wav")
                try:
                    with open(tmp, "wb") as f:
                        f.write(audio_bytes)
                except:
                    tmp = ""
                await self._tts_queue.put({
                    "type": "audio", "audio_path": tmp, "text": text,
                    "emotion": action.get("emotion", "开心")
                })

    def _resolve_tts_config(self) -> dict:
        """解析 TTS 配置（api_key/api_url/model），优先对话页audio供应商"""
        cfg = {"api_key": "", "api_url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2audio/cosyvoice", "model": "cosyvoice-v3-flash"}
        try:
            from desktop_core.storage import meta_get, decrypt_api_key
            raw = meta_get("desktop_config")
            if raw:
                dc = json.loads(raw)
                for pid, pcfg in dc.get("api_providers", {}).items():
                    if pcfg.get("type", "chat") == "audio":
                        raw_key = pcfg.get("api_key", "")
                        if raw_key.startswith("enc:"):
                            try:
                                cfg["api_key"] = decrypt_api_key(raw_key)
                            except:
                                cfg["api_key"] = raw_key
                        else:
                            cfg["api_key"] = raw_key
                        if pcfg.get("api_url"):
                            cfg["api_url"] = pcfg["api_url"]
                        if pcfg.get("model"):
                            cfg["model"] = pcfg["model"]
                        return cfg
        except:
            pass
        if not cfg["api_key"]:
            cfg["api_key"] = self._dashscope_api_key
        if not cfg["api_key"]:
            cfg["api_key"] = os.environ.get("DASHSCOPE_API_KEY", "")
        return cfg

    async def _cosyvoice_request(self, text: str, timeout: int = 30) -> Optional[bytes]:
        """调用 TTS，返回音频 bytes（内存流式，不存文件）"""
        tts = self._resolve_tts_config()
        if not tts["api_key"]:
            return None
        is_dashscope = "dashscope" in tts["api_url"] or "aliyuncs" in tts["api_url"]
        try:
            if is_dashscope:
                # 百炼 WebSocket 流式合成（返回完整音频字节，无临时文件）
                import dashscope
                from dashscope.audio.tts_v2 import SpeechSynthesizer
                dashscope.api_key = tts["api_key"]
                voice = os.environ.get("COSYVOICE_VOICE", "longfeifei_v3")
                # SpeechSynthesizer 是同步的，放线程池跑
                def _sync_synth():
                    synth = SpeechSynthesizer(model=tts["model"], voice=voice)
                    return synth.call(text)
                loop = asyncio.get_event_loop()
                audio = await loop.run_in_executor(None, _sync_synth)
                return audio if audio else None
            else:
                # OpenAI 兼容模式：HTTP 直接返回音频字节
                from aiohttp import ClientSession
                headers = {"Authorization": f"Bearer {tts['api_key']}", "Content-Type": "application/json"}
                url = tts["api_url"].rstrip("/") + "/audio/speech"
                payload = {"model": tts["model"], "input": text, "voice": "alloy", "response_format": "wav"}
                async with ClientSession() as s:
                    async with s.post(url, json=payload, headers=headers, timeout=timeout) as r:
                        if r.status == 200:
                            return await r.read()
        except:
            pass
        return None

    async def test_tts(self) -> str:
        """测试 TTS 配置是否可用"""
        tts = self._resolve_tts_config()
        if not tts["api_key"]:
            return "未配置 API Key"
        is_dashscope = "dashscope" in tts["api_url"] or "aliyuncs" in tts["api_url"]
        try:
            from aiohttp import ClientSession
            headers = {"Authorization": f"Bearer {tts['api_key']}", "Content-Type": "application/json"}
            if is_dashscope:
                url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
                payload = {"model": tts["model"], "input": {"text": "测试", "voice": "longfeifei_v3", "format": "wav", "sample_rate": 24000}}
            else:
                url = tts["api_url"].rstrip("/") + "/audio/speech"
                payload = {"model": tts["model"], "input": "测试", "voice": "alloy", "response_format": "wav"}
            async with ClientSession() as s:
                async with s.post(url, json=payload, headers=headers, timeout=10) as r:
                    if r.status == 200:
                        return ""
                    txt = (await r.text())[:100]
                    return f"API 返回 {r.status}: {txt}"
        except Exception as e:
            return f"请求失败: {e}"

    async def _synthesize(self, text: str) -> Optional[bytes]:
        """语音合成 — 对话页audio供应商 → 直播页配置 → Edge-TTS，返回音频 bytes"""
        # 尝试 CosyVoice（百炼 WebSocket 流式，直接返回 bytes）
        data = await self._cosyvoice_request(text)
        if data:
            return data
        # 降级 Edge-TTS（仍需临时文件，返回后清理）
        tmp = os.path.join(tempfile.gettempdir(), f"live_tts_{int(time.time()*1000)}.mp3")
        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
            await communicate.save(tmp)
            with open(tmp, "rb") as f:
                data = f.read()
            try: os.remove(tmp)
            except: pass
            return data
        except Exception:
            return None

    # ═══════════════════════════════════════════════════════════════════════
    # Agent: 虚拟角色（画面生成）
    # ═══════════════════════════════════════════════════════════════════════

    async def _agent_avatar(self):
        """形象 Agent — 文字+表情 → 画面帧元数据"""
        while self._running:
            try:
                action = await asyncio.wait_for(self._tts_queue.get(), timeout=QUEUE_TIMEOUT)
            except asyncio.TimeoutError:
                continue

            if action.get("type") == "audio":
                text = action.get("text", "")
                emotion = action.get("emotion", "开心")
                self._current_text = text
                self._current_emotion = emotion
                await self._avatar_queue.put({
                    "type": "frame_meta",
                    "text": text,
                    "emotion": emotion,
                })

    # ═══════════════════════════════════════════════════════════════════════
    # Agent: RTMP 推流
    # ═══════════════════════════════════════════════════════════════════════

    async def _agent_stream(self):
        """推流 Agent — 帧元数据 → ffmpeg 画面合成 → RTMP"""
        while self._running:
            try:
                meta = await asyncio.wait_for(self._avatar_queue.get(), timeout=QUEUE_TIMEOUT)
            except asyncio.TimeoutError:
                continue

            if meta.get("type") != "frame_meta":
                continue

            text = meta.get("text", "")
            audio_path = meta.get("audio_path", "")
            log.info(f"[推流] 推送语音 ({len(text)}字): {text[:30]}...")
            if self._rtmp_url and audio_path and os.path.exists(audio_path):
                await self._composite_and_push(audio_path, text)
                # 用完删除临时文件
                try: os.remove(audio_path)
                except: pass

    async def _composite_and_push(self, audio_path: str, text: str):
        """合成音视频并推流"""
        # 用 ffmpeg drawtext 叠上文字+背景推流
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=0x1a1a2e:s={STREAM_WIDTH}x{STREAM_HEIGHT}:r={STREAM_FPS}",
            "-i", audio_path,
            "-filter_complex",
            f"drawtext=text='{text[:60]}':fontcolor=white:fontsize=24:x=(w-text_w)/2:y=h-80:"
            f"box=1:boxcolor=black@0.4:boxborderw=8, "
            f"drawtext=text='奶昔直播 {_fmt_time(time.time())}':fontcolor=gray:fontsize=14:x=10:y=10",
            "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "2000k",
            "-c:a", "aac", "-b:a", "128k", "-shortest",
            "-f", "flv", self._rtmp_url,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            await asyncio.sleep(0.5)
            if proc.returncode is not None and proc.returncode != 0:
                log.warning(f"[推流] ffmpeg 异常退出: {proc.returncode}")
        except Exception as e:
            log.warning(f"[推流] 合成失败: {e}")

    async def start_stream(self, rtmp_url: str = "") -> bool:
        """启动持续推流（背景循环画面）"""
        if rtmp_url:
            self._rtmp_url = rtmp_url
            self.save_config(rtmp_url=rtmp_url)
        if not self._rtmp_url:
            self._last_error = "未配置 RTMP 地址"
            return False
        if self._ffmpeg_proc and self._ffmpeg_proc.returncode is None:
            return True
        try:
            self._ffmpeg_proc = subprocess.Popen(
                ["ffmpeg", "-y",
                 "-f", "lavfi", "-i", f"color=c=0x1a1a2e:s={STREAM_WIDTH}x{STREAM_HEIGHT}:r=5",
                 "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                 "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "1000k",
                 "-c:a", "aac", "-b:a", "64k", "-shortest",
                 "-f", "flv", self._rtmp_url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            log.info(f"[直播] 持续推流已启动")
            return True
        except FileNotFoundError:
            self._last_error = "ffmpeg 未安装"
            return False
        except Exception as e:
            self._last_error = f"推流启动失败: {e}"
            return False

    async def stop_stream(self):
        """停止推流"""
        await self._stop_ffmpeg()

    async def _stop_ffmpeg(self):
        if self._ffmpeg_proc:
            try:
                self._ffmpeg_proc.terminate()
                await asyncio.sleep(0.5)
                if self._ffmpeg_proc.returncode is None:
                    self._ffmpeg_proc.kill()
            except: pass
            self._ffmpeg_proc = None
            log.info("[直播] 推流已停止")

    def _start_pet(self, model_path: str = ""):
        """启动桌宠子进程（PySide6 独立窗口）"""
        if self._pet_proc and self._pet_proc.poll() is None:
            log.info("[桌宠] 已在运行")
            return True
        try:
            sidecar = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src-tauri", "sidecar")
            pet_script = os.path.join(sidecar, "pet_window.py")
            if not os.path.exists(pet_script):
                # 也可能是和桌面端代码放在一起
                pet_script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "desktop_core", "pet_window.py")
            args = [sys.executable, "-B", pet_script]
            if model_path:
                args.append(model_path)
            self._pet_proc = subprocess.Popen(args)
            log.info(f"[桌宠] 已启动: {' '.join(args[-2:])}")
            return True
        except Exception as e:
            log.warning(f"[桌宠] 启动失败: {e}")
            return False

    def _stop_pet(self):
        """停止桌宠子进程"""
        if self._pet_proc and self._pet_proc.poll() is None:
            try:
                self._pet_proc.terminate()
                self._pet_proc.wait(timeout=3)
            except:
                try: self._pet_proc.kill()
                except: pass
            self._pet_proc = None
            log.info("[桌宠] 已停止")


# 全局单例
engine = LiveEngine()
engine._load_config()  # 启动时从数据库加载配置
