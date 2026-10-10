"""连接器进程管理器（桌面后端侧）。

职责：
  - 把连接器（naixi_connector，独立 Python 包）作为子进程拉起 / 停止 / 重启；
  - 配置存进桌面 meta（与 API Key 同机制），首次从连接器原 connector_config.json 迁移；
  - 跟踪进程存活，供前端显示「连接器运行中」；
  - 提供微信二维码路径查找（连接器把二维码写在项目根，位置随版本可能漂移，做多候选）。

为什么单独起进程而不是 in-process：连接器依赖 lark-oapi / dingtalk-stream / pycryptodome 等，
装在它自己的 venv 里；桌面后端跑在 python-embed。分开进程互不污染，且连接器崩溃不影响桌面。

发布版落地：把 naixi_connector 包连同其 venv 打进 resources/connector/，再用环境变量
NAIXI_CONNECTOR_DIR / NAIXI_CONNECTOR_PYTHON 指过去即可，逻辑无需改动。
"""

import asyncio
import json
import logging
import os

log = logging.getLogger("connector.manager")

# ── 路径解析（环境变量 > 开发态 venv > 打包态随包）──
_DEV_CONNECTOR_DIR = r"D:\数据\naixi_connector"


def _packaged_dir() -> str:
    """打包态：本文件位于 <安装>\\resources\\desktop_core\\，连接器在同级 resources\\connector\\。"""
    res = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pkg = os.path.join(res, "connector")
    py = os.path.join(res, "python-embed", "python.exe")
    if os.path.isdir(pkg) and os.path.exists(py):
        return pkg
    return ""


def _dev_dir() -> str:
    """开发态：独立连接器工程 + 其 venv。"""
    if os.path.exists(os.path.join(_DEV_CONNECTOR_DIR, ".venv", "Scripts", "python.exe")):
        return _DEV_CONNECTOR_DIR
    return ""


def _default_python_for(d: str) -> str:
    venv_py = os.path.join(d, ".venv", "Scripts", "python.exe")
    if os.path.exists(venv_py):
        return venv_py
    # 打包态：用随包 python-embed 跑（连接器依赖在 resources/connector/site-packages）
    res = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(res, "python-embed", "python.exe")


CONNECTOR_DIR = (
    os.environ.get("NAIXI_CONNECTOR_DIR")
    or _dev_dir()
    or _packaged_dir()
    or _DEV_CONNECTOR_DIR
)
CONNECTOR_PYTHON = os.environ.get("NAIXI_CONNECTOR_PYTHON") or _default_python_for(CONNECTOR_DIR)

CONFIG_META_KEY = "connector_config"

# 字段名含这些的视为密钥，GET 时掩码
_SECRET_KEYS = {"app_secret", "client_secret", "corp_secret", "token", "aes_key",
                "bot_token", "password", "access_token", "app_token"}

# 进程句柄（单事件循环内全局可变，无需锁）
_proc = None
_pid = None
_pid_checked = 0.0


class ConnError(Exception):
    pass


def _win_hide_kwargs() -> dict:
    if os.name == "nt":
        import subprocess

        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": si}
    return {}


# ── 存储（优先桌面 meta；不可用时退化为内存，便于独立测试）──
def _store_get(key: str) -> str:
    try:
        from desktop_core.storage import meta_get

        return meta_get(key) or ""
    except Exception:
        return _MEM.get(key, "")


def _store_set(key: str, value: str) -> None:
    try:
        from desktop_core.storage import meta_set

        meta_set(key, value)
        return
    except Exception:
        _MEM[key] = value


_MEM: dict = {}


def _default_config() -> dict:
    return {
        "desktop": {"base_url": "http://127.0.0.1:9845"},
        "adapters": {
            "loopback": {"enabled": False, "port": 19876},
            "napcat": {"enabled": False, "ws_url": "ws://127.0.0.1:3001", "access_token": "",
                       "group_require_at": True},
            "feishu": {"enabled": False, "app_id": "", "app_secret": ""},
            "dingtalk": {"enabled": False, "client_id": "", "client_secret": ""},
            "wechat": {"enabled": False, "bot_token": "", "channel_version": "1.0.2"},
            "wecom": {
                "enabled": False,
                "corp_id": "",
                "corp_secret": "",
                "agent_id": "",
                "token": "",
                "aes_key": "",
                "host": "127.0.0.1",
                "port": 19877,
                "path": "/wecom/callback",
            },
            "telegram": {"enabled": False, "bot_token": "", "group_require_at": True},
            "discord": {"enabled": False, "bot_token": ""},
            "slack": {"enabled": False, "bot_token": "", "app_token": "",
                      "group_require_at": True},
            "github": {
                "enabled": False,
                "token": "",
                "owner": "",
                "repo": "",
                "poll_seconds": 60,
            },
            "gitlab": {
                "enabled": False,
                "token": "",
                "base_url": "https://gitlab.com",
                "project_id": "",
                "poll_seconds": 60,
            },
            "email": {
                "enabled": False,
                "host": "",
                "port": 993,
                "user": "",
                "password": "",
                "use_ssl": True,
                "mailbox": "INBOX",
                "poll_seconds": 30,
                "mark_seen": False,
            },
            "whatsapp": {
                "enabled": False,
                "verify_token": "",
                "phone_number_id": "",
                "access_token": "",
                "host": "127.0.0.1",
                "port": 19878,
                "path": "/whatsapp/webhook",
            },
            "generic": {
                "enabled": False,
                "host": "127.0.0.1",
                "port": 19879,
                "path": "/webhook",
            },
        },
    }


