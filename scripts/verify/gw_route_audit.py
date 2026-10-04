"""
Gateway 对等互联 —— 端点路由一致性审计（2026-10-04）

抓的是「能力登记的入参 / 方法 与 后端端点实际注册方法不匹配」这类错配。
错配的后果：QQ 侧 gateway_bridge 按「schema 非空→POST」判定，
打到只收 GET 的端点 → 405；或打到 GET/POST 语义不同的通配端点 → 触发错误分支
（如 /api/gateway/capabilities 的 POST 分支是「注册一条能力」，有副作用）。

规则（2026-10-04 起，bridge._do_http 的实际行为）：
  1. meta.http_method 有声明 → 一律按它走
  2. 没声明 → 有参 POST / 无参 GET
端点实际方法：从 desktop_core/api.py 的 router 注册语句里读（不猜）。
"""
import json
import re
import sys
import urllib.request

BASE = "http://127.0.0.1:9845"
SRC = r"D:\naixi_desktop\desktop_core\api.py"

fails = []


def need(cond, msg):
    print(("  OK   " if cond else "  MISS ") + msg)
    if not cond:
        fails.append(msg)


with urllib.request.urlopen(BASE + "/api/gateway/capabilities", timeout=6) as r:
    caps = json.loads(r.read().decode("utf-8"))["capabilities"]

src = open(SRC, encoding="utf-8").read()


def route_method(path: str) -> str:
    """从 api.py 源码里查该 path 注册成什么方法"""
    p = re.escape(path)
    if re.search(rf'add_get\(\s*"{p}"', src):
        return "GET"
    if re.search(rf'add_post\(\s*"{p}"', src):
        return "POST"
    if re.search(rf'add_route\(\s*"\*"\s*,\s*"{p}"', src):
        return "*"
    return "?"


def method_of(c):
    """复刻 bridge._do_http / 前端 methodOf 的判定"""
    declared = ((c.get("meta") or {}).get("http_method") or "").upper()
    if declared in ("GET", "POST"):
        return declared, "meta声明"
    props = (c.get("schema") or {}).get("properties") or {}
    return ("POST" if props else "GET"), "按schema推断"


print("能力登记 vs 端点实际方法：")
print(f"{'能力':34s} {'桥接会走':9s} {'端点实际':9s} 入参  判定")
for c in caps:
    ep = c["endpoint"]
    props = (c.get("schema") or {}).get("properties") or {}
    actual = route_method(ep)
    expect, why = method_of(c)
    if actual == "?":
        ok, note = False, "端点未在 api.py 的 router 注册语句里找到"
    elif actual == "*":
        ok, note = True, f"通配路由，桥接按{why}走 {expect}"
    else:
        ok = (expect == actual)
        note = "一致" if ok else f"错配：应走 {expect}，端点只收 {actual}"
    print(f"{c['id']:34s} {expect:9s} {actual:9s} {len(props):4d}  "
          f"{'OK  ' if ok else 'FAIL'} {note}")
    if not ok:
        fails.append(f"{c['id']}: {note}")

print()
print("=== 显式声明 http_method 的能力（GET类端点必须支持 GET）===")
declared_caps = [c for c in caps
                 if isinstance(c.get("meta"), dict) and c["meta"].get("http_method")]
need(len(declared_caps) > 0, "至少有 1 条能力显式声明 http_method（新机制生效）")
for c in declared_caps:
    m = c["meta"]["http_method"].upper()
    a = route_method(c["endpoint"])
    print(f"  {c['id']:34s} 声明={m} 端点实际={a}")
    need(a in (m, "*"), f"{c['id']} 端点支持声明的 {m}")

print()
print("=== GET 端点的能力不得声明带筛选入参（否则会误导bridge 走 POST）===")
for c in caps:
    a = route_method(c["endpoint"])
    props = (c.get("schema") or {}).get("properties") or {}
    if a == "GET" and props:
        need(False, f"{c['id']} 是纯 GET 端点却登记了 {len(props)} 个入参")
        print(f"    实际入参: {list(props)}")

print()
print(f"总计失败 {len(fails)} 项")
for f in fails:
    print("  FAIL:", f)
sys.exit(1 if fails else 0)