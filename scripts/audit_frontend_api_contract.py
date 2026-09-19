"""前端字段访问 vs 后端响应键 的契约审计（文件级并集策略）。

背景：后端某个字段"从不返回"时，前端 `xxx?.field ?? 0` 会静默显示 0 / N/A / 空，
页面不报错、控制台也干净 —— 常规功能测试抓不到（仪表盘的 gpu_* 曾长期如此）。

做法（为避免复杂的变量→端点映射，采用文件级并集）：
  1. 采集运行时 schema（每个端点的响应键路径）→ 取顶层键并集；
  2. 逐组件文件解析：该文件访问了哪些端点（apiGet 字面量）+ 访问了哪些 `变量.字段`；
  3. 若某字段不在"该文件所访问端点的键并集"里，则报为可疑。

可疑 ≠ 一定有问题（字段可能来自本地 state 或常量），但**必须逐条确认**，
这正是"读了但后端不返回"的唯一信号来源。

用法：
    python scripts/audit_frontend_api_contract.py <api_schema.json> [--src src]
"""
from __future__ import annotations

import io
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 这些变量名显然来自本地状态/常量，不算 API 数据
NOT_API_VARS = {
    "e", "err", "error", "err_", "ev", "evt", "event", "window", "document", "navigator",
    "console", "json", "math", "promise", "array", "object", "localstorage", "res", "response",
    "prev", "next", "item", "idx", "index", "key", "keys", "props", "state", "self", "this",
}


def load_schema(path: str) -> dict[str, set[str] | None]:
    d = json.load(io.open(path, encoding="utf-8"))
    out: dict[str, set[str] | None] = {}
    for ep, keys in d.items():
        if not isinstance(keys, list):
            continue
        if keys and str(keys[0]).startswith("__ERROR__"):
            out[ep] = None
        else:
            out[ep] = {k.split(".")[0].split("[]")[0] for k in keys}
    return out


def endpoints_in(text: str) -> set[str]:
    eps = set()
    for m in re.finditer(r'api(?:Get|Post)<[^>]*>\(\s*[`"\']([^`"\'$]*)[`"\']', text):
        ep = m.group(1)
        if ep.startswith("/api/"):
            eps.add(ep)
    return eps


def var_field_accesses(text: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for m in re.finditer(r'\b([a-zA-Z_]\w*)\?\.([a-zA-Z_]\w*)\b', text):
        var, field = m.group(1), m.group(2)
        if var.lower() in NOT_API_VARS:
            continue
        out.setdefault(var, set()).add(field)
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    schema = load_schema(sys.argv[1])
    src = ROOT / "src"
    if "--src" in sys.argv:
        src = pathlib.Path(sys.argv[sys.argv.index("--src") + 1])

    all_keys: set[str] = set()
    for v in schema.values():
        all_keys |= (v or set())
    print(f"schema: {len(schema)} 个端点，顶层键并集 {len(all_keys)} 个")

    findings = []
    checked = 0
    for p in sorted(src.rglob("*.ts*")):
        text = io.open(p, encoding="utf-8", errors="replace").read()
        eps = endpoints_in(text)
        if not eps:
            continue
        keys: set[str] = set()
        for ep in eps:
            keys |= (schema.get(ep) or set())
        accesses = var_field_accesses(text)
        rel = str(p.relative_to(ROOT))
        for var, fields in accesses.items():
            for f in sorted(fields):
                checked += 1
                if f not in keys and f not in all_keys:
                    findings.append((rel, var, f, sorted(eps)[:3]))

    print(f"核对字段访问 {checked} 处\n" + "=" * 78)
    if not findings:
        print("✓ 未发现「前端在读但后端不返回」的字段")
    else:
        # 按文件聚合
        byfile: dict[str, list[tuple[str, str, list[str]]]] = {}
        for rel, var, f, eps in findings:
            byfile.setdefault(rel, []).append((var, f, eps))
        print(f"发现 {len(findings)} 处可疑字段访问（按其所在文件访问的端点键并集判定）：\n")
        for rel, items in sorted(byfile.items()):
            print(f"  {rel}")
            merged: dict[str, list[str]] = {}
            for var, f, eps in items:
                merged.setdefault(var, []).append(f)
            for var, fs in sorted(merged.items()):
                print(f"      {var}.{{{', '.join(sorted(set(fs)))}}}")
            print()
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
