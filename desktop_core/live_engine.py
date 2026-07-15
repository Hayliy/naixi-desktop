"""虚拟主播引擎 — 完整直播管道
架构：danmaku → scene → tts → avatar → stream (5 Agent asyncio.Queue 串联)
"""

import asyncio, hashlib, hmac, json, logging, os, re, subprocess, tempfile, time
from datetime import datetime
from typing import Optional

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
        self._rtmp_url = ""
        self._game_id = ""
        self._bili_config_saved = False

        # B站连接
        self._connected = False
        self._ws = None
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
            "last_error": self._last_error,
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
                self._room_id = cfg.get("room_id", "")
                self._rtmp_url = cfg.get("rtmp_url", "")
                self._bili_config_saved = bool(self._access_key_id and self._access_key_secret)
        except: pass

    def save_config(self, **kwargs) -> bool:
        """保存直播配置到 SQLite"""
        try:
            cfg = {
                "access_key_id": kwargs.get("access_key_id", self._access_key_id),
                "access_key_secret": kwargs.get("access_key_secret", self._access_key_secret),
                "app_id": kwargs.get("app_id", self._app_id),
                "room_id": kwargs.get("room_id", self._room_id),
                "rtmp_url": kwargs.get("rtmp_url", self._rtmp_url),
            }
            from desktop_core.storage import meta_set
            meta_set("live_config", json.dumps(cfg))
            self._access_key_id = cfg["access_key_id"]
            self._access_key_secret = cfg["access_key_secret"]
            self._app_id = cfg["app_id"]
            self._room_id = cfg["room_id"]
            self._rtmp_url = cfg["rtmp_url"]
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

        # 自动连接 B站
        ok = await self.connect_bilibili()
        if not ok:
            log.warning(f"[直播] B站 自动连接失败: {self._last_error}")

        log.info("[直播] 引擎已启动")
        return True

    async def stop(self):
        """停止所有 Agent 和连接"""
        self._running = False
        await self.disconnect_bilibili()
        await self._stop_ffmpeg()
        for aid in list(self._agent_tasks.keys()):
            t = self._agent_tasks.pop(aid, None)
            if t and not t.done():
                t.cancel()
                try: await t
                except: pass
            self._agent_status[aid] = "stopped"
        self._start_time = 0
        log.info("[直播] 引擎已停止")

    async def _start_agent(self, agent_id: str, coro_func):
        """启动一个 Agent 协程"""
        if agent_id in self._agent_tasks and not self._agent_tasks[agent_id].done():
            self._agent_tasks[agent_id].cancel()
        self._agent_status[agent_id] = "ready"
        task = asyncio.create_task(self._agent_wrapper(agent_id, coro_func()))
        self._agent_tasks[agent_id] = task

    async def _agent_wrapper(self, agent_id: str, coro):
        """Agent 包装器：捕获异常并更新状态"""
        self._agent_status[agent_id] = "running"
        try:
            await coro
        except asyncio.CancelledError:
            pass
        except Exception as e:
            err = f"[{agent_id}] {e}"
            self._agent_errors.append(err)
            self._last_error = err
            log.warning(f"[直播] Agent 异常: {err}")
        finally:
            if self._running:
                self._agent_status[agent_id] = "error"

    # ═══════════════════════════════════════════════════════════════════════
    # B站 连接 / 断开
    # ═══════════════════════════════════════════════════════════════════════

    def _sign_bili(self, params: dict) -> dict:
        """B站开放平台 HMAC-SHA256 签名"""
        params["timestamp"] = int(time.time())
        keys = sorted(params.keys())
        raw = "&".join(f"{k}={params[k]}" for k in keys)
        sig = hmac.new(
            self._access_key_secret.encode(),
            raw.encode(),
            hashlib.sha256
        ).hexdigest()
        params["signature"] = sig
        return params

    async def connect_bilibili(self) -> bool:
        """连接 B站 弹幕 WebSocket"""
        if self._connected:
            return True
        if not self._bili_config_saved:
            self._last_error = "B站 配置不完整"
            return False

        try:
            import aiohttp
            # 1. 调用 /v2/app/start 获取弹幕服务器地址
            params = self._sign_bili({
                "code": self._room_id or "",
                "app_id": self._app_id,
            })
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{OPEN_LIVE_API}/xlive/web-room/v1/index/getDanmuInfo", json=params, timeout=5) as r:
                    if r.status != 200:
                        self._last_error = f"B站 API 返回 {r.status}"
                        return False
                    data = await r.json()
                if data.get("code") != 0:
                    self._last_error = f"B站认证失败: {data.get('message', '')}"
                    return False
                ws_info = data["data"]
                self._game_id = ws_info.get("game_info", {}).get("game_id", "")
                auth_body_str = ws_info.get("websocket_info", {}).get("auth_body", "{}")
                wss_links = ws_info.get("websocket_info", {}).get("wss_link", [])

            # 2. 启动心跳
            self._hb_task = asyncio.create_task(self._heartbeat_loop())

            # 3. 连接 WS
            auth_body = json.loads(auth_body_str) if isinstance(auth_body_str, str) else auth_body_str
            for wss_url in wss_links:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(wss_url, heartbeat=30) as ws:
                        self._ws = ws
                        await ws.send_json(auth_body)
                        self._connected = True
                        log.info(f"[直播] 已连接到 B站 直播间")
                        async for msg in ws:
                            if not self._running:
                                break
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await self._on_bili_message(msg.data)
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                break
            return True
        except Exception as e:
            self._last_error = f"B站连接失败: {e}"
            log.warning(f"[直播] {self._last_error}")
            return False

    async def disconnect_bilibili(self):
        """断开 B站 连接"""
        self._connected = False
        if self._hb_task and not self._hb_task.done():
            self._hb_task.cancel()
            try: await self._hb_task
            except: pass
        self._hb_task = None
        if self._ws:
            try: await self._ws.close()
            except: pass
            self._ws = None
        self._game_id = ""
        log.info("[直播] 已断开 B站 连接")

    async def _heartbeat_loop(self):
        """B站 心跳（每 20s 调用 API）"""
        while self._running and self._game_id:
            try:
                import aiohttp
                params = self._sign_bili({"game_id": self._game_id})
                async with aiohttp.ClientSession() as session:
                    async with session.post(f"{OPEN_LIVE_API}/xlive/web-room/v1/index/heartbeat", json=params, timeout=5) as r:
                        if r.status != 200:
                            log.warning(f"[直播] 心跳失败: {r.status}")
            except Exception as e:
                log.warning(f"[直播] 心跳异常: {e}")
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def _on_bili_message(self, raw: str):
        """处理 B站 WebSocket 消息"""
        try:
            data = json.loads(raw)
            cmd = data.get("cmd", "")
            if cmd == "DANMU_MSG":
                info = data["info"]
                text = info[1]
                uid = info[2][0]
                uname = info[2][1]
                msg = {"type": "danmaku", "uid": uid, "user": uname, "text": text, "time": time.time()}
                self._cache_danmaku(uname, text)
                await self._danmaku_queue.put(msg)
        except Exception:
            pass

    def _cache_danmaku(self, user: str, text: str):
        self._danmaku_cache.append({"user": user, "text": text[:200], "time": time.time(), "time_str": _fmt_time(time.time())})
        if len(self._danmaku_cache) > MAX_DANMAKU:
            self._danmaku_cache = self._danmaku_cache[-MAX_DANMAKU:]

    # ═══════════════════════════════════════════════════════════════════════
    # Agent: 弹幕监听（由 connect_bilibili 的回调驱动）
    # ═══════════════════════════════════════════════════════════════════════

    async def _agent_danmaku(self):
        """弹幕 Agent — B站 WS 回调本身已驱动，此协程保持运行"""
        while self._running:
            await asyncio.sleep(1)

    # ═══════════════════════════════════════════════════════════════════════
    # Agent: 场景决策（LLM 或规则）
    # ═══════════════════════════════════════════════════════════════════════

    async def _agent_scene(self):
        """场景 Agent — 弹幕 → LLM/规则 决策 → 动作"""
        while self._running:
            try:
                msg = await asyncio.wait_for(self._danmaku_queue.get(), timeout=QUEUE_TIMEOUT)
            except asyncio.TimeoutError:
                continue

            if msg.get("type") != "danmaku":
                continue

            text = msg.get("text", "").strip()
            user = msg.get("user", "")
            if not text:
                continue

            # 规则分类 + LLM
            reply = await self._decide_reply(text, user)
            if reply:
                await self._scene_queue.put({"type": "speak", "text": reply, "emotion": "开心"})

    async def _decide_reply(self, text: str, user: str) -> Optional[str]:
        """弹幕 → 回复策略（规则 + 可选 LLM）"""
        text_lower = text.lower()
        # 规则匹配
        if any(kw in text for kw in ["你好", "hi", "hello", "在吗"]):
            return f"欢迎{user}来到直播间～"
        if any(kw in text for kw in ["谢谢", "感谢", "thx"]):
            return f"谢谢{user}的支持！"
        if any(kw in text for kw in ["?", "吗", "什么", "怎么", "为啥", "为什么"]):
            return f"{user}问了一个问题呢～{text}让奶昔想想..."
        if any(kw in text for kw in ["666", "哈哈", "笑死", "好活"]):
            return f"嘻嘻～{user}开心就好！"
        if any(kw in text for kw in ["主播", "奶昔", "老婆", "可爱"]):
            return f"呜…被{user}夸了，好害羞(｡>ω<｡)"
        # 默认
        return f"感谢{user}的弹幕～{text}"

    # ═══════════════════════════════════════════════════════════════════════
    # Agent: TTS 语音合成
    # ═══════════════════════════════════════════════════════════════════════

    async def _agent_tts(self):
        """TTS Agent — 文本 → 语音文件"""
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

            audio_path = await self._synthesize(text)
            if audio_path:
                self._audio_playlist.append(audio_path)
                await self._tts_queue.put({"type": "audio", "path": audio_path, "text": text, "emotion": action.get("emotion", "开心")})

    async def _synthesize(self, text: str) -> Optional[str]:
        """语音合成 — 优先 CosyVoice，降级 Edge-TTS"""
        tmp = os.path.join(tempfile.gettempdir(), f"live_tts_{int(time.time()*1000)}.mp3")
        try:
            # 尝试 CosyVoice (百炼)
            from aiohttp import ClientSession
            cosy_api = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2audio/cosyvoice"
            headers = {"Authorization": f"Bearer {os.environ.get('DASHSCOPE_API_KEY', '')}",
                       "Content-Type": "application/json"}
            body = {"model": "cosyvoice-v3-flash", "input": {"text": text[:300]},
                    "parameters": {"voice": os.environ.get("COSYVOICE_VOICE", "longfeifei_v3")}}
            async with ClientSession() as s:
                async with s.post(cosy_api, json=body, headers=headers, timeout=30) as r:
                    if r.status == 200:
                        result = await r.read()
                        with open(tmp, "wb") as f:
                            f.write(result)
                        return tmp
        except Exception:
            pass

        # 降级 Edge-TTS
        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
            await communicate.save(tmp)
            return tmp
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
                    "audio_path": action.get("path", ""),
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
            if audio_path and os.path.exists(audio_path):
                log.info(f"[推流] 推送语音 ({len(text)}字): {text[:30]}...")
                if self._rtmp_url:
                    await self._composite_and_push(audio_path, text)

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


# 全局单例
engine = LiveEngine()
