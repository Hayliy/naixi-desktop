"""虚拟主播引擎 — 完整直播管道
架构：danmaku → scene → tts → avatar → stream (5 Agent asyncio.Queue 串联)
"""

import asyncio, hashlib, hmac, json, logging, os, re, subprocess, sys, tempfile, time
from datetime import datetime
from typing import Optional
import aiohttp
from aiohttp import WSMsgType

from desktop_core.live_bus import (
    LiveBus, SpeechArbiter, AgentConnector, NaixiConnector, HttpAgentConnector,
    WsAgentConnector, WsServerConnector, HumanConnector, ConnectorGuard,
    make_speech_request, normalize_utterance, should_react_to_cue,
    PRIORITY_HOST, PRIORITY_GUEST, MAX_CUE_DEPTH,
)

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
PCM_RATE = 44100             # 推流音频采样率（Hz）
PCM_CHANNELS = 1             # 推流音频声道数（单声道）
PCM_CHUNK_MS = 100           # 音频喂帧粒度（毫秒），用于实时节流
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
        self._ffmpeg_proc = None                       # 单常驻推流 ffmpeg（asyncio 子进程）
        self._stream_running = False                    # 常驻推流循环开关
        self._pcm_queue: asyncio.Queue = asyncio.Queue()  # 待播 PCM 段队列
        self._audio_pump_task: Optional[asyncio.Task] = None  # 实时喂音任务
        self._subtitle_file = ""                        # drawtext 字幕文件（reload=1 防注入）
        self._current_text = ""
        self._current_emotion = "开心"
        self._audio_playlist: list[str] = []
        # VTube Studio 多实例连接池（每个角色 = 一个 VTS 实例，端口 8001 + index）
        # 同框做法：VTS 单实例仅渲染一个模型，多模型同框须开多个 VTS 实例，
        # 每个实例监听独立端口（参照 Lumi_Nox 的 VTS_BASE_PORT + i 契约）。
        self._vts_instances: dict[int, "VtsInstance"] = {}
        self._vts_host: str = "127.0.0.1"
        self._vts_base_port: int = 8001     # 端口公式：实例 i 监听 8001 + i
        self._vts_by_model: dict[str, int] = {}   # modelID(GUID) -> instance_index（枚举后反查路由）
        self._vts_by_agent: dict[str, int] = {}   # agent_id -> instance_index（角色→实例）

        # 渲染后端适配器层（AvatarBackend）：agent_id -> kind（"vts"|"vmc"|"self"）
        # 默认 "vts"（存量 VTS 实例池即第1级后端，不平移不重写）；
        # "vmc" = VMC 协议(OSC/UDP, 39539+i) 驱动 VSeeFace/Warudo 等；
        # "self" = 自研 Live2D 渲染（前端 PetWindow/舞台，经桌宠 WebSocket）。
        self._backend_kinds: dict[str, str] = {}          # agent_id -> kind（持久化）
        self._backends: dict[str, object] = {}            # agent_id -> 非VTS后端实例

        # 层3 真人语音闭环（麦克风 ASR → 自动上麦）
        self._human_voice_task: Optional[asyncio.Task] = None   # 麦克风采集协程
        self._asr_model: str = "vosk-model-small-cn-0.22"    # 默认中文小模型（42MB，离线）
        self._asr_device: str = ""                            # 留空=系统默认输入设备
        self._asr_status: dict = {"enabled": False, "state": "idle",
                                 "model": "", "error": ""}     # 前端轮询的状态
        self._model_bindings: dict = {}     # agent_id -> modelID（持久化，重启后恢复绑定）
        # 桌宠 WebSocket（前端 Live2D 窗口）；_live2d_clients 支持多窗口（桌宠+舞台）同时在线
        self._live2d_ws: Optional[aiohttp.WebSocketResponse] = None
        self._live2d_clients: set = set()
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
        # 桌宠配置（前端 SettingsPet 读写）
        self._model_path: str = ""
        self._render_mode: str = "live2d"
        self._tts_engine: str = "cosyvoice"
        self._sd_available: bool = False
        try:
            import sounddevice
            self._sd_available = True
        except:
            pass

        # 多角色舞台：总线 + 麦位仲裁 + 角色连接器注册表（Lumi_Nox 多角色整合）
        self._bus = LiveBus()
        self._arbiter = SpeechArbiter()
        # 隔离状态持久化到 SQLite meta（按 agent_id 单行），重启/重连的刷屏 agent 仍在隔离期
        self._guard = ConnectorGuard(
            trusted_ids=("naixi", "human"),
            mem_get=self._guard_mem_get, mem_set=self._guard_mem_set,
        )
        self._connectors: dict[str, AgentConnector] = {}
        self._load_model_bindings()
        self._load_backend_kinds()
        self._register_builtin_connectors()

    @staticmethod
    def _guard_mem_get(key: str) -> str:
        """治理层隔离状态读取（默认落 SQLite meta；storage 不可用时静默降级为无持久化）。"""
        try:
            from desktop_core import storage
            return storage.meta_get(key, "")
        except Exception:
            return ""

    @staticmethod
    def _guard_mem_set(key: str, value: str):
        """治理层隔离状态写入（默认落 SQLite meta；storage 不可用时静默降级）。"""
        try:
            from desktop_core import storage
            storage.meta_set(key, value)
        except Exception:
            pass

    # ── 多角色连接器 ────────────────────────────────────────────────────────

    def _register_builtin_connectors(self):
        """注册内置角色：奶昔本体（主咖）+ 人类副播（操作员手动上麦的槽位）。"""
        naixi = NaixiConnector(self._decide_reply)
        human = HumanConnector("human", "人类副播")
        self._apply_model_binding(naixi)
        self._apply_model_binding(human)
        self._connectors["naixi"] = naixi
        self._connectors["human"] = human
        self._vts_by_agent["naixi"] = 0
        self._vts_by_agent["human"] = 1

    # ── 模型绑定持久化（按 VTS 模型 GUID 隔离，重启后恢复）──
    def _load_model_bindings(self):
        """从 SQLite meta 读取角色→模型绑定（live_model_bindings）。"""
        try:
            from desktop_core.storage import meta_get
            raw = meta_get("live_model_bindings", "")
            if raw:
                self._model_bindings = json.loads(raw) or {}
        except Exception:
            self._model_bindings = {}

    def _save_model_bindings(self):
        """把角色→模型绑定落库（live_model_bindings）。"""
        try:
            from desktop_core.storage import meta_set
            meta_set("live_model_bindings", json.dumps(self._model_bindings or {}))
        except Exception:
            pass

    def _apply_model_binding(self, connector: AgentConnector):
        """把持久化绑定应用到连接器（若该 agent_id 已存绑定）。"""
        mid = self._model_bindings.get(connector.agent_id)
        if mid:
            connector.model_id = mid

    # ── 渲染后端适配器层（AvatarBackend）─────────────────────────────────────

    def _load_backend_kinds(self):
        """从 SQLite meta 读取角色→渲染后端类型（live_backend_kinds）。"""
        try:
            from desktop_core.storage import meta_get
            raw = meta_get("live_backend_kinds", "")
            if raw:
                self._backend_kinds = json.loads(raw) or {}
        except Exception:
            self._backend_kinds = {}

    def _save_backend_kinds(self):
        try:
            from desktop_core.storage import meta_set
            meta_set("live_backend_kinds", json.dumps(self._backend_kinds or {}))
        except Exception:
            pass

    def set_agent_backend(self, agent_id: str, kind: str) -> dict:
        """设置某角色的渲染后端类型并持久化。kind: "vts"|"vmc"|"self"。

        非 VTS 后端即时构建实例（VMC 端口公式 39539 + vts实例索引，与 8001+i 同构）。
        """
        from desktop_core.avatar_backends import (
            ALL_KINDS, KIND_VTS, KIND_VMC, KIND_SELF, VmcBackend, SelfRenderBackend)
        if kind not in ALL_KINDS:
            return {"ok": False, "error": f"未知后端类型: {kind}（可选: {'/'.join(ALL_KINDS)}）"}
        self._backend_kinds[agent_id] = kind
        old = self._backends.pop(agent_id, None)
        if old is not None:
            try:
                asyncio.create_task(old.disconnect())
            except Exception:
                pass
        if kind == KIND_VMC:
            idx = self._vts_by_agent.get(agent_id, len(self._backends))
            be = VmcBackend(port=39539 + idx)
            self._backends[agent_id] = be
            asyncio.create_task(be.connect())
        elif kind == KIND_SELF:
            self._backends[agent_id] = SelfRenderBackend(lambda: self._live2d_ws, agent_id=agent_id,
                                                         clients_getter=lambda: self._live2d_clients)
        # KIND_VTS：走存量实例池，无需独立实例
        self._save_backend_kinds()
        log.info(f"[后端] {agent_id} 渲染后端 → {kind}")
        return {"ok": True, "agent_id": agent_id, "kind": kind}

    def _ensure_backend(self, agent_id: str):
        """按持久化的 kind 惰性构建后端实例（重启后恢复）。返回非VTS后端或 None。"""
        kind = self._backend_kinds.get(agent_id, "vts")
        if kind == "vts":
            return None
        be = self._backends.get(agent_id)
        if be is None:
            self.set_agent_backend(agent_id, kind)
            be = self._backends.get(agent_id)
        return be

    def _backend_for_model(self, model_id) -> object:
        """按 model_id 反查绑定角色的非VTS后端；查不到或角色用 VTS 时返回 None（走存量路径）。"""
        if not model_id:
            return None
        for aid, mid in self._model_bindings.items():
            if mid == model_id:
                return self._ensure_backend(aid)
        return None

    def backend_summary(self) -> dict:
        """各角色渲染后端状态快照（前端角色卡片用）。"""
        out = {}
        for aid in self._connectors:
            kind = self._backend_kinds.get(aid, "vts")
            be = self._backends.get(aid)
            out[aid] = be.describe() if be is not None else {"kind": kind, "connected": None}
        return out

    def register_connector(self, connector: AgentConnector) -> bool:
        """注册一个外部角色连接器（其他人的 agent 上台）。同名 agent_id 覆盖。

        注册前经治理层校验：远程连接器必须带 token（不可信面），否则拒绝上台。
        """
        if not getattr(connector, "agent_id", ""):
            return False
        ok_reg, reason = self._guard.check_register(connector)
        if not ok_reg:
            log.warning(f"[舞台] 注册被拒 {connector.name}({connector.agent_id}): {reason}")
            return False
        self._apply_model_binding(connector)
        if connector.agent_id not in self._vts_by_agent:
            self._vts_by_agent[connector.agent_id] = len(self._connectors)
        self._connectors[connector.agent_id] = connector
        # 角色上台即尝试连接其专属 VTS 实例（端口 8001 + index）
        try:
            asyncio.get_running_loop()
            asyncio.create_task(self._vts_connect_instance(self._vts_by_agent[connector.agent_id]))
        except RuntimeError:
            pass
        log.info(f"[舞台] 角色已上台: {connector.name}({connector.agent_id}) 优先级={connector.priority}"
                 f" 模型={connector.model_id or '当前模型'}")
        return True

    async def unregister_connector(self, agent_id: str) -> bool:
        """让一个外部角色下台。内置奶昔不可下台。"""
        if agent_id == "naixi":
            return False
        c = self._connectors.pop(agent_id, None)
        if c:
            try: await c.close()
            except: pass
            # 干净释放该角色占用的麦位：丢弃其排队请求，若正占麦则把麦位顺给下一等待者
            try:
                model_key = getattr(c, "model_id", None) or "__current__"
                await self._arbiter.evict(model_key, agent_id)
            except Exception as e:
                log.warning(f"[舞台] 下台时清理麦位失败: {e}")
            log.info(f"[舞台] 角色已下台: {agent_id}")
            return True
        return False

    def register_http_connector(self, agent_id: str, name: str, endpoint: str,
                                priority: int = PRIORITY_GUEST, token: str = "",
                                model_id: Optional[str] = None) -> bool:
        """便捷注册一个 HTTP 外部角色（QQ 机器人等）。供 API 调用。"""
        if not agent_id or not name or not endpoint:
            return False
        conn = HttpAgentConnector(agent_id, name, endpoint, priority=priority, token=token, model_id=model_id)
        if model_id:
            self._model_bindings[agent_id] = model_id
            self._save_model_bindings()
        return self.register_connector(conn)

    def register_ws_connector(self, agent_id: str, name: str, ws_url: str,
                              priority: int = PRIORITY_GUEST, token: str = "",
                              model_id: Optional[str] = None) -> bool:
        """便捷注册一个远程 ws 外部角色（常驻双向连接的远端 agent）。供 API 调用。"""
        if not agent_id or not name or not ws_url:
            return False
        conn = WsAgentConnector(agent_id, name, ws_url, priority=priority, token=token, model_id=model_id)
        if model_id:
            self._model_bindings[agent_id] = model_id
            self._save_model_bindings()
        return self.register_connector(conn)

    async def inject_human_speech(self, agent_id: str, text: str,
                                  emotion: str = "开心", action: str = "") -> bool:
        """人类副播上麦：把一个人工输入当作某人类连接器角色的发言，直接占麦。

        操作员在副播面板输入后调用。受信任，不受限流隔离。返回是否成功投放。
        """
        connector = self._connectors.get(agent_id)
        if not connector or not isinstance(connector, HumanConnector):
            return False
        text = (text or "").strip()
        if not text:
            return False
        utt = {"text": text, "emotion": emotion, "action": action}
        await self._emit(connector, utt, source_id=agent_id, cue_depth=0)
        return True

    # ── 层3 真人语音闭环（麦克风 ASR → 自动上麦） ─────────────────────────

    def _asr_model_dir(self) -> str:
        """语音识别模型本地目录（data/vosk_models/<模型名>）。"""
        return os.path.join(DATA_DIR, "vosk_models", self._asr_model)

    def human_voice_status(self) -> dict:
        """返回真人语音识别状态，供前端轮询展示（是否开启/模型是否就绪/报错）。"""
        st = dict(self._asr_status)
        st["model_ready"] = os.path.isdir(self._asr_model_dir())
        st["model"] = self._asr_model
        st["running"] = self._human_voice_task is not None and not self._human_voice_task.done()
        return st

    def _ensure_human_connector(self) -> bool:
        """确保"human"人类副播连接器存在（真人语音/手动上麦都依赖它）。不存在则自动注册。"""
        if "human" in self._connectors:
            return True
        try:
            human = HumanConnector()
            self.register_connector(human)
            log.info("[真人语音] 已自动注册人类副播连接器")
            return True
        except Exception as e:
            log.warning(f"[真人语音] 注册人类副播失败: {e}")
            return False

    async def start_human_voice(self, device: str = "") -> dict:
        """开启真人语音闭环：麦克风采集 → VAD → ASR 转文字 → 自动当 human_speak 上麦。

        依赖：vosk（已装）+ 中文模型（首次自动下载，需联网）。返回状态字典。
        device 留空=系统默认输入设备；也可传设备名/索引。
        """
        if self._human_voice_task is not None and not self._human_voice_task.done():
            return {"ok": False, "msg": "真人语音已在运行"}
        if device:
            self._asr_device = device
        # 确保人类副播连接器存在
        if not self._ensure_human_connector():
            self._asr_status = {"enabled": False, "state": "error",
                                "model": self._asr_model, "error": "人类副播注册失败"}
            return {"ok": False, "msg": "人类副播注册失败"}
        # 模型未就绪则先下载（用户已授权下载模型）
        model_dir = self._asr_model_dir()
        if not os.path.isdir(model_dir):
            self._asr_status = {"enabled": True, "state": "downloading",
                                "model": self._asr_model, "error": ""}
            try:
                await self._download_asr_model(self._asr_model)
            except Exception as e:
                self._asr_status = {"enabled": False, "state": "error",
                                    "model": self._asr_model, "error": f"模型下载失败: {e}"}
                return {"ok": False, "msg": f"模型下载失败: {e}"}
        self._asr_status = {"enabled": True, "state": "listening",
                            "model": self._asr_model, "error": ""}
        self._human_voice_task = asyncio.create_task(
            self._agent_human_voice(model_dir, self._asr_device))
        log.info("[真人语音] 已开启（模型=%s，设备=%s）" % (self._asr_model, self._asr_device or "默认"))
        return {"ok": True, "msg": "真人语音已开启"}

    async def stop_human_voice(self) -> dict:
        """关闭真人语音闭环，取消麦克风采集协程。"""
        if self._human_voice_task is None or self._human_voice_task.done():
            self._asr_status = {"enabled": False, "state": "idle",
                                "model": self._asr_model, "error": ""}
            return {"ok": True, "msg": "真人语音本就未运行"}
        self._human_voice_task.cancel()
        try:
            await self._human_voice_task
        except (asyncio.CancelledError, Exception):
            pass
        self._human_voice_task = None
        self._asr_status = {"enabled": False, "state": "idle",
                            "model": self._asr_model, "error": ""}
        log.info("[真人语音] 已关闭")
        return {"ok": True, "msg": "真人语音已关闭"}

    async def _download_asr_model(self, model_name: str):
        """下载并解压 vosk 语音识别模型到 data/vosk_models/（仅首次需要，用户已授权）。"""
        import urllib.request, zipfile
        base = os.path.join(DATA_DIR, "vosk_models")
        os.makedirs(base, exist_ok=True)
        url = f"https://alphacephei.com/vosk/models/{model_name}.zip"
        dst = os.path.join(base, f"{model_name}.zip")
        log.info(f"[真人语音] 下载语音模型 {model_name} ...")
        urllib.request.urlretrieve(url, dst)
        with zipfile.ZipFile(dst) as z:
            z.extractall(base)
        try:
            os.remove(dst)
        except Exception:
            pass
        log.info(f"[真人语音] 模型 {model_name} 已就绪")

    async def _agent_human_voice(self, model_dir: str, device: str):
        """麦克风采集 → VAD(端点检测) → vosk ASR → 转写文本自动上麦为人类副播发言。

        流式识别：vosk 的 KaldiRecognizer 自带端点检测，部分结果丢弃、最终结果才上麦，
        避免半句话打断。识别到的整句经 inject_human_speech 注入舞台，行为与手动输入一致
        （其它 agent 会接话、被点名模型会做被搭话反应）。
        """
        try:
            import sounddevice as sd
            from vosk import Model, KaldiRecognizer
        except Exception as e:
            self._asr_status = {"enabled": False, "state": "error",
                                "model": self._asr_model, "error": f"依赖缺失: {e}"}
            log.warning(f"[真人语音] ASR 依赖缺失: {e}")
            return
        try:
            model = Model(model_dir)
        except Exception as e:
            self._asr_status = {"enabled": False, "state": "error",
                                "model": self._asr_model, "error": f"模型加载失败: {e}"}
            log.warning(f"[真人语音] 模型加载失败: {e}")
            return

        # 解析输入设备（名称/索引），默认系统输入
        dev_idx = None
        if device:
            try:
                dev_idx = int(device)
            except ValueError:
                dev_idx = device  # 传名称

        sample_rate = 16000
        rec = KaldiRecognizer(model, sample_rate)
        rec.SetWords(False)
        # 捕获主线程事件循环，供 sounddevice 回调线程安全地把任务丢回
        loop = asyncio.get_running_loop()

        def _callback(indata, frames, time_info, status):
            if status:
                log.warning(f"[真人语音] 音频状态: {status}")
            try:
                data = bytes(indata)
                # 部分结果忽略；仅最终结果（句末）触发上麦
                if rec.AcceptWaveform(data):
                    res = json.loads(rec.Result())
                    text = (res.get("text") or "").strip()
                    if text:
                        log.info(f"[真人语音] 识别到: {text}")
                        # 跨线程安全地把任务丢回事件循环
                        asyncio.run_coroutine_threadsafe(
                            self.inject_human_speech("human", text, emotion="开心", action="wave"),
                            loop)
                else:
                    # 部分结果（可选）：可用于实时字幕，这里不处理
                    pass
            except Exception as e:
                log.warning(f"[真人语音] 识别异常: {e}")

        log.info("[真人语音] 开始监听麦克风（说话即可自动上麦）")
        try:
            with sd.RawInputStream(samplerate=sample_rate, blocksize=4000,
                                   device=dev_idx, dtype="int16",
                                   channels=1, callback=_callback):
                while True:
                    await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            log.info("[真人语音] 监听被取消")
        except Exception as e:
            self._asr_status = {"enabled": False, "state": "error",
                                "model": self._asr_model, "error": f"麦克风打开失败: {e}"}
            log.warning(f"[真人语音] 麦克风打开失败: {e}")
        finally:
            self._human_voice_task = None

    def list_connectors(self) -> list:
        """列出当前在台的角色（供前端/API 展示），含传输方式与治理状态。"""
        out = []
        for c in self._connectors.values():
            item = {"agent_id": c.agent_id, "name": c.name, "priority": c.priority,
                    "builtin": c.agent_id in ("naixi", "human"),
                    "transport": "ws-in" if isinstance(c, WsServerConnector)
                                 else "http" if isinstance(c, HttpAgentConnector)
                                 else "ws" if isinstance(c, WsAgentConnector)
                                 else "local",
                    "model_id": getattr(c, "model_id", None) or "",
                    "human_controlled": getattr(c, "human_controlled", False)}
            if getattr(c, "endpoint", ""):
                item["endpoint"] = c.endpoint
            g = self._guard.status(c.agent_id)
            item["quarantined"] = g["quarantined"]
            item["emits_in_window"] = g["emits_in_window"]
            out.append(item)
        return out

    def list_vts_models(self) -> dict:
        """返回所有 VTS 实例的模型清单与当前模型，供前端绑定下拉。
        多实例下 merged.models 为全部实例模型并集（modelID->name）；
        instances 给出每实例端口/当前模型/表情动作数量，并带 agent_id
        （角色→实例映射反查），便于前端按角色展示其 VTS 端口与当前模型。"""
        merged = {}
        for inst in self._vts_instances.values():
            merged.update(inst.models)
        # 反查 实例 index -> agent_id（角色→实例映射）
        agent_by_idx: dict[int, str] = {idx: aid for aid, idx in self._vts_by_agent.items()}
        return {
            "models": merged,
            "current": {idx: inst.current_model for idx, inst in self._vts_instances.items()},
            "instances": {
                idx: {"agent_id": agent_by_idx.get(idx, ""), "port": inst.port,
                      "authenticated": inst.authenticated,
                      "current_model": inst.current_model, "models": inst.models,
                      "expressions": len(inst.expressions), "motions": len(inst.motions)}
                for idx, inst in self._vts_instances.items()
            },
            # 渲染后端适配器层：agent_id -> {kind, connected, ...}（"vts"|"vmc"|"self"）
            "backends": self.backend_summary(),
        }

    async def bind_connector_model(self, agent_id: str, model_id: Optional[str]) -> bool:
        """把某角色绑定到指定 VTS 模型（model_id 为空串/None 表示用当前模型），持久化。

        真人独占模型：仅记录绑定用于冲突提示，奶昔不会写入该模型。
        """
        connector = self._connectors.get(agent_id)
        if not connector:
            return False
        mid = (model_id or "").strip() or None
        connector.model_id = mid
        if mid:
            self._model_bindings[agent_id] = mid
        else:
            self._model_bindings.pop(agent_id, None)
        self._save_model_bindings()
        log.info(f"[舞台] 角色 {agent_id} 绑定模型: {mid or '（当前模型）'}")
        # 绑定后确保该角色对应的 VTS 实例已连接（端口 8001 + index）
        idx = self._vts_by_agent.get(agent_id)
        if idx is not None:
            try:
                asyncio.get_running_loop()
                asyncio.create_task(self._vts_connect_instance(idx))
            except RuntimeError:
                pass
        return True

    async def _enqueue_speak(self, req: dict):
        """把仲裁通过的发言请求投入既有语音管道（_scene_queue），携带角色元数据。"""
        await self._scene_queue.put({
            "type": "speak",
            "text": req.get("text", ""),
            "emotion": req.get("emotion", "开心"),
            "action": req.get("action", ""),
            "agent_id": req.get("agent_id", "naixi"),
            "name": req.get("name", "奶昔"),
            "source_id": req.get("source_id", req.get("agent_id", "naixi")),
            "cue_depth": req.get("cue_depth", 0),
            "model_key": req.get("model_key", "__current__"),
            "human_controlled": req.get("human_controlled", False),
            "target_id": req.get("target_id", ""),  # 层1：这句话对着谁说
        })
        # 层2 肢体反馈：某模型开麦 → 台上其它模型做"倾听"姿态（不抢麦、不 TTS）
        try:
            await self._vts_ambient_to_others("listen", req.get("agent_id", ""))
        except Exception as e:
            log.warning(f"[舞台] 倾听姿态广播失败: {e}")

    async def _emit(self, connector: AgentConnector, utt: dict, *,
                    source_id: str = "", cue_depth: int = 0, target_id: str = ""):
        """一个角色产出一句发言 → 占麦仲裁 → 抢到则入语音管道，否则排队/丢弃。

        真人独占模型(human_controlled)：奶昔不合成/不写 VTS，仅把这句当作舞台提示
        广播给其它角色，让其它 agent 能在各自的模型上接话（真人自己在真机/真模型上说话）。

        target_id：层1 语音对话指向增强——这句话对着谁说（被点名角色会做"被搭话"反应）。
        """
        req = make_speech_request(connector, utt, source_id=source_id,
                                  cue_depth=cue_depth, target_id=target_id)
        if getattr(connector, "human_controlled", False):
            await self._broadcast_human_cue(req)
            return
        model_key = req.get("model_key", "__current__")
        admitted = await self._arbiter.submit(model_key, req)
        if admitted:
            await self._enqueue_speak(admitted)

    async def _broadcast_human_cue(self, req: dict):
        """真人发言：仅广播舞台提示供其它角色接话，不占麦/不合成/不写 VTS。"""
        cue = {
            "name": req.get("name", "人类副播"),
            "text": req.get("text", ""),
            "source_id": req.get("source_id", req.get("agent_id", "human")),
            "agent_id": req.get("agent_id", "human"),
            "cue_depth": req.get("cue_depth", 0) + 1,
            "target_id": req.get("target_id", ""),  # 层1：真人这句话若点名某角色
        }
        try:
            await self._broadcast_cue(cue)
        except Exception as e:
            log.warning(f"[舞台] 广播真人提示失败: {e}")

    def _looks_like_question(self, text: str) -> bool:
        """粗略判断一句话是否像提问（用于层1 对话回合增强，驱动 A↔B 你来我往）。"""
        if not text:
            return False
        t = text.rstrip()
        if t.endswith(("？", "?", "吗", "呢", "啥", "咋")):
            return True
        return any(w in text for w in ("谁", "什么", "为什么", "怎么", "干嘛", "几", "多少"))

    def _match_mention(self, text: str):
        """解析 @路由：弹幕含 @角色名/agent_id 时只投给该角色。返回 (目标连接器, 去掉@后的文本)。"""
        if not text or "@" not in text:
            return None, text
        for connector in self._connectors.values():
            for tag in (connector.name, connector.agent_id):
                if tag and f"@{tag}" in text:
                    cleaned = text.replace(f"@{tag}", "").strip()
                    return connector, cleaned
        return None, text

    async def _dispatch_danmaku(self, danmaku: dict):
        """把一条（或一批）弹幕分发给在台角色。含 @路由 则定向，否则全体判断是否接。"""
        target, cleaned = self._match_mention(danmaku.get("text", ""))
        if target is not None:
            danmaku = {**danmaku, "text": cleaned}
            targets = [target]
        else:
            targets = list(self._connectors.values())
        for connector in targets:
            if not self._guard.allow_emit(connector.agent_id):
                log.warning(f"[舞台] {connector.name} 被限流隔离，跳过本轮弹幕")
                continue
            try:
                utt = normalize_utterance(await connector.handle_danmaku(danmaku))
            except Exception as e:
                log.warning(f"[舞台] {connector.name} 处理弹幕异常: {e}")
                utt = None
            if utt:
                await self._emit(connector, utt, source_id=connector.agent_id, cue_depth=0)

    async def _broadcast_cue(self, cue: dict):
        """一句话说完后，广播舞台提示给"其他"角色（D4 回声防护 + 层1 指向增强）。

        - 普通角色：按概率衰减（should_react_to_cue）接话，防无限对喷。
        - 被点名角色(target_id==该角色 agent_id)：强制接话（做"被搭话"反应），但仍受链深上限
          约束，形成 A→B 的对话回合而不失控。
        """
        target_id = cue.get("target_id", "")
        if not should_react_to_cue(cue) and not target_id:
            # 没有任何角色被点名，且原始链已衰减到不反应 → 整轮不接话
            return
        for connector in list(self._connectors.values()):
            if connector.agent_id == cue.get("source_id"):
                continue  # 不回应自己引发的链
            if not self._guard.allow_emit(connector.agent_id):
                continue  # 限流隔离中，本轮不接话
            addressed = bool(target_id) and connector.agent_id == target_id
            if addressed:
                # 被点名强制接话，但链深到顶则停（防 A↔B 无限对喷）
                if cue.get("cue_depth", 0) >= MAX_CUE_DEPTH:
                    continue
            else:
                if not should_react_to_cue(cue):
                    continue
            c = dict(cue)
            c["addressed"] = addressed  # 告知被点名角色：这是"被搭话"
            try:
                utt = normalize_utterance(await connector.handle_cue(c))
            except Exception as e:
                log.warning(f"[舞台] {connector.name} 处理舞台提示异常: {e}")
                utt = None
            if utt:
                tid = utt.get("target_id", "")
                # 层1 回合增强：若这句是提问且未显式指定被搭话对象，则把上一位发言者设为目标，
                # 实现"我问你→你回问→我再答"的自然对话。
                if not tid and self._looks_like_question(utt.get("text", "")) and cue.get("source_id"):
                    tid = cue.get("source_id")
                # 反应句继承 source_id（仍算同一条链），链深 +1
                await self._emit(connector, utt, source_id=cue.get("source_id", ""),
                                 cue_depth=cue.get("cue_depth", 1), target_id=tid)

    async def _after_speak(self, action: dict, spoken: bool):
        """一句发言处理完：广播舞台提示给其他角色，并释放麦位、放行下一句。"""
        # 只有真正说出口的话才广播为舞台提示（合成失败的不算"说过"）
        if spoken:
            cue = {
                "name": action.get("name", "奶昔"),
                "text": action.get("text", ""),
                "source_id": action.get("source_id", action.get("agent_id", "naixi")),
                "agent_id": action.get("agent_id", "naixi"),
                "cue_depth": action.get("cue_depth", 0) + 1,
                "target_id": action.get("target_id", ""),  # 层1：把"这句话对着谁说"带进舞台提示
            }
            try:
                await self._broadcast_cue(cue)
            except Exception as e:
                log.warning(f"[舞台] 广播舞台提示失败: {e}")
            # 层2 肢体反馈：某模型说完 → 其它模型做"点头/鼓掌"反应姿态
            try:
                await self._vts_ambient_to_others("react", action.get("agent_id", ""))
            except Exception as e:
                log.warning(f"[舞台] 反应姿态广播失败: {e}")
        # 释放麦位，取出下一句排队发言（按模型各自独立）
        try:
            model_key = action.get("model_key", "__current__")
            nxt = await self._arbiter.release(model_key)
            if nxt:
                await self._enqueue_speak(nxt)
        except Exception as e:
            log.warning(f"[舞台] 释放麦位失败: {e}")

    # ── 状态快照 ──────────────────────────────────────────────────────────

    @property
    def status(self) -> dict:
        elapsed = time.time() - self._start_time if self._start_time else 0
        danmaku_rate = round(len(self._danmaku_cache) / max(elapsed, 1), 1) if elapsed > 0 else 0
        # 实例 index -> agent_id 反查（角色→实例映射），供前端按角色展示 VTS 实例
        agent_by_idx: dict[int, str] = {idx: aid for aid, idx in self._vts_by_agent.items()}
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
            "vts_connected": any(i.authenticated for i in self._vts_instances.values()),
            "vts_models": {mid: name for i in self._vts_instances.values() for mid, name in i.models.items()},
            "vts_current_model": {idx: i.current_model for idx, i in self._vts_instances.items()},
            # 实例 index -> agent_id 反查，便于前端按角色关联实例
            "_vts_idx_to_agent": {idx: aid for aid, idx in self._vts_by_agent.items()},
            "vts_instances": {idx: {"agent_id": agent_by_idx.get(idx, ""), "port": i.port, "authenticated": i.authenticated,
                                    "current_model": i.current_model,
                                    "expressions": len(i.expressions), "motions": len(i.motions)}
                               for idx, i in self._vts_instances.items()},
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
                self._model_path = cfg.get("model_path", "")
                self._render_mode = cfg.get("render_mode", "live2d")
                self._tts_engine = cfg.get("tts_engine", "cosyvoice")
                # 层3 真人语音闭环配置
                self._asr_model = cfg.get("asr_model", "vosk-model-small-cn-0.22")
                self._asr_device = cfg.get("asr_device", "")
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
                "app_id": (kwargs.get("app_id") if (kwargs.get("app_id") and str(kwargs.get("app_id")).isdigit() and "****" not in str(kwargs.get("app_id"))) else base.get("app_id", self._app_id)),
                "room_id": kwargs.get("room_id", base.get("room_id", self._room_id)),
                "code": _real(kwargs.get("code"), base.get("code", self._code)),
                "rtmp_url": kwargs.get("rtmp_url", base.get("rtmp_url", self._rtmp_url)),
                "dashscope_api_key": _real(kwargs.get("dashscope_api_key"), base.get("dashscope_api_key", self._dashscope_api_key)),
                "live_prompt": kwargs.get("live_prompt", base.get("live_prompt", self._live_prompt)),
                "audio_out_device": kwargs.get("audio_out_device", base.get("audio_out_device", self._audio_out_device)),
                "audio_in_device": kwargs.get("audio_in_device", base.get("audio_in_device", self._audio_in_device)),
                "model_path": kwargs.get("model_path", base.get("model_path", self._model_path)),
                "render_mode": kwargs.get("render_mode", base.get("render_mode", self._render_mode)),
                "tts_engine": kwargs.get("tts_engine", base.get("tts_engine", self._tts_engine)),
                # 层3 真人语音闭环配置
                "asr_model": kwargs.get("asr_model", base.get("asr_model", self._asr_model)),
                "asr_device": kwargs.get("asr_device", base.get("asr_device", self._asr_device)),
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
            self._model_path = cfg["model_path"]
            self._render_mode = cfg["render_mode"]
            self._tts_engine = cfg["tts_engine"]
            # 层3 真人语音闭环配置
            self._asr_model = cfg["asr_model"]
            self._asr_device = cfg["asr_device"]
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
        asyncio.create_task(self._vts_connect_all())

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
        await self._vts_disconnect_all()
        self._stop_pet()
        await self._stop_ffmpeg()
        # 清空占麦仲裁状态，避免上一场残留 busy 卡住下一场
        try: self._arbiter.clear()
        except: pass
        # 层3：停止真人语音闭环（取消麦克风采集协程）
        if self._human_voice_task is not None and not self._human_voice_task.done():
            self._human_voice_task.cancel()
            try: await self._human_voice_task
            except: pass
            self._human_voice_task = None
        self._asr_status = {"enabled": False, "state": "idle",
                            "model": self._asr_model, "error": ""}
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
                "errors": len(self._agent_errors),
                "last_run": time.strftime("%Y-%m-%d %H:%M:%S"),
                "room_id": self._room_id,
            }
            from desktop_core.storage import meta_get
            old = meta_get("live_stats")
            if old:
                try:
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
        # 取消上一轮残留的心跳/读取任务，避免重连时任务泄漏（旧实现直接覆盖 task 引用）
        await self._cancel_bili_tasks()

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

    async def _cancel_bili_tasks(self):
        """取消 B站 心跳/读取后台任务（重连与断开共用，避免 task 泄漏）。"""
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

    async def disconnect_bilibili(self):
        """断开 B站 连接"""
        self._connected = False
        await self._cancel_bili_tasks()
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

            # 高优：礼物/上舰/SC/进入 → 奶昔主咖立即回应（走占麦仲裁，主咖高优可插队）
            if msg_type in ("gift", "guard", "super_chat", "enter"):
                if msg_type in ("gift", "guard"):
                    reply = f"感谢{msg['user']}的{'礼物' if msg_type=='gift' else '大航海'}！"
                elif msg_type == "super_chat":
                    reply = f"感谢{msg['user']}的醒目留言！"
                else:
                    reply = f"欢迎{msg['user']}进入直播间～"
                emotion = "开心" if msg_type in ("gift", "guard") else "欢迎"
                naixi = self._connectors.get("naixi")
                if naixi:
                    await self._emit(naixi, {"text": reply, "emotion": emotion, "action": "wave"},
                                     source_id="naixi", cue_depth=0)
                continue

            # 弹幕：削峰 + 批量
            if msg_type != "danmaku" or not msg.get("text"):
                continue

            now = time.time()

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

            danmaku = self._build_danmaku_event(batch)
            await self._dispatch_danmaku(danmaku)

    def _build_danmaku_event(self, batch: list) -> dict:
        """把一批弹幕合成一个分发事件：太多时采样 + 高频词统计。"""
        if len(batch) > 5:
            from collections import Counter
            words = []
            for b in batch:
                words.extend(b.get("text", "")[:20])
            top_words = Counter(words).most_common(3)
            samples = batch[:3]
            summary = f"（共{len(batch)}条弹幕，高频词:{' '.join(w for w,_ in top_words)}）"
            text = summary + "\n".join(f"[弹幕] {b['user']}: {b['text'][:60]}" for b in samples)
        else:
            text = "\n".join(f"[弹幕] {b['user']}: {b['text'][:60]}" for b in batch)
        return {"type": "danmaku", "user": "", "text": text, "batch": batch}

    async def _process_batch(self):
        """处理积压的批量缓冲（超时触发）"""
        batch = list(self._danmaku_batch)
        self._danmaku_batch.clear()
        if not batch:
            return
        danmaku = self._build_danmaku_event(batch)
        await self._dispatch_danmaku(danmaku)

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

    def _resolve_ffmpeg(self) -> Optional[str]:
        """探测可用的 ffmpeg 可执行文件路径。

        后端 sidecar 由 Tauri 启动，子进程继承的 PATH 往往不含系统 ffmpeg
        （如 D:/软件/Ollama/ffmpeg），裸调用 "ffmpeg" 会 FileNotFoundError 被静默吞掉。
        探测顺序：PATH -> 解释器(embed)同目录 -> 打包 resources/ffmpeg -> 已知兜底位置；
        结果缓存到 self._ffmpeg_path，避免每句重复探测。
        """
        cached = getattr(self, "_ffmpeg_path", None)
        if cached:
            return cached
        import shutil, sys, os
        cands = []
        # 1) 系统 PATH
        p = shutil.which("ffmpeg")
        if p:
            cands.append(p)
        # 2) 解释器（embed python）同目录：未来可把 ffmpeg 一并塞进自包含包
        cands.append(os.path.join(os.path.dirname(sys.executable), "ffmpeg.exe"))
        # 3) 打包资源目录 resources/ffmpeg
        try:
            res = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "resources", "ffmpeg", "ffmpeg.exe")
            cands.append(res)
        except Exception:
            pass
        # 4) 用户机器已知 ffmpeg 位置（兜底）
        cands.append("D:/软件/Ollama/ffmpeg/ffmpeg.exe")
        cands.append("D:/软件/ffmpeg/bin/ffmpeg.exe")
        for c in cands:
            if c and os.path.exists(c):
                self._ffmpeg_path = c
                log.info(f"[语音] 使用 ffmpeg: {c}")
                return c
        self._ffmpeg_path = None
        return None

    def _to_wav_base64(self, audio_bytes: bytes, sample_rate: int = 24000) -> str:
        """把任意合成音频 bytes 统一转成标准 WAV（24000/1ch/s16）并返回 base64。

        用于推给客户端（Qt 桌宠 / 浏览器舞台）自行播放，避免在后端进程出声
        （后端由 Tauri 拉起，音频会话/设备易出问题导致听不到）。ffmpeg 路径复用
        _resolve_ffmpeg 探测；转码失败返回空串，由调用方记录日志。
        """
        if not audio_bytes:
            return ""
        ffmpeg_path = self._resolve_ffmpeg()
        if not ffmpeg_path:
            log.warning("[语音] ffmpeg 不可用，无法转 wav 推给客户端")
            return ""
        try:
            import io, os, base64, subprocess, tempfile
            tmp_in = os.path.join(tempfile.gettempdir(), f"tts_in_{int(time.time()*1000)}")
            tmp_out = os.path.join(tempfile.gettempdir(), f"tts_out_{int(time.time()*1000)}.wav")
            with open(tmp_in, "wb") as f:
                f.write(audio_bytes)
            r = subprocess.run(
                [ffmpeg_path, "-y", "-i", tmp_in, "-ar", str(sample_rate), "-ac", "1",
                 "-sample_fmt", "s16", "-f", "wav", tmp_out],
                capture_output=True, timeout=15
            )
            try: os.remove(tmp_in)
            except: pass
            if r.returncode != 0 or not os.path.exists(tmp_out):
                log.warning(f"[语音] ffmpeg 转 wav 失败（rc={getattr(r,'returncode','?')}），未推送音频")
                return ""
            with open(tmp_out, "rb") as f:
                wav = f.read()
            try: os.remove(tmp_out)
            except: pass
            return base64.b64encode(wav).decode()
        except Exception as e:
            log.warning(f"[语音] 转 wav 异常: {e}")
            return ""

    def play_audio(self, audio_bytes: bytes, sample_rate: int = 24000):
        """播放音频 bytes 到输出设备（ffmpeg 转 WAV，路径自动探测）"""
        if not self._sd_available:
            log.warning("[语音] sounddevice 不可用，无法播放语音")
            return
        if not audio_bytes:
            return
        ffmpeg_path = self._resolve_ffmpeg()
        if not ffmpeg_path:
            log.warning("[语音] ffmpeg 不可用（PATH 未包含且候选目录未找到），无法播放语音")
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
            r = subprocess.run(
                [ffmpeg_path, "-y", "-i", tmp_in, "-ar", "24000", "-ac", "1",
                 "-sample_fmt", "s16", "-f", "wav", tmp_out],
                capture_output=True, timeout=10
            )
            try: os.remove(tmp_in)
            except: pass

            if not os.path.exists(tmp_out):
                log.warning(f"[语音] ffmpeg 转码失败（returncode={getattr(r, 'returncode', '?')}），无法播放语音")
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

            def _play_target():
                # 单独捕获线程内异常：外层 try 包不到 daemon 线程里的 sd.play，
                # 否则 sd.play 失败会静默丢失、永远无日志。
                try:
                    sd.wait()
                    sd.play(data, rate, device=out_id)
                    sd.wait()
                except Exception as e:
                    log.warning(f"[语音播放失败] sd.play 异常(device={out_id}): {e}")

            self._play_thread = threading.Thread(target=_play_target, daemon=True)
            self._play_thread.start()
        except Exception as e:
            log.warning(f"[语音播放失败] {e}")

    # ── VTube Studio 控制（WebSocket API） ───────────────────────────────

    class VtsInstance:
        """单个 VTube Studio 实例的连接与自省数据（端口 = 8001 + index）。"""
        def __init__(self, index: int, host: str, port: int):
            self.index = index
            self.host = host
            self.port = port
            self.ws = None
            self.authenticated = False
            self.expressions: list = []   # 表情文件名列表
            self.motions: list = []       # 动作热键名列表
            self.req_seq: int = 0         # 请求自增序号
            self.models: dict = {}        # modelID -> modelName
            self.current_model: str = ""  # 当前激活模型 GUID

    def _vts_inst_for_model(self, model_id: Optional[str]) -> Optional["VtsInstance"]:
        """按 modelID(GUID) 反查目标 VTS 实例；未命中则退回首个已认证实例（兼容未绑定/单实例）。"""
        if model_id:
            idx = self._vts_by_model.get(model_id)
            if idx is not None and idx in self._vts_instances:
                inst = self._vts_instances[idx]
                if inst.ws and not inst.ws.closed:
                    return inst
        for inst in self._vts_instances.values():
            if inst.authenticated and inst.ws and not inst.ws.closed:
                return inst
        return None

    async def _vts_connect_all(self):
        """连接所有已注册角色对应的 VTS 实例（端口 = 8001 + index）。逐实例并发、非阻塞。"""
        for agent_id, idx in list(self._vts_by_agent.items()):
            asyncio.create_task(self._vts_connect_instance(idx))

    async def _vts_connect_instance(self, index: int):
        """连接指定 index 的 VTS 实例（端口 8001 + index），含认证+自省+枚举模型。"""
        import aiohttp
        inst = self._vts_instances.get(index)
        if inst is None:
            inst = VtsInstance(index, self._vts_host, self._vts_base_port + index)
            self._vts_instances[index] = inst
        if inst.ws and not inst.ws.closed:
            return True
        try:
            ws = await aiohttp.ClientSession().ws_connect(f"ws://{inst.host}:{inst.port}", heartbeat=10)
            inst.ws = ws
            # 完整认证握手：先取临时 token，再带 token 认证（VTS 1.0 标准流程）
            token = ""
            try:
                await self._vts_request(inst, "AuthenticationTokenRequest",
                                        {"pluginName": "奶昔直播", "pluginDeveloper": "Naixi"})
                resp = json.loads(await asyncio.wait_for(ws.receive_str(), timeout=5))
                token = resp.get("data", {}).get("authenticationToken", "")
            except Exception as e:
                log.info(f"[VTS#{index}] 获取临时 token 失败（尝试无 token 认证）: {e}")
            await self._vts_request(inst, "AuthenticationRequest",
                                    {"pluginName": "奶昔直播", "pluginDeveloper": "Naixi", "authenticationToken": token})
            resp = json.loads(await asyncio.wait_for(ws.receive_str(), timeout=5))
            if resp.get("data", {}).get("authenticated"):
                inst.authenticated = True
                log.info(f"[VTS#{index}] 已连接并认证 (port={inst.port})")
            else:
                log.info(f"[VTS#{index}] 已连接（未认证，需在 VTS 中点击确认授权）(port={inst.port})")
            # 自省可用表情/动作列表，供情绪/动作模糊匹配
            await self._vts_introspect(inst)
            # 枚举已加载模型（currentModel 即该实例渲染的模型，用于路由）
            await self._vts_enumerate_models(inst)
            # 启动后台读取循环，消费 VTS 响应，避免未读消息堆积
            asyncio.create_task(self._vts_read_loop(inst))
            return True
        except Exception as e:
            log.warning(f"[VTS#{index}] 连接失败 (port={inst.port}): {e}")
            return False

    async def _vts_request(self, inst: "VtsInstance", message_type: str, data: dict):
        """向指定 VTS 实例发送一条请求（不等待响应，由后台读取循环消费）。"""
        if not inst.ws or inst.ws.closed:
            return
        try:
            inst.req_seq += 1
            req = json.dumps({
                "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0",
                "requestID": f"naixi_{inst.index}_{inst.req_seq}", "messageType": message_type, "data": data
            })
            await inst.ws.send_str(req)
        except Exception as e:
            log.info(f"[VTS#{inst.index}] 发送 {message_type} 失败: {e}")

    async def _vts_read_loop(self, inst: "VtsInstance"):
        """后台消费某 VTS 实例响应，避免未读消息堆积导致连接异常。"""
        import aiohttp
        try:
            while inst.ws and not inst.ws.closed:
                msg = await inst.ws.receive()
                if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except Exception:
            pass
        inst.authenticated = False
        log.info(f"[VTS#{inst.index}] 读取循环结束，连接已断开")

    async def _vts_introspect(self, inst: "VtsInstance"):
        """自省某 VTS 实例模型可用表情(ExpressionStateRequest)/动作热键(HotkeysInCurrentModelRequest)。"""
        inst.expressions = []
        inst.motions = []
        # 1) 表情列表
        try:
            await self._vts_request(inst, "ExpressionStateRequest", {})
            resp = json.loads(await asyncio.wait_for(inst.ws.receive_str(), timeout=5))
            exprs = resp.get("data", {}).get("expressions", []) or []
            # 每个表情含 file（完整文件名，如 xxx.exp3.json）与 name
            inst.expressions = [e.get("file", e.get("name", "")) for e in exprs if isinstance(e, dict)]
        except Exception as e:
            log.info(f"[VTS#{inst.index}] 读取表情列表失败: {e}")
        # 2) 动作热键（type=TriggerAnimation 的热键即为可触发的动作）
        try:
            await self._vts_request(inst, "HotkeysInCurrentModelRequest", {})
            resp = json.loads(await asyncio.wait_for(inst.ws.receive_str(), timeout=5))
            hotkeys = resp.get("data", {}).get("availableHotkeys", []) or []
            inst.motions = [
                h.get("name", "") for h in hotkeys
                if isinstance(h, dict) and h.get("type") == "TriggerAnimation" and h.get("name")
            ]
        except Exception as e:
            log.info(f"[VTS#{inst.index}] 读取动作热键失败: {e}")
        if inst.expressions or inst.motions:
            log.info(f"[VTS#{inst.index}] 自省完成：表情 {len(inst.expressions)} 个，动作热键 {len(inst.motions)} 个")

    async def _vts_enumerate_models(self, inst: "VtsInstance"):
        """枚举某 VTS 实例模型，登记 modelID->实例 路由映射（currentModel 为主渲染模型）。"""
        inst.models = {}
        inst.current_model = ""
        try:
            await self._vts_request(inst, "AvailableModelsRequest", {})
            resp = json.loads(await asyncio.wait_for(inst.ws.receive_str(), timeout=5))
            models = (resp.get("data", {}) or {}).get("availableModels", []) or []
            inst.models = {m.get("modelID"): m.get("modelName", "") for m in models if m.get("modelID")}
        except Exception as e:
            log.info(f"[VTS#{inst.index}] 枚举模型失败: {e}")
        try:
            await self._vts_request(inst, "CurrentModelRequest", {})
            resp = json.loads(await asyncio.wait_for(inst.ws.receive_str(), timeout=5))
            inst.current_model = (resp.get("data", {}) or {}).get("modelID", "")
        except Exception as e:
            log.info(f"[VTS#{inst.index}] 读取当前模型失败: {e}")
        # 登记路由：该实例渲染的所有模型(尤其 current)都指向本实例
        if inst.current_model:
            self._vts_by_model[inst.current_model] = inst.index
        for mid in inst.models:
            self._vts_by_model.setdefault(mid, inst.index)
        if inst.models:
            log.info(f"[VTS#{inst.index}] 已枚举模型 {len(inst.models)} 个，当前: {inst.current_model or '未识别'}")

    # 情绪/动作关键词 → VTS 表情/动作文件名子串（中英对照，覆盖常见命名）
    _VTS_EMOTION_MAP = {
        "开心": ["happy", "joy", "smile"],
        "欢迎": ["welcome", "hello", "wave", "happy"],
        "惊讶": ["surprise", "shock"],
        "悲伤": ["sad", "cry", "tear"],
        "害羞": ["shy", "blush", "embarrass"],
        "生气": ["angry", "mad", "rage"],
        "卖萌": ["joy", "cute", "love", "happy"],
        "无奈": ["neutral", "tired", "sigh"],
    }
    _VTS_ACTION_MAP = {
        "wave": ["wave"], "bye": ["bye", "wave"], "nod": ["nod", "bow"],
        "think": ["think", "ponder"], "surprise": ["surprise"],
        "shake": ["shake", "no"], "kime": ["kime", "pose"], "sing": ["sing", "song"],
        "angry": ["angry"], "cry": ["cry", "tear"], "smile": ["smile", "happy"],
        "sad": ["sad"],
    }

    def _vts_match(self, keyword: str, candidates: list) -> str:
        """在候选文件名（VTS 表情/动作）中按关键词模糊匹配，命中返回文件名"""
        if not keyword or not candidates:
            return ""
        subs = self._VTS_EMOTION_MAP.get(keyword) or self._VTS_ACTION_MAP.get(keyword) or [keyword.lower()]
        for sub in subs:
            sub = sub.lower()
            for c in candidates:
                cname = c if isinstance(c, str) else str(c)
                if sub in cname.lower():
                    return c
        return ""

    async def _vts_send_expression(self, emotion: str, model_id: Optional[str] = None):
        """按情绪触发某 VTS 实例的表情（ExpressionActivationRequest，active=true）。model_id 指定目标模型/实例。

        适配器层分发：角色绑定了非VTS后端（vmc/self）时改道该后端，capabilities 不支持则静默跳过。
        """
        be = self._backend_for_model(model_id)
        if be is not None:
            if "expression" in be.capabilities:
                await be.send_expression(emotion, model_id)
            return
        inst = self._vts_inst_for_model(model_id)
        if inst is None or not inst.authenticated:
            return
        name = self._vts_match(emotion, inst.expressions)
        if not name:
            return
        data = {"expressionFile": name, "fadeTime": 0.5, "active": True}
        if model_id:
            data["modelID"] = model_id
        try:
            await self._vts_request(inst, "ExpressionActivationRequest", data)
            log.info(f"[VTS#{inst.index}] 表情触发: {emotion} → {name}" + (f" 模型={model_id}" if model_id else ""))
        except Exception as e:
            log.info(f"[VTS#{inst.index}] 表情触发失败: {e}")

    async def _vts_send_motion(self, action: str, model_id: Optional[str] = None):
        """按动作标签触发某 VTS 实例的动作（HotkeyTriggerRequest，匹配 TriggerAnimation 热键名）。

        适配器层分发：非VTS后端改道，capabilities 不支持 motion 则静默跳过。
        """
        be = self._backend_for_model(model_id)
        if be is not None:
            if "motion" in be.capabilities:
                await be.send_motion(action, model_id)
            return
        inst = self._vts_inst_for_model(model_id)
        if inst is None or not inst.authenticated:
            return
        name = self._vts_match(action, inst.motions)
        if not name:
            return
        try:
            # VTS 允许直接用热键名称（不区分大小写）作为 hotkeyID 触发
            data = {"hotkeyID": name}
            if model_id:
                data["modelID"] = model_id
            await self._vts_request(inst, "HotkeyTriggerRequest", data)
            log.info(f"[VTS#{inst.index}] 动作触发: {action} → 热键[{name}]" + (f" 模型={model_id}" if model_id else ""))
        except Exception as e:
            log.info(f"[VTS#{inst.index}] 动作触发失败: {e}")

    async def _vts_disconnect_instance(self, index: int):
        """断开指定 VTS 实例连接，干净释放该角色占用的实例与麦位资源。"""
        inst = self._vts_instances.get(index)
        if inst and inst.ws:
            try:
                await inst.ws.close()
            except Exception:
                pass
            inst.ws = None
            inst.authenticated = False

    async def _vts_disconnect_all(self):
        """断开所有 VTS 实例连接（引擎停止时调用）。"""
        for idx in list(self._vts_instances.keys()):
            await self._vts_disconnect_instance(idx)
        self._vts_instances.clear()
        self._vts_by_model.clear()

    async def _vts_send_parameters(self, params: dict, model_id: Optional[str] = None):
        """发送参数到指定 VTS 实例（如 MouthOpen, FaceAngleX 等）。model_id 指定目标模型/实例。

        适配器层分发：非VTS后端改道（VMC 映射为 BlendShape，自研直发前端）。
        """
        be = self._backend_for_model(model_id)
        if be is not None:
            if "parameters" in be.capabilities:
                await be.send_parameters(params, model_id)
            return
        inst = self._vts_inst_for_model(model_id)
        if inst is None or inst.ws is None or inst.ws.closed:
            return
        try:
            data = {"parameterValues": [{"id": k, "value": v} for k, v in params.items()]}
            if model_id:
                data["modelID"] = model_id
            req = json.dumps({
                "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0",
                "messageType": "InjectParameterDataRequest",
                "data": data,
            })
            await inst.ws.send_str(req)
        except Exception:
            pass

    # ── 层2 肢体反馈：倾听/点头姿态（不抢麦、不 TTS，仅打 VTS 参数） ──────────

    async def _vts_send_listen_pose(self, model_id: str):
        """层2 肢体反馈：向某 VTS 模型注入"倾听"姿态（微抬头+侧倾），持续至该模型自己开口或说话结束。

        使用 VTS 内置通用参数（所有模型都支持），避免依赖模型特定的表情/动作热键名。
        """
        if not model_id:
            return
        # BrowUpDown 上扬(专注/好奇) + FaceAngleX 微侧倾(偏头听)
        await self._vts_send_parameters({"BrowUpDown": 0.55, "FaceAngleX": 6.0}, model_id)

    async def _vts_send_react_pose(self, model_id: str):
        """层2 肢体反馈：向某 VTS 模型注入"点头/鼓掌"反应姿态（微笑+眼弯），1.5s 后自动复位。"""
        if not model_id:
            return
        # 复位倾听姿态，并打出微笑/眼弯反应
        await self._vts_send_parameters(
            {"MouthForm": 0.7, "EyeSmile": 0.7, "BrowUpDown": 0.0, "FaceAngleX": 0.0}, model_id)
        async def _reset():
            await asyncio.sleep(1.5)
            try:
                await self._vts_send_parameters({"MouthForm": 0.0, "EyeSmile": 0.0}, model_id)
            except Exception:
                pass
        asyncio.create_task(_reset())

    async def _vts_ambient_to_others(self, pose: str, exclude_agent_id: str):
        """层2 肢体反馈：把"倾听/反应"姿态广播给台上其它已绑定 VTS 模型。

        - 跳过说话者自身（exclude_agent_id）
        - 跳过真人独占模型（human_controlled，由真人自己在真机操控，奶昔不写）
        - 跳过未绑定模型的角色（无 modelID 无法精准投递，避免误伤当前激活模型）
        VTS 未连接时整体静默跳过。
        """
        # 有任一 VTS 实例认证、或有角色绑定了非VTS后端（vmc/self）时才广播；否则整体静默
        has_alt_backend = any(k != "vts" for k in self._backend_kinds.values())
        if not any(i.authenticated for i in self._vts_instances.values()) and not has_alt_backend:
            return
        for c in self._connectors.values():
            if c.agent_id == exclude_agent_id:
                continue
            if getattr(c, "human_controlled", False):
                continue
            mid = getattr(c, "model_id", None)
            if not mid:
                continue
            try:
                if pose == "listen":
                    await self._vts_send_listen_pose(mid)
                elif pose == "react":
                    await self._vts_send_react_pose(mid)
            except Exception as e:
                log.warning(f"[舞台] 向 {c.name} 发送{pose}姿态失败: {e}")

    def _audio_to_mouth_data(self, audio_bytes: bytes, frame_ms: int = 80) -> list[float]:
        """分析音频 bytes 生成 MouthOpen 值序列（0.0~1.0）。

        支持 WAV 与压缩格式（如 Edge-TTS 输出的 MP3）：非 WAV 时先用 ffmpeg
        转码为标准 WAV 再解析，避免口型序列退化为 [0.0]（此前 MP3 直读 wave
        模块会抛 "file does not start with RIFF id"，导致口型全平）。
        """
        import numpy as np, io, wave, subprocess, tempfile, os

        def _parse(wav_bytes: bytes):
            with io.BytesIO(wav_bytes) as buf:
                with wave.open(buf, 'rb') as wf:
                    frames = wf.readframes(wf.getnframes())
                    data = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
                    rate = wf.getframerate()
            return data, rate

        pcm = None
        rate = None
        try:
            pcm, rate = _parse(audio_bytes)
        except Exception:
            # 非 WAV（如 Edge-TTS 的 MP3）：ffmpeg 转码为 WAV 后解析
            try:
                tmp_in = os.path.join(tempfile.gettempdir(), f"mouth_in_{int(time.time() * 1000)}")
                tmp_out = os.path.join(tempfile.gettempdir(), f"mouth_out_{int(time.time() * 1000)}.wav")
                with open(tmp_in, "wb") as f:
                    f.write(audio_bytes)
                subprocess.run(
                    ["ffmpeg", "-y", "-i", tmp_in, "-ar", "24000", "-ac", "1",
                     "-sample_fmt", "s16", "-f", "wav", tmp_out],
                    capture_output=True, timeout=10,
                )
                if os.path.exists(tmp_out):
                    with open(tmp_out, "rb") as f:
                        pcm, rate = _parse(f.read())
                try:
                    os.remove(tmp_in)
                except Exception:
                    pass
                try:
                    os.remove(tmp_out)
                except Exception:
                    pass
            except Exception:
                return [0.0]
        if pcm is None or rate is None:
            return [0.0]
        frame_size = int(rate * frame_ms / 1000)
        mouth_values = []
        for i in range(0, len(pcm), frame_size):
            chunk = pcm[i:i + frame_size]
            if len(chunk) == 0:
                break
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            # 映射到 0.0~1.0（阈值 500~8000）
            mouth = min(1.0, max(0.0, (rms - 500) / 8000))
            mouth_values.append(mouth)
        return mouth_values if mouth_values else [0.0]

    async def live2d_broadcast(self, payload: dict):
        """向所有前端 Live2D 客户端（桌宠 + 舞台等多窗口）广播消息，静默清理死连接。"""
        dead = []
        for ws in list(self._live2d_clients):
            if ws.closed:
                dead.append(ws)
                continue
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._live2d_clients.discard(ws)

    async def _vts_speak(self, audio_bytes: bytes, text: str = "", emotion: str = "",
                         action: str = "", model_id: Optional[str] = None, human_controlled: bool = False,
                         agent_id: str = ""):
        """TTS 音频播放 + 口型同步（VTS + 桌宠双通道）。

        model_id: 绑定的 VTS 模型 GUID；真人模型(human_controlled)完全由真人操控，
        奶昔不写入任何 VTS 数据（口型/表情/动作），直接返回。
        """
        # 真人独占模型：奶昔不写入 VTS（真人自己在真机上操控），仅做桌宠内渲（若有）
        if human_controlled:
            log.info(f"[VTS] 真人模型({model_id or 'human'})由真人独占，奶昔跳过所有 VTS 写入")
            return
        mouth_data = self._audio_to_mouth_data(audio_bytes)
        if not mouth_data:
            return
        self.play_audio(audio_bytes)
        await self.live2d_broadcast({
            "type": "speak", "mouth": mouth_data,
            "frame_ms": 80, "text": text, "emotion": emotion, "action": action,
            "model_id": model_id or "", "agent_id": agent_id or "",
        })
        # VTS 表情/动作触发（与桌宠内渲共用同一份 emotion/action）
        if emotion:
            await self._vts_send_expression(emotion, model_id)
        if action:
            await self._vts_send_motion(action, model_id)
        # 逐帧发送口型参数到 VTube Studio（80ms/帧，按 model_id 精准投递）
        frame_interval = 0.08
        for mouth in mouth_data:
            if not self._running:
                break
            await self._vts_send_parameters({"MouthOpen": mouth}, model_id)
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

            spoken = False
            try:
                audio_bytes = await self._synthesize(text)
                if audio_bytes:
                    connector = self._connectors.get(action.get("agent_id", "naixi"))
                    model_id = getattr(connector, "model_id", None) if connector else None
                    human_controlled = getattr(connector, "human_controlled", False) if connector else False
                    await self._vts_speak(audio_bytes, text, action.get("emotion", "开心"),
                                          action.get("action", ""), model_id, human_controlled,
                                          agent_id=action.get("agent_id", ""))
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
                    spoken = True
            finally:
                # 无论合成成功与否都必须释放麦位，否则占麦仲裁会永久卡死
                await self._after_speak(action, spoken)

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
        except Exception as e:
            log.warning(f"[语音合成失败] Edge-TTS 不可用：{e}")
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
        """把一句语音送进常驻推流：更新字幕文件 + 解码 PCM 入播放队列。

        不再每句新开 ffmpeg（旧实现每句一进程 + -shortest 会导致每句掉线、
        双进程抢同一 RTMP 地址）。字幕改走 textfile + reload=1，彻底避免把
        弹幕文本直接拼进 filter 字符串带来的注入风险。
        """
        # 确保常驻推流已在运行（未开则按需拉起）
        if not (self._ffmpeg_proc and self._ffmpeg_proc.returncode is None):
            ok = await self.start_stream()
            if not ok:
                log.warning(f"[推流] 常驻推流未就绪，丢弃本句: {text[:20]}")
                return
        # 更新字幕（写文件，drawtext reload=1 会自动读取，避免注入）
        self._set_subtitle(text)
        # 解码音频为 raw PCM 并入队，由 _audio_pump_loop 实时喂给 ffmpeg
        pcm = await self._decode_to_pcm(audio_path)
        if pcm:
            await self._pcm_queue.put(pcm)
            log.info(f"[推流] 已入队语音 {_fmt_size(len(pcm))}: {text[:20]}")

    async def _decode_to_pcm(self, audio_path: str) -> bytes:
        """用一次性 ffmpeg 把任意音频文件解码为 s16le 单声道 raw PCM。"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", audio_path,
                "-f", "s16le", "-ar", str(PCM_RATE), "-ac", str(PCM_CHANNELS), "pipe:1",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            pcm, _ = await proc.communicate()
            return pcm or b""
        except FileNotFoundError:
            log.warning("[推流] ffmpeg 未安装，无法解码音频")
            return b""
        except Exception as e:
            log.warning(f"[推流] 音频解码失败: {e}")
            return b""

    def _ensure_subtitle_file(self):
        """确保字幕文件存在（drawtext reload=1 要求文件常在，空文件写一个空格占位）。"""
        if not self._subtitle_file:
            self._subtitle_file = os.path.join(tempfile.gettempdir(), "naixi_live_subtitle.txt")
        if not os.path.exists(self._subtitle_file):
            try:
                with open(self._subtitle_file, "w", encoding="utf-8") as f:
                    f.write(" ")
            except Exception as e:
                log.warning(f"[推流] 创建字幕文件失败: {e}")

    def _set_subtitle(self, text: str):
        """更新字幕文件内容（限长 60 字，纯文件写入，天然免疫 filter 注入）。"""
        self._ensure_subtitle_file()
        try:
            safe = (text or " ")[:60] or " "
            with open(self._subtitle_file, "w", encoding="utf-8") as f:
                f.write(safe)
        except Exception as e:
            log.warning(f"[推流] 更新字幕失败: {e}")

    def _subtitle_filter(self) -> str:
        """构造 drawtext filter：从字幕文件读，Windows 路径按 ffmpeg 规则转义。"""
        esc = self._subtitle_file.replace("\\", "/").replace(":", "\\:")
        return (
            f"drawtext=textfile='{esc}':reload=1:fontcolor=white:fontsize=24:"
            f"x=(w-text_w)/2:y=h-80:box=1:boxcolor=black@0.4:boxborderw=8"
        )

    async def _audio_pump_loop(self):
        """实时向常驻 ffmpeg 的 stdin 喂 PCM：有语音喂语音，空闲喂静音。

        以 PCM_CHUNK_MS 为粒度按真实时间节流，避免一次性灌爆缓冲；空闲时持续
        喂静音帧，保证音频流不断（否则观众端会卡顿/断流）。
        """
        chunk_samples = PCM_RATE * PCM_CHUNK_MS // 1000
        chunk_bytes = chunk_samples * 2 * PCM_CHANNELS      # s16le = 2 字节/采样
        silence = b"\x00" * chunk_bytes
        interval = PCM_CHUNK_MS / 1000.0
        current = b""
        while self._stream_running and self._ffmpeg_proc and self._ffmpeg_proc.returncode is None:
            t0 = time.monotonic()
            if not current:
                try:
                    current = self._pcm_queue.get_nowait()
                except asyncio.QueueEmpty:
                    current = b""
            if current:
                chunk = current[:chunk_bytes]
                current = current[chunk_bytes:]
                if len(chunk) < chunk_bytes:
                    chunk = chunk + silence[len(chunk):]
            else:
                chunk = silence
            try:
                self._ffmpeg_proc.stdin.write(chunk)
                await self._ffmpeg_proc.stdin.drain()
            except Exception as e:
                log.warning(f"[推流] 写入音频流失败，停止喂音: {e}")
                break
            dt = time.monotonic() - t0
            if dt < interval:
                await asyncio.sleep(interval - dt)

    async def start_stream(self, rtmp_url: str = "") -> bool:
        """启动单常驻推流：一个 ffmpeg 全程在线，画面 + 字幕(reload) + stdin 音频。

        画面用 lavfi 无限背景，字幕从 textfile 每帧 reload，音频从 stdin 管道喂
        （由 _audio_pump_loop 持续供给，空闲静音垫底）。全程只有这一个 ffmpeg
        进程，杜绝旧实现每句新开进程 + 双进程抢 RTMP 导致的掉线。
        """
        if rtmp_url:
            self._rtmp_url = rtmp_url
            self.save_config(rtmp_url=rtmp_url)
        if not self._rtmp_url:
            self._last_error = "未配置 RTMP 地址"
            return False
        if self._ffmpeg_proc and self._ffmpeg_proc.returncode is None:
            return True
        self._ensure_subtitle_file()
        self._set_subtitle(" ")
        try:
            self._ffmpeg_proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"color=c=0x1a1a2e:s={STREAM_WIDTH}x{STREAM_HEIGHT}:r={STREAM_FPS}",
                "-f", "s16le", "-ar", str(PCM_RATE), "-ac", str(PCM_CHANNELS), "-i", "pipe:0",
                "-vf", self._subtitle_filter(),
                "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
                "-pix_fmt", "yuv420p", "-g", str(STREAM_FPS * 2), "-b:v", "2000k",
                "-c:a", "aac", "-b:a", "128k",
                "-f", "flv", self._rtmp_url,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            self._stream_running = True
            # 启动实时喂音循环（有语音喂语音，空闲喂静音）
            self._audio_pump_task = asyncio.create_task(self._audio_pump_loop())
            log.info("[直播] 单常驻推流已启动")
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
        """停止常驻推流：先停喂音循环，关 stdin，再优雅结束 ffmpeg。"""
        self._stream_running = False
        # 停止喂音任务
        if self._audio_pump_task:
            self._audio_pump_task.cancel()
            try:
                await self._audio_pump_task
            except: pass
            self._audio_pump_task = None
        # 清空待播队列
        try:
            while True:
                self._pcm_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        if self._ffmpeg_proc:
            try:
                if self._ffmpeg_proc.stdin:
                    try:
                        self._ffmpeg_proc.stdin.close()
                    except: pass
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
