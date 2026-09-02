"""Live2D 模型表情/动作发现（共享模块）。

供两处复用（同一套逻辑，禁止各写一份）：
  - desktop_core/api.py         → web 宠物 /pet：注入 model3.json 给 easy-live2d
  - desktop_core/pet_window.py  → Qt 桌宠：LoadExtraExpression/LoadExtraMotion 注入

背景：VTS 商店模型普遍不在 model3.json 的 FileReferences 里声明表情/动作，
而是散落在目录（含子目录）的 *.exp3.json / *.motion3.json 与 *.vtube.json 的
Hotkeys 里。任何渲染端直接读磁盘 model3.json 都会得到空表情列表。
"""

import ctypes
import glob
import json
import os
import time

__all__ = [
    "strip_ext",
    "is_valid_motion3",
    "exp3_display_name",
    "discover_model_actions",
    "discover_models",
    "get_extra_roots",
    "add_model_root",
    "remove_model_root",
]


def strip_ext(fn: str) -> str:
    """去掉 Live2D 双层扩展名（.model3.json / .exp3.json / .motion3.json / .json）。"""
    b = os.path.basename(fn)
    for suf in (".model3.json", ".exp3.json", ".motion3.json", ".json"):
        if b.lower().endswith(suf):
            return b[: -len(suf)]
    return os.path.splitext(b)[0]


