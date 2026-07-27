"""VTS 风格全局热键 — 系统级键盘监听 → 触发 Live2D 模型动作/表情。

设计要点：
- 热键配置存 SQLite（desktop_core.storage），语义标签对应 avatarDriver 的
  ACTION_KEYWORDS / EMOTION_KEYWORDS，跨模型通用（不同模型用模糊匹配命中各自 motion/expression）。
- 命中后通过 live_engine.live2d_broadcast 广播 {type: avatar_motion|avatar_expression}，
  前端 PetWindow 已能处理这两类 WS 消息 → 无需改渲染逻辑。
- 全局监听用 pynput（可选依赖）：系统级生效，即使桌宠窗口未聚焦也能触发（VTS 同款体验）。
  pynput 不可用时 GLOBAL_LISTENER_ACTIVE=False，由前端 PetWindow 的窗口内 keydown 兜底。
"""
import asyncio
import logging
import threading

log = logging.getLogger("desktop")

GLOBAL_LISTENER_ACTIVE = False
_ACTIVE_MAP: dict = {}
_LOOP = None
_listener = None

_MOD_SET = {
    "ctrl", "alt", "shift", "meta",
}


def _key_name(key) -> str:
    """pynput Key/KeyCode → 归一化字符串（与前端 DOM 归一化保持一致）。"""
    # 字符键
    if hasattr(key, "char") and key.char:
        return key.char.lower()
    # 特殊键
    name = getattr(key, "name", None)
    if name:
        return name.lower()
    return ""


def _build_combo(mods: set, name: str) -> str:
    parts = sorted(m for m in mods if m in _MOD_SET)
    parts.append(name)
    return "+".join(parts)


def _mod_of(key):
    mapping = {
        "ctrl": "ctrl", "alt": "alt", "shift": "shift", "cmd": "meta",
    }
    name = getattr(key, "name", None)
    if name in mapping:
        return mapping[name]
    return None


async def _broadcast(payload: dict):
    try:
        from desktop_core.live_engine import engine
        if not getattr(engine, "_live2d_clients", None):
            return
        await engine.live2d_broadcast(payload)
    except Exception as e:
        log.warning(f"[HOTKEY] 广播失败: {e}")


def _fire(combo: str):
    entry = _ACTIVE_MAP.get(combo)
    if not entry:
        return
    kind = entry.get("kind", "motion")
    label = entry.get("label", "")
    if kind == "expression":
        payload = {"type": "avatar_expression", "emotion": label}
    else:
        payload = {"type": "avatar_motion", "action": label}
    log.info(f"[HOTKEY] 命中 {combo} → {kind}:{label}")
    if _LOOP is not None:
        asyncio.run_coroutine_threadsafe(_broadcast(payload), _LOOP)
    else:
        # 无事件循环则丢弃（极端兜底）
        log.warning("[HOTKEY] 无事件循环，跳过广播")


def _start_pynput():
    global _listener
    try:
        from pynput import keyboard
    except Exception as e:
        log.warning(f"[HOTKEY] pynput 不可用（{e}），全局热键停用；前端窗口内 keydown 兜底生效")
        return False

    mods = set()

    def on_press(key):
        m = _mod_of(key)
        if m:
            mods.add(m)
            return
        name = _key_name(key)
        if not name:
            return
        combo = _build_combo(mods, name)
        try:
            _fire(combo)
        except Exception:
            pass

    def on_release(key):
        m = _mod_of(key)
        if m and m in mods:
            mods.discard(m)

    _listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    _listener.daemon = True
    _listener.start()
    return True


def reload_hotkeys():
    """从 SQLite 重新加载活跃热键映射（配置变更后调用）。"""
    global _ACTIVE_MAP
    try:
        from desktop_core.storage import hotkey_get_active_map
        _ACTIVE_MAP = hotkey_get_active_map()
        log.info(f"[HOTKEY] 已加载 {len(_ACTIVE_MAP)} 条活跃热键")
    except Exception as e:
        log.warning(f"[HOTKEY] 加载配置失败: {e}")
        _ACTIVE_MAP = {}


def init_hotkeys():
    """启动时初始化：种子默认热键 + 加载配置 + 启动全局监听（若可用）。"""
    global GLOBAL_LISTENER_ACTIVE, _LOOP
    try:
        from desktop_core.storage import hotkey_seed_defaults
        hotkey_seed_defaults()
    except Exception as e:
        log.warning(f"[HOTKEY] 种子默认热键失败: {e}")
    reload_hotkeys()
    try:
        _LOOP = asyncio.get_event_loop()
    except Exception:
        _LOOP = None
    if _start_pynput():
        GLOBAL_LISTENER_ACTIVE = True
        log.info("[HOTKEY] 全局热键监听已启动（pynput）")
    else:
        GLOBAL_LISTENER_ACTIVE = False
