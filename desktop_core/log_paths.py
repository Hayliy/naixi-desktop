"""日志路径单一真相源（2026-09-03 建立）。

★为什么需要它（血泪坑，详见 2026-09-03.md「日志统一」节）：
  此前各模块都用 `os.path.dirname(os.path.abspath(__file__))` 之类的手法拼日志路径。
  而 dev 模式实际加载的是 **副本** `src-tauri/resources/desktop_core/`（不是项目根活代码），
  于是 `__file__` 指向副本 → 日志跟着写进副本目录，用户在项目根永远找不到。
  实测后果：pet_debug.log 1.2MB 躺在 src-tauri/resources/desktop_core/ 里；
  api.py 算到 src-tauri/logs/ 而 sidecar 算到项目根/logs/，同一个文件名两处打架。

  全项目**只有 voice_input.py 当初做对了**（env + 向上探测 + cwd 兜底），
  本模块就是把它那套逻辑抽出来，让所有模块共用。

规则（禁止在别处再拼日志路径）：
  1. NAIXI_LOG_DIR       —— 最高优先，直接指定日志目录（自测/隔离用）
  2. 开发树              —— 探测到项目根则写 <项目根>/logs/（开发时一眼找得到）
  3. 安装态              —— 写用户目录 %APPDATA%/奶昔/logs/（绕开 Program Files 只读）
  4. cwd 兜底            —— 都失败才用 <cwd>/logs

用法：
    from log_paths import log_dir, log_file
    LOG = log_file("pet_debug.log")
"""
import os
import sys

__all__ = ["project_root", "log_dir", "log_file", "is_dev_tree", "APP_NAME"]

APP_NAME = "奶昔"
_ENV_LOG_DIR = "NAIXI_LOG_DIR"
_ENV_ROOT = "NAIXI_DESKTOP_ROOT"


def is_dev_tree(path):
    """判定某目录是否奶昔开发树（源码可写）。

    特征：同时具备 src-tauri/tauri.conf.json 与 desktop_core/。
    从副本 src-tauri/resources/desktop_core 向上逐级探测时，会在真正的
    项目根命中（src-tauri 这一级自身没有 src-tauri/src-tauri/... 所以不会误判）。
    """
    try:
        return (os.path.isfile(os.path.join(path, "src-tauri", "tauri.conf.json"))
                and os.path.isdir(os.path.join(path, "desktop_core")))
    except Exception:
        return False


def project_root():
    """探测奶昔项目根；找不到返回 ''。"""
    env = (os.environ.get(_ENV_ROOT) or "").strip()
    if env and os.path.isdir(env):
        return env
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(10):
        if is_dev_tree(d):
            return d
        nd = os.path.dirname(d)
        if not nd or nd == d:
            break
        d = nd
    return ""


def _install_log_dir():
    """安装态日志目录：写到用户目录，避免往 Program Files 写（只读 / 触发 UAC）。"""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, APP_NAME, "logs")


def log_dir():
    """统一日志目录（不存在时自动创建；创建失败不抛异常，返回路径由调用方兜底）。"""
    env = (os.environ.get(_ENV_LOG_DIR) or "").strip()
    if env:
        try:
            os.makedirs(env, exist_ok=True)
        except Exception:
            pass
        return env

    root = project_root()
    d = os.path.join(root, "logs") if root else _install_log_dir()
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except Exception:
        pass

    # 最后兜底：cwd
    try:
        fb = os.path.join(os.getcwd(), "logs")
        os.makedirs(fb, exist_ok=True)
        return fb
    except Exception:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


def log_file(name):
    """日志文件绝对路径。name 只给文件名（如 'pet_debug.log'），不要带目录。"""
    return os.path.join(log_dir(), name)


if __name__ == "__main__":
    print("project_root =", project_root() or "(未探测到，视为安装态)")
    print("log_dir      =", log_dir())
    for n in ("naixi_desktop.log", "pet_debug.log", "pet_voice.log", "pet_vrm.log"):
        print("  %-20s -> %s" % (n, log_file(n)))