def _seed_from_connector_file() -> dict:
    """首次无配置时，从连接器自己的 connector_config.json 迁移（保留已验证的飞书凭据等）。"""
    path = os.path.join(CONNECTOR_DIR, "connector_config.json")
    if not os.path.exists(path):
        return _default_config()
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        log.warning("[connector.manager] 读取 %s 失败: %s", path, e)
        return _default_config()
    cfg = _default_config()
    src_adapters = (raw.get("adapters") or {})
    for name, acfg in cfg["adapters"].items():
        if isinstance(src_adapters.get(name), dict):
            # 只拷贝已知字段，避免把未知字段带进来
            for k in acfg.keys():
                if k in src_adapters[name]:
                    acfg[k] = src_adapters[name][k]
    if isinstance(raw.get("desktop"), dict) and raw["desktop"].get("base_url"):
        cfg["desktop"]["base_url"] = raw["desktop"]["base_url"]
    return cfg


def get_config() -> dict:
    raw = _store_get(CONFIG_META_KEY)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    cfg = _seed_from_connector_file()
    _store_set(CONFIG_META_KEY, json.dumps(cfg, ensure_ascii=False))
    return cfg


def save_config(cfg: dict) -> dict:
    # 只保留已知适配器与已知字段，防止前端误写污染
    clean = _default_config()
    src = (cfg or {}).get("adapters") or {}
    for name, acfg in clean["adapters"].items():
        if isinstance(src.get(name), dict):
            for k in acfg.keys():
                if k in src[name]:
                    v = src[name][k]
                    acfg[k] = v if not isinstance(v, str) else v.strip()
    if isinstance((cfg or {}).get("desktop"), dict) and cfg["desktop"].get("base_url"):
        clean["desktop"]["base_url"] = str(cfg["desktop"]["base_url"]).strip()
    _store_set(CONFIG_META_KEY, json.dumps(clean, ensure_ascii=False))
    return clean


def get_masked_config() -> dict:
    cfg = get_config()
    masked = json.loads(json.dumps(cfg, ensure_ascii=False))
    for acfg in (masked.get("adapters") or {}).values():
        if not isinstance(acfg, dict):
            continue
        for k in list(acfg.keys()):
            if k in _SECRET_KEYS and acfg.get(k):
                acfg[k] = "••••••••"
    return masked


def _reap() -> bool:
    """若进程已退出，清空句柄并返回 True。"""
    global _proc, _pid
    if _proc is None:
        return False
    if _proc.returncode is not None:
        _proc = None
        _pid = None
        return True
    return False


def is_running() -> bool:
    _reap()
    return _proc is not None and _proc.returncode is None


