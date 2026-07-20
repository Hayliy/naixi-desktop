"""桌宠子进程入口 — 由后端 launcher 启动"""
import os, sys

# 向上查找包含 desktop_core 包的目录（兼容开发态与打包态）
def _find_core_root():
    here = os.path.dirname(os.path.abspath(__file__))
    d = here
    while True:
        if os.path.isdir(os.path.join(d, "desktop_core")):
            return d
        # 打包态：desktop_core 在 resources/ 下（Tauri 资源目录分层结构）
        if os.path.isdir(os.path.join(d, "resources", "desktop_core")):
            return os.path.join(d, "resources")
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return here

CORE_ROOT = _find_core_root()
if CORE_ROOT not in sys.path:
    sys.path.insert(0, CORE_ROOT)

from desktop_core.pet_window import run_pet

if __name__ == "__main__":
    run_pet(sys.argv[1] if len(sys.argv) > 1 else "")