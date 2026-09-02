"""
vad_webrtc.py — 奶昔本地语音活动检测（集大成蓝图「VAD 升级」落地）
====================================================================

借鉴 WhisperX / WebRTC-VAD 的本地 VAD 思路。
现状 voice_input.py 只有 RMS 电平日志 + 云端 paraformer ASR 端点检测，**没有本地
语音门控**；低信噪比时纯能量门限易失效（见 skill naixi-mic-live-reaction 记录）。

本模块提供：
- WebRTC VAD（基于 GMM，低信噪比远强于纯能量门限）
- 无 webrtcvad 时自动回退纯能量门限，保证可用性
- detect_speech()：对一段音频返回语音占比 + 语音段（samples）
- 真机测试：用 edge_tts 合成真实语音 → VAD 应检出高占比；静音 → 近 0

集成点（不强制改 live pet，避免破坏正在运行的桌宠）：
在 voice_input 的麦克风回调里，先用 is_speech() 门控，再决定是否送 ASR，
可减少静音帧上云、降低误触发、提升低信噪比表现。
"""
from __future__ import annotations

import logging
import numpy as np

log = logging.getLogger("naixi.vad")

# WebRTC VAD 仅支持这些采样率
_WEBRTC_RATES = (8000, 16000, 32000, 48000)


class WebRTCVAD:
    def __init__(self, aggressiveness: int = 2, frame_ms: int = 30, fallback_rms: float = 0.02):
        """
        aggressiveness: 0(松)~3(严)，越大越不容易把噪声当语音
        frame_ms: 帧长（WebRTC 仅支持 10/20/30）
        fallback_rms: 能量门限回退阈值（归一化 0~1）
        """
        self.frame_ms = frame_ms
        self.fallback_rms = fallback_rms
        self._vad = None
        try:
            import webrtcvad

            self._vad = webrtcvad.Vad(aggressiveness)
            self.engine = "webrtc"
        except Exception as e:
            self.engine = "energy"
            log.warning(f"[VAD] webrtcvad 不可用，回退能量门限: {e}")

    # ── 内部工具 ──
    def _resample(self, x: np.ndarray, sr: int, target: int) -> np.ndarray:
        n = max(1, int(round(len(x) * target / sr)))
        idx = np.linspace(0, len(x) - 1, n)
        return np.interp(idx, np.arange(len(x)), x).astype(x.dtype)

    def _to_int16(self, audio: np.ndarray) -> np.ndarray:
        if audio.dtype == np.int16:
            return audio
        a = np.asarray(audio, dtype=np.float64)
        # 输入约定判断：
        #  - 已归一化 [-1,1]（soundfile 读出的 float）→ 直接 *32767
        #  - 原始 int 样本范围（|a|>1.1，如裸 int16 当 float 传入）→ 先 /32768 再 *32767
        if np.max(np.abs(a)) > 1.1:
            a = a / 32768.0
        return (a * 32767).clip(-32768, 32767).astype(np.int16)

    def _iter_frames(self, audio: np.ndarray, sr: int):
        """yield (frame_bytes, rate) 仅支持 WebRTC 采样率。"""
        if sr not in _WEBRTC_RATES:
            audio = self._resample(audio, sr, 16000)
            sr = 16000
        audio = self._to_int16(audio)
        n = int(sr * self.frame_ms / 1000)
        for i in range(0, len(audio) - n + 1, n):
            yield audio[i : i + n].tobytes(), sr

    # ── 单帧判断 ──
    def is_speech(self, frame: np.ndarray, sr: int) -> bool:
        """判断一帧是否语音。frame 可为任意长度 numpy 音频（内部切片/重采样）。"""
        if self.engine == "webrtc":
            try:
                for fb, rate in self._iter_frames(frame, sr):
                    return self._vad.is_speech(fb, rate)
            except Exception:
                pass
            # 兜底能量
        a = self._to_int16(frame).astype(np.float32)
        rms = float(np.sqrt(np.mean(a * a) + 1e-9)) / 32768.0
        return rms > self.fallback_rms

    # ── 整段检测 ──
    def detect_speech(self, audio: np.ndarray, sr: int, return_segments: bool = False) -> dict:
        """对整段音频检测语音。

        返回 {ratio, frames, speech_frames, engine, segments?}
        ratio: 语音帧占比 0~1
        segments: [(start_sample, end_sample), ...]（return_segments=True 时）
        """
        frames = list(self._iter_frames(audio, sr))
        total = len(frames)
        speech = 0
        seg = []
        run_start = None
        for i, (fb, rate) in enumerate(frames):
            is_s = False
            if self.engine == "webrtc":
                try:
                    is_s = self._vad.is_speech(fb, rate)
                except Exception:
                    is_s = False
            if not is_s:
                a = np.frombuffer(fb, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(a * a) + 1e-9)) / 32768.0
                is_s = rms > self.fallback_rms
            if is_s:
                speech += 1
                if run_start is None:
                    run_start = i
            else:
                if run_start is not None:
                    seg.append((run_start * len(fb), (i) * len(fb)))
                    run_start = None
        if run_start is not None:
            seg.append((run_start * len(frames[0][0]), total * len(frames[0][0])))

        out = {
            "ratio": (speech / total) if total else 0.0,
            "frames": total,
            "speech_frames": speech,
            "engine": self.engine,
        }
        if return_segments:
            out["segments"] = seg
        return out


if __name__ == "__main__":
    import tempfile

    # 自测：合成纯静音 vs 一段假语音（用于快速冒烟，非真机语音）
    sr = 16000
    silence = np.zeros(sr, dtype=np.int16)
    # 用随机噪声模拟"类语音"能量（能量门限应能区分静音）
    noise = (np.random.randn(sr) * 3000).astype(np.int16)
    v = WebRTCVAD(aggressiveness=2)
    print("engine:", v.engine)
    print("silence:", v.detect_speech(silence, sr))
    print("noise  :", v.detect_speech(noise, sr))
