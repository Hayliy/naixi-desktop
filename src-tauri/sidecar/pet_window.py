"""桌宠子进程入口 — 由后端 launcher 启动"""
import sys, os
# 项目根目录：src-tauri/sidecar/ 的父目录的父目录 = naixi_desktop/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from desktop_core.pet_window import run_pet

if __name__ == "__main__":
    run_pet(sys.argv[1] if len(sys.argv) > 1 else "")