def is_valid_motion3(motion_path: str) -> bool:
    """校验 motion3.json 是否可被渲染端正常解析。

    部分 VTS 导出的 motion 含畸形 Curve（缺 Target 字段），easy-live2d 解析会抛
    ``Cannot set properties of undefined (setting 'time')``，导致整个模型加载失败、
    快捷键无法驱动模型。此处提前剔除这类坏文件，从根源避免崩溃。
    """
    try:
        with open(motion_path, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        return False
    for c in d.get("Curves", []) or []:
        if not isinstance(c, dict):
            continue
        t = c.get("Target")
        if t is None or t == "":
            return False
    return True


def exp3_display_name(exp3_path: str) -> str:
    """表情显示名：优先取 exp3.json 的 ``Name`` 字段（渲染端以此注册表达式），
    缺失时回退到文件名（去扩展名）。热键绑定必须用这个名字，setExpression 才能命中。"""
    try:
        with open(exp3_path, encoding="utf-8") as fh:
            d = json.load(fh)
        nm = (d.get("Name") or "").strip()
        if nm:
            return nm
    except Exception:
        pass
    return strip_ext(exp3_path)


def discover_model_actions(model3_path: str) -> dict:
    """读取模型文件里原本写的快捷键动作。

    来源：
      1) 目录内（含子目录，递归）*.exp3.json / *.motion3.json —— 模型真实表情/动作文件；
      2) model3.json 自身 FileReferences 声明的表情/动作；
      3) 同目录 *.vtube.json 的 Hotkeys 数组 —— VTS「原本写的」快捷键动作。

    返回 {expressions:[{name,file}...], motions:[{group,name,file,no}...], hotkeys:[{name,kind,file}...]}
      file 为相对模型目录的路径（含子目录），供 model3 注入与渲染端精确加载。
    """
    model_dir = os.path.dirname(model3_path)
    out = {"expressions": [], "motions": [], "hotkeys": []}
    seen_exp = set()
    seen_mot = set()

    def _add_exp(name, rel):
        if name and name not in seen_exp:
            seen_exp.add(name)
            out["expressions"].append({"name": name, "file": rel})

    def _add_mot(name, rel, grp="Action"):
        if name and name not in seen_mot:
            seen_mot.add(name)
            out["motions"].append({"group": grp, "name": name, "file": rel, "no": len(out["motions"])})

    # 1) 目录内独立的 *.exp3.json / *.motion3.json
    try:
        for f in sorted(glob.glob(os.path.join(model_dir, "**", "*.exp3.json"), recursive=True)):
            rel = os.path.relpath(f, model_dir).replace("\\", "/")
            _add_exp(exp3_display_name(f), rel)
    except Exception:
        pass
    try:
        for f in sorted(glob.glob(os.path.join(model_dir, "**", "*.motion3.json"), recursive=True)):
            rel = os.path.relpath(f, model_dir).replace("\\", "/")
            # 跳过畸形 motion（缺 Target 曲线会让渲染端解析崩溃、动作无法播放）
            if not is_valid_motion3(f):
                continue
            _add_mot(strip_ext(f), rel)
    except Exception:
        pass

    # 2) model3.json 自身 FileReferences 直接声明的表情/动作。很多 VTS 模型把表情写在这里
    #    而非独立 exp3 文件，必须纳入；否则这类模型的发现列表为空 → 默认热键为空 → “按下没反应”。
    try:
        with open(model3_path, encoding="utf-8") as fh:
            md = json.load(fh)
        fr = md.get("FileReferences", {}) or {}
        for e in (fr.get("Expressions") or []):
            if not isinstance(e, dict):
                continue
            name = (e.get("Name") or strip_ext(e.get("File") or "")).strip()
            rel = (e.get("File") or "").replace("\\", "/")
            _add_exp(name, rel)
        for grp, lst in (fr.get("Motions") or {}).items():
            if not isinstance(lst, list):
                continue
            for m in lst:
                if not isinstance(m, dict):
                    continue
                rel = (m.get("File") or "").replace("\\", "/")
                if not rel:
                    continue
                full = os.path.join(model_dir, rel)
                if os.path.exists(full) and not is_valid_motion3(full):
                    continue
                _add_mot(strip_ext(rel), rel, grp)
    except Exception:
        pass

    # 3) vtube.json Hotkeys
    vtube = os.path.join(model_dir, strip_ext(os.path.basename(model3_path)) + ".vtube.json")
    if os.path.exists(vtube):
        try:
            d = json.load(open(vtube, encoding="utf-8"))
            for h in d.get("Hotkeys", []) or []:
                name = (h.get("Name") or "").strip()
                action = (h.get("Action") or "").strip()
                file = (h.get("File") or "").strip()
                if not name and file:
                    name = strip_ext(file)
                if not name:
                    continue
                kind = "expression"
                if "motion" in action.lower() or file.lower().endswith(".motion3.json") or "animation" in action.lower():
                    kind = "motion"
                out["hotkeys"].append({"name": name, "kind": kind, "file": file})
        except Exception:
            pass
    return out


# VTube Studio 商店模型目录（业界固定布局，用 ProgramFiles 环境变量推导，不写死盘符）。
# 与 pet_window.py 原本写死的 VTS_MODELS 保持一致，集中在此避免两处再次漂移。
VTS_MODELS = os.path.join(
    os.environ.get("ProgramFiles", r"C:\Program Files"),
    "Steam", "steamapps", "common", "VTube Studio",
    "VTube Studio_Data", "StreamingAssets", "Live2DModels",
)

# 部分机器 Steam 装在 ProgramFiles(x86)；补一路搜索根，避免“有模型却没自动发现”。
VTS_MODELS_X86 = os.path.join(
    os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    "Steam", "steamapps", "common", "VTube Studio",
    "VTube Studio_Data", "StreamingAssets", "Live2DModels",
)


# ─────────────────────────────────────────────────────────────────────────────
# 一劳永逸的模型根探测（2026-08-06 重写，彻底消除硬编码）
#
# 设计原则：不写死任何盘符 / 用户名 / 子目录名。
#   ① 标准根：data/models、godot_renderer/models、VTS 商店目录（布局固定，用环境变量推导）。
#   ② 用户模型库：用 Windows API 取「真实文档路径」（SHGetFolderPathW，junction-safe），
#      再递归扫描其下所有层级的 *.model3.json —— 不再假设「素材」之类的子目录名。
#   ③ 自定义根：用户通过 API / UI 显式添加的常驻模型目录，持久化到 data/models_roots.json，
#      亲手指定的路径永不漏、永不依赖猜目录结构，是最稳的一层。
#   ④ 缓存：带 TTL，避免每次启动全量递归扫描；用户增删自定义根立即失效缓存。
# ─────────────────────────────────────────────────────────────────────────────

def _known_folder_path(csidl: int) -> str:
    """用 Windows API 取真实已知文件夹路径（正确处理 junction / 库重定向）。

    优于读 USERPROFILE 环境变量：后者在 junction 机器上会解析到逻辑路径
    （C:\\Users\\xxx）而非物理路径（D:\\用户\\xxx），导致漏掉真实模型库。
    失败（非 Windows / 沙箱）时回退到 USERPROFILE 环境变量推导。
    """
    try:
        buf = ctypes.create_unicode_buffer(4096)
        res = ctypes.windll.shell32.SHGetFolderPathW(0, csidl, 0, 0, buf)
        if res == 0 and buf.value:
            return buf.value
    except Exception:
        pass
    # 回退：CSIDL_Documents = 5
    if csidl == 5:
        up = os.environ.get("USERPROFILE", "")
        if up:
            return os.path.join(up, "Documents")
    return ""


def _roots_config_path() -> str:
    desktop_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(desktop_root, "data", "models_roots.json")


def get_extra_roots() -> list:
    """用户显式添加的常驻模型根目录（持久化）。不存在返回 []。"""
    p = _roots_config_path()
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, list):
            return [os.path.abspath(str(x)) for x in d if x]
    except Exception:
        pass
    return []


