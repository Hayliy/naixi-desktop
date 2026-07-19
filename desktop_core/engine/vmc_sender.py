"""
VMC 协议发送器 — 将 ECS 骨骼变换通过 UDP 发送到 Godot VRM 渲染器
"""
import socket, json, subprocess, os, threading

GODOT_PORT = 39539
GODOT_EXE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "godot_renderer", "export", "NaixiVRM.exe")

class VmcSender:
    def __init__(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._proc: subprocess.Popen = None
        self._running = False

    def start_godot(self):
        """启动 Godot VRM 渲染子进程"""
        if self._proc and self._proc.poll() is None:
            return True
        if not os.path.exists(GODOT_EXE):
            print("[VMC] Godot 渲染器未导出:", GODOT_EXE)
            return False
        try:
            self._proc = subprocess.Popen([GODOT_EXE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[VMC] Godot 渲染器已启动")
            return True
        except Exception as e:
            print(f"[VMC] 启动失败: {e}")
            return False

    def stop_godot(self):
        """停止 Godot 渲染进程"""
        if self._proc and self._proc.poll() is None:
            self._proc.kill()
            self._proc = None
            print("[VMC] Godot 渲染器已停止")

    def send_bones(self, bone_angles: dict[str, float]):
        """发送骨骼角度数据到 Godot"""
        try:
            data = json.dumps({"bones": bone_angles}).encode()
            self._sock.sendto(data, ("127.0.0.1", GODOT_PORT))
        except Exception as e:
            print(f"[VMC] 发送失败: {e}")
