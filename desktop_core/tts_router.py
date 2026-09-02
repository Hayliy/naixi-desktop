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

# ───────────────────────── 本地 TTS（kokoro-onnx）配置 ─────────────────────────
# 模型缓存默认放在「应用根目录/naixi_tts_models」下，随安装包便携移动，
# 始终位于 resources/ 之外（**不会被打包进安装包**），且不写 C 盘
# （符合「禁止往 C 盘写数据」铁则）。可用 NAT_TTS_MODEL_DIR 覆盖
# （如指向共享盘上已下载好的模型，避免每台机器重复下载）。
#
# 路径解析同时兼容两种布局，但**无论哪种都把模型放在 resources/ 之外**：
#   * 开发态：desktop_core/tts_router.py → 父目录即项目根（D:/naixi_desktop）
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
    - 优先 desktop_config 里 type=audio 的真密钥供应商；
    - 但其密钥为空或掩码(_KEY_MASK)时**跳过**，回退到 dashscope_api_key / 环境变量，
      绝不能让掩码把真密钥盖掉。
    """
    cfg = {
        "api_key": "",
        "api_url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2audio/cosyvoice",
        "model": "cosyvoice-v3-flash",
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
                        if pcfg.get("model"):
                            cfg["model"] = pcfg["model"]
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
        cfg["api_key"] = os.environ.get("DASHSCOPE_API_KEY", "")
    return cfg


# ───────────────────────── 引擎实现 ─────────────────────────

class CosyVoiceEngine:
    """阿里云百炼 CosyVoice（dashscope 端点 / OpenAI 兼容端点）。"""

    name = "cosyvoice"

    def available(self) -> bool:
        try:
            import aiohttp  # noqa: F401
            return True
        except Exception:
            return False

    async def asynth(self, text: str, model: str, voice: str, timeout: int = 60) -> Optional[bytes]:
        tts = resolve_tts_config()
        if not tts["api_key"]:
            return None
        api_key, api_url = tts["api_key"], tts["api_url"]
        is_dashscope = "dashscope" in api_url or "aliyuncs" in api_url
        try:
            import aiohttp
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            if is_dashscope:
                tts_url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
                payload = {"model": model, "input": {"text": text, "voice": voice or COSYVOICE_VOICE,
                                                      "format": "wav", "sample_rate": COSYVOICE_SR}}
                async with aiohttp.ClientSession(headers=headers) as session:
                    async with session.post(tts_url, json=payload, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            output = result.get("output", {})
                            audio_url = output.get("audio", {}).get("url", "")
                            if audio_url:
                                async with aiohttp.ClientSession() as dl:
                                    async with dl.get(audio_url, timeout=aiohttp.ClientTimeout(total=30)) as ar:
                                        if ar.status == 200:
                                            return await ar.read()
                            else:
                                data = output.get("audio", {}).get("data") or output.get("data")
                                if data:
                                    return base64.b64decode(data)
            else:
                tts_url = api_url.rstrip("/") + "/audio/speech"
                payload = {"model": model, "input": text, "voice": voice or "alloy", "response_format": "wav"}
                async with aiohttp.ClientSession(headers=headers) as s:
                    async with s.post(tts_url, json=payload, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                        if r.status == 200:
                            return await r.read()
        except Exception as e:
            log.warning(f"[tts_router] CosyVoice 合成失败: {e}")
        return None

    def synth_sync(self, text: str, model: str, voice: str, timeout: int = 60) -> Optional[bytes]:
        """同步实现（requests），供纯同步上下文（如 voice_input）使用。"""
        tts = resolve_tts_config()
        if not tts["api_key"]:
            return None
        api_key, api_url = tts["api_key"], tts["api_url"]
        try:
            import requests
            url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
            hdr = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"model": model, "input": {"text": text, "voice": voice or COSYVOICE_VOICE,
                                                  "format": "wav", "sample_rate": COSYVOICE_SR}}
            r = requests.post(url, json=payload, headers=hdr, timeout=timeout)
            if r.status_code == 200:
                out = r.json().get("output", {})
                u = out.get("audio", {}).get("url", "")
                if u:
                    ad = requests.get(u, timeout=30).content
                    return ad or None
                data = out.get("audio", {}).get("data") or out.get("data")
                if data:
                    return base64.b64decode(data) if isinstance(data, str) else data
            else:
                log.warning(f"[tts_router] CosyVoice HTTP {r.status_code}: {r.text[:160]}")
        except Exception as e:
            log.warning(f"[tts_router] CosyVoice 同步合成失败: {e}")
        return None


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
    if provider:
        eng = reg.get(provider)
        if eng is None:
            log.warning(f"[tts_router] 未知/不可用引擎 {provider}，走 fallback")
        else:
            model_id = model_id or _default_model_for(provider)
            fmt = "wav" if provider in ("cosyvoice", "kokoro") else "mp3"
            audio = await eng.asynth(text, model_id, voice or "", timeout=timeout)
            if audio:
                return TTSResult(audio=audio, format=fmt, engine=provider, model=f"{provider}/{model_id}",
                                  voice=voice or _default_model_for(provider) if provider == "edge_tts" else (voice or COSYVOICE_VOICE))
            log.warning(f"[tts_router] 引擎 {provider} 合成失败，尝试 fallback")

    # 2) fallback 链
    for prov in fallback:
        eng = reg.get(prov)
        if eng is None:
            continue
        mid = _default_model_for(prov)
        fmt = "wav" if prov in ("cosyvoice", "kokoro") else "mp3"
        audio = await eng.asynth(text, mid, voice or "", timeout=timeout)
        if audio:
            return TTSResult(audio=audio, format=fmt, engine=prov, model=f"{prov}/{mid}",
                              voice=voice or (EDGE_TTS_VOICE if prov == "edge_tts" else COSYVOICE_VOICE))
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