async def stop_connector() -> dict:
    global _proc, _pid
    _reap()
    proc = _proc
    if proc is None:
        return {"ok": True, "was_running": False}
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=3)
        except Exception:
            pass
    # 兜底：按 PID 强杀（Windows 上 terminate 偶发不生效）
    if _pid:
        try:
            import subprocess

            subprocess.run(
                ["taskkill", "/F", "/PID", str(_pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception:
            pass
    _proc = None
    _pid = None
    return {"ok": True, "was_running": True}


def any_enabled(cfg: dict) -> bool:
    return any(
        (a.get("enabled") is True) for a in (cfg.get("adapters") or {}).values()
    )


def _is_connector_cmd(cmd_list) -> bool:
    """判断命令行是否为连接器进程（python + naixi_connector 特征）。"""
    cmd = " ".join(cmd_list or [])
    return "naixi_connector" in cmd and "python" in cmd.lower()


def _kill_stale_connectors() -> int:
    """杀掉所有残留的连接器进程，返回数量。

    连接器是单实例设计（同一份配置 + 同一个 NapCat/平台连接），多实例并存会导致
    同一条消息被多个进程重复处理、重复回复，且旧进程可能跑着旧代码。
    后端被杀时无法级联杀子进程 ⇒ 连接器孤儿化堆积（2026-10-10 实证：4 组孤儿
    旧进程同时连着 NapCat，用无过滤旧代码回复群消息）。故每次拉起新连接器前
    先全量清理，保证单实例。
    """
    killed = 0
    try:
        import psutil
    except ImportError:
        log.warning("[connector.manager] 无 psutil，跳过残留连接器清理")
        return 0
    me = os.getpid()
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            if p.info["pid"] == me:
                continue
            if _is_connector_cmd(p.info.get("cmdline")):
                p.kill()
                killed += 1
        except Exception:
            continue
    if killed:
        log.warning("[connector.manager] 已清理 %d 个残留连接器进程（多实例会重复回复）", killed)
    return killed


async def start_connector(force: bool = False) -> dict:
    global _proc, _pid
    cfg = get_config()
    if not force and not any_enabled(cfg):
        raise ConnError("没有启用的适配器，无需启动连接器")
    if not os.path.isdir(CONNECTOR_DIR):
        raise ConnError(f"连接器目录不存在: {CONNECTOR_DIR}（请设置 NAIXI_CONNECTOR_DIR）")
    python = CONNECTOR_PYTHON
    if not os.path.exists(python):
        raise ConnError(
            f"连接器 Python 不存在: {python}（请设置 NAIXI_CONNECTOR_PYTHON）"
        )
    # 若已在跑，先停掉再重启，保证配置生效
    if is_running():
        await stop_connector()
    # 单实例保障：清理上一次后端留下来的孤儿连接器（后端退出无法级联杀子进程）
    _kill_stale_connectors()

    env = os.environ.copy()
    env["NAIXI_CONNECTOR_CONFIG_JSON"] = json.dumps(cfg, ensure_ascii=False)
    env["PYTHONUTF8"] = "1"
    venv_scripts = os.path.dirname(python)
    env["PATH"] = venv_scripts + os.pathsep + env.get("PATH", "")
    # 打包态（python-embed 跑连接器）：python313._pth 会让解释器忽略 PYTHONPATH，
    # 且 python-embed 的 site-packages 混着桌面后端依赖（不能覆盖版本）——
    # 所以用 -c 包装脚本在进程内注入 sys.path（同 sidecar 的 sys.path.insert 做法）。
    py_path_parts = [CONNECTOR_DIR]
    site_packages = os.path.join(CONNECTOR_DIR, "site-packages")
    if os.path.isdir(site_packages):
        py_path_parts.append(site_packages)
    if env.get("PYTHONPATH"):
        py_path_parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(py_path_parts)
    # 微信登录态/二维码等运行时数据写可写目录（安装目录可能只读，且升级会清空）
    data_dir = os.environ.get("NAIXI_CONNECTOR_DATA_DIR") or os.path.join(
        os.environ.get("APPDATA") or os.path.expanduser("~"), "naixi", "connector-data")
    try:
        os.makedirs(data_dir, exist_ok=True)
    except Exception:
        pass
    env["NAIXI_CONNECTOR_DATA_DIR"] = data_dir

    needs_path_inject = os.path.isdir(site_packages)
    if needs_path_inject:
        # 打包态：-c 注入 sys.path 再进连接器入口
        bootstrap = (
            "import sys; sys.path[:0] = " + repr(py_path_parts) + "; "
            "from naixi_connector.main import main; sys.exit(main())"
        )
        cmd = [python, "-c", bootstrap]
    else:
        # 开发态：venv 内已装 naixi_connector，cwd 兜底
        cmd = [python, "-m", "naixi_connector.main"]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=CONNECTOR_DIR, env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            **_win_hide_kwargs(),
        )
    except Exception as e:
        raise ConnError(f"启动连接器失败: {type(e).__name__}: {e}")
    _proc = proc
    _pid = proc.pid
    log.info("[connector.manager] 已拉起连接器 PID=%s", proc.pid)
    return {"ok": True, "pid": proc.pid}


async def restart_connector() -> dict:
    await stop_connector()
    return await start_connector(force=True)


def qr_path() -> str | None:
    """微信二维码 PNG 候选路径（适配器把二维码写在项目根，位置随版本可能漂移）。"""
    candidates = [
        os.path.join(CONNECTOR_DIR, "wechat_qr.png"),
        os.path.join(os.path.dirname(CONNECTOR_DIR), "wechat_qr.png"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def status_info() -> dict:
    return {
        "running": is_running(),
        "pid": _pid,
        "dir": CONNECTOR_DIR,
        "python": CONNECTOR_PYTHON,
        "any_enabled": any_enabled(get_config()),
    }
