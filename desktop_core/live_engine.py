"""虚拟主播引擎 — 完整直播管道
架构：danmaku → scene → tts → avatar → stream (5 Agent asyncio.Queue 串联)
"""

import asyncio, hashlib, hmac, json, logging, os, re, subprocess, tempfile, time
from datetime import datetime
from typing import Optional
from aiohttp import WSMsgType

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
                self._bili_config_saved = bool(self._access_key_id and self._access_key_secret)
        except: pass

    def save_config(self, **kwargs) -> bool:
        """保存直播配置到 SQLite"""
        try:
            # 防止前端把遮罩后的密钥传回来覆盖真实密钥
            def _real(v, cur):
                if v is None or (isinstance(v, str) and "****" in v):
                    return cur
                return v
            cfg = {
                "access_key_id": _real(kwargs.get("access_key_id"), self._access_key_id),
                "access_key_secret": _real(kwargs.get("access_key_secret"), self._access_key_secret),
                "app_id": _real(kwargs.get("app_id"), self._app_id),
                "room_id": kwargs.get("room_id", self._room_id),
                "code": _real(kwargs.get("code"), self._code),
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
        except:
            pass

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
        import struct
        header_len = 16
        total_len = header_len + len(body)
        return struct.pack(">IHHII", total_len, header_len, ver, op, 1) + body

    async def _ws_read_loop(self, ws):
        """WS 消息读取循环（后台任务）"""
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
        """B站 心跳（每 20s 调 /v2/app/heartbeat）"""
        while self._running and self._game_id:
            await asyncio.sleep(20)
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
        """场景 Agent — 弹幕/礼物/进入 → LLM 决策 → 回复"""
        while self._running:
            try:
                msg = await asyncio.wait_for(self._danmaku_queue.get(), timeout=2)
            except asyncio.TimeoutError:
                continue

            msg_type = msg.get("type", "")
            user = msg.get("user", "")
            text = msg.get("text", "")

            # 礼物/上舰 → 立即感谢
            if msg_type in ("gift", "guard"):
                reply = f"感谢{user}的{'礼物' if msg_type=='gift' else '大航海'}！"
                await self._scene_queue.put({"type": "speak", "text": reply, "emotion": "开心"})
                continue

            # 进入直播间 → 欢迎
            if msg_type == "enter":
                await self._scene_queue.put({"type": "speak", "text": f"欢迎{user}进入直播间～", "emotion": "开心"})
                continue

            # 弹幕 → 规则+LLM
            if msg_type == "danmaku" and text:
                reply = await self._decide_reply(text, user)
                if reply:
                    await self._scene_queue.put({"type": "speak", "text": reply, "emotion": "开心"})

    async def _decide_reply(self, text: str, user: str) -> Optional[str]:
        """弹幕回复决策：规则匹配 + LLM 尝试"""
        t = text.lower()
        # 规则
        rules = [
            (lambda t: any(k in t for k in ["你好","hi","hello","在吗"]), f"欢迎{user}来到直播间～"),
            (lambda t: any(k in t for k in ["谢谢","感谢","thx"]), f"谢谢{user}的支持！"),
            (lambda t: any(k in t for k in ["666","哈哈","笑死","好活"]), f"嘻嘻～{user}开心就好！"),
            (lambda t: any(k in t for k in ["主播","奶昔","老婆","可爱"]), f"被{user}夸了，好害羞(｡>ω<｡)"),
            (lambda t: "?" in t or any(k in t for k in ["吗","什么","怎么","为啥","为什么"]), f"{user}让奶昔想想..."),
        ]
        for cond, reply in rules:
            if cond(t):
                return reply
        # 默认回复
        return f"感谢{user}的弹幕～{text[:40]}"

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
