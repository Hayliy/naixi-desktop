"""本地模型库：浏览 + 下载（ModelScope 魔搭源，国内直连）。

为什么走魔搭而不是 HuggingFace：
  实测 HF API 在本机**连不上**（curl 返回 000，需梯子），
  魔搭 `modelscope.cn` 直连 200。对国内用户这是唯一可用的选择。

下载为什么要自己写：
  桌面包里不预装 huggingface_hub（体积大、要依赖），而模型动辄几个 GB，
  必须支持：断点续传（Range）、进度回报、取消、可选量化版本。
  这是 llama.cpp / Ollama 的下载器在做的事，自己实现反而更可控。

下载目录固定在数据盘 `D:\\数据\\本地模型\\`：
  遵循项目约定——模型权重属于数据，不塞进软件安装目录。
"""

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger("local_model.download")

MS_BASE = "https://modelscope.cn/api/v1"

# 魔搭深翻页限制（实测）：page>=1500 直接 HTTP 500；page=999 不报错，而是返回一个
# "任意位置"的无关结果（前端会误以为是新结果）。故限制可翻范围并如实告知用户。
_MAX_SAFE_PAGE = 200

# ── 下载目录：可自定义 + 持久化 ──────────────────────────────
# 不写死：每个人机器的磁盘布局不一样，模型又动辄几个 GB。
# 持久化到 data/hub_config.json（项目内只存"配置"，不存模型本体）。
#
# ★ 默认值绝不能写死成某个人的盘符（踩过：曾硬编码 D:\数据\本地模型）。
#   装到别人机器上时那个盘符可能不存在 → 静默回退、模型存到怪地方。
#   现在从系统盘符 + 用户目录推导，任何 Windows 机器都成立，
#   且仍可被用户改（改后持久化，不再受这里影响）。
_CONFIG_FILE_NAME = "hub_config.json"


def _default_download_dir() -> str:
    """默认模型目录：用户目录下的 naixi_models（跨机器成立，不写死盘符）。

    为什么放用户目录而不是程序目录：模型动辄几个 GB，
    塞进 Program Files 既没权限也不合适（程序目录该由安装器管理）。
    放用户目录天然可写、天然跟着用户走。
    """
    try:
        home = Path.home()
        return str(home / "naixi_models")
    except Exception:
        # 连 Path.home() 都失败（极端环境）→ 才退回系统临时目录
        import tempfile
        return str(Path(tempfile.gettempdir()) / "naixi_models")


def _config_path() -> Path:
    try:
        from desktop_core import log_paths  # 与项目其它模块的路径解析保持一致
        base = Path(getattr(log_paths, "DATA_DIR", None) or
                    Path(__file__).resolve().parent.parent / "data")
    except Exception:
        base = Path(__file__).resolve().parent.parent / "data"
    return Path(base) / _CONFIG_FILE_NAME


def _load_config() -> dict:
    p = _config_path()
    try:
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("[model_hub] 读配置失败: %s", e)
    return {}


def _save_config(cfg: dict) -> bool:
    try:
        p = _config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        log.warning("[model_hub] 写配置失败: %s", e)
        return False


def get_download_dir() -> str:
    """当前下载目录（用户可改，改后持久化）。"""
    cfg = _load_config()
    d = str(cfg.get("download_dir") or "").strip()
    if d and Path(d).is_dir():
        return d
    # 配的目录不存在（换了盘/被删）→ 尝试重建；仍失败才回默认
    if d:
        try:
            Path(d).mkdir(parents=True, exist_ok=True)
            return d
        except Exception as e:
            log.warning("[model_hub] 配的目录 %s 不可用(%s)，回退默认", d, e)
    try:
        Path(_default_download_dir()).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.warning("[model_hub] 默认目录创建失败: %s", e)
    return _default_download_dir()


def set_download_dir(path: str) -> dict:
    """改下载目录。校验：可写、空间够、不是文件。"""
    p = str(path or "").strip().strip('"')
    if not p:
        return {"ok": False, "error": "目录不能为空"}
    try:
        pp = Path(p)
        pp.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"ok": False, "error": f"无法创建该目录：{str(e)[:90]}"}
    if not pp.is_dir():
        return {"ok": False, "error": "这是一个文件，不是目录"}
    # 试写一下（真能写才让用户存）
    try:
        t = pp / ".naixi_write_test"
        t.write_text("ok", encoding="utf-8")
        t.unlink()
    except Exception as e:
        return {"ok": False, "error": f"该目录不可写：{str(e)[:90]}"}
    # 剩余空间提示（不足 5GB 提醒一下，不拦）
    try:
        import shutil
        free_gb = shutil.disk_usage(str(pp)).free / (1024 ** 3)
    except Exception:
        free_gb = None
    cfg = _load_config()
    cfg["download_dir"] = str(pp)
    _save_config(cfg)
    return {"ok": True, "download_dir": str(pp), "free_gb": round(free_gb, 1) if free_gb else None,
            "warning": (f"该盘只剩 {free_gb:.1f}GB，几个 GB 的模型可能下不完"
                        if free_gb is not None and free_gb < 5 else "")}

