"""Qt 桌宠独立语音输入模块 —— 完全不依赖后端 broadcast / connector / cue 链路。

闭环（全部在桌宠进程内完成）：
    麦克风采集(sounddevice) → 百炼云端 ASR(paraformer-realtime-v2)
    → 桌宠直接反应(气泡/表情/动作) → LLM 生成回复(qwen-turbo)
    → 百炼 TTS(covyvoice-v3-flash, HTTP 直连) → 桌宠播放。

设计原则（用户明确要求）：
- 不经过 inject_human_speech / _broadcast_cue / should_react_to_cue 概率衰减；
- 不连后端任何接口，桌宠自己闭环，单测失败即整体失败（无“其他链路”兜底）；
- 密钥与 TTS 与桌面端「语音模型」页共用同一百炼 Key（live_config.dashscope_api_key）。
"""
import os, json, logging, threading, queue, time, base64
log = logging.getLogger("pet_voice")


def _setup_pet_voice_log():
    """把桌宠语音日志写到 <项目根>/logs/pet_voice.log。

    桌宠是独立 pythonw 子进程，stderr 被丢弃，logging 又没配 handler，
    默认 lastResort 只打 WARNING 且进丢弃的 stderr——真机断点(ASR 连接/设备/
    识别)完全看不见。此函数补一个文件 handler，让『说话没反应』可诊断。
    """
    lg = logging.getLogger("pet_voice")
    if lg.handlers:
        return
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        root = here
        for _ in range(6):
            if os.path.exists(os.path.join(root, "data", "naixi_desktop.db")):
                break
            root = os.path.dirname(root)
        logdir = os.path.join(root, "logs")
        os.makedirs(logdir, exist_ok=True)
        fh = logging.FileHandler(os.path.join(logdir, "pet_voice.log"),
                                 encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"))
        lg.addHandler(fh)
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
    except Exception:
        pass


class PetVoiceInput:
    """桌宠语音输入采集器。reactor 实现 on_heard / on_reply / on_state / on_error。"""

    def __init__(self, reactor, device=None, sample_rate: int = 16000, input_gain: float = 1.0):
        self.reactor = reactor              # PetWindow（实现下方四个回调）
        self.device = device                # 麦克风索引/名称；None=自动选物理麦
        self.sample_rate = sample_rate
        self.input_gain = input_gain        # 麦克风数字增益（1.0=不变；>1 放大，<1 衰减）
        self._thread = None
        self._stop = threading.Event()
        self._running = False
        self._api_key = ""
        self._reco = None
        self._speaking = threading.Event()   # 播放 TTS 期间置位：麦帧全部丢弃，防扬声器回声被识别成说话
        self._history = []                  # 多轮对话上下文（最近若干轮 user/assistant）
        self._history_limit = 16            # 上下文最多保留条数（≈8 轮）
        self._lock = threading.Lock()       # 保护 history / 记忆读写，避免并发回复污染

    # ───────────────────────── 密钥（与 TTS 共用） ─────────────────────────
    def _load_key(self) -> bool:
        try:
            from desktop_core import storage
            self._ensure_db(storage)
            k = ""
            # 优先 audio 供应商真密钥（与后端 _resolve_tts_config 同口径）
            try:
                raw_dc = storage.meta_get("desktop_config")
                if raw_dc:
                    dc = json.loads(raw_dc)
                    from desktop_core.storage import _KEY_MASK
                    for _pid, _pc in dc.get("api_providers", {}).items():
                        if _pc.get("type") == "audio":
                            rk = _pc.get("api_key", "")
                            if isinstance(rk, str) and rk.startswith("enc:"):
                                rk = storage.decrypt_api_key(rk)
                            if rk and rk != _KEY_MASK:
                                k = rk
                                break
            except Exception:
                pass
            if not k:
                raw = storage.meta_get("live_config")
                cfg = json.loads(raw) if raw else {}
                k = cfg.get("dashscope_api_key", "")
                if isinstance(k, str) and k.startswith("enc:"):
                    k = storage.decrypt_api_key(k)
            self._api_key = k
            return bool(k)
        except Exception as e:
            log.warning(f"[桌宠语音] 读取密钥失败: {e}")
            return False

    @staticmethod
    def _ensure_db(storage):
        """桌宠是独立进程，需自己定位 data/naixi_desktop.db（后端在导入前设了 DB_PATH）。"""
        if storage.DB_PATH and os.path.exists(storage.DB_PATH):
            return
        here = os.path.dirname(os.path.abspath(__file__))
        d = here
        for _ in range(6):
            cand = os.path.join(d, "data", "naixi_desktop.db")
            if os.path.exists(cand):
                storage.DB_PATH = cand
                return
            d = os.path.dirname(d)
        storage.DB_PATH = os.path.join(here, "..", "data", "naixi_desktop.db")

    # ───────────────────────── 设备解析（跳过虚拟麦/Sound Mapper） ─────────────────────────
    def _resolve_device(self):
        if self.device is not None:
            try:
                return int(self.device)
            except (ValueError, TypeError):
                return self.device
        try:
            import sounddevice as sd
            devs = sd.query_devices()
            di = int(sd.default.device[0])
            VIRTUAL = ("virtual", "cable", "wo mic", "audiorelay", "vb-audio",
                       "voicemeeter", "sound mapper", "microsoft")
            if 0 <= di < len(devs):
                nm = (devs[di].get("name") or "").lower()
                if devs[di].get("max_input_channels", 0) > 0 and \
                   not any(v in nm for v in VIRTUAL):
                    return di
            for i, d in enumerate(devs):
                if d.get("max_input_channels", 0) > 0 and \
                   not any(v in (d.get("name") or "").lower() for v in VIRTUAL):
                    return i
        except Exception:
            pass
        return None

    # 输出环回设备的名字特征（不该出现在“可用麦克风”里，避免 A1~A5/B1~B3 迷惑用户）
    _OUT_LOOPBACK_HINTS = ("output", "out a", "out b")

    @staticmethod
    def _is_output_loopback(name: str) -> bool:
        """该名字是不是音频输出环回设备（不是麦克风，选了也没法听你说话）。"""
        n = (name or "").lower()
        return any(h in n for h in PetVoiceInput._OUT_LOOPBACK_HINTS)

    # ───────────────── 设备中文解释知识库（易扩展：新增设备家族只需加一行） ─────────────────
    # 每项：(匹配片段(小写), 输入侧解释, 输出侧解释)
    # 解释为 None 表示该侧不适用此规则，继续往后匹配；顺序越具体越靠前。
    _DEVICE_KB = [
        # VoiceMeeter —— 命名极易搞反：Input 是「应用把声音送进 VM」的入端；
        # Out B1 是「采集真人声」的总线；Output 是「VM 混音结果送出」的播放端。
        ("voicemeeter out b1", "你的人声总线：VM 把物理麦路由到 B1，选它收真人声、自动挡掉视频/直播声（看视频或直播最推荐）", None),
        ("voicemeeter out b",  "VM 额外人声总线(B2/B3)，一般不用", None),
        ("voicemeeter out a1", "系统/视频混合总线，不是纯人声，一般不作麦", None),
        ("voicemeeter out a",  "VM 输出总线，一般不作麦", None),
        ("voicemeeter vaio",   "VM 虚拟麦(VAIO)，一般不用；收真人声请选 Out B1", None),
        ("voicemeeter aux",    "VM 虚拟麦(AUX)，一般不用", None),
        ("voicemeeter input",  "VM 虚拟麦(播放端)，一般不用；收真人声请选 Out B1", "VM 输入端(把桌宠声音送进 VM 混音，随你一起推流/录屏·推荐)"),
        ("voicemeeter output", None, "VM 输出端(VM 混音结果由此出声，一般连着你的扬声器)"),
        # VB-Audio Cable / Virtual Audio Cable
        ("cable input",        "虚拟声卡输入(别人往里送声)，一般不用", "虚拟声卡输入端(把桌宠声音送进 CABLE，再转给直播/录制·推荐)"),
        ("cable output",       None, "虚拟声卡输出端(CABLE 已混好的声音由此出声，一般不选)"),
        ("virtual audio cable", "虚拟音频线(输入)", "虚拟音频线(输出)"),
        # 通用 VM / VB-Audio 兜底（某侧专用）
        ("voicemeeter",        None, "VM 虚拟音频设备(路由/混音用)"),
        ("vb-audio",           "VB-Audio 虚拟音频(路由/录制用)", "VB-Audio 虚拟音频(路由/录制用)"),
    ]

    # 芯片/厂商识别（物理声卡补充说明，越具体越靠前）
    _VENDOR_KB = [
        ("realtek",        "Realtek 板载声卡"),
        ("conexant",       "Conexant 声卡"),
        ("synaptics",      "Synaptics 声卡"),
        ("cirrus",         "Cirrus 声卡(多见于笔记本/苹果)"),
        ("creative",       "Creative 独立声卡"),
        ("sound blaster",  "Sound Blaster 声卡"),
        ("asus",           "华硕声卡"),
        ("supremefx",      "华硕 SupremeFX 声卡"),
        ("intel display",  "Intel 显卡 HDMI 音频"),
        ("nvidia",         "NVIDIA 显卡 HDMI 音频"),
        ("amd",            "AMD 显卡 HDMI 音频"),
        ("high definition audio", "高清声卡"),
    ]

    # 类别识别（按 kind 给角色说明，命中即代表设备用途）
    _CAT_OUTPUT = [
        ("扬声器", "放音设备(你听桌宠说话从这里出声)"),
        ("speaker", "放音设备(你听桌宠说话从这里出声)"),
        ("音箱", "放音设备"),
        ("耳机", "耳机(贴耳放音)"),
        ("headphone", "耳机(贴耳放音)"),
        ("headset", "耳麦(带麦)"),
        ("显示器", "显示器内置音响"),
        ("monitor", "显示器内置音响"),
        ("蓝牙", "蓝牙放音设备"),
        ("bluetooth", "蓝牙放音设备"),
        ("bt ", "蓝牙放音设备"),
        ("hdmi", "显卡 HDMI 接的音响/电视"),
        ("displayport", "显卡 DP 接的音响/电视"),
        ("电视", "电视"),
        ("tv", "电视"),
    ]
    _CAT_INPUT = [
        ("麦克风", "收音设备(收你的声音)"),
        ("microphone", "收音设备(收你的声音)"),
        (" mic", "收音设备(收你的声音)"),
        ("阵列", "阵列麦(笔记本内置)"),
        ("array", "阵列麦(笔记本内置)"),
        ("摄像头", "摄像头麦"),
        ("camera", "摄像头麦"),
        ("webcam", "摄像头麦"),
        ("headset", "耳麦麦"),
    ]

    # 虚拟设备签名（未知品牌的虚拟声卡也能识别）
    _VIRTUAL_SIG = ("virtual", "voicemeeter", "vb-audio", "cable", "vac",
                    "wo mic", "audiorelay", "blackhole", "soundflower", "jack audio")

    @staticmethod
    def describe_audio_device(name: str, kind: str) -> str:
        """把任意音频设备名翻译成中文可读解释（输入/输出通用，未来新设备也自动归类）。

        kind: "input"=麦克风(采集) / "output"=扬声器(播放)。
        返回 "原名（解释）"，解释永远不为空——即使从没见过的设备，也会按
        虚拟/物理/扬声器/麦克风等特征给出类别说明，不再把原始英文裸名丢给用户。
        """
        n = (name or "").strip()
        if not n:
            return "未知设备"
        low = n.lower()
        is_in = (kind == "input")
        # 1) 已知家族知识库（最具体优先，某侧不适用的规则跳过）
        for frag, in_expl, out_expl in PetVoiceInput._DEVICE_KB:
            if frag in low:
                expl = in_expl if is_in else out_expl
                if expl:
                    return f"{n}（{expl}）"
        # 2) 厂商/芯片识别
        vendor = ""
        for frag, v in PetVoiceInput._VENDOR_KB:
            if frag in low:
                vendor = v
                break
        # 3) 类别识别（按 kind 给角色说明）
        cat = ""
        table = PetVoiceInput._CAT_INPUT if is_in else PetVoiceInput._CAT_OUTPUT
        for frag, c in table:
            if frag in low:
                cat = c
                break
        # 4) 虚拟设备签名（覆盖未知虚拟品牌）
        is_virtual = any(s in low for s in PetVoiceInput._VIRTUAL_SIG)
        # 5) 组装解释（绝不裸名）
        parts = []
        if cat:
            parts.append(cat)
        if vendor:
            parts.append(vendor)
        if is_virtual and not parts:
            parts.append("虚拟音频设备(软件声卡，常用于路由/录制)")
        if not parts:
            parts.append("音频输入设备(麦克风类)" if is_in else "音频输出设备(扬声器/耳机类)")
        return f"{n}（{('，'.join(parts))}）"

    @staticmethod
    def friendly_input_label(name: str) -> str:
        """（兼容别名）输入设备中文解释。"""
        return PetVoiceInput.describe_audio_device(name, "input")

    @staticmethod
    def friendly_output_label(name: str) -> str:
        """（兼容别名）输出设备中文解释。"""
        return PetVoiceInput.describe_audio_device(name, "output")

    @staticmethod
    def list_input_devices(usable_only: bool = True, include_all: bool = False):
        """列出可用输入设备，供桌宠右键菜单选择采集设备。

        Windows 上 PortAudio 会把同一物理麦按 MME / DirectSound / WASAPI /
        WDM-KS 多个 host API 各列一次，名字一字不差 → 菜单刷满“重复”项。
        默认只返回 WASAPI 端点（现代 Windows 推荐、对 ASR 最稳；VoiceMeeter
        虚拟麦也只在 WASAPI 下以独特名字出现），彻底去重。

        usable_only=True（默认）：额外剔除“输出环回”设备（Voicemeeter Out
        A1~A5 / B1~B3、VoiceMeeter Output、CABLE Output 等），只留真正能当
        麦克风用的设备（物理麦 + VoiceMeeter Input 等虚拟输入），避免一堆
        A1~A5 让用户不知道选哪个。
        include_all=True：返回全部输入设备（跨 host API + 含环回），用于高级排查。

        返回 [(index, label, host_name), ...]。label 仅展示；真正传给采集的是
        index（全局唯一，不随 host 重复）。
        """
        try:
            import sounddevice as sd
            devs = sd.query_devices()
            hosts = sd.query_hostapis()

            def _host_name(hidx):
                try:
                    return hosts[hidx].get("name", "") if 0 <= hidx < len(hosts) else ""
                except Exception:
                    return ""

            wasapi_idx = None
            for i, h in enumerate(hosts):
                if "wasapi" in (h.get("name") or "").lower():
                    # 设备的 hostapi 字段值即该 host API 在列表中的位置索引
                    wasapi_idx = i
                    break

            out = []
            seen_names = set()  # 名称级去重兜底：同一物理麦在部分机器上可能以相同名字出现两次
            for i, d in enumerate(devs):
                if d.get("max_input_channels", 0) <= 0:
                    continue
                hidx = d.get("hostapi")
                if (not include_all) and wasapi_idx is not None and hidx != wasapi_idx:
                    continue  # 默认只留 WASAPI，剔除 MME/DirectSound/WDM-KS 复制品
                nm = d.get("name", f"device {i}")
                # 默认视图剔除「立体声混音/系统音频采集」这类很少用作桌宠麦的设备，减少干扰；
                # VM 的 B1/A1 等总线保留（B1 正是路由后承载你人声的采集设备，用户需要可选）
                if usable_only and not include_all:
                    _low = (nm or "").lower()
                    if "立体声混音" in (nm or "") or "stereo mix" in _low:
                        continue
                hn = _host_name(hidx)
                label = nm
                if include_all and hn:
                    label = f"{label}  ·  {hn}"   # 全量模式标注 host，便于区分同名
                _key = label.strip().lower()
                if _key in seen_names:
                    continue
                seen_names.add(_key)
                out.append((i, label, hn))
            if not out and not include_all:
                # 极端情况：本机无 WASAPI 或全被过滤，退回全部“非环回”输入设备
                for i, d in enumerate(devs):
                    if d.get("max_input_channels", 0) > 0 and not PetVoiceInput._is_output_loopback(d.get("name", "")):
                        out.append((i, d.get("name", f"device {i}"), _host_name(d.get("hostapi"))))
            return out
        except Exception:
            return []

    @staticmethod
    def list_output_devices(usable_only: bool = True, include_all: bool = False):
        """列出可用输出设备，供桌宠 TTS 播放选路（默认只列 WASAPI 端点，名称级去重）。"""
        try:
            import sounddevice as sd
            devs = sd.query_devices()
            hosts = sd.query_hostapis()

            wasapi_idx = None
            for i, h in enumerate(hosts):
                if "wasapi" in (h.get("name") or "").lower():
                    wasapi_idx = i
                    break

            out = []
            seen = set()
            for i, d in enumerate(devs):
                if d.get("max_output_channels", 0) <= 0:
                    continue
                hidx = d.get("hostapi")
                if (not include_all) and wasapi_idx is not None and hidx != wasapi_idx:
                    continue
                nm = d.get("name", f"device {i}")
                if nm.strip().lower() in seen:
                    continue
                seen.add(nm.strip().lower())
                out.append((i, nm))
            if not out and not include_all:
                for i, d in enumerate(devs):
                    if d.get("max_output_channels", 0) > 0:
                        out.append((i, d.get("name", f"device {i}")))
            return out
        except Exception:
            return []

    # ───────────────────────── 启停 ─────────────────────────
    def start(self) -> bool:
        _setup_pet_voice_log()
        if self._running:
            return True
        if not self._load_key():
            log.error("[桌宠语音] 未配置百炼 Key，语音输入不可用")
            self.reactor.on_error("未配置百炼 Key（与 TTS 同款），无法使用语音输入")
            return False
        self._running = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._running = False
        self._stop.set()

    # ───────────────────────── 主循环：采集 + ASR ─────────────────────────
    def _run(self):
        import time
        import sounddevice as sd
        import dashscope
        from dashscope.audio.asr import Recognition, RecognitionCallback
        dashscope.api_key = self._api_key
        dev_idx = self._resolve_device()
        self.reactor.on_state("listening", dev_idx)
        log.info(f"[桌宠语音] 进入聆听，采集设备={dev_idx}")
        SR = self.sample_rate
        outer = self

        class CB(RecognitionCallback):
            def on_event(self, result):
                if result is None:
                    return
                if result.get("header", {}).get("name") == "TaskFailed":
                    log.error(f"[桌宠语音] ASR 任务失败: {result}")
                    outer.reactor.on_error(f"ASR 任务失败: {result}")
                    return
                s = result.get_sentence()
                if not s:
                    return
                # dashscope 不同小版本 get_sentence() 可能返回 dict（文本在 .text）或 str
                txt = (s.get("text") if isinstance(s, dict) else str(s)).strip()
                if txt and result.is_sentence_end(s):
                    outer._on_sentence(txt)

        try:
            reco = Recognition(model="paraformer-realtime-v2", format="pcm",
                               sample_rate=SR, callback=CB())
            reco.start()
            outer._reco = reco
            log.info("[桌宠语音] ASR 已连接百炼云端")
            q: "queue.Queue" = queue.Queue()
            _rms_last = [0.0]
            _rms_acc = [0.0, 0]

            def _cb(indata, frames, t, status):
                if status:
                    log.warning(f"[桌宠语音] 音频回调状态: {status}")
                # 播放 TTS 期间丢弃麦克风帧，避免扬声器声音被麦捕获形成回声回路
                if outer._speaking.is_set():
                    return
                import numpy as _np
                a = _np.frombuffer(indata, dtype=_np.int16).astype(_np.float32)
                # 电平 RMS 日志（每秒一行）：≈0=无声，>300=正常说话。
                # 用于诊断“说话没反应”——有电平却无识别说明 ASR 端问题；恒≈0 说明采集设备没收到人声（选错设备）。
                rms = float(_np.sqrt(_np.mean(a * a) + 1e-9))
                _rms_acc[0] += rms
                _rms_acc[1] += 1
                now = time.time()
                if now - _rms_last[0] >= 1.0:
                    avg = _rms_acc[0] / max(1, _rms_acc[1])
                    log.info(f"[桌宠语音] 采集电平 RMS={avg:.1f}（≈0=无声，>300=正常说话）dev={dev_idx}")
                    _rms_last[0] = now
                    _rms_acc[0] = 0.0
                    _rms_acc[1] = 0
                # 麦克风数字增益（音量滑块 0-100 映射到 0.0-2.0；1.0 即不变）
                if outer.input_gain and outer.input_gain != 1.0:
                    a = a * outer.input_gain
                    a = _np.clip(a, -32768, 32767).astype(_np.int16)
                    q.put(a.tobytes())
                else:
                    q.put(bytes(indata))

            stream = sd.RawInputStream(device=dev_idx, samplerate=SR, blocksize=960,
                                       dtype="int16", channels=1, callback=_cb)
            with stream:
                while not outer._stop.is_set():
                    try:
                        data = q.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    reco.send_audio_frame(data)
        except Exception as e:
            log.error(f"[桌宠语音] 运行异常: {e}")
            self.reactor.on_error(f"语音识别异常: {e}")
        finally:
            try:
                if outer._reco:
                    outer._reco.stop()
            except Exception:
                pass
            outer._reco = None
            outer.reactor.on_state("stopped", None)

    # ───────────────────────── 句子处理：反应 + 回复 + TTS ─────────────────────────
    def _on_sentence(self, text: str):
        log.info(f"[桌宠语音] 识别到: {text}")
        self.reactor.on_heard(text)
        threading.Thread(target=self._respond, args=(text,), daemon=True).start()

    def _respond(self, text: str):
        with self._lock:
            reply = self._llm_reply(text)
            audio_b64 = self._tts(reply) if reply else ""
            self.reactor.on_reply(reply, audio_b64)
        # 记忆抽取异步进行，不阻塞本轮回复与上下文写入
        if reply:
            threading.Thread(target=self._extract_memories,
                             args=(text, reply), daemon=True).start()

    def _llm_reply(self, text: str) -> str:
        try:
            import dashscope
            from dashscope import Generation
            dashscope.api_key = self._api_key  # 独立设置，不依赖 _run 时序
            mem = self._load_memories(text)    # 按当前话题语义召回相关记忆
            sys_content = ("你是桌宠奶昔，一个可爱贴心的桌面伙伴。"
                           "用简短口语化中文回应，带情绪，不超过30字。")
            if mem:
                sys_content += f"\n【你已知关于用户的事】\n{mem}"
            messages = [{"role": "system", "content": sys_content}]
            # 注入多轮上下文（最近若干轮）
            for m in self._history[-self._history_limit:]:
                messages.append(m)
            messages.append({"role": "user", "content": text})
            r = Generation.call(model="qwen-turbo", messages=messages,
                                result_format="message")
            if r.status_code == 200:
                ans = r.output.choices[0].message.content.strip()
                self._history.append({"role": "user", "content": text})
                self._history.append({"role": "assistant", "content": ans})
                if len(self._history) > self._history_limit:
                    self._history = self._history[-self._history_limit:]
                return ans
        except Exception as e:
            log.warning(f"[桌宠语音] LLM 失败: {e}")
        return "嗯？我听到你说话啦~"

    def _tts(self, text: str) -> str:
        """百炼 TTS（HTTP 直连，复刻后端已验证写法 cosyvoice-v3-flash）。
        返回 base64 WAV；失败返回空串（桌宠仍会显示文字气泡）。"""
        if not self._api_key or not text:
            return ""
        try:
            import requests
            url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
            hdr = {"Authorization": f"Bearer {self._api_key}",
                   "Content-Type": "application/json"}
            payload = {"model": "cosyvoice-v3-flash",
                       "input": {"text": text, "voice": "longfeifei_v3",
                                 "format": "wav", "sample_rate": 24000}}
            r = requests.post(url, json=payload, headers=hdr, timeout=60)
            if r.status_code == 200:
                out = r.json().get("output", {})
                u = out.get("audio", {}).get("url", "")
                if u:
                    ad = requests.get(u, timeout=30).content
                    return base64.b64encode(ad).decode() if ad else ""
                data = out.get("audio", {}).get("data") or out.get("data")
                if data:
                    return data if isinstance(data, str) else base64.b64encode(data).decode()
            else:
                log.warning(f"[桌宠语音] TTS HTTP {r.status_code}: {r.text[:160]}")
        except Exception as e:
            log.warning(f"[桌宠语音] TTS 失败: {e}")
        return ""

    # ───────────────────────── 上下文 & 长期记忆层 ─────────────────────────
    # 记忆直接复用后端那套 agent_memory（storage.mem_*），与「桌面对话 / 直播 /
    # 弹幕」走同一张表、同一 viewer("主人") 维度——桌宠无论输入来自自己听麦还是
    # 直播链路，记忆都在一处，不割裂。仅共享 data/naixi_desktop.db 文件，不连后端进程。

    def _load_memories(self, query: str = "") -> str:
        """读长期记忆，token 预算内按优先级打包（画像>当日>语义召回）。

        复用后端 storage.mem_build_injection（与直播/桌面对话共用同一张表
        agent=naixi / viewer=主人），记忆互通；内部已做 token 估算 + 画像封顶
        + 优先级丢弃，解决「字符数当预算」与「画像无上限挤掉其它」两坑。
        """
        try:
            from desktop_core import storage
            self._ensure_db(storage)
            text, _used, _info = storage.mem_build_injection(
                "naixi", "主人", query=query, budget=800)
            return text
        except Exception as e:
            log.warning(f"[桌宠语音] 读记忆失败: {e}")
            return ""

    def _save_memory(self, content: str):
        """存一条稳定事实到 agent_memory（viewer=主人），mem_profile_set 自带去重。"""
        try:
            from desktop_core import storage
            self._ensure_db(storage)
            storage.mem_profile_set("naixi", "主人", content)
        except Exception as e:
            log.warning(f"[桌宠语音] 存记忆失败: {e}")

    def _extract_memories(self, text: str, reply: str):
        """对话后异步抽取值得长期记住的用户事实，存入记忆库（不阻塞回复）。"""
        try:
            import dashscope, json as _json
            from dashscope import Generation
            dashscope.api_key = self._api_key
            prompt = ("从下面的对话中抽取值得长期记住的关于用户的事实"
                      "（偏好、身份、习惯、重要信息）。只输出 JSON 数组，"
                      "元素为简短中文事实字符串；没有则输出 []，不要其他内容。\n"
                      f"用户：{text}\n桌宠：{reply}")
            r = Generation.call(model="qwen-turbo",
                                messages=[{"role": "user", "content": prompt}],
                                result_format="message")
            if r.status_code != 200:
                return
            raw = r.output.choices[0].message.content.strip()
            arr = _json.loads(raw)
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, str) and item.strip():
                        self._save_memory(item.strip())
        except Exception as e:
            log.warning(f"[桌宠语音] 记忆抽取失败: {e}")

    def clear_memory(self):
        """清空桌宠(主人维度)长期记忆与当前会话上下文（右键菜单调用）。"""
        try:
            from desktop_core import storage
            self._ensure_db(storage)
            conn = storage._get_conn()
            try:
                conn.execute("DELETE FROM agent_memory WHERE agent_id=? AND viewer_id=?",
                             ("naixi", "主人"))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            log.warning(f"[桌宠语音] 清空记忆失败: {e}")
        self._history = []
        log.info("[桌宠语音] 已清空桌宠记忆(主人维度)")
