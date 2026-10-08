"""本地模型：发现 + 推理服务管理（桌面端自己部署模型的能力）。

设计要点（与项目既有风格一致）：
  · 只做"发现 + 启动 + 停止 + 健康检查"，不重复造推理引擎——
    推理交给本机已有的 llama.cpp(llama-server) / Ollama，它们是成熟方案。
  · OpenAI 兼容：两者都提供 /v1/chat/completions，所以对话层统一走 OpenAI 格式，
    本地模型和云端模型对上层是同一套接口。
  · 硬件适配：本机是 GTX 1050 Ti 4GB（Pascal），参数按实测结论给默认值
    （Vulkan 后端 + KV q8_0 + 适中上下文），避免显存 OOM。

端口约定（避免冲突）：
  · Ollama      11434
  · llama.cpp   11436（本模块拉起 llama-server 用这个）
"""

import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path

import logging

log = logging.getLogger("local_model")

# ── 端口与引擎 ──────────────────────────────────────────────
OLLAMA_PORT = 11434
LLAMACPP_PORT = 11436

# ★ 推理引擎**不再写死任何开发机私有路径**（用户明确批评：D:\软件\...、
#   C:\Users\21222\... 这类路径装到别人机器上根本不存在，等于功能失效）。
# 引擎解析顺序（见 find_llamacpp / find_ollama）：
#   1) 随软件下发的自带引擎  →  <resources>/engines/llama-cpp/llama-server(.exe)
#      （"奶昔本身就支持"：引擎随安装包走，干净虚拟机也能跑，不依赖用户另装）
#   2) 数据目录自管引擎      →  <DATA_DIR>/engines/llama-cpp/llama-server(.exe)
#      （ensure_llamacpp() 一键下载的落地处，或用户自己丢进去的）
#   3) 系统标准安装位置      →  跨用户、不依赖盘符/用户名的约定路径
#                                （ProgramFiles / LOCALAPPDATA 等，运行时从环境变量取）
#   4) PATH 中的命令         →  shutil.which("llama-server") / which("ollama")

# ── 模型扫描目录：用户可配 + 自动发现，绝不写死某人的盘符 ──────
# 踩过（用户明确批评）：曾把 D:\数据\VLM\gguf、D:\数据\Ollama_GGUF 这类
# **开发者本机的私人路径**写进扫描列表。那等于让装到别人机器上的程序
# 去扫一个不存在的目录 —— 功能等于没有，而且换个人装就失效。
# 正确做法：① 用户在设置里配的目录（含下载目录，永远包含）
#        ② 各引擎的**标准安装位置**（Ollama/HuggingFace 的约定目录）
#        ③ 用户自己添加的任意目录（存在性由用户决定，不是我们猜）
#
# ★ 用户自定义目录是**必需能力，不是可选**：模型可以放在任何地方
#   （别的盘、别人的D 盘、移动硬盘），程序不可能猜得到。
#   所以必须提供"添加目录"入口并持久化，否则用户模型全都不显示。
_SCAN_CFG_FILE = "model_dirs.json"


def _scan_cfg_path() -> Path:
    try:
        from desktop_core import config
        base = Path(getattr(config, "DATA_DIR", None) or
                    Path(__file__).resolve().parent.parent / "data")
    except Exception:
        base = Path(__file__).resolve().parent.parent / "data"
    return Path(base) / _SCAN_CFG_FILE


def get_extra_dirs() -> list:
    """用户手动添加的模型目录（持久化）。"""
    try:
        p = _scan_cfg_path()
        if not p.is_file():
            return []
        d = json.loads(p.read_text(encoding="utf-8"))
        items = d.get("dirs") if isinstance(d, dict) else d
        return [str(x) for x in (items or []) if x]
    except Exception as e:
        log.warning("[local_model] 读模型目录配置失败: %s", e)
        return []


