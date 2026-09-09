"""
tts_router.py — 奶昔桌宠统一 TTS 路由层
========================================

设计借鉴 moeru-ai/unspeech 的「OpenAI 兼容 + provider/model 路由」思想，
但**本地实现（Python）**，**不引入 unspeech 二进制**（AGPL-3.0 且纯云端，
与奶昔「无云 key 也能本地」需求冲突）。

解决的问题
----------
散落在三处的 TTS 逻辑（live_engine._synthesize / api.py / voice_input._tts）
各自实现了一遍 CosyVoice→Edge-TTS 降级，且配置解析逻辑重复。本模块把它们
统一到一处，并带来：
  * provider/model 路由：model 形如 "cosyvoice/cosyvoice-v3-flash" 或
    "edge_tts/zh-CN-XiaoxiaoNeural"，调用方只认一个入口。
  * 故障转移：主引擎失败按 fallback 链自动降级（默认 cosyvoice -> edge_tts）。
  * 可扩展：自动发现本地引擎（如 kokoro），有则注册、无则跳过。
  * 同步/异步双接口，返回结构化 TTSResult(audio, format, engine, model)。

关键约束
--------
必须精确保留奶昔原有的「配置掩码回退」逻辑（见 resolve_tts_config）：
audio 供应商密钥若是掩码/空，绝不能盖掉 B站页填的 _dashscope_api_key，
否则会误降级到 Edge-TTS（表现为“桌宠不走我的语音模型”）。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger("naixi.tts_router")

# 默认引擎顺序（故障转移链）。provider 解析失败或显式 model 未指定时按此顺序。
# 末尾的 kokoro 是纯本地离线兜底：云端（cosyvoice/edge_tts）全失败时仍能出声。
DEFAULT_FALLBACK = ["cosyvoice", "edge_tts", "kokoro"]

# 默认音色
COSYVOICE_VOICE = "longfeifei_v3"
EDGE_TTS_VOICE = "zh-CN-XiaoxiaoNeural"
COSYVOICE_SR = 24000
# TTS 默认值（仅当用户未在直播页指定时回退用，绝不在业务逻辑里再写死模型名/嗓音）
# 唯一默认端点：dashscope SpeechSynthesizer（实测对 cosyvoice 与 qwen-audio 家族都可用）。
# 旧默认 .../aigc/text2audio/cosyvoice 实测报 "url error"，且曾被 normalize_tts_endpoint
# 误判成 base 再补 /audio/speech（打出不存在的 .../text2audio/cosyvoice/audio/speech），已废。
_DEFAULT_TTS_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
DEFAULT_COSYVOICE_URL = _DEFAULT_TTS_ENDPOINT
DEFAULT_TTS_MODEL = "cosyvoice-v3-flash"
DEFAULT_TTS_VOICE = "longfeifei_v3"


def _default_voice_for_model(model: str) -> str:
    """按模型家族给一个「能出声」的默认嗓音（仅当用户未显式填 tts_voice 时回退用）。

    关键事实（已用真实 key 实测，非假设）：
    - cosyvoice 家族（cosyvoice-v3-flash 等）走 dashscope SpeechSynthesizer，默认嗓音 longfeifei_v3；
    - qwen-audio 家族（qwen-audio-3.0-tts-flash 等）共用同一 SpeechSynthesizer 端点，但默认嗓音
      必须是 qwen 系（如 longanhuan_v3.6），喂 cosyvoice 的 longfeifei_v3 会 400/411 引擎错误。
    故按模型名前缀自适应默认嗓音：用户留空也能「填了模型名就出声」，同时 tts_voice 始终可覆盖。
    这不是写死用户配置——只在用户未指定时才生效，且随时可被 tts_voice 输入框覆盖。
    """
    m = (model or "").lower()
    if m.startswith("qwen-audio"):
        return "longanhuan_v3.6"
    if m.startswith("cosyvoice"):
        return COSYVOICE_VOICE
    return DEFAULT_TTS_VOICE

# ───────────────────────── 本地 TTS（kokoro-onnx）配置 ─────────────────────────
# 模型缓存默认放在「应用根目录/naixi_tts_models」下，随安装包便携移动，
# 始终位于 resources/ 之外（**不会被打包进安装包**），且不写 C 盘
# （符合「禁止往 C 盘写数据」铁则）。可用 NAT_TTS_MODEL_DIR 覆盖
# （如指向共享盘上已下载好的模型，避免每台机器重复下载）。
#
# 路径解析同时兼容两种布局，但**无论哪种都把模型放在 resources/ 之外**：
#   * 开发态：desktop_core/tts_router.py → 父目录即项目根（仓库根目录）
#   * 打包态：resources/desktop_core/tts_router.py → 父目录为 resources，需再上一层
# 这样安装包不会把 ~120MB 模型打进去，且用户机器上模型落在安装根之外、不在 C 盘。
_TTS_SRC_DIR = os.path.dirname(os.path.abspath(__file__))       # .../desktop_core
_TTS_APP_ROOT = os.path.dirname(_TTS_SRC_DIR)                   # 父目录
if os.path.basename(_TTS_APP_ROOT).lower() == "resources":
    _TTS_APP_ROOT = os.path.dirname(_TTS_APP_ROOT)              # 打包态：越过 resources
TTS_MODEL_DIR = os.environ.get("NAT_TTS_MODEL_DIR", "")
if not TTS_MODEL_DIR:
    TTS_MODEL_DIR = os.path.join(_TTS_APP_ROOT, "naixi_tts_models")
# 模型来自 kokoro-onnx 官方发布（thewh1teagle/kokoro-onnx），而非 torch 版 hexgrad/Kokoro-82M
KOKORO_REPO = "thewh1teagle/kokoro-onnx"
# 默认用 int8 量化版：CPU 推理更快、体积仅 ~92MB（fp32 为 325MB），音质对桌宠足够。
KOKORO_MODEL_FILE = "kokoro-v1.0.int8.onnx"
KOKORO_VOICES_FILE = "voices-v1.0.bin"
KOKORO_RELEASE_TAG = "model-files-v1.0"
KOKORO_RELEASE_BASE = f"https://github.com/{KOKORO_REPO}/releases/download/{KOKORO_RELEASE_TAG}"
KOKORO_MODEL_URL = f"{KOKORO_RELEASE_BASE}/{KOKORO_MODEL_FILE}"
KOKORO_VOICES_URL = f"{KOKORO_RELEASE_BASE}/{KOKORO_VOICES_FILE}"
# 中文默认音色（zf_/zm_ 系列为中文；af_/am_ 为英文）
ZH_DEFAULT_VOICE = "zf_xiaobei"


# ───────────────────────── espeak-ng 修复（关键） ─────────────────────────
# espeak-ng 的全局初始化缺陷：进程内只有「第一个」EspeakWrapper 实例能成功枚举
# 音色（available_voices），后续实例一律返回 0。而 kokoro_onnx 的 tokenizer 在
# 每次 phonemize 时都会 new 一个全新 EspeakWrapper，于是 phonemizer 判定所有语言
# "not supported" / "invalid voice code"，本地 TTS 整体失效。
# 修复：把首个实例枚举到的音色缓存，供所有实例复用（幂等、线程安全）。
import threading as _threading

_espeak_patch_lock = _threading.Lock()
_espeak_patched = False


def _kokoro_lang_for_voice(v: str) -> str:
    """把 kokoro 音色名前缀映射到 phonemizer 接受的语言码。

    关键：中文在 phonemizer 里是 'cmn'（不是 'zh'），否则会被判 'not supported'。
    见 verify_integration 的 kokoro 真机烟测。
    """
    prefix = (v or "")[:1].lower()
    return {
        "z": "cmn",   # 中文
        "j": "ja",    # 日文
        "a": "en-us", # 美式英文 (af_/am_)
        "m": "en-us", # 英文系
        "b": "en-gb", # 英式英文
        "e": "es",    # 西班牙文
        "f": "fr",    # 法文
        "h": "hi",    # 印地文
        "i": "it",    # 意大利文
        "p": "pt",    # 葡萄牙文
        "r": "ru",    # 俄文
        "k": "ko",    # 韩文
    }.get(prefix, "en-us")


def _patch_espeak_voices():
    """缓存首个 EspeakWrapper 实例的音色枚举结果，绕过 espeak 全局初始化缺陷。

    必须在 Kokoro() 构造之后、首次 create() 之前调用（此时 kokoro 的 Tokenizer
    已通过 set_data_path/set_library 把正确的 espeak 路径写进类级别，首个实例才能
    枚举到 142 个音色）。幂等。
    """
    global _espeak_patched
    if _espeak_patched:
        return
    with _espeak_patch_lock:
        if _espeak_patched:
            return
        try:
            from phonemizer.backend.espeak.wrapper import EspeakWrapper
            cache = list(EspeakWrapper().available_voices())
            if not cache:
                log.warning("[tts_router] espeak 音色枚举为空，跳过 patch（本地 TTS 可能不可用）")
                return
            EspeakWrapper.available_voices = lambda self, name=None: (  # noqa: E731
                [v for v in cache if v.language == name] if name else cache
            )
            _espeak_patched = True
            log.info(f"[tts_router] espeak 音色缓存就绪（{len(cache)} 个，绕过全局初始化缺陷）")
        except Exception as e:
            log.warning(f"[tts_router] espeak patch 失败（不影响其他引擎）: {e}")


@dataclass
class TTSResult:
    """结构化合成结果，调用方不再自己猜 format。"""
    audio: bytes
    format: str          # "wav" | "mp3"
    engine: str          # 实际命中引擎名
    model: str           # 实际使用的 model 串
    voice: str = ""


# ───────────────────────── 配置解析（精确保留掩码回退逻辑） ─────────────────────────

def resolve_tts_config() -> dict:
    """解析 TTS 配置（api_key / api_url / model）。

    逻辑复刻 live_engine._resolve_tts_config：
    - 优先【直播页显式指定的 tts_model/tts_api_url】（用户在 B站 配置页自由切换）；
    - 其次 desktop_config 里 type=audio 的真密钥供应商（模型供应商页），仅当其 model 非空且用户未指定时生效；
    - 最后回退到模块默认常量；
    - audio 供应商密钥为空或掩码(_KEY_MASK)时**跳过**，回退到 dashscope_api_key / 环境变量，
      绝不能让掩码把真密钥盖掉。
    """
    user_model = ""
    user_url = ""
    user_voice = ""
    try:
        from desktop_core.live_engine import engine as _eng
        user_model = (getattr(_eng, "_tts_model", "") or "").strip()
        user_url = (getattr(_eng, "_tts_api_url", "") or "").strip()
        user_voice = (getattr(_eng, "_tts_voice", "") or "").strip()
    except Exception:
        pass
    cfg = {
        "api_key": "",
        "api_url": user_url or DEFAULT_COSYVOICE_URL,
        "model": user_model or DEFAULT_TTS_MODEL,
        # 用户填了 tts_voice 就按其值；否则按模型家族给能出声的默认嗓音（qwen-audio→longanhuan_v3.6）
        "voice": user_voice or _default_voice_for_model(user_model or DEFAULT_TTS_MODEL),
    }
    try:
        from desktop_core.storage import meta_get, decrypt_api_key, _KEY_MASK
        raw = meta_get("desktop_config")
        if raw:
            dc = json.loads(raw)
            for _pid, pcfg in dc.get("api_providers", {}).items():
                if pcfg.get("type", "chat") == "audio":
                    raw_key = pcfg.get("api_key", "")
                    key = decrypt_api_key(raw_key) if isinstance(raw_key, str) and raw_key.startswith("enc:") else raw_key
                    if key and key != _KEY_MASK:
                        cfg["api_key"] = key
                        if pcfg.get("api_url"):
                            cfg["api_url"] = pcfg["api_url"]
                        # 用户已在直播页显式指定 → 优先用用户值，不被供应商 model/voice 覆盖
                        if not user_model and pcfg.get("model"):
                            cfg["model"] = pcfg["model"]
                        if not user_url and pcfg.get("api_url"):
                            cfg["api_url"] = pcfg["api_url"]
                        if not user_voice and pcfg.get("voice"):
                            cfg["voice"] = pcfg["voice"]
                        return cfg
    except Exception:
        pass
    if not cfg["api_key"]:
        try:
            from desktop_core.live_engine import engine as _eng
            cfg["api_key"] = getattr(_eng, "_dashscope_api_key", "") or ""
        except Exception:
            pass
    if not cfg["api_key"]:
        # 对齐 Qt voice_input._load_key：audio 供应商无真密钥时，回退读
        # live_config.dashscope_api_key 原始值。该 key 是有效百炼 Key（sk-... 35位），
        # 否则后端云端会 401 → 静默降级 edge_tts，而 Qt 因直接读此字段能出真声，
        # 造成「Qt 出真 TTS、弹幕/对话却用浏览器 TTS 保底」的分裂（2026-09-09 复现）。
        try:
            from desktop_core import storage
            _lc_raw = storage.meta_get("live_config")
            if _lc_raw:
                _lc = json.loads(_lc_raw)
                _k = _lc.get("dashscope_api_key", "")
                if _k and _k != _KEY_MASK:
                    cfg["api_key"] = _k
        except Exception:
            pass
    if not cfg["api_key"]:
        cfg["api_key"] = os.environ.get("DASHSCOPE_API_KEY", "")
    return cfg


# ───────── 通用云端 TTS 适配层（端点/协议/嗓音全配置驱动，零写死） ─────────
# 针对历史缺陷"换个名字/换个 key/换个端点就废"而重写，四条铁律：
#   1. 端点：用户填什么用什么。已带具体端点路径(如 /audio/speech、/SpeechSynthesizer)→原样用，
#      **不再无脑拼 /audio/speech**（旧代码会把完整端点拼成 .../audio/speech/audio/speech）；
#      只填 base(如 https://host/v1)→按 OpenAI 兼容惯例补 /audio/speech；留空→默认端点。
#   2. 协议：按端点路径"猜"优先协议，但**不是白名单**——首选失败会依次重试其余协议。
#      不同服务商 payload 形态确实不同（嵌套 input / 扁平 input / 多模态），必须探测才能通用。
#   3. 响应：裸音频字节 / JSON(url) / JSON(base64) 三种形态统一解析，不绑死某家结构。
#   4. 模型名：原样透传，**绝不按模型名做路由、加前缀或查白名单**——换任何名字都直接生效。

# 端点路径片段 → 优先协议（仅用于排序，命中也允许重试其它）
_ENDPOINT_PROTOCOL_HINTS = (
    ("/audio/tts/speechsynthesizer", "dashscope_nested"),
    ("/text2audio", "dashscope_nested"),
    ("/multimodal-generation/generation", "dashscope_mm"),
    ("/audio/speech", "openai_flat"),
    ("/synthesize", "openai_flat"),
    ("/tts", "openai_flat"),
)
# 视作"已是完整端点"的路径片段（避免重复拼接）
_ENDPOINT_PATH_SEGS = tuple(seg for seg, _ in _ENDPOINT_PROTOCOL_HINTS)
# 协议全集（首选之外全部兜底重试）
PROTOCOL_ORDER = ("dashscope_nested", "openai_flat", "dashscope_mm")


def _guess_protocol(url: str) -> str:
    u = (url or "").lower()
    for seg, proto in _ENDPOINT_PROTOCOL_HINTS:
        if seg in u:
            return proto
    return "dashscope_nested"


def normalize_tts_endpoint(url: str) -> str:
    """归一化用户填的 TTS 接口地址为可直投端点（见设计要点 1）。"""
    u = (url or "").strip().rstrip("/")
    if not u:
        return _DEFAULT_TTS_ENDPOINT
    # dashscope 旧语音端点 /text2audio/* 实测报 "url error"（该服务早已并到 SpeechSynthesizer），
    # 纠正到唯一可用端点，避免老配置/老默认值打废
    if "/text2audio/" in u and ("dashscope" in u or "aliyuncs" in u):
        return _DEFAULT_TTS_ENDPOINT
    for seg in _ENDPOINT_PATH_SEGS:
        if u.lower().endswith(seg):
            return u
    return u + "/audio/speech"


def _protocol_order_for(url: str) -> tuple:
    """该端点的协议尝试顺序：猜测协议优先，其余兜底。"""
    first = _guess_protocol(url)
    return (first,) + tuple(p for p in PROTOCOL_ORDER if p != first)


def build_tts_payload(protocol: str, model: str, text: str, voice: str) -> dict:
    """按协议构造请求体。

    嗓音：OpenAI 兼容系可省略（让服务商用默认）；dashscope 系**必须**带
    （实测省略会 400/411），故由调用方保证非空（用户值 > 供应商配置 > 家族默认）。
    """
    if protocol == "openai_flat":
        p = {"model": model, "input": text, "response_format": "wav"}
        if voice:
            p["voice"] = voice
        return p
    if protocol == "dashscope_mm":
        params = {"response_format": "wav"}
        if voice:
            params["voice"] = voice
        return {"model": model,
                "input": {"messages": [{"role": "user",
                                        "content": [{"type": "text", "text": text}]}]},
                "parameters": params}
    # dashscope_nested
    inp = {"text": text, "format": "wav", "sample_rate": COSYVOICE_SR}
    if voice:
        inp["voice"] = voice
    return {"model": model, "input": inp}


def _find_audio_ref(obj, depth: int = 0):
    """从任意 JSON 结构递归找音频引用，返回 (kind, value)，kind ∈ url/b64。"""
    if depth > 6:
        return None
    if isinstance(obj, dict):
        out = obj.get("output")
        if isinstance(out, dict):
            au = out.get("audio")
            if isinstance(au, dict):
                if isinstance(au.get("url"), str) and au["url"]:
                    return ("url", au["url"])
                if isinstance(au.get("data"), str) and au["data"]:
                    return ("b64", au["data"])
            if isinstance(out.get("url"), str) and out["url"]:
                return ("url", out["url"])
        for k in ("url", "audio_url", "audio", "data", "audio_data", "result", "b64"):
            v = obj.get(k)
            if isinstance(v, str) and v:
                if v.startswith(("http://", "https://")):
                    return ("url", v)
                if len(v) > 200:  # 疑似 base64 音频
                    return ("b64", v)
        for v in obj.values():
            r = _find_audio_ref(v, depth + 1)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_audio_ref(v, depth + 1)
            if r:
                return r
    return None


async def _read_audio_async(resp) -> Optional[bytes]:
    """通用响应解析：裸音频字节 / JSON(url) / JSON(base64)。"""
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "json" not in ctype:
        data = await resp.read()
        return data or None
    try:
        j = await resp.json(content_type=None)
    except Exception:
        return await resp.read() or None
    ref = _find_audio_ref(j)
    if not ref:
        return None
    kind, val = ref
    if kind == "b64":
        try:
            return base64.b64decode(val)
        except Exception:
            return None
    try:
        import aiohttp
        async with aiohttp.ClientSession() as dl:
            async with dl.get(val, timeout=aiohttp.ClientTimeout(total=30)) as ar:
                if ar.status == 200:
                    return await ar.read()
    except Exception:
        pass
    return None


_SESSION = None

def _get_session():
    """复用持久 aiohttp ClientSession（避免每次 TTS 合成重做 TCP+TLS 握手）。
    loop 安全：session 绑死创建时的 loop，变更则重建，杜绝跨 loop 报错。"""
    import aiohttp, asyncio
    loop = asyncio.get_event_loop()
    global _SESSION
    s = _SESSION
    if s is not None and not s.closed and getattr(s, "_loop", None) is loop:
        return s
    if s is not None and not s.closed:
        try:
            asyncio.ensure_future(s.close())
        except Exception:
            pass
    _SESSION = aiohttp.ClientSession()
    return _SESSION


async def cloud_tts_synth(api_key: str, api_url: str, model: str, voice: str, text: str,
                          timeout: int = 60, return_diag: bool = False):
    """通用云端 TTS 合成（异步）：端点归一化 + 协议自适应重试 + 通用响应解析。

    返回 bytes（失败 None）；return_diag=True 时返回 (bytes|None, diag)，
    diag 含实际端点/协议/嗓音与每个协议的失败原因（供前端逐项诊断展示）。
    """
    if not api_key:
        return (None, {"error": "未配置 API Key"}) if return_diag else None
    endpoint = normalize_tts_endpoint(api_url)
    eff_voice = voice or _default_voice_for_model(model)
    diag = {"endpoint": endpoint, "model": model, "voice": eff_voice,
            "voice_source": "user" if voice else "auto", "tried": []}
    try:
        import aiohttp
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        for proto in _protocol_order_for(endpoint):
            payload = build_tts_payload(proto, model, text, eff_voice)
            entry = {"protocol": proto, "status": 0, "error": ""}
            try:
                s = _get_session()
                async with s.post(endpoint, json=payload, headers=headers,
                                  timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                        entry["status"] = r.status
                        if r.status == 200:
                            audio = await _read_audio_async(r)
                            if audio:
                                diag["protocol"] = proto
                                return (audio, diag) if return_diag else audio
                            entry["error"] = "HTTP 200 但响应里没解析出音频"
                        else:
                            entry["error"] = (await r.text())[:200]
            except Exception as e:
                entry["error"] = str(e)[:200]
            diag["tried"].append(entry)
    except Exception as e:
        log.warning(f"[tts_router] 云端 TTS 合成失败: {e}")
    return (None, diag) if return_diag else None


def cloud_tts_synth_sync(api_key: str, api_url: str, model: str, voice: str, text: str,
                         timeout: int = 60, return_diag: bool = False):
    """通用云端 TTS 合成（同步，requests），供纯同步上下文使用。逻辑同 cloud_tts_synth。"""
    if not api_key:
        return (None, {"error": "未配置 API Key"}) if return_diag else None
    endpoint = normalize_tts_endpoint(api_url)
    eff_voice = voice or _default_voice_for_model(model)
    diag = {"endpoint": endpoint, "model": model, "voice": eff_voice,
            "voice_source": "user" if voice else "auto", "tried": []}
    try:
        import requests
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        for proto in _protocol_order_for(endpoint):
            payload = build_tts_payload(proto, model, text, eff_voice)
            entry = {"protocol": proto, "status": 0, "error": ""}
            try:
                r = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
                entry["status"] = r.status_code
                if r.status_code == 200:
                    ctype = (r.headers.get("Content-Type") or "").lower()
                    audio = None
                    if "json" in ctype:
                        ref = _find_audio_ref(r.json())
                        if ref:
                            kind, val = ref
                            if kind == "b64":
                                audio = base64.b64decode(val)
                            else:
                                ad = requests.get(val, timeout=30).content
                                audio = ad or None
                    else:
                        audio = r.content or None
                    if audio:
                        diag["protocol"] = proto
                        return (audio, diag) if return_diag else audio
                    entry["error"] = "HTTP 200 但响应里没解析出音频"
                else:
                    entry["error"] = (r.text or "")[:200]
            except Exception as e:
                entry["error"] = str(e)[:200]
            diag["tried"].append(entry)
    except Exception as e:
        log.warning(f"[tts_router] 云端 TTS 同步合成失败: {e}")
    return (None, diag) if return_diag else None


def _models_list_url(api_url: str) -> str:
    """从 TTS 端点推导该服务商的模型列表 URL。dashscope 固定 compatible-mode/v1/models。"""
    u = (api_url or "").strip()
    if not u or "dashscope" in u or "aliyuncs" in u:
        return "https://dashscope.aliyuncs.com/compatible-mode/v1/models"
    u = u.rstrip("/")
    for seg in _ENDPOINT_PATH_SEGS:
        if u.lower().endswith(seg):
            u = u[: -len(seg)].rstrip("/")
            break
    return u + "/models"


def _tts_candidates_from_models(models: list) -> list:
    """从 key 的模型列表派生 TTS 候选（含同族变体推导），排除非合成端点。

    注意：模型列表 ≠ 可用模型（实测 key 列表里有 qwen3-tts-* 但 403 无额度，而
    qwen-audio-3.0-tts-flash 不在列表里却能出声）——所以候选必须逐个【真实试合成】，
    出声才算数。这里只负责生成"有希望的候选"并排序。
    """
    import re
    ids = [m.get("id") for m in models if isinstance(m, dict) and m.get("id")]
    cands = []
    def add(x):
        if x and x not in cands:
            cands.append(x)
    # 1) 同族变体推导（最可能可用）：qwen-audio-3.0-asr-flash → qwen-audio-3.0-tts-flash/-plus
    for i in ids:
        m = re.match(r"^(qwen-audio-[\d.]+)-asr", i or "")
        if m:
            add(f"{m.group(1)}-tts-flash")
            add(f"{m.group(1)}-tts-plus")
    # 2) 列表里明确的 TTS 模型（排除 asr/realtime/vc/vd 等非一次合成端点）
    bad = ("asr", "realtime", "-vc", "-vd")
    for i in ids:
        low = (i or "").lower()
        if ("tts" in low or "cosyvoice" in low) and not any(b in low for b in bad):
            add(i)
    return cands[:8]


async def _fetch_models(api_key: str, api_url: str = "") -> tuple:
    """拉该 key 的模型列表（OpenAI 兼容 /models）。返回 (list|None, error)。"""
    try:
        import aiohttp
        url = _models_list_url(api_url)
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers={"Authorization": f"Bearer {api_key}"},
                             timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    return None, f"{r.status}: {(await r.text())[:120]}"
                j = await r.json(content_type=None)
                return j.get("data") or [], ""
    except Exception as e:
        return None, str(e)[:160]


async def discover_tts_model(api_key: str, api_url: str = "", text: str = "你好") -> dict:
    """模型名留空时的自动发现：拉该 key 的模型列表 → 派生 TTS 候选 → 逐个真实试合成。

    实现「换个 key 就能用」：key 有效 → 自动找到能出声的模型并返回；
    key 无效 → models 请求即 401，error 如实返回。
    返回 {model, voice, diag}；未发现时 model=None。
    """
    diag = {"candidates": [], "tried": [], "discover": True}
    if not api_key:
        diag["error"] = "未配置 API Key"
        return {"model": None, "diag": diag}
    models, err = await _fetch_models(api_key, api_url)
    if models is None:
        diag["error"] = f"模型列表请求失败 {err}"
        return {"model": None, "diag": diag}
    cands = _tts_candidates_from_models(models)
    diag["candidates"] = cands
    for cand in cands:
        audio, d = await cloud_tts_synth(api_key, "", cand, "", text,
                                         timeout=15, return_diag=True)
        status = (d.get("tried") or [{}])[0].get("status")
        diag["tried"].append({"model": cand, "status": status})
        if audio:
            return {"model": cand, "voice": _default_voice_for_model(cand), "diag": diag}
    diag.setdefault("error", "该 key 下候选模型均无法出声（全部无额度/不支持）")
    return {"model": None, "diag": diag}


def _vision_candidates_from_models(models: list) -> list:
    """筛视觉对话候选：vl/vision 系，排除非多模态对话模型（i2v/t2i/tts/asr/ocr 等）。"""
    ids = [m.get("id") for m in models if isinstance(m, dict) and m.get("id")]
    bad = ("i2v", "t2i", "tts", "asr", "embed", "rerank", "realtime",
           "omni", "ocr", "video", "wan", "qvq")
    cands = []
    for i in ids:
        low = (i or "").lower()
        if ("vl" in low or "vision" in low) and not any(b in low for b in bad):
            if i not in cands:
                cands.append(i)
    return cands[:8]


def _chat_candidates_from_models(models: list, prefer_light: bool = False) -> list:
    """筛纯文本对话候选：排除多模态/语音/视觉/向量/**代码模型**，通用对话模型排前。

    教训：kimi-k2.7-code 这类代码模型曾被当成桌宠对话模型（对闲聊人设提示词响应
    不当，用户感知"桌宠还是回复默认"）——代码模型必须排除，通用对话模型排前。
    """
    ids = [m.get("id") for m in models if isinstance(m, dict) and m.get("id")]
    bad = ("vl", "vision", "tts", "asr", "embed", "rerank", "realtime",
           "omni", "ocr", "video", "audio", "i2v", "t2i", "wan", "qvq",
           "guard", "judge", "math", "-code", "coder", "clampe")
    cands = []
    for i in ids:
        low = (i or "").lower()
        if any(b in low for b in bad):
            continue
        if i and i not in cands:
            cands.append(i)
    def _rank(name: str) -> int:
        low = name.lower()
        if prefer_light:
            # 直播弹幕高频调用：轻量/便宜模型优先，大模型排后，避免 token 爆炸
            for kw, score in (("flash", 0), ("turbo", 0), ("lite", 0), ("mini", 0),
                              ("8b", 1), ("7b", 1), ("4b", 1), ("14b", 2), ("32b", 3),
                              ("plus", 4), ("max", 5), ("72b", 6), ("235b", 7), ("671b", 8)):
                if kw in low:
                    return score
            return 2
        for kw, score in (("qwen-plus", 0), ("qwen3", 1), ("qwen-max", 1), ("qwen-flash", 1),
                          ("deepseek-chat", 1), ("deepseek-v3", 1), ("qwen-turbo", 2),
                          ("glm", 2), ("kimi", 3)):
            if kw in low:
                return score
        return 5
    return sorted(cands, key=_rank)[:8]


_VISION_PING_IMG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
                    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


async def _probe_chat_completion(api_key: str, chat_url: str, model: str,
                                 vision: bool = False, timeout: int = 20) -> tuple:
    """发一次最小 chat/vision 请求。返回 (status, text)。"""
    try:
        import aiohttp
        u = (chat_url or "").strip().rstrip("/")
        # 端点为空时用 dashscope 默认（否则拼出 "/chat/completions" 相对路径必炸）
        if not u or not u.startswith(("http://", "https://")):
            u = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        elif not u.lower().endswith("/chat/completions"):
            u = u + "/chat/completions"
        content = [{"type": "image_url", "image_url": {"url": _VISION_PING_IMG}},
                   {"type": "text", "text": "describe in one word"}] if vision \
            else "ping"
        payload = {"model": model, "messages": [{"role": "user", "content": content}],
                   "max_tokens": 8}
        async with aiohttp.ClientSession() as s:
            async with s.post(u, json=payload, headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                return r.status, (await r.text())[:200]
    except Exception as e:
        return 0, str(e)[:160]


async def discover_vision_model(api_key: str, api_url: str = "") -> dict:
    """视觉模型自动发现：与 discover_tts_model 同思路，逐个发最小 vision 请求真实测。"""
    diag = {"candidates": [], "tried": [], "discover": True}
    if not api_key:
        diag["error"] = "未配置 API Key"
        return {"model": None, "diag": diag}
    models, err = await _fetch_models(api_key, api_url)
    if models is None:
        diag["error"] = f"模型列表请求失败 {err}"
        return {"model": None, "diag": diag}
    cands = _vision_candidates_from_models(models)
    diag["candidates"] = cands
    for cand in cands:
        status, _txt = await _probe_chat_completion(api_key, api_url, cand, vision=True)
        diag["tried"].append({"model": cand, "status": status})
        if status == 200:
            return {"model": cand, "diag": diag}
    diag.setdefault("error", "该 key 下视觉候选全部不可用（无额度/不支持）")
    return {"model": None, "diag": diag}


async def discover_chat_model(api_key: str, api_url: str = "",
                              prefer_light: bool = False) -> dict:
    """对话模型自动发现：逐个发最小 chat 请求真实测。

    prefer_light=True 用于【直播弹幕模型】：轻量/便宜模型优先排序，避免高频调用烧 token。
    """
    diag = {"candidates": [], "tried": [], "discover": True}
    if not api_key:
        diag["error"] = "未配置 API Key"
        return {"model": None, "diag": diag}
    models, err = await _fetch_models(api_key, api_url)
    if models is None:
        diag["error"] = f"模型列表请求失败 {err}"
        return {"model": None, "diag": diag}
    cands = _chat_candidates_from_models(models, prefer_light=prefer_light)
    diag["candidates"] = cands
    for cand in cands:
        status, _txt = await _probe_chat_completion(api_key, api_url, cand, vision=False)
        diag["tried"].append({"model": cand, "status": status})
        if status == 200:
            return {"model": cand, "diag": diag}
    diag.setdefault("error", "该 key 下对话候选全部不可用（无额度/不支持）")
    return {"model": None, "diag": diag}


# ───────────────────────── 引擎实现 ─────────────────────────

class CosyVoiceEngine:
    """云端 TTS 引擎（通用适配层驱动）。

    名字沿用 cosyvoice（历史原因），但它不再是"只认阿里云 cosyvoice"：
    端点、协议、模型名、嗓音全部来自配置，可指向任何兼容服务商。
    """

    name = "cosyvoice"

    def available(self) -> bool:
        try:
            import aiohttp  # noqa: F401
            return True
        except Exception:
            return False

    async def asynth(self, text: str, model: str, voice: str, timeout: int = 60) -> Optional[bytes]:
        # 全部走通用适配层：端点/协议/嗓音由配置驱动，模型名原样透传（零路由、零前缀）。
        # voice 原样透传（留空由 cloud_tts_synth 按本次 model 家族给默认）——
        # 不得用配置里的嗓音兜底：override 场景本次 model 可能与配置模型不同族，
        # 拿配置嗓音（如 longfeifei_v3）喂 qwen 模型会 403/411。
        tts = resolve_tts_config()
        return await cloud_tts_synth(
            api_key=tts.get("api_key", ""), api_url=tts.get("api_url", ""),
            model=model or tts.get("model", ""), voice=voice or "",
            text=text, timeout=timeout)

    def synth_sync(self, text: str, model: str, voice: str, timeout: int = 60) -> Optional[bytes]:
        """同步实现（requests），供纯同步上下文（如 voice_input）使用。同样走通用适配层。"""
        tts = resolve_tts_config()
        return cloud_tts_synth_sync(
            api_key=tts.get("api_key", ""), api_url=tts.get("api_url", ""),
            model=model or tts.get("model", ""), voice=voice or "",
            text=text, timeout=timeout)


class EdgeTTSEngine:
    """微软 Edge-TTS（云端兜底，保证总有声音）。"""

    name = "edge_tts"

    def available(self) -> bool:
        try:
            import edge_tts  # noqa: F401
            return True
        except Exception:
            return False

    async def asynth(self, text: str, model: str, voice: str, timeout: int = 60) -> Optional[bytes]:
        try:
            import edge_tts
            tmp = os.path.join(tempfile.gettempdir(), f"tts_router_{int(asyncio.get_event_loop().time()*1000)}.mp3")
            communicate = edge_tts.Communicate(text, voice or EDGE_TTS_VOICE)
            await communicate.save(tmp)
            with open(tmp, "rb") as f:
                data = f.read()
            try:
                os.remove(tmp)
            except Exception:
                pass
            return data
        except Exception as e:
            log.warning(f"[tts_router] Edge-TTS 合成失败: {e}")
        return None

    def synth_sync(self, text: str, model: str, voice: str, timeout: int = 60) -> Optional[bytes]:
        # edge_tts 仅 async，同步上下文不支持；返回 None 让调用方用 async 接口。
        return None


class KokoroEngine:
    """本地 TTS（kokoro-onnx，纯 ONNX 推理，无需 torch）。

    可选引擎：装了 `kokoro_onnx` + `onnxruntime` 才注册。下载的模型/音色锁在 D 盘
    TTS_MODEL_DIR，首次使用自动从 GitHub release（thewh1teagle/kokoro-onnx）拉取，
    用 urllib 走系统证书链，规避 huggingface_hub 的 SSL 问题。
    断网或云端引擎失败时由故障转移链兜底，保证「无 key / 无网也能出声」。
    注意：依赖 espeak-ng（由 espeakng_loader 提供），并已打上 _patch_espeak_voices
    绕过其全局初始化缺陷。
    """

    name = "kokoro"

    def __init__(self):
        self._pipe = None

    def available(self) -> bool:
        try:
            import kokoro_onnx  # noqa: F401
            import onnxruntime  # noqa: F401
            return True
        except Exception:
            return False

    def _ensure(self):
        """懒加载 kokoro 推理管线（首次触发模型下载到 D 盘缓存）。"""
        if self._pipe is None:
            from kokoro_onnx import Kokoro
            from kokoro_onnx.config import EspeakConfig
            os.makedirs(TTS_MODEL_DIR, exist_ok=True)
            model_path = os.path.join(TTS_MODEL_DIR, KOKORO_MODEL_FILE)
            voices_path = os.path.join(TTS_MODEL_DIR, KOKORO_VOICES_FILE)
            if not os.path.exists(model_path):
                _download_file(KOKORO_MODEL_URL, model_path)
            if not os.path.exists(voices_path):
                _download_file(KOKORO_VOICES_URL, voices_path)
            # espeak-ng 数据/库目录在某些环境下无法自动解析，显式指定避免
            # "phontab not found" 与语言枚举失败（首次调用必须拿到正确路径）。
            espeak_cfg = EspeakConfig()
            try:
                import espeakng_loader
                espeak_cfg.data_path = espeakng_loader.get_data_path()
                espeak_cfg.lib_path = espeakng_loader.get_library_path()
            except Exception:
                pass
            self._pipe = Kokoro(model_path, voices_path, espeak_config=espeak_cfg)
            # 关键：绕过 espeak 全局初始化缺陷（见 _patch_espeak_voices 注释）。
            # 必须在 Kokoro() 构造之后立即调用，保证缓存的是首个（成功的）实例。
            _patch_espeak_voices()
        return self._pipe

    async def asynth(self, text: str, model: str, voice: str, timeout: int = 60) -> Optional[bytes]:
        try:
            kk = self._ensure()
            import soundfile as sf
            import io
            import numpy as np
            v = voice or ZH_DEFAULT_VOICE
            # 音色前缀判定语言（中文在 phonemizer 里是 'cmn'，见 _kokoro_lang_for_voice）
            lang = _kokoro_lang_for_voice(v)
            samples, sr = kk.create(text, voice=v, speed=1.0, lang=lang)
            buf = io.BytesIO()
            sf.write(buf, np.asarray(samples, dtype=np.float32), int(sr), format="WAV")
            return buf.getvalue()
        except Exception as e:
            log.warning(f"[tts_router] Kokoro 合成失败: {e}")
        return None

    def synth_sync(self, text: str, model: str, voice: str, timeout: int = 60) -> Optional[bytes]:
        try:
            kk = self._ensure()
            import soundfile as sf
            import io
            import numpy as np
            v = voice or ZH_DEFAULT_VOICE
            lang = _kokoro_lang_for_voice(v)
            samples, sr = kk.create(text, voice=v, speed=1.0, lang=lang)
            buf = io.BytesIO()
            sf.write(buf, np.asarray(samples, dtype=np.float32), int(sr), format="WAV")
            return buf.getvalue()
        except Exception as e:
            log.warning(f"[tts_router] Kokoro 同步合成失败: {e}")
        return None


def _download_file(url: str, dest: str):
    """从 GitHub release 下载模型文件到 D 盘缓存（用 urllib 走系统证书链，规避 huggingface_hub 的 SSL 问题）。"""
    import urllib.request as _u
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    log.info(f"[tts_router] 下载 kokoro 模型: {url}")
    with _u.urlopen(url, timeout=300) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    log.info(f"[tts_router] 模型已就绪: {dest} ({os.path.getsize(dest)} bytes)")


# ───────────────────────── 引擎注册表（自动发现） ─────────────────────────

def _build_registry() -> dict:
    reg = {}
    for eng in (CosyVoiceEngine(), EdgeTTSEngine(), KokoroEngine()):
        if eng.available():
            reg[eng.name] = eng
        else:
            if eng.name == "kokoro":
                log.info("[tts_router] Kokoro 未安装，跳过注册（不影响其他引擎）")
            else:
                log.warning(f"[tts_router] 引擎 {eng.name} 依赖缺失，不可用")
    return reg


_REGISTRY: Optional[dict] = None


def registry() -> dict:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def _parse_model(model: Optional[str]):
    """把 model 串解析为 (provider, model_id)。无 '/' 时按引擎名处理。"""
    if not model:
        return None, None
    if "/" in model:
        p, m = model.split("/", 1)
        return p.strip().lower(), m.strip()
    return model.strip().lower(), None


def _default_model_for(provider: str) -> str:
    if provider == "cosyvoice":
        return resolve_tts_config().get("model", "cosyvoice-v3-flash")
    if provider == "edge_tts":
        return EDGE_TTS_VOICE
    if provider == "kokoro":
        return ZH_DEFAULT_VOICE
    return ""


# ───────────────────────── 公开路由接口 ─────────────────────────

async def asynthesize(text: str, model: Optional[str] = None, voice: Optional[str] = None,
                      fallback: Optional[list] = None, timeout: int = 60) -> Optional[TTSResult]:
    """异步合成。返回 TTSResult，全失败返回 None。

    model 形如 "cosyvoice/cosyvoice-v3-flash"；省略则按 fallback 链依次尝试。
    """
    if not text:
        return None
    reg = registry()
    fallback = fallback or DEFAULT_FALLBACK

    # 1) 显式指定 provider/model
    provider, model_id = _parse_model(model)
    raw_model = None
    if provider:
        eng = reg.get(provider)
        if eng is None:
            # 未知 provider（用户直接填的裸模型名，如 qwen-audio-3.0-tts-flash，无 '/' 前缀）
            # → 当 raw model 走 cosyvoice 引擎做协议自适应（qwen-audio 与 cosyvoice 共用 SpeechSynthesizer 端点）
            if model and "/" not in model:
                raw_model = model
                log.info(f"[tts_router] 裸模型名 {model} 按 cloud TTS 引擎处理")
            else:
                log.warning(f"[tts_router] 未知/不可用引擎 {provider}，走 fallback")
        else:
            model_id = model_id or _default_model_for(provider)
            fmt = "wav" if provider in ("cosyvoice", "kokoro") else "mp3"
            audio = await eng.asynth(text, model_id, voice or "", timeout=timeout)
            if audio:
                return TTSResult(audio=audio, format=fmt, engine=provider, model=f"{provider}/{model_id}",
                                  voice=voice or _default_model_for(provider) if provider == "edge_tts" else (voice or _default_voice_for_model(model_id)))
            log.warning(f"[tts_router] 引擎 {provider} 合成失败，尝试 fallback")

    # 2) fallback 链
    for prov in fallback:
        eng = reg.get(prov)
        if eng is None:
            continue
        # 裸模型名（如 qwen-audio-3.0-tts-flash）只在 cloud TTS 引擎上生效，否则用该引擎默认模型
        mid = raw_model if (raw_model and prov == "cosyvoice") else _default_model_for(prov)
        fmt = "wav" if prov in ("cosyvoice", "kokoro") else "mp3"
        try:
            audio = await eng.asynth(text, mid, voice or "", timeout=timeout)
        except Exception as e:
            # 单引擎异常（如配置解析 NameError）绝不能炸掉整条降级链
            log.warning(f"[tts_router] 引擎 {prov} 抛异常，跳过: {e}")
            continue
        if audio:
            return TTSResult(audio=audio, format=fmt, engine=prov, model=f"{prov}/{mid}",
                              voice=voice or (EDGE_TTS_VOICE if prov == "edge_tts" else _default_voice_for_model(mid)))
    log.error("[tts_router] 所有引擎均失败")
    return None


def synthesize(text: str, model: Optional[str] = None, voice: Optional[str] = None,
               timeout: int = 60) -> Optional[TTSResult]:
    """同步合成。仅 CosyVoice / Kokoro 支持同步（Edge-TTS 仅 async）。
    用于纯同步上下文（如 voice_input）。"""
    if not text:
        return None
    reg = registry()

    provider, model_id = _parse_model(model)
    # 同步路径只允许 cosyvoice / kokoro
    if provider and provider in ("cosyvoice", "kokoro"):
        eng = reg.get(provider)
        if eng is not None:
            mid = model_id or _default_model_for(provider)
            fmt = "wav"
            audio = eng.synth_sync(text, mid, voice or "", timeout=timeout)
            if audio:
                return TTSResult(audio=audio, format=fmt, engine=provider, model=f"{provider}/{mid}",
                                  voice=voice or COSYVOICE_VOICE)
            log.warning(f"[tts_router] 同步引擎 {provider} 失败")
            return None

    # 未指定或指定了 edge_tts（无同步实现）→ 用 asyncio 跑 cosyvoice 同步兜底
    eng = reg.get("cosyvoice")
    if eng is not None:
        mid = _default_model_for("cosyvoice")
        audio = eng.synth_sync(text, mid, voice or "", timeout=timeout)
        if audio:
            return TTSResult(audio=audio, format="wav", engine="cosyvoice", model=f"cosyvoice/{mid}",
                              voice=voice or COSYVOICE_VOICE)
    log.error("[tts_router] 同步合成失败（无可用同步引擎）")
    return None


# 便捷：直接拿 base64（兼容 voice_input._tts 旧签名）
def synthesize_b64(text: str, model: Optional[str] = None, voice: Optional[str] = None,
                   timeout: int = 60) -> str:
    res = synthesize(text, model=model, voice=voice, timeout=timeout)
    if res and res.audio:
        return base64.b64encode(res.audio).decode()
    return ""


# ───────── 音色清单：内置预置音色 + 该 key 的复刻音色（供前端下拉选择） ─────────
# dashscope 没有"预置音色查询 API"（官方只有复刻音色的 list_voice），故预置音色
# 采用内置清单（来自官方音色表，用户仍可自由输入任意音色名——清单只是选项，不是限制）。
PRESET_VOICES = {
    "cosyvoice 系（cosyvoice-v2/v3 及 plus）": [
        "longfeifei_v3", "longshu_v3", "longhua_v3", "longwen_v3", "longxing_v3",
        "longxiaochun", "longxiaoxia", "longyuan", "longwan", "longjielidou",
        "loongbella", "loongstella", "longanrou", "longqiang", "longshu",
    ],
    "qwen-audio 系（qwen-audio-3.0-tts-flash/plus）": [
        "longanhuan_v3.6", "longwan_v3.6", "longxiaochun_v3.6", "longyuan_v3.6",
        "longfeifei_v3.6", "longshu_v3.6",
    ],
}


async def list_tts_voices(api_key: str) -> dict:
    """返回可选音色清单：内置预置音色（按模型家族分组）+ 该 key 已复刻的音色（真实拉取）。"""
    groups = [{"family": k, "voices": list(v)} for k, v in PRESET_VOICES.items()]
    cloned = []
    if api_key:
        try:
            import aiohttp
            url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
            payload = {"model": "voice-enrollment",
                       "input": {"action": "list_voice", "prefix": "",
                                 "page_index": 0, "page_size": 50}}
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json=payload, headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 200:
                        out = ((await r.json(content_type=None)) or {}).get("output") or {}
                        for it in out.get("voice_list") or []:
                            vid = it.get("voice_id") or it.get("voice")
                            if vid:
                                cloned.append(vid)
        except Exception as e:
            log.warning(f"[tts_router] 复刻音色列表拉取失败（忽略）: {e}")
    if cloned:
        groups.append({"family": "我的复刻音色（此 key）", "voices": cloned})
    return {"groups": groups}