# ── 预置模型库 ──────────────────────────────────────────────
# 精选国内用户真正常用的 GGUF，按显存需求分档（用户本机 4GB 显存，
# 超过 ~3.5B 全量放 GPU 会 OOM，所以小模型标注"4GB 可全量"）。
# owner/name 均为魔搭仓库，文件是仓库里的 GGUF。

# 下载任务（模块级，单任务串行——多任务并发会抢带宽反而更慢）
_DOWNLOAD: dict = {
    "running": False, "cancelled": False, "thread": None,
    "file": "", "dest": "", "total": 0, "done": 0,
    "speed_bps": 0, "started_at": 0, "error": "", "finished": False,
}
_LOCK = threading.Lock()


# ── 工具 ────────────────────────────────────────────────────
def ensure_dir() -> Path:
    p = Path(get_download_dir())
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ms_headers() -> dict:
    # 魔搭的 API 对 UA 有点挑，不给会 403
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) naixi-desktop/1.0",
        "Accept": "*/*",
    }


def list_repo_files(owner: str, repo: str) -> dict:
    """列魔搭仓库里的文件（只留 GGUF，别的对推理没用）。

    ★★ 必须带 `Recursive=true`，否则只能看到顶层 10 条 —— 而 GGUF 仓库的惯例是
    **按量化档位分子目录**（IQ2_XS/、Q4_K_M/…），顶层除了 README 只有目录。
    实测（ISTA-DASLab/Qwen3.8-…-GGUF）：不带 Recursive 时 Files=10、顶层 gguf 命中
    仅 1 个且恰好是 mmproj → has_gguf 误判 False，前端直接不给下载按钮
    （用户报「名字带 GGUF 却显示无 GGUF」）。带 Recursive 后 Files=29 / gguf=9，
    体积也能拿到真实值（顶层目录的 Size 恒为 0，不能拿来算大小）。
    """
    url = f"{MS_BASE}/models/{owner}/{repo}/repo/files?Revision=master&Recursive=true"
    try:
        req = urllib.request.Request(url, headers=_ms_headers())
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:100]}", "files": []}
    data = d.get("Data") or {}
    files = data.get("Files") or []
    out = []
    for f in files:
        # 用 Path（完整相对路径）而不是 Name：递归后 Name 只是叶子名，会丢掉所属目录
        name = str(f.get("Path") or f.get("Name") or "")
        if not name.lower().endswith((".gguf", ".safetensors", ".json")):
            continue
        if str(f.get("Type")) == "tree":      # 目录（不带 Recursive 时会混进来）
            continue
        low = name.lower()
        if low.endswith(".gguf"):
            kind = "mmproj" if "mmproj" in low else "model"
        elif low.endswith(".safetensors"):
            # HuggingFace 权重：奶昔内置转换层能转 GGUF，所以**必须放行**。
            # 以前只留 .gguf/.json，导致 safetensors 仓库在 UI 上只能"查看"不能下载，
            # 转换层做好了却用不上（用户报「甚至只是查看而不是下载，不然加转换做什么」）。
            kind = "weights"
        else:
            kind = "meta"
        out.append({
            "name": name,
            "size_gb": round((f.get("Size") or 0) / (1024 ** 3), 2),
            "kind": kind,
        })
    # 排序：主模型优先，其后 safetensors 权重、mmproj，最后元数据；同类按体积从大到小
    _rank = {"model": 0, "weights": 1, "mmproj": 2, "meta": 3}
    out.sort(key=lambda x: (_rank.get(x["kind"], 9), -x["size_gb"]))
    return {"ok": True, "files": out}


def has_gguf(owner: str, repo: str) -> dict:
    """查仓库里有没有**能直接喂给 llama.cpp 的文件**。

    返回三态，让 UI 能区分「有现成 GGUF」和「只有 safetensors 但我们能转」：
      · has_gguf       —— 有 .gguf 主模型（下载即可跑）
      · has_weights    —— 没有 gguf，但有 .safetensors 权重（**照样可下载**，
                         首次启动时由奶昔内置转换层自动转 GGUF）
      · count          —— gguf 文件数
    以前只有 has_gguf 一个布尔，非 GGUF 仓库一律显示"只能查看"，
    等于把刚做好的转换层废掉一半（用户报「名字带 GGUF 反而显示无 GGUF，
    甚至只是查看而不是下载，不然加转换做什么」）。
    """
    r = list_repo_files(owner, repo)
    if not r.get("ok"):
        return {"ok": False, "has_gguf": False, "has_weights": False, "error": r.get("error")}
    files = r["files"]
    ggufs = [f for f in files if f["name"].lower().endswith(".gguf")]
    # mmproj 是视觉投影文件，只有它没有主模型
    real = [f for f in ggufs if f["kind"] != "mmproj"]
    weights = [f for f in files if f["kind"] == "weights"]
    return {"ok": True,
            "has_gguf": bool(real),
            "has_weights": bool(weights) and not real,
            "weight_count": len(weights),
            "count": len(ggufs),
            "files": files}