def add_extra_dir(path: str) -> dict:
    """添加一个模型扫描目录。校验存在且是目录，避免存废路径。"""
    p = str(path or "").strip().strip('"')
    if not p:
        return {"ok": False, "error": "目录不能为空"}
    pp = Path(p).expanduser()
    if not pp.is_dir():
        return {"ok": False, "error": "目录不存在，请检查路径"}
    cur = get_extra_dirs()
    key = str(pp).rstrip("\\/").lower()
    if any(str(x).rstrip("\\/").lower() == key for x in cur):
        return {"ok": True, "dirs": cur, "note": "该目录已在列表里"}
    cur.append(str(pp))
    try:
        p2 = _scan_cfg_path()
        p2.parent.mkdir(parents=True, exist_ok=True)
        p2.write_text(json.dumps({"dirs": cur}, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"保存失败：{str(e)[:90]}"}
    return {"ok": True, "dirs": cur}


def remove_extra_dir(path: str) -> dict:
    """移除一个用户添加的扫描目录（只删配置，不删文件）。"""
    key = str(path or "").strip().strip('"').rstrip("\\/").lower()
    cur = [x for x in get_extra_dirs() if str(x).rstrip("\\/").lower() != key]
    try:
        p2 = _scan_cfg_path()
        p2.parent.mkdir(parents=True, exist_ok=True)
        p2.write_text(json.dumps({"dirs": cur}, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"保存失败：{str(e)[:90]}"}
    return {"ok": True, "dirs": cur}


def _user_scan_dirs() -> list:
    """扫描目录 = 用户添加 + 用户配置的下载目录 + 约定标准位置。
    全部动态推导 + 只用真实存在的，不含任何写死的盘符。"""
    dirs: list = list(get_extra_dirs())
    # ① 用户自己设的下载目录（他下的模型必然在这儿，必须扫）
    try:
        from desktop_core import model_hub
        dirs.append(model_hub.get_download_dir())
    except Exception:
        pass
    # ② Ollama 官方约定的模型目录（按平台给，不写死盘符）
    home = Path.home()
    dirs.append(str(home / ".ollama" / "models"))
    # HuggingFace 缓存（HF 格式权重的默认落点）
    hf_home = os.environ.get("HF_HOME") or str(home / ".cache" / "huggingface")
    dirs.append(str(Path(hf_home) / "hub"))
    # ③ 本程序自己的模型目录（与默认下载目录一致）
    dirs.append(str(home / "naixi_models"))
    # Ollama 在 Windows 的常见安装位置（安装器默认值）
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(str(Path(local) / "Ollama"))
    # 去重 + 只保留真实存在的目录
    seen, out = set(), []
    for d in dirs:
        if not d:
            continue
        key = str(d).rstrip("\\/").lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            if Path(d).is_dir():
                out.append(d)
        except Exception:
            continue
    return out


# 兼容旧引用名（真实值由 _user_scan_dirs() 每次动态给出）
GGUF_SCAN_DIRS: list = []
HF_SCAN_DIRS: list = []

# 排除的目录（探针/临时/版本库）
GGUF_EXCLUDE = {"_probe", "node_modules", ".git", "__pycache__", ".cache"}

# 本模块拉起的 llama-server 进程（模块级单例）
_SERVER: dict = {"proc": None, "port": LLAMACPP_PORT, "model_path": "", "started_at": 0}


# ── 引擎探测（完全不依赖开发机私有路径） ──────────────────────
def _exe_names(base: str) -> list:
    return [base + ".exe"] if os.name == "nt" else [base]


def _engine_search_roots() -> list:
    """随包下发的引擎所在「根目录」候选，按存在性去重后返回。

    设计：local_model.py 在打包副本里位于 <resources>/desktop_core/ ，
    在开发态位于 <src-tauri>/sidecar/desktop_core/ ，
    因此 ``__file__`` 的父目录的父目录即资源/项目根。
    再叠加数据目录与可能的环境变量覆盖，覆盖各种部署形态。
    """
    roots: list = []
    env_root = os.environ.get("NAIXI_ENGINE_DIR")
    if env_root:
        roots.append(Path(env_root))
    here = Path(__file__).resolve()
    roots.append(here.parent.parent)        # resources/ 或 src-tauri/
    roots.append(here.parent.parent.parent)  # 开发态 sidecar 在 src-tauri/sidecar
    res_env = os.environ.get("NAIXI_RESOURCES")
    if res_env:
        roots.append(Path(res_env))
    try:
        from desktop_core import config
        dd = getattr(config, "DATA_DIR", None)
        if dd:
            roots.append(Path(dd))
    except Exception:
        pass
    seen, out = set(), []
    for r in roots:
        try:
            rp = Path(r)
        except Exception:
            continue
        key = str(rp).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(rp)
    return out


def _self_managed_engine_dir() -> Path:
    """用户/软件自管的引擎目录（ensure_llamacpp 落地处，也在解析链路里）。"""
    try:
        from desktop_core import config
        dd = getattr(config, "DATA_DIR", None) or str(Path.home() / ".naixi")
    except Exception:
        dd = str(Path.home() / ".naixi")
    return Path(dd) / "engines" / "llama-cpp"


def _engine_usable(exe: str) -> bool:
    """判断一个 llama-server 路径是否**真的能启动**。

    必须查：llama-server.exe 本体只有 9KB，它是个**加载 DLL 的桩**。
    只看 exe 存在会把「缺 llama-server-impl.dll」的残缺目录当成可用引擎，
    用户点启动才炸（实测踩过）。
    """
    try:
        if not exe or not os.path.isfile(exe):
            return False
        if os.name == "nt":
            # 桩 exe 依赖的实现 dll，缺任一则无法启动
            for dep in ("llama-server-impl.dll",):
                if not os.path.isfile(os.path.join(os.path.dirname(exe), dep)):
                    return False
        return True
    except Exception:
        return False


def _glob_llamacpp_exe() -> list:
    """在常见「软件安装目录」里通配寻找 llama-server。

    不写死任何具体版本号或用户名（旧版写死 ``D:\\软件\\llama.cpp\\b10902`` 会随
    版本失效、且只对一台机器有效）。用「软件目录 + 通配」尽力探测：
      - <软件目录>/llama.cpp/<版本号>/llama-server.exe   绿色安装
      - <软件目录>/llamacpp_cuda/vk/llama-server.exe    Vulkan 构建（本机布局）
      - 上述目录的扁平布局
    命中后一律用 _engine_usable 过滤，排除残缺目录。
    """
    names = _exe_names("llama-server")
    out = []

    def _collect(base: str) -> None:
        """在 base 及其子目录里收集可用 exe（限深度，避免全盘硬扫）。

        深度到 2 层：真实布局有 <软件目录>/llamacpp_cuda/vk/llama-server.exe
        这种两级子目录（Vulkan 构建），只搜一层会漏掉。
        """
        if not os.path.isdir(base):
            return
        try:
            entries = os.listdir(base)
        except Exception:
            return
        for nm in names:
            p = os.path.join(base, nm)
            if os.path.isfile(p) and _engine_usable(p):
                out.append(p)
        for sub in entries:
            subp = os.path.join(base, sub)
            if not os.path.isdir(subp):
                continue
            for nm in names:
                p = os.path.join(subp, nm)
                if os.path.isfile(p) and _engine_usable(p):
                    out.append(p)
            # 第二层（如 .../llamacpp_cuda/vk/）
            try:
                for sub2 in os.listdir(subp):
                    sub2p = os.path.join(subp, sub2)
                    if not os.path.isdir(sub2p):
                        continue
                    for nm in names:
                        p = os.path.join(sub2p, nm)
                        if os.path.isfile(p) and _engine_usable(p):
                            out.append(p)
            except Exception:
                continue

    bases = []
    if os.name == "nt":
        # 仅遍历真实存在的盘符，避免光驱/网络盘卡顿
        for d in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            rp = f"{d}:\\"
            if not os.path.isdir(rp):
                continue
            bases.append(os.path.join(rp, "llama.cpp"))
            bases.append(os.path.join(rp, "llamacpp"))
            bases.append(os.path.join(rp, "llamacpp_cuda"))  # Vulkan 构建常见布局
            for sd in ("软件", "software", "Software", "apps", "Apps", "Programs"):
                sd_path = os.path.join(rp, sd)
                if os.path.isdir(sd_path):
                    bases.append(os.path.join(sd_path, "llama.cpp"))
                    bases.append(os.path.join(sd_path, "llamacpp"))
                    bases.append(os.path.join(sd_path, "llamacpp_cuda"))
    else:
        for rp in ("/opt", "/usr/local", str(Path.home())):
            bases.append(os.path.join(rp, "llama.cpp"))
            bases.append(os.path.join(rp, "llamacpp"))

    for base in bases:
        _collect(base)
    return out


def _candidate_llamacpp_paths() -> list:
    names = _exe_names("llama-server")
    out = []
    # ① 随包引擎 / 数据目录自管引擎：<root>/engines/llama-cpp/<exe>
    for root in _engine_search_roots():
        for n in names:
            out.append(str(root / "engines" / "llama-cpp" / n))
    # ② 系统标准安装位置（不写死盘符/用户名，全部从环境变量推导）
    if os.name == "nt":
        pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
        pf86 = os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
        local = os.environ.get("LOCALAPPDATA") or ""
        cands = [Path(pf) / "llama.cpp" / "llama-server.exe",
                 Path(pf86) / "llama.cpp" / "llama-server.exe"]
        if local:
            cands.append(Path(local) / "Programs" / "llama.cpp" / "llama-server.exe")
            cands.append(Path(local) / "llama.cpp" / "llama-server.exe")
        for c in cands:
            out.append(str(c))
    else:
        for c in ("/usr/local/bin/llama-server", "/opt/llama.cpp/llama-server",
                  str(Path.home() / ".local" / "bin" / "llama-server")):
            out.append(c)
    # ③ 常见「软件安装目录」通配探测（绿色版 llama.cpp，不写死版本号/用户名）
    out += _glob_llamacpp_exe()
    # ④ 若装了 Ollama，它自带一份 llama-server，可复用
    ol = find_ollama()
    if ol:
        ol_dir = Path(ol).parent
        for n in names:
            out.append(str(ol_dir / n))
        # 新版布局：引擎在 lib/ollama/ 下；本机实测还有 lib/ollama/llamacpp_cuda/vk/
        # （Vulkan 构建）。逐个子目录扫，避免只认死路径漏掉 Vulkan 引擎。
        for rel in ("lib/ollama", "lib", "."):
            out += _scan_dir_for_exe(str(ol_dir / rel), names)
    return out


def _scan_dir_for_exe(base: str, names: list) -> list:
    """在 base 及最多两层子目录里收集可用 llama-server（限深，避免全盘扫）。"""
    out: list = []
    if not os.path.isdir(base):
        return out
    try:
        level1 = os.listdir(base)
    except Exception:
        return out
    for nm in names:
        p = os.path.join(base, nm)
        if os.path.isfile(p) and _engine_usable(p):
            out.append(p)
    for sub in level1:
        sp = os.path.join(base, sub)
        if not os.path.isdir(sp):
            continue
        for nm in names:
            p = os.path.join(sp, nm)
            if os.path.isfile(p) and _engine_usable(p):
                out.append(p)
        try:
            for sub2 in os.listdir(sp):
                s2p = os.path.join(sp, sub2)
                if not os.path.isdir(s2p):
                    continue
                for nm in names:
                    p = os.path.join(s2p, nm)
                    if os.path.isfile(p) and _engine_usable(p):
                        out.append(p)
        except Exception:
            continue
    return out


def find_llamacpp() -> str:
    """定位可用的 llama-server。

    顺序：用户当前选中的版本（引擎更新/切换落在这里）→ PATH（用户自己装的）
    → 随包自带引擎 → 自管目录 → 系统标准位置 → 软件目录通配 → Ollama 自带。
    所有候选都用 _engine_usable 过滤——exe 存在不等于能启动（9KB 桩 exe 缺 dll）。
    """
    # ① 用户选中的版本（engine_activate / engine_update 写入 current.json）
    cur = _read_engine_state().get("current", "")
    if cur:
        exe = _engines_root() / f"llama-cpp-{cur}" / _exe_names("llama-server")[0]
        if _engine_usable(str(exe)):
            return str(exe)
    w = shutil.which("llama-server")
    if _engine_usable(w):
        return w
    for p in _candidate_llamacpp_paths():
        if _engine_usable(p):
            return p
    return ""


def _candidate_ollama_paths() -> list:
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA") or ""
        pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
        out = []
        if local:
            out.append(Path(local) / "Ollama" / "ollama.exe")
            out.append(Path(local) / "Programs" / "Ollama" / "ollama.exe")
        out.append(Path(pf) / "Ollama" / "ollama.exe")
        return [str(x) for x in out]
    return [str(x) for x in ("/usr/local/bin/ollama",
                             "/opt/ollama/ollama",
                             Path.home() / ".ollama" / "ollama")]


def find_ollama() -> str:
    w = shutil.which("ollama")
    if w and os.path.isfile(w):
        return w
    for p in _candidate_ollama_paths():
        if p and os.path.isfile(p):
            return p
    return ""


def _engine_source(exe: str) -> str:
    """判断引擎来自哪里：bundled=奶昔自带（用户无需另装）/managed=自管目录 /
    system=外部安装 / path=PATH。"""
    if not exe:
        return ""
    try:
        ep = Path(exe).resolve()
        # 随包下发
        for root in _engine_search_roots():
            try:
                if ep.is_relative_to(Path(root).resolve() / "engines" / "llama-cpp"):
                    return "bundled"
            except Exception:
                continue
        # 软件自管目录（用户点过"一键获取"落地在这）
        try:
            if ep.is_relative_to(_self_managed_engine_dir().resolve()):
                return "managed"
        except Exception:
            pass
        if shutil.which("llama-server"):
            try:
                if ep == Path(shutil.which("llama-server")).resolve():
                    return "path"
            except Exception:
                pass
        return "system"
    except Exception:
        return "system"


def engine_status() -> dict:
    """汇报本地推理引擎整体情况，给前端决定要不要提示用户装引擎。"""
    lc = find_llamacpp()
    ol = find_ollama()
    src = _engine_source(lc)
    return {
        "ok": True,
        "llamacpp": {"found": bool(lc), "path": lc, "source": src,
                     "bundled": src == "bundled"},
        "ollama": {"found": bool(ol), "path": ol},
        # 有没有任何一种可用的本地推理方式（决定"本地模型"入口能否用）
        "any_engine": bool(lc or ol),
        # 关键：引擎是否随软件自带 —— 为真时用户**什么都不用装**
        "needs_no_install": bool(lc) and src in ("bundled", "managed"),
        "source": src,
        "self_managed_dir": str(_self_managed_engine_dir()),
        "note": "引擎随安装包下发（resources/engines/llama-cpp/）即"
                "可在干净虚拟机直接运行，无需用户另装；否则可用 Ollama 或一键获取。",
    }


def ensure_llamacpp(url: str = "") -> dict:
    """把推理引擎落地到软件自管目录（<DATA_DIR>/engines/llama-cpp/）。

    **不瞎猜下载地址**：必须显式给出 url（环境变量 NAIXI_LLAMACPP_URL /
    配置项 / 调用方传入）。没给就明确告诉用户去安装包勾选引擎组件或装 Ollama，
    而不是凭空编一个 404 的地址。
    """
    target = _self_managed_engine_dir()
    exe = target / _exe_names("llama-server")[0]
    if exe.is_file():
        return {"ok": True, "already": True, "path": str(exe),
                "note": "引擎已就绪"}
    url = (url or "").strip() or os.environ.get("NAIXI_LLAMACPP_URL", "").strip()
    if not url:
        return {"ok": False, "error": "未配置推理引擎下载地址",
                "hint": "请在设置里填写 llama.cpp 的发布包地址（NAIXI_LLAMACPP_URL），"
                        "或在安装包中勾选「推理引擎」组件，或安装 Ollama 后重试。"}
    try:
        target.mkdir(parents=True, exist_ok=True)
        import tempfile, urllib.request, zipfile
        tmp = tempfile.mkdtemp(prefix="naixi_engine_")
        zp = Path(tmp) / "engine.zip"
        log.info("[local_model] 下载推理引擎: %s", url)
        # 走系统代理（urllib 默认读 http(s)_proxy 环境变量），不强制直连
        req = urllib.request.Request(url, headers={"User-Agent": "naixi-desktop"})
        with urllib.request.urlopen(req, timeout=300) as r, open(zp, "wb") as f:
            f.write(r.read())
        with zipfile.ZipFile(zp) as z:
            z.extractall(target)
        if not exe.is_file():
            # 有些包把 exe 放在子目录，做一次扁平化查找
            hits = list(target.rglob(_exe_names("llama-server")[0]))
            if hits:
                import shutil as _sh
                _sh.copy(hits[0], exe)
        if not exe.is_file():
            return {"ok": False, "error": "下载包中未找到 llama-server 可执行文件",
                    "hint": "该地址可能不是 llama.cpp 的发布包，请换用包含 llama-server 的 zip"}
        return {"ok": True, "path": str(exe), "note": "引擎已下载到软件自管目录"}
    except Exception as e:
        return {"ok": False, "error": f"下载失败：{str(e)[:120]}",
                "hint": "检查网络/代理，或改用安装包内置引擎、Ollama"}


# ── 引擎版本管理（更新/切换/回退）────────────────────────────
#
# 为什么需要：引擎随安装包下发后，用户不能为了升级引擎去重装整个软件。
# 设计要点（都是踩过的坑）：
#   1. **不覆盖随包目录**（resources/engines/）：安装后可能只读，且降级时要能回退。
#      所有下载的引擎落`DATA_DIR/engines/llama-cpp-<build号>/`。
#   2. **先验证再切换**：新引擎跑不起来绝不能把旧引擎搞坏（更新失败=保持原样）。
#   3. **正在推理时禁止更新**：exe 被占用，强换会失败甚至崩进程。
#   4. **用 current 指针文件做原子切换**：写指针是原子的（写临时文件再 rename），
#      比"删旧目录再拷新目录"安全 —— 中途失败还有旧版可用。

_ENGINE_REPO = "ggml-org/llama.cpp"
_ENGINE_STATE = "current.json"       # {current: "b11435", previous: "b10883"}
_VER_CACHE: dict = {"ts": 0, "local": None, "remote": None}


def _net_err_hint(e: Exception) -> str:
    """把网络异常翻译成用户看得懂的原因（尤其代理问题，本机高发）。"""
    s = str(e)
    low = s.lower()
    if "name 'urllib' is not defined" in low:
        return "内部错误：缺少网络模块"
    if "urlopen error" in low or "connection refused" in low or "failed to establish" in low:
        px = (os.environ.get("https_proxy") or os.environ.get("http_proxy") or "").strip()
        if px:
            return f"网络不通（当前代理 {px} 可能不可用）"
        return "网络不通，请检查网络/防火墙"
    if "timed out" in low:
        return "网络超时，请稍后重试"
    if "http error" in low:
        return f"GitHub 返回错误（{(e.args[1] if len(e.args) > 1 else '')})，可能触发限流"
    return s[:140]


def _engines_root() -> Path:
    try:
        from desktop_core import config
        dd = getattr(config, "DATA_DIR", None) or str(Path.home() / ".naixi")
    except Exception:
        dd = str(Path.home() / ".naixi")
    return Path(dd) / "engines"


def _engine_state_path() -> Path:
    return _engines_root() / _ENGINE_STATE


def _read_engine_state() -> dict:
    try:
        p = _engine_state_path()
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def _write_engine_state(st: dict) -> None:
    p = _engine_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)  # 原子替换


def _build_from_version_text(text: str) -> int:
    """从 `version: 0.4.0-dev (build 10883, commit xxx)` 里抽出 build 号。"""
    m = re.search(r"build\s+(\d+)", text or "")
    return int(m.group(1)) if m else 0


def engine_local_version(exe: str = "") -> dict:
    """读当前引擎的版本号（执行 --version）。拿不到返回 build=0。"""
    exe = exe or find_llamacpp()
    if not exe:
        return {"ok": False, "build": 0, "version_text": "", "path": ""}
    try:
        r = subprocess.run([exe, "--version"], capture_output=True,
                           timeout=30, text=True, errors="replace")
        txt = ((r.stdout or "") + (r.stderr or "")).strip()
        return {"ok": True, "build": _build_from_version_text(txt),
                "version_text": txt.splitlines()[0] if txt else "", "path": exe}
    except Exception as e:
        return {"ok": False, "build": 0, "version_text": "",
                "path": exe, "error": str(e)[:100]}


def _pick_asset(names: list, tag: str) -> str:
    """在官方资产里挑最适合本机的包：优先 Vulkan（老显卡可加速），退 CPU。"""
    n64 = "x64"
    prefer = [
        f"llama-{tag}-bin-win-vulkan-{n64}.zip",
        f"llama-{tag}-bin-win-cpu-{n64}.zip",
    ]
    low = {x.lower(): x for x in names}
    for p in prefer:
        if p.lower() in low:
            return low[p.lower()]
    # 兜底：任何 win + x64 + 非 arm 的包
    for x in sorted(names):
        xl = x.lower()
        if "win" in xl and n64 in xl and "arm64" not in xl and xl.endswith(".zip"):
            return x
    return ""


def engine_check_update(force: bool = False) -> dict:
    """查官方最新引擎版本 + 本地版本，给出是否有更新。"""
    local = engine_local_version()
    # 本地引擎缓存 60s，避免频繁启动进程
    if not force and time.time() - _VER_CACHE["ts"] < 60 and _VER_CACHE["remote"]:
        remote = _VER_CACHE["remote"]
    else:
        remote = {}
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{_ENGINE_REPO}/releases?per_page=10",
                headers={"User-Agent": "naixi-desktop", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                rels = json.loads(r.read().decode("utf-8", "replace"))
            for rel in rels:
                tag = (rel.get("tag_name") or "").lstrip("v")
                if not re.match(r"^b\d+$", tag):
                    continue  # 只认 bNNNN 形式的正式构建，跳过 v0.x 之类
                asset = _pick_asset([a["name"] for a in rel.get("assets", [])], tag)
                if not asset:
                    continue
                url = (rel.get("assets") or [{}])[0]
                # 精确取该 asset 的下载 url
                for a in rel.get("assets", []):
                    if a.get("name") == asset:
                        url = a
                        break
                remote = {"tag": tag, "asset": asset,
                          "url": url.get("browser_download_url", ""),
                          "published": rel.get("published_at", "")}
                break
            _VER_CACHE.update({"ts": time.time(), "remote": remote or None})
        except Exception as e:
            remote = {"error": _net_err_hint(e)}
            _VER_CACHE.update({"ts": time.time(), "remote": None})
    lb = int(local.get("build") or 0)
    rb = int(re.sub(r"\D", "", remote.get("tag", "") or "0") or 0)
    return {
        "ok": True,
        "local": {"build": lb, "version_text": local.get("version_text", ""),
                  "path": local.get("path", "")},
        "remote": remote,
        "has_update": bool(rb and lb and rb > lb),
        "note": ("本地已是最新" if rb and lb and rb <= lb
                 else "无法获取官方版本" if not remote.get("tag")
                 else "可更新"),
    }


def engine_update(tag: str = "", asset_url: str = "") -> dict:
    """下载新引擎 → 验证 → 原子切换；失败保持原引擎不动。"""
    # 1) 正在推理时禁止更新（exe 被占用，强换会失败/崩）
    try:
        if get_status().get("llamacpp_running"):
            return {"ok": False, "error": "推理服务正在运行，请先停止再更新引擎",
                    "hint": "在「本地模型」页点停止，或关掉正在跑的对话"}
    except Exception:
        pass

    info = engine_check_update(force=True)
    tag = (tag or info.get("remote", {}).get("tag") or "").strip()
    url = (asset_url or info.get("remote", {}).get("url") or "").strip()
    if not tag or not url:
        return {"ok": False, "error": "获取不到官方更新包信息",
                "hint": "请检查网络，或手动填写 llama.cpp 发布包地址"}

    target = _engines_root() / f"llama-cpp-{tag}"
    exe_name = _exe_names("llama-server")[0]
    try:
        import tempfile
        tmp = tempfile.mkdtemp(prefix="naixi_engine_up_")
        zp = Path(tmp) / "engine.zip"
        log.info("[local_model] 更新引擎 %s: %s", tag, url)
        req = urllib.request.Request(url, headers={"User-Agent": "naixi-desktop"})
        with urllib.request.urlopen(req, timeout=600) as r, open(zp, "wb") as f:
            while True:  # 流式落盘，避免大包占内存
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp) as z:
            z.extractall(target)
        exe = target / exe_name
        if not exe.is_file():
            # 官方包可能带一层 llama-<tag>-bin-win-xxx/ 子目录
            hits = list(target.rglob(exe_name))
            if not hits:
                shutil.rmtree(target, ignore_errors=True)
                return {"ok": False, "error": "更新包里没有 llama-server",
                        "hint": "该地址可能不是 llama.cpp 官方 Windows 发布包"}
            # 把 exe 及其同目录依赖一并搬到扁平结构
            src_dir = hits[0].parent
            for f in src_dir.iterdir():
                if f.is_file() and f.suffix.lower() in (".exe", ".dll"):
                    shutil.copy2(f, target / f.name)
        # 2) 验证：新引擎必须真能跑起来，否则绝不切换
        if not _engine_usable(str(exe)):
            shutil.rmtree(target, ignore_errors=True)
            return {"ok": False, "error": "新引擎依赖不完整，已放弃更新",
                    "hint": "原有引擎未受影响，可稍后重试"}
        ver = engine_local_version(str(exe))
        if ver.get("build", 0) <= 0:
            shutil.rmtree(target, ignore_errors=True)
            return {"ok": False, "error": "新引擎无法执行（--version 失败），已放弃更新",
                    "hint": "原有引擎未受影响"}
        shutil.rmtree(tmp, ignore_errors=True)
        # 3) 原子切换指针
        old = _read_engine_state().get("current", "")
        _write_engine_state({"current": tag, "previous": old,
                             "updated_at": int(time.time())})
        return {"ok": True, "tag": tag, "build": ver.get("build", 0),
                "version_text": ver.get("version_text", ""),
                "previous": old, "path": str(exe),
                "note": f"已更新到 {tag}，下次启动模型即生效（无需重启软件）"}
    except Exception as e:
        log.warning("[local_model] 引擎更新失败: %s", e)
        return {"ok": False, "error": f"更新失败：{str(e)[:140]}",
                "hint": "原有引擎未受影响，可稍后重试或手动下载后放入 engines 目录"}


def engine_update_status() -> dict:
    """本地已安装的多版本引擎列表 + 当前生效版本（供 UI 切换/回退）。"""
    root = _engines_root()
    items = []
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if not d.is_dir() or not d.name.startswith("llama-cpp-"):
                continue
            exe = d / _exe_names("llama-server")[0]
            if not exe.is_file():
                continue
            ver = engine_local_version(str(exe))
            items.append({"dir": d.name, "tag": d.name.replace("llama-cpp-", ""),
                          "build": ver.get("build", 0),
                          "usable": _engine_usable(str(exe))})
    state = _read_engine_state()
    return {"ok": True, "installed": items, "current": state.get("current", ""),
            "previous": state.get("previous", ""),
            "bundled": {"build": engine_local_version().get("build", 0),
                        "path": _candidate_llamacpp_paths()[0] if _candidate_llamacpp_paths() else ""},
            "note": "当前生效：%s" % (state.get("current") or "随包自带引擎")}


def engine_activate(tag: str = "") -> dict:
    """切换到指定已安装版本（tag 为空=切回随包自带引擎）。"""
    state = _read_engine_state()
    if not tag:
        _write_engine_state({})
        return {"ok": True, "note": "已切回随包自带引擎", "current": ""}
    d = _engines_root() / f"llama-cpp-{tag}"
    exe = d / _exe_names("llama-server")[0]
    if not _engine_usable(str(exe)):
        return {"ok": False, "error": f"版本 {tag} 不可用（文件缺失或不完整）"}
    _write_engine_state({"current": tag, "previous": state.get("current", ""),
                         "updated_at": int(time.time())})
    return {"ok": True, "current": tag, "note": f"已切换到 {tag}，下次启动模型生效"}


_GPU_CACHE: dict = {"checked": False, "device": ""}


def detect_gpu_device(exe: str = "") -> str:
    """探测 llama.cpp 可用的 GPU 设备名；没有就返回 ""（走纯 CPU）。

    踩过的坑：记忆里记的是 `-dev Vulkan1`（b10883 的参数），但本机现在装的
    b10901/b10902 编译时**没带 Vulkan 后端**，硬传会直接报
    `invalid device: Vulkan1` 并退出。所以这里必须**运行时探测**，
    探测不到就老老实实纯 CPU，别硬编码设备名。
    """
    exe = exe or find_llamacpp()
    if not exe:
        return ""
    if _GPU_CACHE["checked"]:
        return _GPU_CACHE["device"]
    _GPU_CACHE["checked"] = True
    try:
        import re
        r = subprocess.run([exe, "--list-devices"], capture_output=True,
                           timeout=25, text=True, errors="replace")
        # 输出形如：
        #   Vulkan0: Intel(R) HD Graphics 630 (...)
        #   Vulkan1: NVIDIA GeForce GTX 1050 Ti (...)
        # 设备名可能带尾随冒号（Vulkan0:），不能 split()[0] 取整行首 token
        # （那样会拿到 "Vulkan0:"，传给 -dev 被引擎判为无效设备，启动必失败）。
        # 用正则提取干净的设备标识符；并优先选独显（NVIDIA/AMD），
        # 而不是第一个（可能是 Intel 核显，加速无意义）。
        devs = []
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if not line or "available devices" in line.lower():
                continue
            if "(none)" in line.lower():
                continue
            m = re.search(r'(Vulkan\d+|CUDA\d+|GPU\d+|CPU|Metal\d+|ROCm\d+|hip\d+)', line)
            if m:
                devs.append((m.group(1), line))
        if devs:
            pref = next((d for d, ln in devs
                         if any(k in ln for k in ("NVIDIA", "GeForce", "AMD", "Radeon", "RTX", "GTX"))),
                        devs[0][0])
            _GPU_CACHE["device"] = pref
            log.info("[local_model] 检测到 GPU 设备: %s（共 %d 个：%s）",
                     pref, len(devs), ", ".join(d for d, _ in devs))
    except Exception as e:
        log.warning("[local_model] GPU 探测失败(将用纯CPU): %s", e)
    return _GPU_CACHE["device"]


def _port_alive(port: int, host: str = "127.0.0.1", timeout: float = 1.5) -> bool:
    import socket
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


# ── 模型发现 ────────────────────────────────────────────────
def _is_vision_name(low: str) -> bool:
    """按文件名判断是否视觉/多模态模型。

    踩过的坑：只匹配 "4v" 会漏掉 glm-4.1v（中间有小数点）、
    只匹配 "vl" 会漏掉 internvl 之外的写法。所以用正则覆盖
    「数字 + 可选小数点 + v」这类版本后缀（4v / 4.1v / 2.5v）。
    """
    import re
    if any(k in low for k in ("vision", "vlm", "-vl", "vl-", "minicpm")):
        return True
    # 形如 glm-4v / glm-4.1v / qwen2.5v / internvl3
    return bool(re.search(r"\d(?:\.\d+)?v\b", low))


def scan_gguf_models() -> list:
    """扫描本机 GGUF 模型文件。返回 [{path, name, size_gb, kind}]。

    kind 粗分类：vision（名字含 mmproj/vl/vision/glm-4v 等）/ text。
    mmproj 单独一类（投影文件）：它不能自己当主模型，但**可以点**——
    start_server 会自动反查并与视觉主模型配对联合启动。
    """
    out = []
    seen = set()
    for base in _user_scan_dirs():
        base_p = Path(base)
        if not base_p.is_dir():
            continue
        try:
            for f in base_p.rglob("*.gguf"):
                # 排除探针/缓存目录
                parts = {p.lower() for p in f.parts}
                if parts & {e.lower() for e in GGUF_EXCLUDE}:
                    continue
                key = str(f).lower()
                if key in seen:
                    continue
                seen.add(key)
                try:
                    size_gb = round(f.stat().st_size / (1024 ** 3), 2)
                except Exception:
                    size_gb = 0
                name = f.name
                low = name.lower()
                # mmproj 是视觉投影文件：不是独立主模型，但可点（点=与视觉主模型配对启动）
                if "mmproj" in low:
                    kind = "mmproj"
                elif _is_vision_name(low):
                    kind = "vision"
                else:
                    kind = "text"
                out.append({
                    "path": str(f), "name": name,
                    "size_gb": size_gb, "kind": kind,
                    "source": "gguf",
                    # 同名模型可能在不同目录（如备份/旧版），带上所在目录便于区分
                    "dir": str(f.parent.name),
                })
        except Exception as e:
            log.warning("[local_model] 扫描 %s 失败: %s", base, e)
    out.sort(key=lambda x: -x["size_gb"])
    return out


# ── safetensors 权重扫描 ────────────────────────────────────
# 为什么扫它：llama-server 只吃 GGUF（实测 safetensors 直接报
# "invalid magic characters, expected 'GGUF"），但safetensors 是
# HuggingFace 官方格式，**大量模型只发safetensors**。
# 不扫 = 明明硬盘上有模型却显示不出来，用户只能干瞪眼。
# 这里**只负责发现与标注**，能不能跑由引擎决定（见 resolve_engine）。
HF_WEIGHT_EXTS = (".safetensors", ".bin", ".pt")
# sharded 权重是 model-00001-of-00004.safetensors 这类，
# 一个模型是「一个目录里的所有分片」，不能当成 N 个模型。
_SHARD_RE = __import__("re").compile(r"-(\d{5})-of-(\d{5,6})")


def scan_hf_models() -> list:
    """扫描本机 HuggingFace 格式权重（safetensors / bin / pt）。

    现在这些模型**也能由奶昔本地启动**：后端 start_server 在收到非 GGUF 路径时会
    先调用内置转换层（convert_hf_to_gguf.py + torch 随包，无需任何外部软件）转成 GGUF，
    再交给 llama.cpp 跑。所以前端对所有 kind=text/vision 的模型都展示「启动」按钮，
    不再以"是否 GGUF"作为能否运行的判据。
    """
    out = []
    seen = set()
    for base in _user_scan_dirs():
        base_p = Path(base)
        if not base_p.is_dir():
            continue
        try:
            # 一个模型 = 一个含权重的目录（分片都在同目录）
            for d in base_p.rglob("*"):
                if not d.is_dir():
                    continue
                parts = {p.lower() for p in d.parts}
                if parts & {e.lower() for e in GGUF_EXCLUDE}:
                    continue
                try:
                    files = [f for f in d.iterdir()
                             if f.is_file() and f.suffix.lower() in HF_WEIGHT_EXTS]
                except Exception:
                    continue
                if not files:
                    continue
                # 分片模型：只认编号 00001 的那个分片算一次
                shards = [f for f in files if _SHARD_RE.search(f.name)]
                if shards:
                    files = [shards[0]]
                total = sum(f.stat().st_size for f in files)
                conf = d / "config.json"
                name = d.name
                low = name.lower()
                kind = "vision" if _is_vision_name(low) else "text"
                # 有 config.json 才像真的模型目录，否则可能只是半个下载
                has_cfg = conf.is_file()
                out.append({
                    "path": str(d),
                    "name": name,
                    "size_gb": round(total / (1024 ** 3), 2),
                    "kind": kind,
                    "source": "safetensors",
                    "engine": "llamacpp",     # 经内置转换层转 GGUF 后由 llama.cpp 加载
                    "engine_reason": "HuggingFace 权重格式，启动时会由奶昔内置转换层（torch 随包）先转成 GGUF 再交给 llama.cpp 跑，无需安装任何外部软件",
                    "has_config": has_cfg,
                    "shards": len(shards),
                    "dir": d.name,
                })
                seen.add(str(d).lower())
        except Exception as e:
            log.warning("[local_model] 扫描 HF 权重 %s 失败: %s", base, e)
    out.sort(key=lambda x: -x["size_gb"])
    return out


def find_mmproj_for(model_path: str) -> str | None:
    """给视觉主模型找配套的 mmproj（视觉投影文件）。

    **实测（b10902）**：视觉模型不带 --mmproj 起不来/读不了图；
    而 mmproj 自己当主模型会报
    "CLIP cannot be used as main model, use it with --mmproj instead"。
    两者是**配对关系**，缺一不可，所以启动视觉模型必须自动带上它。

    找法：同目录优先（llama.cpp 生态的惯例就是放一起），
    再退到同盘符任意扫描目录里同名族匹配。

    ★ 只有**视觉模型**才需要 mmproj。纯文本模型传--mmproj 是多余的
      （实测会给文本模型强行挂上视觉投影，浪费显存还可能报错）。
    """
    mp = Path(model_path)
    if not _is_vision_name(mp.stem.lower()):
        return None
    stem = mp.stem.lower()
    # 从主模型名里剥掉量化后缀：glm-4.1v-9b-q4_k_m → glm-4.1v-9b
    base = _SHARD_RE.sub("", stem)
    for suf in ("-q4_k_m", "-q4_0", "-q5_k_m", "-q8_0", "-q4_k_s",
                "-f16", "-f16_gguf", "-bf16", "-q3_k_m", "-q2_k", "-i8"):
        if base.endswith(suf):
            base = base[: -len(suf)]
            break
    key = base.split("-")[0] if "-" in base else base
    # 例：glm-4.1v-9b-q4_k_m → 找 mmproj 里含 glm 的
    cands = [p for p in mp.parent.glob("*mmproj*.gguf")]
    if not cands:
        for d in _user_scan_dirs():
            dp = Path(d)
            if not dp.is_dir():
                continue
            cands = [p for p in dp.rglob("*mmproj*.gguf")
                     if key and key in p.stem.lower()]
            if cands:
                break
    return str(cands[0]) if cands else None


def find_vision_for_mmproj(mmproj_path: str) -> str | None:
    """给 mmproj 投影文件反查它搭配的视觉**主模型**（用户直接点 mmproj 时用）。

    为什么需要：llama-server 的用法是 `--model 主模型 --mmproj 投影文件`，
    mmproj 自己当主模型会报 "CLIP cannot be used as main model"。
    所以用户在 UI 上点的是 mmproj 时，我们要能自动把它和主模型配成一对，
    而不是只显示一句"需搭配视觉模型"让用户自己猜怎么用。

    找法：同目录优先（llama.cpp 生态惯例就是主模型与 mmproj 放一起），
    候选里排除 mmproj 自身，取**视觉主模型**（名字匹配 _is_vision_name）；
    同目录没有就退到各扫描目录按体积找同族视觉模型。
    """
    mp = Path(mmproj_path)
    if "mmproj" not in mp.name.lower():
        return None

    def _pick(cands: list) -> str | None:
        # 排除 mmproj 自身
        cands = [p for p in cands if "mmproj" not in p.name.lower() and p.is_file()]
        if not cands:
            return None
        vis = [p for p in cands if _is_vision_name(p.stem.lower())]
        pool = vis or cands
        # ★ 优先量化版（q4/q5/q8/iq…），别默认挑 f16/bf16。
        #   实测踩坑：同目录里 glm-4.1v 同时有 17.5GB 的 f16 和 5.7GB 的 Q4_K_M，
        #   按"取最大"会选中 f16 —— 4GB 显存 + 纯 CPU 下首次推理要等几十秒甚至
        #   直接内存不够被杀掉。量化版才是能真跑起来的那个。
        #   同级之间再按体积小优先（更快启动）。
        QUANT = ("q2_", "q3_", "q4_", "q5_", "q6_", "q8_", "iq2", "iq3", "iq4",
                 "q2_k", "q3_k", "q4_k", "q5_k", "q6_k", "q3_k_m", "q4_k_m",
                 "q4_k_s", "q5_k_m", "q4_0", "q4_1", "q5_0", "q5_1", "q8_0", "iq4_xs")
        quant = [p for p in pool if any(t in p.stem.lower() for t in QUANT)]
        if quant:
            return str(min(quant, key=lambda p: p.stat().st_size))
        return str(min(pool, key=lambda p: p.stat().st_size))

    # 同目录（父目录）里找非 mmproj 的 gguf
    same = _pick(list(mp.parent.glob("*.gguf")))
    if same:
        return same
    # 退：各扫描目录里找视觉主模型（同样由 _pick 决定量化优先）
    best = None
    for d in _user_scan_dirs():
        dp = Path(d)
        if not dp.is_dir():
            continue
        got = _pick([p for p in dp.rglob("*.gguf") if _is_vision_name(p.stem.lower())])
        if got:
            sz = Path(got).stat().st_size
            if best is None or sz < Path(best).stat().st_size:
                best = got
    return best


def list_ollama_models() -> list:
    """读 Ollama 已安装模型（~/.ollama/models/manifests）。不依赖 ollama 命令。"""
    out = []
    root = Path.home() / ".ollama" / "models" / "manifests"
    if not root.is_dir():
        return out
    try:
        for ns_dir in root.iterdir():
            if not ns_dir.is_dir():
                continue
            for fam_dir in ns_dir.iterdir():
                if not fam_dir.is_dir():
                    continue
                for tag_file in fam_dir.iterdir():
                    out.append({
                        "name": f"{ns_dir.name}/{fam_dir.name}:{tag_file.name}"
                        if ns_dir.name != "library" else f"{fam_dir.name}:{tag_file.name}",
                        "source": "ollama",
                        "kind": "text",
                    })
    except Exception as e:
        log.warning("[local_model] 读 Ollama 模型库失败: %s", e)
    return out


def get_models() -> dict:
    """汇总本机可用模型 + 引擎情况。"""
    gguf = scan_gguf_models()
    hf = scan_hf_models()
    ollama = list_ollama_models()
    return {
        "ok": True,
        "engines": {
            "llamacpp": bool(find_llamacpp()),
            "llamacpp_path": find_llamacpp(),
            "ollama": bool(find_ollama()),
            "ollama_path": find_ollama(),
        },
        "models": gguf + hf + ollama,
        "gguf_count": len(gguf),
        "hf_count": len(hf),
        "ollama_count": len(ollama),
        # 扫了哪些目录、为什么 —— 用户模型不在列表里时要能自查
        "scan_dirs": _user_scan_dirs(),
    }


# ── 服务状态 ────────────────────────────────────────────────
# ★ 性能（2026-10-07）：`get_status()` 的短 TTL 缓存。
#   它内含 2 次本地回环 socket 端口探测；本机实测单次探测要 ~0.26s（走满超时，
#   本地端口未开放时不是立刻 RST），于是 get_status 天然要 0.5s+。
#   而 /api/desktop/config、/api/local/status 会被前端多个组件高频轮询，
#   每次都探一遍既慢又阻塞 aiohttp 事件循环。
#   状态本身是低频变化的（用户手动启停引擎），1s TTL 完全够用；
#   启停时用 invalidate_status_cache() 立刻失效，不必等自然过期。
_STATUS_CACHE: dict = {"ts": 0.0, "value": None}
_STATUS_TTL = 1.0  # 秒


def invalidate_status_cache():
    """启停本地推理服务后调用，立刻让下一次 get_status() 重算。"""
    _STATUS_CACHE["ts"] = 0.0
    _STATUS_CACHE["value"] = None


def _get_status_uncached() -> dict:
    """本地推理服务状态（Ollama / llama.cpp / 本模块拉起的实例）。

    额外给出 **对外接入信息**（`endpoint`）—— 模型不能只装不用：
    除了奶昔自己调用，还要能让第三方工具（VS Code / Cursor / Cherry Studio /
    任何 OpenAI 兼容客户端）填 base_url 接进来用。
    """
    p = _SERVER.get("proc")
    self_alive = bool(p is not None and p.poll() is None)
    # 当前实际绑定地址：默认只监听回环（安全），用户可在设置里放开到局域网。
    bind = str(_SERVER.get("host") or "127.0.0.1")
    external = bind not in ("127.0.0.1", "localhost", "::1")
    model_path = _SERVER.get("model_path", "")
    key = str(_SERVER.get("api_key") or "")
    # ★ 对外展示用的主机：局域网放开时不能给 127.0.0.1 ——
    #   那是"本机回环"，别的机器填了连的是它自己，等于永远连不上。
    shown_host = "127.0.0.1"
    if external:
        shown_host = _lan_ip() or bind

    # ★ 性能（2026-10-07）：端口探测结果**只算一次**，下面多处复用。
    #   原来这里连调 3 次 _port_alive()（ollama_running / llamacpp_running / endpoint.running），
    #   而它对**未开放**的端口要等满 socket 超时才返回 False ——
    #   实测 /api/desktop/config 慢到 4.5s，几乎全是这里白等出来的。
    #
    # ★★ 修正（2026-10-07 第二轮）：本机回环端口**未开放时不是立刻 RST**，
    #   connect 会一直等到超时才返回 —— 实测每次探测稳定耗 ~0.26s（正好是超时值）。
    #   所以「缩短超时」是唯一有效手段，而两个端口**串行探测就是两次白等相加**。
    #   修法：两个端口并发探测，总耗时 = 较慢的那个（~0.26s）而不是相加（~0.52s）。
    import concurrent.futures as _cf
    _alive_t = 0.12  # 本机回环 connect 秒通或秒拒，0.12s 足够判定；再大就是白等
    with _cf.ThreadPoolExecutor(max_workers=2) as _ex:
        _f_ollama = _ex.submit(_port_alive, OLLAMA_PORT, "127.0.0.1", _alive_t)
        _f_llamacpp = _ex.submit(_port_alive, LLAMACPP_PORT, "127.0.0.1", _alive_t)
        ollama_running = _f_ollama.result()
        llamacpp_running = _f_llamacpp.result()

    return {
        "ok": True,
        "ollama_running": ollama_running,
        "ollama_port": OLLAMA_PORT,
        "llamacpp_running": llamacpp_running,
        "llamacpp_port": LLAMACPP_PORT,
        "self_managed": self_alive,
        "self_model": model_path,
        "self_uptime_s": int(time.time() - _SERVER["started_at"]) if self_alive and _SERVER.get("started_at") else 0,
        # ── 对外接入（OpenAI 兼容）────────────────────────────
        # 第三方工具填 base_url 用；llama-server 不校验 key，随便填即可。
        "endpoint": {
            "base_url": f"http://{shown_host}:{LLAMACPP_PORT}/v1",
            "chat_url": f"http://{shown_host}:{LLAMACPP_PORT}/v1/chat/completions",
            "models_url": f"http://{shown_host}:{LLAMACPP_PORT}/v1/models",
            # 真设了 key 就把 key 给出（用户要拿它去第三方客户端填）；
            # 没设就给占位串，并靠 authenticated=False 提示"当前不鉴权"。
            "api_key": key or "local",
            "authenticated": bool(key),
            "bind": bind,
            "external_access": external,  # True = 已放开到局域网
            "running": llamacpp_running,   # 复用上面已算好的结果，别再探一次
            "model": os.path.basename(model_path) if model_path else "",
            "protocol": "OpenAI 兼容",
        },
    }


def get_status() -> dict:
    """带 1s TTL 缓存的入口（见 `_STATUS_CACHE` 处的性能说明）。

    返回浅拷贝：调用方（api.py 的 `_local_provider_entries_uncached`、
    `/api/local/status`）只读不写，但浅拷贝能挡住「有人往返回值里塞 key」这类意外。
    """
    now = time.time()
    cached = _STATUS_CACHE["value"]
    if cached is not None and (now - _STATUS_CACHE["ts"]) < _STATUS_TTL:
        return dict(cached)
    val = _get_status_uncached()
    _STATUS_CACHE["ts"] = now
    _STATUS_CACHE["value"] = dict(val)
    # endpoint 子字典也要拷一层，否则调用方改它会污染缓存
    if isinstance(val.get("endpoint"), dict):
        _STATUS_CACHE["value"]["endpoint"] = dict(val["endpoint"])
        return {**val, "endpoint": dict(val["endpoint"])}
    return val


def _lan_ip() -> str:
    """取本机在局域网里的 IP（给第三方设备填 base_url 用）。

    为什么不能直接给 127.0.0.1：那是回环地址，**别的机器填了连的是它自己**，
    表现为"地址看着对但永远连不上"。
    """
    import socket as _sk
    try:
        s = _sk.socket(_sk.AF_INET, _sk.SOCK_DGRAM)
        s.settimeout(0.5)
        # 连一个外部地址只为让系统选出出口网卡，并不会真的发包
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip if ip and not ip.startswith("127.") else ""
    except Exception:
        return ""


# ── 启动 / 停止 ─────────────────────────────────────────────
def _sanitize_config_for_convert(model_dir) -> None:
    """修正 HF config.json 里会让官方转换脚本崩溃的词表字段（**只改副本，不动用户原文件**）。

    实测踩坑：`gguf/vocab.py::_set_special_token` 对 `tid < 0` 直接
    `raise ValueError('invalid value for special token type pad: -1')`，
    而 `config.json` 里 `pad_token_id: -1`（表示"无 pad 填充"）是很常见的写法，
    官方脚本没兜住。HF 上有些模型（尤其 tiny/测试模型）就带这种值，
    于是一上来就崩，用户完全看不到 GGUF 长什么样。

    规则：**缺失(null)保持缺失**（脚本对非 int 直接 return，不动它），
    只把**负数**替换为 0（合法且语义最接近"不填充"）。真正的 pad id 0 不受影响。
    """
    import json as _json
    cfg = Path(model_dir) / "config.json"
    if not cfg.is_file():
        return
    try:
        data = _json.loads(cfg.read_text(encoding="utf-8"))
    except Exception:
        return
    changed = []
    for key in ("pad_token_id", "bos_token_id", "eos_token_id", "unk_token_id"):
        for holder in (data, data.get("text_config") or {}):
            if isinstance(holder, dict) and isinstance(holder.get(key), int) and holder[key] < 0:
                changed.append(f"{key}:{holder[key]}->0")
                holder[key] = 0
    if changed:
        try:
            cfg.write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            log.info("[local_model] 修正 config 词表字段(副本): %s", ", ".join(changed))
        except Exception as e:
            log.warning("[local_model] 修正 config 失败(忽略): %s", e)


def convert_to_gguf(model_path: str) -> dict:
    """把 HuggingFace 权重（safetensors / bin / pt 目录）转成 GGUF 再交给 llama.cpp。

    对齐 Ollama 的做法：Ollama 内部也是把 Safetensors/PyTorch 转成 GGUF 再跑，
    而不是让推理引擎直接吃原始权重。奶昔复用 llama.cpp 官方 convert_hf_to_gguf.py
    （随包在 resources/engines/convert/，由 `npm run bundle:converter` 获取）。

    转换依赖纯 Python 轻量包（gguf / safetensors / numpy），随 python-embed 自带，
    不要求用户安装任何外部软件。转换结果按模型目录缓存（*-converted.gguf）。
    """
    import subprocess as _sp, sys as _sys
    # ★ 用 DESKTOP_DIR 定位资源目录，**不要靠 parent.parent 猜层级**：
    #   开发态 local_model.py 在 <项目根>/desktop_core/  → parent.parent = 项目根，
    #     但转换器在 <项目根>/src-tauri/resources/engines/convert/；
    #   打包态在 <安装>/resources/desktop_core/            → parent.parent = resources/，
    #     转换器在 resources/engines/convert/。
    #   两种形态层级不同，靠数目录必然在其中一种下找不到。
    #   DESKTOP_DIR 由 naixi_api._find_core_root() 统一算出（开发态=项目根，打包态=resources），
    #   与引擎定位用的是同一套逻辑，避免出现"引擎找得到、转换器找不到"的分裂。
    _desktop = os.environ.get("DESKTOP_DIR")
    if _desktop:
        conv_dir = Path(_desktop) / "engines" / "convert"
        if not conv_dir.is_dir():
            # 开发态：DESKTOP_DIR=项目根，转换器在 src-tauri/resources 下
            conv_dir = Path(_desktop) / "src-tauri" / "resources" / "engines" / "convert"
    else:
        # 兜底（独立跑测试等无 DESKTOP_DIR 场景）：按 __file__ 向上找 engines/convert
        conv_dir = Path(__file__).resolve().parent.parent / "engines" / "convert"
    conv = conv_dir / "convert_hf_to_gguf.py"
    if not conv.is_file():
        return {"ok": False, "need_converter": True,
                "error": "未找到模型转换组件",
                "hint": "请先运行 `npm run bundle:converter` 获取转换工具（奶昔自带，无需安装任何外部软件）"}
    src = Path(model_path)
    base = src.name if src.is_dir() else src.stem
    outfile = (src.parent if src.is_dir() else src.parent) / f"{base}-converted.gguf"
    if outfile.is_file():
        log.info("[local_model] 命中已转换缓存: %s", outfile)
        return {"ok": True, "gguf": str(outfile), "cached": True}
    env = os.environ.copy()
    # ★ 不要设 NO_LOCAL_GGUF —— 那会让官方脚本改用 PyPI 的 gguf 包（当前 0.19.0），
    #   而随包 conversion/ 是与引擎同源的新版，二者枚举不匹配，实测直接炸：
    #   "AttributeError: type object 'MODEL_ARCH' has no attribute 'DFLASH'"。
    #   不设它时脚本会用**同目录随包的 gguf-py**（与 conversion/ 严格同源），
    #   这正是官方提供该开关的意图：转换层必须版本自洽。
    env["PYTHONUTF8"] = "1"
    # ★ 必须用 -c 显式把转换器目录插进 sys.path，不能直接 `python convert_hf_to_gguf.py`。
    #   原因（实测踩坑）：python-embed 自带 python313._pth 会**锁死 sys.path**
    #   （只有 python313.zip / . / site-packages 三条），脚本所在目录**不会**自动进 path，
    #   于是官方脚本的 `from conversion import ...` 必然 ModuleNotFoundError。
    #   而 `_pth` 是整个后端解释器的地基，不能为了转换器去改它（会外溢影响后端行为），
    #   所以在子进程里手动补 sys.path 是唯一干净解法。
    runner = (
        "import sys, runpy\n"
        f"sys.path.insert(0, {str(conv_dir)!r})\n"
        f"sys.argv = [{str(conv)!r}] + sys.argv[1:]\n"
        f"runpy.run_path({str(conv)!r}, run_name='__main__')\n"
    )
    # ★★ 中文路径必须绕道 —— 这是 Windows 上的硬坑（实测）：
    #   sentencepiece 的 C++ 层用窄字符 API 打开 tokenizer.model，
    #   `os.path.exists(中文路径)` 返回 True，但 LoadFromFile 直接报
    #   `NOT_FOUND: ... No such file or directory Error #2`。
    #   同样的文件拷到纯 ASCII 路径下立刻 LOAD_OK —— 文件没问题，是路径编码问题。
    #   而奶昔默认模型目录是 `D:\数据\本地模型`（纯中文），**所有中文用户都会踩**，
    #   官方脚本 `tokenizer.LoadFromFile(str(self.dir_model / 'tokenizer.model'))`
    #   传的是绝对路径，改不动（改官方脚本会在升级时丢）。
    #   所以：路径含非 ASCII 时，把模型镜像到纯 ASCII 影子目录再转，完成后搬回原目录。
    src_arg = str(src)
    shadow = None
    try:
        # 统一走影子目录，两个理由（都不是"为了省事"）：
        #  ① 中文路径：sentencepiece 窄字符 API 打不开（见上）；
        #  ② 连通性：转换过程会**改写 config.json**（_sanitize_config_for_convert），
        #     直接改用户下载的原始模型目录是越界行为（铁则：不擅动用户数据）。
        #     影子目录是一次性副本，转换完连同产物一起清理/搬回。
        #     ASCII 路径同样走影子目录，代价只是拷贝一次，收益是行为一致 + 不污染原文件。
        import shutil as _sh, tempfile as _tf
        ascii_root = _tf.gettempdir()
        if not ascii_root.isascii():
            ascii_root = "C:\\Windows\\Temp"
        import re as _re
        tag = _re.sub(r"[^A-Za-z0-9_.-]", "_", src.name)[:40] or "model"
        shadow = Path(ascii_root) / f"naixi_conv_{tag}"
        if shadow.is_dir():
            _sh.rmtree(shadow, ignore_errors=True)
        _sh.copytree(str(src), str(shadow))
        _sanitize_config_for_convert(shadow)
        # outfile 也必须落在 ASCII 路径，否则写出来同样会被下游窄字符 API 拒
        shadow_out = shadow.parent / f"{shadow.name}-out.gguf"
        src_arg = str(shadow)
        out_arg = str(shadow_out)
        if not str(src).isascii():
            log.info("[local_model] 中文路径，转换走 ASCII 影子目录: %s", shadow)
        log.info("[local_model] 开始转换 HF 权重 → GGUF: %s", model_path)
        r = _sp.run([_sys.executable, "-c", runner, src_arg,
                     "--outfile", out_arg, "--outtype", "f16"],
                    capture_output=True, text=True, env=env, timeout=7200)
        if shadow:
            # 搬回原目录（跨盘符移动用 copy+delete；同盘优先 os.replace）
            import shutil as _sh2
            got = Path(out_arg)
            if got.is_file():
                if outfile.is_file():
                    outfile.unlink()
                try:
                    os.replace(str(got), str(outfile))
                except OSError:
                    _sh2.copy2(str(got), str(outfile))
                    got.unlink(missing_ok=True)
        if r.returncode != 0 or not outfile.is_file():
            tail = "\n".join((r.stderr or r.stdout or "").splitlines()[-12:])
            return {"ok": False, "error": "HF 权重转 GGUF 失败", "detail": tail}
    except Exception as e:
        return {"ok": False, "error": f"转换异常: {e}"}
    finally:
        if shadow:
            import shutil as _sh3
            _sh3.rmtree(str(shadow), ignore_errors=True)
    log.info("[local_model] 转换完成: %s", outfile)
    return {"ok": True, "gguf": str(outfile), "cached": False}


def start_server(model_path: str, ctx: int = 8192, gpu_layers: int = 999,
                 threads: int = 0, batch: int = 512,
                 port: int = LLAMACPP_PORT, host: str = "",
                 api_key: str = "") -> dict:
    """用 llama-server 拉起本地推理服务（OpenAI 兼容端口）。

    参数默认值按本机 GTX 1050 Ti 4GB 实测给出：
      · --ctx 默认 8192（记忆里 65536 是长上下文场景，4GB 卡常规对话 8192 更稳）
      · -ctk/-ctv q8_0（KV 量化，省显存；本机 Vulkan无 q4_0 快速 kernel，别用 q4_0）
      · -dev Vulkan1（Pascal 走 Vulkan 后端）
      · threads=0 → llama.cpp 自动（按 CPU 逻辑核数）；batch=512 是 4GB 卡稳妥值
    注意：ctx / gpu_layers / threads / batch 都是「启动期」参数，改了必须重启才生效。
    采样类参数（temperature/top_p/...）在每次对话请求里传，即时生效，见 chat()。

    `host` 监听地址：**默认只绑 127.0.0.1**。
    放开到 0.0.0.0 会暴露到局域网，所以必须由用户显式开启。
    传 "" 即用默认（回环）。

    `api_key`：llama-server **原生支持** `--api-key`（实测：无/错 token 401，对 token 200），
    无需自己实现鉴权层。放开局域网时**必须**带 key —— 不让用户裸奔。
    留空 = 不鉴权（仅限回环监听时可接受）。
    """
    exe = find_llamacpp()
    if not exe:
        return {"ok": False, "error": "未找到 llama-server.exe"}
    if not model_path:
        return {"ok": False, "error": "缺少 model_path"}
    low = model_path.lower()
    is_gguf = low.endswith(".gguf")
    # ★ 用户可能在 UI 上直接点了 mmproj 投影文件。llama-server 的正确用法是
    #   `--model 主模型 --mmproj 投影文件`，mmproj 自己当主模型会报
    #   "CLIP cannot be used as main model"。所以这里不报错，而是**反查主模型**，
    #   把两者配成一对联合启动——这才是用户点 mmproj 时真正想要的效果。
    if "mmproj" in Path(model_path).name.lower():
        main_model = find_vision_for_mmproj(model_path)
        if not main_model:
            return {"ok": False,
                    "error": "这是一个视觉投影文件(mmproj)，但没找到与它搭配的视觉主模型",
                    "hint": "视觉模型需要「主模型(.gguf) + mmproj 投影文件(.gguf)」成对存在。"
                            "请把主模型也放到同一目录（llama.cpp 生态惯例），或直接在列表里点视觉主模型启动。"}
        log.info("[local_model] 检测到 mmproj 入口，自动配对视觉主模型: %s",
                 os.path.basename(main_model))
        model_path = main_model
        low = model_path.lower()
        is_gguf = low.endswith(".gguf")
    # GGUF 是单文件；HuggingFace 权重(safetensors/bin/pt)是一个目录
    if is_gguf or low.endswith((".safetensors", ".bin", ".pt")):
        exists = os.path.isfile(model_path)
    else:
        exists = os.path.isdir(model_path)
    if not exists:
        return {"ok": False, "error": f"模型不存在: {model_path}"}
    # 非 GGUF（HuggingFace 权重）→ 先转成 GGUF 再加载（对齐 Ollama 做法，奶昔自带转换层）
    if not is_gguf:
        conv = convert_to_gguf(model_path)
        if not conv.get("ok"):
            return conv
        model_path = conv["gguf"]
        log.info("[local_model] 使用转换后的 GGUF: %s", model_path)
    p = _SERVER.get("proc")
    if p is not None and p.poll() is None:
        return {"ok": False, "error": "本地推理服务已在运行，请先停止"}

    # 放开到局域网时**强制**要求 key：不让人裸奔（llama-server 原生鉴权，实测有效）
    _bind = (host or "127.0.0.1")
    _external = _bind not in ("127.0.0.1", "localhost", "::1")
    if _external and not api_key:
        return {"ok": False,
                "error": "放开局域网访问必须设置访问令牌",
                "hint": "局域网内任何人都能调用你的模型，必须加令牌；"
                        "只在自己电脑用就别放开（保持默认 127.0.0.1）。"}
    cmd = [
        exe, "--model", model_path,
        # 监听地址：默认只回环。放开到 0.0.0.0 需用户显式传 host，且必须带 api_key。
        "--host", _bind, "--port", str(port),
        "-c", str(ctx),
        "-ngl", str(gpu_layers),
        "-ctk", "q8_0", "-ctv", "q8_0",
    ]
    if api_key:
        # llama-server 原生 --api-key（支持多个），不必自己造鉴权层
        cmd += ["--api-key", api_key]
    # 性能类启动参数：用户没指定就走 llama.cpp 自动（不强行塞默认值）
    if threads and threads > 0:
        cmd += ["-t", str(threads)]
    if batch and batch > 0:
        cmd += ["-b", str(batch)]
    # ★ 视觉模型必须配对 mmproj —— 实测（b10902）：
    #   带 mmproj → 纯文本和读图都成功；不带 → 读不了图。
    #   而 mmproj 自己不能当主模型（CLIP cannot be used as main model）。
    #   所以「视觉主模型 + mmproj」是一对，必须一起拉起来。
    mmproj = ""
    if Path(model_path).name.lower().find("mmproj") < 0:
        mmproj = find_mmproj_for(model_path) or ""
    if mmproj and Path(mmproj).is_file():
        cmd += ["--mmproj", mmproj]
        log.info("[local_model] 视觉模型自动配对 mmproj: %s", os.path.basename(mmproj))
    # GPU 设备要运行时探测：本机装的 llama.cpp 构建若没带 Vulkan 后端，
    # 硬传 -dev 会直接报 invalid device 并退出（踩过）。
    dev = detect_gpu_device(exe)
    if dev:
        cmd += ["-dev", dev]
        cmd += ["-fa", "on"]
    else:
        log.info("[local_model] 未检测到 GPU 后端，使用纯 CPU 推理")
    try:
        # 输出落盘而不是 DEVNULL：启动失败时能拿到真实原因
        # （之前吞掉 stderr，只能看到"意外退出"，等于掩盖问题）
        _logdir = Path(__file__).resolve().parent.parent / "data"
        try:
            _logdir.mkdir(parents=True, exist_ok=True)
            _lf = open(_logdir / "llama_server.log", "ab", buffering=0)
        except Exception:
            _lf = subprocess.DEVNULL
        proc = subprocess.Popen(
            cmd, stdout=_lf, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        _SERVER.update({"proc": proc, "port": port, "model_path": model_path,
                        "mmproj": mmproj, "started_at": time.time(),
                        "host": _bind, "api_key": api_key})
        log.info("[local_model] 已启动本地推理: %s (port=%s, mmproj=%s)",
                 os.path.basename(model_path), port, os.path.basename(mmproj) or "-")

        # 等待端口就绪（llama-server 加载模型需要时间，给足 180s：
        # 视觉模型带 mmproj 实测要 100s+ 才加载完）
        for _ in range(180):
            if proc.poll() is not None:
                tail = _read_log_tail(400)
                return {"ok": False,
                        "error": "推理进程启动后意外退出（可能是模型/显存问题）",
                        "detail": tail}
            if _port_alive(port):
                return {"ok": True, "port": port, "model": os.path.basename(model_path),
                        "mmproj": os.path.basename(mmproj) if mmproj else "",
                        "vision": bool(mmproj),
                        "waited_s": int(time.time() - _SERVER["started_at"])}
            time.sleep(1)
        return {"ok": True, "port": port, "model": os.path.basename(model_path),
                "mmproj": os.path.basename(mmproj) if mmproj else "",
                "ready": False, "note": "进程已起但端口未就绪（模型仍在加载）"}
    except Exception as e:
        log.warning("[local_model] 启动失败: %s", e)
        return {"ok": False, "error": str(e)[:120]}


def _read_log_tail(n: int = 300) -> str:
    """读 llama_server.log 末尾 —— 启动失败时把真实原因带给用户，
    而不是只说"意外退出"让人猜。"""
    try:
        p = Path(__file__).resolve().parent.parent / "data" / "llama_server.log"
        if p.is_file():
            with p.open("rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 4096))
                raw = f.read().decode("utf-8", "replace")
            lines = [ln for ln in raw.splitlines() if ln.strip()]
            return "\n".join(lines[-8:])[-n:]
    except Exception:
        pass
    return ""


def chat(model_path_or_name: str, messages: list, max_tokens: int = 1024,
         temperature: float = 0.7, port: int = LLAMACPP_PORT, timeout: int = 180,
         top_p: float | None = None, top_k: int | None = None,
         repeat_penalty: float | None = None, min_p: float | None = None,
         seed: int | None = None) -> dict:
    """调用本地推理服务对话（OpenAI 兼容格式）。

    推理模型（如 Spark X2.5）的两个坑，这里都处理了：
      · 思考过程在 `reasoning_content` 而不是 `content`，max_tokens 给小了
        推理还没结束就被截断 → content 为空（用户看到"没回答"）。
        所以默认给 1024，并在 content 为空时回退用推理内容。
      · 服务端会保留推理（`--reasoning-preserve`），无需额外参数。

    采样参数（top_p/top_k/repeat_penalty/min_p/seed）是「对话期」参数：
    请求级覆盖 server 启动时的默认值，即时生效，无需重启。
    这些参数名就是 llama.cpp server 在 /v1/chat/completions 里认的字段，
    只有用户显式设了（非 None）才透传，否则让 server 用它的默认。
    """
    import urllib.request
    url = f"http://127.0.0.1:{port}/v1/chat/completions"
    payload: dict = {
        "model": model_path_or_name or "local",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    # 采样参数按需透传：None 表示「用 server 默认」，不强行覆盖
    if top_p is not None:
        payload["top_p"] = top_p
    if top_k is not None:
        payload["top_k"] = top_k
    if repeat_penalty is not None:
        payload["repetition_penalty"] = repeat_penalty
    if min_p is not None:
        payload["min_p"] = min_p
    if seed is not None:
        payload["seed"] = seed
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}

    ch = (d.get("choices") or [{}])[0]
    msg = ch.get("message", {})
    content = (msg.get("content") or "").strip()
    reasoning = (msg.get("reasoning_content") or "").strip()
    # content 为空 + 推理被截断 → 提示调用方加大 max_tokens
    hint = ""
    if not content and ch.get("finish_reason") == "length":
        hint = "回答被截断（推理模型思考过程较长），请提高 max_tokens 后重试"
    return {
        "ok": True,
        "content": content,
        "reasoning": reasoning,
        "finish_reason": ch.get("finish_reason"),
        "usage": d.get("usage", {}),
        "hint": hint,
        # content 为空但推理有内容时，把推理尾部作为兜底展示（至少让用户看到东西）
        "fallback": (reasoning[-200:] if (not content and reasoning) else ""),
    }


def stop_server() -> dict:
    p = _SERVER.get("proc")
    if p is None:
        return {"ok": True, "stopped": False, "note": "本模块没有拉起过推理服务"}
    try:
        p.terminate()
        try:
            # ★ 2026-10-08：原来 p.wait(timeout=8) 把整个 /api/local/stop 请求卡了最多 8 秒，
            #   前端按钮虽然转圈，但 8 秒内无响应，用户体感「关闭点了没反应」。
            #   降到 3 秒：SIGTERM 后绝大多数进程 3 秒内退干净；超时再 SIGKILL 兜底。
            #   同步等满 3 秒（而非后台线程）是为了**保证端口 11436 真正释放**再返回，
            #   否则紧接着的「启动」会因端口被占而失败。
            p.wait(timeout=3)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    except Exception as e:
        log.warning("[local_model] 停止异常: %s", e)
    _SERVER.update({"proc": None, "model_path": "", "started_at": 0,
                    "host": "127.0.0.1", "api_key": ""})
    return {"ok": True, "stopped": True}
