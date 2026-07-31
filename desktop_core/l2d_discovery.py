"""Live2D 模型表情/动作发现（共享模块）。

供两处复用（同一套逻辑，禁止各写一份）：
  - desktop_core/api.py         → web 宠物 /pet：注入 model3.json 给 easy-live2d
  - desktop_core/pet_window.py  → Qt 桌宠：LoadExtraExpression/LoadExtraMotion 注入

背景：VTS 商店模型普遍不在 model3.json 的 FileReferences 里声明表情/动作，
而是散落在目录（含子目录）的 *.exp3.json / *.motion3.json 与 *.vtube.json 的
Hotkeys 里。任何渲染端直接读磁盘 model3.json 都会得到空表情列表。
"""

import glob
import json
import os

__all__ = [
    "strip_ext",
    "is_valid_motion3",
    "exp3_display_name",
    "discover_model_actions",
    "discover_models",
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


# VTube Studio 商店模型目录（用户实际模型常驻于此；桌面端 data/models 往往为空）。
# 与 pet_window.py 原本写死的 VTS_MODELS 保持一致，集中在此避免两处再次漂移。
VTS_MODELS = r"D:\Program Files\Steam\steamapps\common\VTube Studio\VTube Studio_Data\StreamingAssets\Live2DModels"


def discover_models() -> list:
    """自动发现本地 Live2D 模型（与 pet_window.find_model3 同源，供后端 / 前端共用）。

    搜索根（按优先级）：
      1) 桌面 data/models        —— 用户通过「导入模型」落盘目录；
      2) godot_renderer/models   —— VRM/Godot 渲染兜底目录；
      3) VTube Studio 商店目录   —— 用户真实模型常驻处（桌面端 data/models 常为空）。

    返回 [{"name","modelFile","path"}...]，按目录名稳定排序；未发现返回 []，
    调用方据此决定是否回退到文件选择器。

    注意：本函数仅依赖标准库，不引入 PySide/live2d，可在后端 aiohttp 进程与
    Qt 桌宠子进程中安全共用，是「自动发现模型地址」的唯一权威实现。
    """
    desktop_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    roots = [
        os.path.join(desktop_root, "data", "models"),
        os.path.join(desktop_root, "godot_renderer", "models"),
        VTS_MODELS,
    ]
    models = []
    seen = set()
    for base in roots:
        if not os.path.exists(base):
            continue
        for entry in sorted(os.listdir(base)):
            d = os.path.join(base, entry)
            if not os.path.isdir(d):
                continue
            for f in sorted(os.listdir(d)):
                if f.endswith(".model3.json") and f not in seen:
                    seen.add(f)
                    models.append({"name": entry, "modelFile": f, "path": os.path.join(d, f)})
                    break
    return models