# 体积过滤时，为凑满一页最多向后多扫几页上游（每页都要一次 HTTP）。
# 实测 ≤8GB 的命中率约 20~30%，10 条要扫 4~8 页；给 20 页余量，
# 并行发出去后单次仍只要几秒。上限同时受 _MAX_SAFE_PAGE 约束。
_MAX_FILL_PAGES = 40


def _ms_search_raw(q: str, page: int, limit: int) -> dict:
    """只做一件事：向魔搭要第 `page` 页的原始条目（不做任何过滤）。

    拆出来是因为「过滤」必须发生在**分页之外**（见 search_models 的说明），
    否则会出现「共 1984 页但每页只有 3 条」这种自相矛盾的结果。
    """
    body = {"PageSize": limit, "PageNumber": page, "Name": q, "SortBy": "Default"}
    req = urllib.request.Request(
        f"{MS_BASE}/dolphin/models", data=json.dumps(body).encode("utf-8"),
        method="PUT", headers={**_ms_headers(), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    mm = (d.get("Data") or {}).get("Model") or {}
    return {"items": mm.get("Models") or [], "total": mm.get("TotalCount") or 0}


# ── 上游匹配总量缓存（探可翻页数用）────────────────────────────────
# 为什么需要：为了知道"最多能翻到第几页"必须先知道 total，否则前端会显示
# 「共 992 页」却怎么都翻不到。但每次搜索都额外探一次是浪费 —— 同一关键词
# 的 total 短时间内不会变，短 TTL 缓存即可。
# 锁也定义在这里：_CURSOR_LOCK 被 _upstream_total（更靠前）使用，
# 定义在使用点之后属于埋雷，import 期不报错但迟早 NameError。
_TOTALS: dict = {}
_TOTAL_TTL = 300
_CURSOR_LOCK = threading.Lock()


def _upstream_total(q: str) -> int:
    with _CURSOR_LOCK:
        hit = _TOTALS.get(q)
        if hit and (time.time() - hit[1] <= _TOTAL_TTL):
            return hit[0]
    try:
        d = _ms_search_raw(q, 1, 1)
    except Exception:
        return 0
    total = int(d.get("total") or 0)
    _remember_total(q, total)
    return total


def _remember_total(q: str, total: int) -> None:
    if total:
        with _CURSOR_LOCK:
            _TOTALS[q] = (int(total), time.time())


def _norm_item(it: dict) -> dict | None:
    if not isinstance(it, dict):
        return None
    ns = (it.get("Path") or "").strip()
    nm = (it.get("Name") or "").strip()
    if not ns or not nm:
        return None
    tasks = [t["ChineseName"] for t in (it.get("Tasks") or [])
             if isinstance(t, dict) and t.get("ChineseName")]
    full = f"{ns}/{nm}"
    size_gb = round((it.get("StorageSize") or 0) / (1024 ** 3), 1)
    return {
        "id": full, "full": full, "name": nm, "namespace": ns,
        "downloads": it.get("Downloads") or 0,
        "stars": it.get("Stars") or 0,
        "desc": (it.get("Description") or "").strip()[:120],
        "tasks": tasks[:3],
        "size_gb": size_gb,
        "license": it.get("LicenseName") or "",
        "revision": it.get("Revision") or "master",
        # 只作提示：名字/命名空间里像 GGUF 的。**不代表真的有 GGUF**，
        # 真实格式要列仓库文件才知道（前端点"下载"会真的去查）。
        "maybe_gguf": "gguf" in full.lower(),
        # 明显不是 GGUF 的大权重仓库，提前告诉用户"可能要转换"
        "likely_safetensors": (not "gguf" in full.lower()) and size_gb > 0,
    }


def search_models(query: str, limit: int = 20, page: int = 1,
                  max_size_gb: float = 0, sort: str = "downloads",
                  verify_gguf: bool = True) -> dict:
    """搜魔搭上的模型（**PUT** 动词，GET 会 404 —— 踩过）。

    魔搭搜索接口实测（**参数名是 `Name`，不是 `Query`** —— 踩了大坑）：
      PUT https://modelscope.cn/api/v1/dolphin/models
      body {"PageSize":N,"PageNumber":1,"Name":"<关键词>","SortBy":"Default"}
      - Name=gemma   → TotalCount=4104，结果是 google/gemma-4-31B-it 等（正确）
      - Query=gemma  → TotalCount=264557（全站数，等于没搜）
    对比测试过 Query / Keyword / Search / Target，只有 **Name** 真正生效。

    重要事实（踩过，别再假设）：**魔搭搜索完全无视关键词格式**——
    搜 "GGUF" 也会返回 Qwen3.8-Flash-Next(335GB)、GLM-5.3(703GB) 这类
    safetensors 大模型。所以：
      · **不能靠搜索结果判断格式**，唯一可靠办法是列仓库文件看有没有 .gguf；
      · 体积上限只能由我们在**拿到结果之后**过滤（上游没有按体积搜的能力）。

    ★ 体积过滤与分页的正确关系（踩过的最反直觉的坑）★
    体积过滤只能发生在「拿到结果之后」（上游没有按体积搜的能力），而 `total`
    是**上游未过滤的全量**。于是有两个坑：
      1. 直接过滤完就返回 → total=19835 让前端算出「共 1984 页」，
         但每页实际只剩 3 条。页数和每页条数自相矛盾，翻几页后面全是空页。
      2. 过滤完不够就「往后多翻几页凑满」→ 更糟：第 2 页会把第 1 页的
         内容**再给一遍**（各页独立往后扫，扫描窗口重叠），翻页遇重复。
    正确做法是**顺序扫描 + 游标切分**：同一个「关键词 + 档位」维护一个扫描游标，
    从上游第 1 页往后依次累积**通过过滤的**条目，第 N 页 = 累积序列的
    [(N-1)*limit, N*limit) 区间。这样：
      · 每页条数真实（不够就是不够，如实说不够，不再编一个假页数）；
      · 翻页不重复、不漏（第 1 页给 5 条，第 2 页就从第 6 条接着给）；
      · 页数按**过滤后的真实累积量**算，不拿未过滤 total 撑门面。
    """
    q = (query or "").strip()
    if not q:
        # 空查询早退也要给齐分页字段（前端无脑读 returned/exhausted/total_pages）
        return {"ok": True, "results": [], "total": 0, "page": page,
                "returned": 0, "page_size": limit, "scanned_pages": 0,
                "upstream_total": 0, "filtered_total": 0,
                "has_more": False, "exhausted": True, "total_pages": 1}
    limit = max(1, min(int(limit), 60))
    page = max(1, int(page))
    max_size = float(max_size_gb or 0)

    def _fetch(p: int) -> dict:
        try:
            return _ms_search_raw(q, p, limit)
        except Exception as e:
            return {"items": [], "total": 0, "error": f"{type(e).__name__}: {str(e)[:100]}"}

    # ── 不过滤：上游一页就是最终一页，直接给（无游标，最快）──────────
    if max_size <= 0:
        # 上游深翻页会 500（实测 page>=201），所以可翻页数有两个上限：
        #   真实总页数（total/limit）与 _MAX_SAFE_PAGE。取小的，并把真实总页数
        # 一并回传 —— 否则前端会显示「共 992 页」却怎么都翻不到，像坏了。
        # 总量做短 TTL 缓存：探总量的请求内容与具体页无关，不必每次都发。
        total = _upstream_total(q)
        real_pages = max(1, (total + limit - 1) // limit) if total else 1
        usable_pages = min(real_pages, _MAX_SAFE_PAGE)
        if page > usable_pages:
            return {"ok": True, "results": [], "total": total, "page": page,
                    "returned": 0, "page_size": limit, "scanned_pages": 0,
                    "upstream_total": total, "filtered_total": total,
                    "has_more": False, "exhausted": True,
                    "total_pages": usable_pages, "real_pages": real_pages,
                    "out_of_range": True,
                    "note": (f"共 {real_pages:,} 页，上游最多支持翻到第 "
                             f"{_MAX_SAFE_PAGE} 页；想看更多请用关键词缩小范围")}
        d = _fetch(page)
        if d.get("error"):
            return {"ok": False, "error": d["error"], "results": []}
        items = d.get("items") or []
        _remember_total(q, d.get("total") or 0)
        if total and page > real_pages and not items:
            # 越界页：魔搭对超出范围的页**不报错**，而是返回一个任意位置的窗口
            # （实测 page=999 给的是完全不相干的模型，前端会误以为是新结果）。
            # 字段必须与正常分支对齐：前端要读 returned / exhausted / total_pages，
            # 缺一个就会渲染成 undefined。
            return {"ok": True, "results": [], "total": total, "page": page,
                    "returned": 0, "page_size": limit, "scanned_pages": 1,
                    "upstream_total": total, "filtered_total": total,
                    "has_more": False, "exhausted": True, "total_pages": real_pages,
                    "out_of_range": True, "note": "page out of range"}
        out = [m for m in (_norm_item(i) for i in items[:limit]) if m]
        _sort_out(out, sort)
        _verify_gguf(out, verify_gguf)
        exhausted = page >= usable_pages
        note = "已标注是否真含 GGUF（实测结果，非按名字猜）"
        if real_pages > _MAX_SAFE_PAGE:
            note += f"（共 {real_pages:,} 页，最多翻到第 {_MAX_SAFE_PAGE} 页，搜索可缩小范围）"
        return {"ok": True, "results": out, "total": total, "page": page,
                "returned": len(out), "page_size": limit,
                "scanned_pages": 1, "max_size_gb": 0, "upstream_total": total,
                "filtered_total": total,
                "has_more": not exhausted, "exhausted": exhausted,
                "total_pages": usable_pages, "real_pages": real_pages,
                "note": note}

    # ── 有体积档位：游标式顺序扫描 -------------------------------------
    cur = _cursor_get(q, max_size, sort, limit)
    want_end = page * limit
    # 本次需要再往后扫几页才可能凑满（并发拉，不串行等）
    # 保守估计：命中率最低按 8% 算（实测 ≤8GB 档大约 20~30%，但关键词变化大），
    # 需要 ceil(缺口 / (limit*0.08)) 页；宁可多扫（并发不慢），也别给用户半页。
    if not cur["done"]:
        gap = max(0, want_end - len(cur["kept"]))
        est = 0 if gap <= 0 else int(gap / max(1.0, limit * 0.08)) + 2
        need_pages = max(1, min(_MAX_FILL_PAGES, est))
    else:
        need_pages = 0
    if need_pages > 1:
        start = cur["next_page"]
        stop = min(start + need_pages - 1, _MAX_SAFE_PAGE)
        pages = list(range(start, stop + 1))
        if pages:
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=8) as ex:
                fetched = list(ex.map(_fetch, pages))
            for p, d in zip(pages, fetched):
                if d.get("error") or not d.get("items"):
                    cur["done"] = True
                    cur["error"] = d.get("error")
                    break
                if not cur["up_total"]:
                    cur["up_total"] = d.get("total") or 0
                cur["scanned"] += 1
                cur["next_page"] = p + 1
                cur["kept"].extend(
                    it for it in d["items"]
                    if ((it.get("StorageSize") or 0) / (1024 ** 3)) <= max_size)
                # 够了就停，别多扫（省时间，也省上游）
                if len(cur["kept"]) >= want_end:
                    break
        if cur["next_page"] > _MAX_SAFE_PAGE:
            cur["done"] = True

    if cur.get("error") and not cur["kept"]:
        return {"ok": False, "error": cur["error"], "results": []}

    seg = cur["kept"][(page - 1) * limit: want_end]
    out = [m for m in (_norm_item(i) for i in seg) if m]
    _sort_out(out, sort)
    _verify_gguf(out, verify_gguf)

    # 页数按**过滤后真实累积量**算：没扫完就还能往后翻，扫完了就是到底了。
    got = len(cur["kept"])
    # has_more 要看"上游还有没有没扫的原始条目"，不能只看"本页取满了没"——
    # 预算耗尽时本页可能没满，但后面还有货，下次翻页会接着扫。
    has_more_raw = (not cur["done"]) and cur["next_page"] <= _MAX_SAFE_PAGE
    exhausted = cur["done"] and not has_more_raw
    total_pages = max(1, (got + limit - 1) // limit) if exhausted else None
    note = (f"≤{max_size:g}GB 是扫到结果后过滤的，已顺序扫 {cur['scanned']} 页上游，"
            f"筛出 {got} 条")
    if exhausted and got <= (page - 1) * limit:
        note = (f"≤{max_size:g}GB 的模型全站只有 {got} 个"
                + (f"（已扫完 {cur['scanned']} 页上游）" if cur["scanned"] else "")
                + "，换个档位或关键词能翻出更多")
    elif got < want_end and has_more_raw:
        note += "，正在继续往后找"
    return {"ok": True, "results": out, "total": got, "page": page,
            "returned": len(out), "page_size": limit,
            "scanned_pages": cur["scanned"], "max_size_gb": max_size,
            "upstream_total": cur["up_total"], "filtered_total": got,
            "has_more": has_more_raw, "exhausted": exhausted,
            "total_pages": total_pages, "note": note}


def _sort_out(out: list, sort: str) -> None:
    key = (lambda m: m["size_gb"]) if sort == "size" else \
          (lambda m: -m["downloads"])
    out.sort(key=key)


def _verify_gguf(out: list, verify: bool) -> None:
    """真实验证有没有 GGUF：搜索结果里大量是 safetensors 仓库（点进去扑空）。

    验证本页全部结果（不是固定前 20 个 —— 页大小现在可到 50，
    会出现"第 21 条之后没 GGUF 标记"= 用户分不清能不能用）。
    """
    if not verify or not out:
        return
    import concurrent.futures as _cf

    def _chk(m):
        try:
            r = has_gguf(m["namespace"], m["name"])
            return (r.get("has_gguf"), (r.get("count") or 0),
                    bool(r.get("has_weights")), (r.get("weight_count") or 0))
        except Exception:
            return None, 0, False, 0

    with _cf.ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(_chk, out))
    for i, (has, cnt, has_w, wcnt) in enumerate(results):
        out[i]["has_gguf"] = has
        out[i]["gguf_count"] = cnt
        out[i]["has_weights"] = has_w
        out[i]["weight_count"] = wcnt
        # ★ 「能不能用」不等于「有没有 GGUF」：只有 safetensors 也能下
        #   （首次启动自动转 GGUF）。所以排序时两者都算可用，只是 GGUF 优先。
        out[i]["usable"] = bool(has) or bool(has_w)
    # 可用的排最前（GGUF 优先于 safetensors），但不删其余 ——
    # 删光会让"搜 gemma 只剩 2 条"看起来像坏了。
    out[:] = ([m for m in out if m.get("has_gguf")]
              + [m for m in out if m.get("has_weights")]
              + [m for m in out if not m.get("usable")])


# ── 体积档位的扫描游标（顺序扫描，保证翻页不重不漏）────────────────
# 为什么需要游标：过滤只能"扫到哪页算哪页"，若每页各自往后扫，
# 各页扫描窗口会重叠 → 翻页出现重复条目（第一版就踩了）。
# 同一「关键词+档位+排序+页大小」共享一个游标，从第 1 页顺序累积。
_CURSORS: dict = {}
# 游标里累积的原始条目上限（防止无限增长占内存；超了就重扫）
_CURSOR_MAX_ITEMS = 6000
# 游标闲置多久清掉（秒）
_CURSOR_TTL = 600


def _cursor_get(q: str, max_size: float, sort: str, limit: int) -> dict:
    key = f"{q}|{max_size:g}|{sort}|{limit}"
    now = time.time()
    with _CURSOR_LOCK:
        c = _CURSORS.get(key)
        if c and (now - c["ts"] > _CURSOR_TTL or len(c["kept"]) > _CURSOR_MAX_ITEMS):
            c = None
        if c is None:
            c = {"next_page": 1, "kept": [], "scanned": 0, "up_total": 0,
                 "done": False, "ts": now}
            _CURSORS[key] = c
        c["ts"] = now
        return c


def trending_models(limit: int = 20, page: int = 1, max_size_gb: float = 0) -> dict:
    """首页默认展示：热门模型（体积档位由前端传，**不在这里写死**）。

    为什么不做默认体积上限：不同用户机器差几个数量级（4GB 核显笔记本 ↔ 64GB 独显工作站），
    替所有人定一个上限就是替所有人做决定。档位交给用户自己选。

    两个参数都必须**原样传给 search_models**：
      · limit —— 扫描游标按 (关键词,档位,排序,页大小) 分区，这里若偷偷换成 60，
        用户选「10 条/页」时会命中另一套游标，扫重复的东西。
      · page —— 漏传就是「翻页永远停在第 1 页」，每页返回同一批（真踩过）。
    """
    r = search_models("GGUF", limit=limit, page=page, max_size_gb=max_size_gb,
                      sort="downloads", verify_gguf=True)
    if not r.get("ok"):
        return r
    out = r["results"]
    return {"ok": True, "results": out,
            "total": r.get("filtered_total", r.get("total", 0)),
            "upstream_total": r.get("upstream_total", 0),
            "filtered_total": r.get("filtered_total", 0),
            "returned": len(out), "page_size": limit,
            "scanned_pages": r.get("scanned_pages", 1),
            "has_more": r.get("has_more", True),
            "exhausted": r.get("exhausted", False),
            "total_pages": r.get("total_pages"),
            "max_size_gb": max_size_gb, "note": r.get("note")}


def get_catalog() -> dict:
    """下载目录信息（模型清单不再硬编码，一律来自魔搭搜索）。

    这里只返回"本地已下载"的清单 + 目录信息，供前端显示。
    """
    d = ensure_dir()
    out = []
    try:
        for f in sorted(d.glob("*.gguf")):
            try:
                sz = f.stat().st_size
            except Exception:
                sz = 0
            out.append({
                "name": f.name, "size_gb": round(sz / (1024 ** 3), 2),
                "downloaded": True,
            })
    except Exception as e:
        log.warning("[model_hub] 列本地模型失败: %s", e)
    free_gb = None
    try:
        import shutil
        free_gb = round(shutil.disk_usage(str(d)).free / (1024 ** 3), 1)
    except Exception:
        pass
    return {"ok": True, "downloaded": out, "download_dir": str(d),
            "free_gb": free_gb,
            "note": "模型清单来自魔搭搜索（全站 26 万+），不再内置硬编码列表"}


# ── 下载（流式 + 断点续传 + 进度 + 取消）─────────────────────
def _download_worker(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    pos = tmp.stat().st_size if tmp.is_file() else 0
    headers = dict(_ms_headers())
    if pos:
        headers["Range"] = f"bytes={pos}-"          # 断点续传
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            # 服务端支持 Range 时返回 206；否则 200（要从头写）
            if r.status == 200 and pos:
                pos = 0
                tmp.unlink(missing_ok=True)
            total = pos + int(r.headers.get("Content-Length") or 0)
            with _LOCK:
                _DOWNLOAD.update({"total": total, "done": pos, "error": ""})
            mode = "ab" if (pos and r.status == 206) else "wb"
            last_t = time.time()
            last_b = pos
            with open(tmp, mode) as f:
                while True:
                    with _LOCK:
                        if _DOWNLOAD["cancelled"]:
                            break
                    chunk = r.read(1024 * 256)      # 256KB 一块，进度更平滑
                    if not chunk:
                        break
                    f.write(chunk)
                    with _LOCK:
                        _DOWNLOAD["done"] += len(chunk)
                        now = time.time()
                        if now - last_t >= 0.5:       # 每 0.5s 算一次速度
                            _DOWNLOAD["speed_bps"] = int(
                                (_DOWNLOAD["done"] - last_b) / (now - last_t))
                            last_t, last_b = now, _DOWNLOAD["done"]
        with _LOCK:
            cancelled = _DOWNLOAD["cancelled"]
        if cancelled:
            tmp.unlink(missing_ok=True)   # 取消则删临时文件（不留垃圾）
        else:
            tmp.replace(dest)             # 完成后原子改名，避免半成品被当成完整模型
    except Exception as e:
        with _LOCK:
            _DOWNLOAD["error"] = f"{type(e).__name__}: {str(e)[:150]}"
    finally:
        with _LOCK:
            _DOWNLOAD["running"] = False
            _DOWNLOAD["finished"] = True


def start_download(owner: str, repo: str, file: str) -> dict:
    """开始下载。同一时刻只允许一个任务。

    注意 `file` 可能是 `Q4_K_M/xxx.gguf` 这种**带子目录**的相对路径
    （list_repo_files 开了 Recursive，GGUF 仓库按量化档位分目录）。
    下载 URL 用完整相对路径拼（魔搭按 FilePath 定位），
    但**落盘只取叶子名平铺到下载目录** —— 否则同仓库不同档位会散进子目录，
    而本地模型扫描是按下载目录平铺找 *.gguf 的，散落会导致「下载了却扫不到」。
    """
    with _LOCK:
        if _DOWNLOAD["running"]:
            return {"ok": False, "error": "已有下载任务在进行中"}
    ensure_dir()
    leaf = os.path.basename(file.replace("\\", "/")) or file
    dest = ensure_dir() / leaf
    if dest.is_file():
        return {"ok": True, "already": True, "path": str(dest),
                "note": "文件已存在，无需下载"}
    url = f"{MS_BASE}/models/{owner}/{repo}/repo?Revision=master&FilePath={urllib.parse.quote(file)}"
    with _LOCK:
        _DOWNLOAD.update({
            "running": True, "cancelled": False, "finished": False,
            "file": leaf, "dest": str(dest), "total": 0, "done": 0,
            "speed_bps": 0, "started_at": time.time(), "error": "",
        })
    th = threading.Thread(target=_download_worker, args=(url, dest), daemon=True)
    with _LOCK:
        _DOWNLOAD["thread"] = th
    th.start()
    return {"ok": True, "file": file, "dest": str(dest)}


# ── safetensors 整包下载 ─────────────────────────────────────
# 为什么必须"整包"：HF 权重是一个**目录**，转换层要 config.json（认架构）、
# tokenizer.json / tokenizer.model（词表）、以及**全部分片**（model-0000x-of-0000y）。
# 只下用户点的那一个分片 → 缺 config 就认不出架构、缺分片权重就不完整，
# 结果是"下载成功但转换必失败"。所以点一次要把整套都拉下来。
_BUNDLE_CONFIG_NAMES = (
    "config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json",
    "tokenizer.model", "special_tokens_map.json", "vocab.json", "merges.txt",
    "preprocessor_config.json", "processor_config.json", "chat_template.json",
)


def _bundle_worker(owner: str, repo: str, rel_dir: str, files: list, dest_dir: Path) -> None:
    """串行下载整个 safetensors 模型目录（权重分片 + 必需配置）。"""
    tmp_dir = dest_dir.with_name(dest_dir.name + ".part")
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        total_all = sum(s for _, _, s in files)
        done_all = 0
        last_t, last_b = time.time(), 0
        for rel, fname, _sz in files:
            with _LOCK:
                if _DOWNLOAD["cancelled"]:
                    break
            out = tmp_dir / fname
            if out.is_file() and out.stat().st_size > 0:
                try:
                    done_all += out.stat().st_size
                except Exception:
                    pass
                continue
            url = (f"{MS_BASE}/models/{owner}/{repo}/repo"
                   f"?Revision=master&FilePath={urllib.parse.quote(rel)}")
            tmp = out.with_suffix(out.suffix + ".part")
            pos = tmp.stat().st_size if tmp.is_file() else 0
            headers = dict(_ms_headers())
            if pos:
                headers["Range"] = f"bytes={pos}-"
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=headers), timeout=60) as r:
                if r.status == 200 and pos:
                    pos = 0
                    tmp.unlink(missing_ok=True)
                total = pos + int(r.headers.get("Content-Length") or 0)
                with _LOCK:
                    _DOWNLOAD.update({"total": total_all, "done": done_all + pos, "error": ""})
                mode = "ab" if (pos and r.status == 206) else "wb"
                with open(tmp, mode) as fh:
                    while True:
                        with _LOCK:
                            if _DOWNLOAD["cancelled"]:
                                break
                        chunk = r.read(1024 * 256)
                        if not chunk:
                            break
                        fh.write(chunk)
                        with _LOCK:
                            _DOWNLOAD["done"] += len(chunk)
                            now = time.time()
                            if now - last_t >= 0.5:
                                _DOWNLOAD["speed_bps"] = int(
                                    (_DOWNLOAD["done"] - last_b) / (now - last_t))
                                last_t, last_b = now, _DOWNLOAD["done"]
            tmp.replace(out)
            try:
                done_all += out.stat().st_size
            except Exception:
                pass
            with _LOCK:
                _DOWNLOAD["done"] = done_all
        with _LOCK:
            cancelled = _DOWNLOAD["cancelled"]
        if cancelled:
            # 取消：保留 .part 以便续传，不删已下好的分片
            log.info("[model_hub] 整包下载已取消（保留 .part 供续传）: %s", dest_dir)
        else:
            if dest_dir.exists():
                import shutil as _sh
                _sh.rmtree(dest_dir, ignore_errors=True)
            tmp_dir.replace(dest_dir)
            log.info("[model_hub] safetensors 模型就绪: %s", dest_dir)
    except Exception as e:
        with _LOCK:
            _DOWNLOAD["error"] = f"{type(e).__name__}: {str(e)[:150]}"
    finally:
        with _LOCK:
            _DOWNLOAD["running"] = False
            _DOWNLOAD["finished"] = True


def start_bundle_download(owner: str, repo: str, file: str) -> dict:
    """下载 safetensors 模型的**整套文件**到同一个目录。

    一次点击 = 权重全部分片 + config/tokenizer 等必需文件，
    保证「下载完 → 本地模型页能扫到 → 点启动能转换」这条链不断。
    """
    with _LOCK:
        if _DOWNLOAD["running"]:
            return {"ok": False, "error": "已有下载任务在进行中"}
    rel_dir = file.replace("\\", "/").rsplit("/", 1)[0] if "/" in file else ""
    files = list_repo_files(owner, repo).get("files", [])
    in_dir = [f for f in files if (f["name"].replace("\\", "/").rsplit("/", 1)[0] if "/" in f["name"] else "") == rel_dir]
    # 权重的全部兄弟分片
    shards = [f for f in in_dir if f["name"].lower().endswith(".safetensors")]
    if not shards:
        return {"ok": False, "error": "该目录下没找到 safetensors 权重文件"}
    # 同目录的配置文件（不同子目录的 json 没用 —— config.json 必须在权重旁）
    metas = [f for f in in_dir if os.path.basename(f["name"]) in _BUNDLE_CONFIG_NAMES]
    plan = [(f["name"], os.path.basename(f["name"]), int(f["size_gb"] * 1024 ** 3))
            for f in (shards + metas)]
    ensure_dir()
    # 目录名：仓库名 + （必要时）子目录前缀。
    #  · 权重在仓库根（Qwen3-0.6B/model.safetensors）→ `Qwen3-0.6B`
    #  · 权重在子目录（repo/Q4_K_M/xxx.safetensors）→ `Qwen3-0.6B-Q4_K_M`
    #   否则同一仓库多个档位会互相覆盖，且都叫 "model"（HF 权重通用名）没法区分。
    sub = rel_dir.replace("/", "-").replace("\\", "-").strip("-")
    base = os.path.basename(repo) or os.path.splitext(os.path.basename(file))[0]
    model_name = f"{base}-{sub}" if sub else base
    dest_dir = ensure_dir() / model_name
    if dest_dir.is_dir() and any(dest_dir.iterdir()):
        return {"ok": True, "already": True, "path": str(dest_dir),
                "note": "模型目录已存在，无需下载"}
    with _LOCK:
        _DOWNLOAD.update({
            "running": True, "cancelled": False, "finished": False,
            "file": model_name, "dest": str(dest_dir),
            "total": sum(p[2] for p in plan), "done": 0,
            "speed_bps": 0, "started_at": time.time(), "error": "",
        })
    th = threading.Thread(target=_bundle_worker,
                         args=(owner, repo, rel_dir, plan, dest_dir), daemon=True)
    with _LOCK:
        _DOWNLOAD["thread"] = th
    th.start()
    return {"ok": True, "file": model_name, "dest": str(dest_dir),
            "file_count": len(plan),
            "note": f"将下载 {len(shards)} 个权重分片 + {len(metas)} 个配置文件"}


def download_progress() -> dict:
    with _LOCK:
        done = _DOWNLOAD["done"]
        total = _DOWNLOAD["total"]
        return {
            "ok": True,
            "running": _DOWNLOAD["running"],
            "finished": _DOWNLOAD["finished"],
            "cancelled": _DOWNLOAD["cancelled"],
            "file": _DOWNLOAD["file"],
            "done_mb": round(done / (1024 ** 2), 1),
            "total_mb": round(total / (1024 ** 2), 1) if total else 0,
            "percent": round(done * 100 / total, 1) if total else 0,
            "speed_mbps": round(_DOWNLOAD["speed_bps"] / (1024 ** 2), 2),
            "elapsed_s": int(time.time() - _DOWNLOAD["started_at"]) if _DOWNLOAD["started_at"] else 0,
            "error": _DOWNLOAD["error"],
        }


def cancel_download() -> dict:
    with _LOCK:
        if not _DOWNLOAD["running"]:
            return {"ok": True, "note": "没有进行中的下载"}
        _DOWNLOAD["cancelled"] = True
    return {"ok": True, "note": "已请求取消"}


def delete_model(name: str) -> dict:
    """删除已下载的模型文件。"""
    ensure_dir()
    p = ensure_dir() / name
    if not p.is_file():
        return {"ok": False, "error": "文件不存在"}
    try:
        size = p.stat().st_size
        p.unlink()
        return {"ok": True, "deleted": name, "freed_gb": round(size / (1024 ** 3), 2)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:100]}
