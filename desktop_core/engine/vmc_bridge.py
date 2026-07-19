"""
VMC 桥接器 — 连接 ECS 引擎到 Godot VRM 渲染器
"""
import threading, time
from .ecs import World
from .transform import Transform
from .skeleton import BoneData, get_bone_angles, _collect_all
from .vmc_sender import VmcSender

class VmcBridge:
    """每帧将 ECS 骨骼角度发送到 Godot"""

    def __init__(self):
        self.sender = VmcSender()
        self._thread: threading.Thread = None
        self._running = False
        self._world: World = None
        self._root = None

    def start(self, world: World, skeleton_root):
        """启动桥接器，自动启动 Godot 并开始发送骨骼数据"""
        self._world = world
        self._root = skeleton_root
        self.sender.start_godot()
        import time
        time.sleep(2)  # 等 Godot 启动
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[VMC] 桥接器已启动")

    def stop(self):
        self._running = False
        self.sender.stop_godot()
        print("[VMC] 桥接器已停止")

    def _loop(self):
        """每 1/60 秒发送一次骨骼数据"""
        while self._running:
            if self._world and self._root:
                self._world.update(1/60)
                angles = get_bone_angles(self._root)
                self.sender.send_bones(angles)
            time.sleep(1/60)
