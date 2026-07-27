"""渲染后端适配器层（AvatarBackend）。

四级驱动架构中的可编程后端实现：
- VTS（第1级）：留在 live_engine.py 的 VtsInstance 池（存量代码即 VtsBackend，不平移不重写）
- VmcBackend（第2级）：VMC 协议（OSC/UDP）驱动 VSeeFace/Warudo/VMagicMirror 等
- SelfRenderBackend（第0级/默认）：自研 Live2D 渲染（前端 PetWindow / 多角色舞台画布）
- 虚拟摄像头/窗口采集（第3/4级）：后续按需实现

统一约定：
- 每个角色（agent_id）绑定一种后端 kind："vts" | "vmc" | "self"
- 路由键与 VTS 一致：model_id（角色绑定的模型标识）
- 后端按 capabilities 声明能力，编排层对不支持的能力静默跳过（不硬编码后端名）
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

log = logging.getLogger("naixi.avatar")

# 后端类型常量（对外 API 与持久化均用字符串，避免枚举序列化负担）
KIND_VTS = "vts"
KIND_VMC = "vmc"
KIND_SELF = "self"
ALL_KINDS = (KIND_VTS, KIND_VMC, KIND_SELF)


class AvatarBackend:
    """渲染后端统一接口。子类按能力实现，未实现的能力必须留在 capabilities 之外。"""

    kind: str = ""
    capabilities: frozenset = frozenset()   # {"expression","motion","parameters"}

    async def connect(self) -> bool:
        return True

    async def disconnect(self):
        pass

    @property
    def connected(self) -> bool:
        return True

    async def send_expression(self, emotion: str, model_id: Optional[str] = None):
        pass

    async def send_motion(self, action: str, model_id: Optional[str] = None):
        pass

    async def send_parameters(self, params: dict, model_id: Optional[str] = None):
        pass

    def describe(self) -> dict:
        """状态快照（前端角色卡片展示用）。"""
        return {"kind": self.kind, "connected": self.connected,
                "capabilities": sorted(self.capabilities)}


# ── VMC 协议后端（OSC over UDP，通吃 VSeeFace/Warudo/VMagicMirror/REALITY）──

# Live2D 通用参数 → VRM BlendShape 名映射（VMC /VMC/Ext/Blend/Val）
_PARAM_TO_BLEND = {
    "MouthOpen": "A",          # 张嘴（口型主参数）
    "MouthForm": "Joy",        # 嘴角上扬 → 喜
    "EyeSmile": "Fun",         # 眼弯 → 乐
    "BrowUpDown": "Surprised", # 挑眉 → 惊（近似）
}

# 情绪关键词 → VRM 标准表情 BlendShape
_EMOTION_TO_BLEND = {
    "开心": "Joy", "高兴": "Joy", "喜": "Joy", "笑": "Joy",
    "生气": "Angry", "愤怒": "Angry",
    "伤心": "Sorrow", "难过": "Sorrow", "哭": "Sorrow",
    "惊讶": "Surprised", "惊": "Surprised",
    "轻松": "Fun", "调皮": "Fun",
}


class VmcBackend(AvatarBackend):
    """VMC 协议发送器：向 host:port 发 OSC 报文驱动 VRM 形象。

    默认端口契约与 VTS 实例池一致的公式化分配：39539 + index。
    表情 = BlendShape 脉冲，参数 = BlendShape 映射投递；骨骼动作暂不实现
    （capabilities 不含 motion，编排层自动跳过）。
    """

    kind = KIND_VMC
    capabilities = frozenset({"expression", "parameters"})

    def __init__(self, host: str = "127.0.0.1", port: int = 39539):
        self.host = host
        self.port = port
        self._client = None
        self._expr_reset_task: Optional[asyncio.Task] = None

    async def connect(self) -> bool:
        try:
            from pythonosc.udp_client import SimpleUDPClient
            self._client = SimpleUDPClient(self.host, self.port)
            return True
        except Exception as e:
            log.warning(f"[VMC:{self.port}] 初始化失败: {e}")
            self._client = None
            return False

    async def disconnect(self):
        self._client = None

    @property
    def connected(self) -> bool:
        # UDP 无连接语义，client 可用即视为在线
        return self._client is not None

    def _blend(self, name: str, value: float):
        self._client.send_message("/VMC/Ext/Blend/Val", [name, float(value)])

    def _apply(self):
        self._client.send_message("/VMC/Ext/Blend/Apply", [])

    async def send_expression(self, emotion: str, model_id: Optional[str] = None):
        if not self._client or not emotion:
            return
        blend = None
        for kw, b in _EMOTION_TO_BLEND.items():
            if kw in emotion:
                blend = b
                break
        if not blend:
            return
        try:
            self._blend(blend, 1.0)
            self._apply()
            log.info(f"[VMC:{self.port}] 表情: {emotion} → {blend}")
        except Exception as e:
            log.info(f"[VMC:{self.port}] 表情发送失败: {e}")
            return
        # 3 秒后淡出复位（VRM 表情是持续量，不复位会僵在脸上）
        if self._expr_reset_task and not self._expr_reset_task.done():
            self._expr_reset_task.cancel()

        async def _reset():
            await asyncio.sleep(3.0)
            try:
                self._blend(blend, 0.0)
                self._apply()
            except Exception:
                pass
        self._expr_reset_task = asyncio.create_task(_reset())

    async def send_parameters(self, params: dict, model_id: Optional[str] = None):
        if not self._client or not params:
            return
        try:
            sent = False
            for pid, value in params.items():
                blend = _PARAM_TO_BLEND.get(pid)
                if blend is None:
                    continue
                self._blend(blend, max(0.0, min(1.0, float(value))))
                sent = True
            if sent:
                self._apply()
        except Exception:
            pass

    def describe(self) -> dict:
        d = super().describe()
        d["port"] = self.port
        return d


# ── 自研渲染后端（前端 PetWindow / 多角色舞台，经 live2d WebSocket 投递）──

class SelfRenderBackend(AvatarBackend):
    """自研 Live2D 渲染驱动：把表情/动作/参数经桌宠 WebSocket 推给前端渲染层。

    前端已有能力（PetWindow.tsx）：setExpression、motion 模糊匹配、
    setParameterValueById。消息按 type 区分，model_id 供多角色舞台路由。
    ws_getter: 返回当前 live2d WebSocket（引擎持有，可能为 None/已关闭）。
    """

    kind = KIND_SELF
    capabilities = frozenset({"expression", "motion", "parameters"})

    def __init__(self, ws_getter: Callable, agent_id: str = "",
                 clients_getter: Optional[Callable] = None):
        self._ws_getter = ws_getter                # 兼容旧单连接
        self._clients_getter = clients_getter      # 多窗口广播（桌宠 + 舞台）
        self.agent_id = agent_id  # 多角色舞台路由标识（StageWindow 按此分发到对应 sprite）

    def _targets(self) -> list:
        """收集当前所有存活的前端 WS 目标（去重）。"""
        out = []
        if self._clients_getter:
            try:
                out.extend(ws for ws in self._clients_getter() if ws is not None and not ws.closed)
            except Exception:
                pass
        ws = self._ws_getter() if self._ws_getter else None
        if ws is not None and not ws.closed and ws not in out:
            out.append(ws)
        return out

    @property
    def connected(self) -> bool:
        return bool(self._targets())

    async def _send(self, payload: dict):
        if self.agent_id:
            payload["agent_id"] = self.agent_id
        for ws in self._targets():
            try:
                await ws.send_json(payload)
            except Exception:
                pass

    async def send_expression(self, emotion: str, model_id: Optional[str] = None):
        if emotion:
            await self._send({"type": "avatar_expression", "emotion": emotion,
                              "model_id": model_id or ""})

    async def send_motion(self, action: str, model_id: Optional[str] = None):
        if action:
            await self._send({"type": "avatar_motion", "action": action,
                              "model_id": model_id or ""})

    async def send_parameters(self, params: dict, model_id: Optional[str] = None):
        if params:
            await self._send({"type": "avatar_params", "params": params,
                              "model_id": model_id or ""})