def add_model_root(path: str) -> bool:
    """持久化添加一个模型根目录；成功返回 True（不存在的目录返回 False）。"""
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        return False
    cur = get_extra_roots()
    if path not in cur:
        cur.append(path)
        try:
            os.makedirs(os.path.dirname(_roots_config_path()), exist_ok=True)
            with open(_roots_config_path(), "w", encoding="utf-8") as f:
                json.dump(cur, f, ensure_ascii=False, indent=2)
            _invalidate_cache()
        except Exception:
            return False
    return True


def remove_model_root(path: str) -> bool:
    """从持久化列表移除一个模型根目录；成功返回 True。"""
    path = os.path.abspath(path)
    cur = get_extra_roots()
    if path in cur:
        cur.remove(path)
        try:
            with open(_roots_config_path(), "w", encoding="utf-8") as f:
                json.dump(cur, f, ensure_ascii=False, indent=2)
            _invalidate_cache()
        except Exception:
            return False
        return True
    return False


def _cache_path() -> str:
    desktop_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(desktop_root, "data", ".discover_cache.json")


_CACHE_TTL = 600  # 秒；短 TTL 防止长期漏扫（用户增删根会立即失效缓存）


def _invalidate_cache() -> None:
    try:
        os.remove(_cache_path())
    except OSError:
        pass


def _read_cache():
    p = _cache_path()
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if time.time() - d.get("ts", 0) > _CACHE_TTL:
            return None
        return d
    except Exception:
        return None


def _write_cache(models: list) -> None:
    try:
        os.makedirs(os.path.dirname(_cache_path()), exist_ok=True)
        with open(_cache_path(), "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "models": models}, f, ensure_ascii=False)
    except Exception:
        pass


def discover_models() -> list:
    """自动发现本地 Live2D 模型（discover 的唯一权威实现，供后端 / 前端 / 桌宠共用）。

    根来源（不写死任何盘符 / 用户名 / 子目录名）：
      1) 桌面 data/models        —— 「导入模型」落盘目录；
      2) godot_renderer/models   —— VRM/Godot 渲染兜底目录；
      3) VTS 商店目录(x64/x86)   —— 业界固定布局，用 ProgramFiles 变量推导；
      4) 真实文档路径            —— Windows API 取（junction-safe），递归扫其下所有模型；
      5) 用户自定义根            —— 持久化于 data/models_roots.json，亲手指定的永不漏。

    每层递归搜索所有层级的 *.model3.json（覆盖 VTS/data/models 深层 与 用户库任意嵌套）。
    name 取模型所在文件夹名；按路径稳定排序；未发现返回 []（调用方回退文件选择器）。

    缓存：TTL 内直接返回上次结果，避免每次启动全量递归扫描；用户增删自定义根立即失效。
    仅依赖标准库（含 ctypes），不引入 PySide/live2d，可在后端 aiohttp 与 Qt 子进程安全共用。
    """
    desktop_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    doc_path = _known_folder_path(5)  # CSIDL_Documents
    raw_roots = [
        os.path.join(desktop_root, "data", "models"),
        os.path.join(desktop_root, "godot_renderer", "models"),
        VTS_MODELS,
        VTS_MODELS_X86,
        doc_path,
    ] + get_extra_roots()

    # 去重 + 仅保留真实存在的目录
    seen_root = set()
    roots = []
    for r in raw_roots:
        if not r:
            continue
        rn = os.path.normcase(os.path.abspath(r))
        if rn in seen_root:
            continue
        seen_root.add(rn)
        if os.path.isdir(rn):
            roots.append(rn)

    # 缓存命中：TTL 内且无人为失效
    cache = _read_cache()
    if cache and cache.get("models") is not None:
        return cache["models"]

    models = []
    seen = set()
    for base in roots:
        for mp in sorted(glob.glob(os.path.join(base, "**", "*.model3.json"), recursive=True)):
            key = os.path.normcase(mp)
            if key in seen:
                continue
            seen.add(key)
            name = os.path.basename(os.path.dirname(mp))
            models.append({"name": name, "modelFile": os.path.basename(mp), "path": mp})

    _write_cache(models)
    return models
