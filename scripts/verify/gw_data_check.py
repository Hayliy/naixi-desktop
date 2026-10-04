"""
Gateway 前端页面数据层真机验证（2026-10-04）

按 src/components/GatewayPanel.tsx 的真实逻辑打真后端，校验：
  · 组件读的每个字段都存在且类型正确
  · 「测试」按钮对每条 read 能力都能调通（复刻 methodOf 规则）
  · write 能力都带 requires_confirm（组件据此禁用直接测试）
"""
import json
import sys
import urllib.error
import urllib.request
from urllib.parse import urlencode

BASE = "http://127.0.0.1:9845"
fails = []


def need(cond, msg):
    print(("  OK   " if cond else "  MISS ") + msg)
    if not cond:
        fails.append(msg)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=6) as r:
        return json.loads(r.read().decode("utf-8"))


print("=== 组件依赖 /api/gateway/status ===")
st = get("/api/gateway/status")
print("  实际返回:", json.dumps(st, ensure_ascii=False))
need(st.get("ok") is True, "ok 为 True（loading 退出条件）")
need(isinstance(st.get("ws_started"), bool), "ws_started 是布尔（算 运行中/未启动）")
need(isinstance(st.get("ws_port"), int), "ws_port 是整数（显示 WS 端口）")
need(isinstance(st.get("peers"), list), "peers 是数组（map 渲染对端列表）")
need(isinstance(st.get("peer_count"), int), "peer_count 是整数（算已连接对端数）")
if not st.get("peers"):
    print("  -> 当前无对端，组件走空态分支（已处理：不 map、不崩）")

print()
print("=== 组件依赖 /api/gateway/capabilities ===")
cp = get("/api/gateway/capabilities")
caps = cp.get("capabilities") or []
print(f"  count={cp.get('count')}  列表长度={len(caps)}")
need(cp.get("ok") is True, "ok 为 True")
need(cp.get("provider") == "desktop-9845", f"provider=desktop-9845（实际 {cp.get('provider')}）")
need(cp.get("count") == len(caps), "count 与列表长度一致")

FIELDS = ["id", "provider", "kind", "title", "description", "endpoint",
          "trust", "requires_confirm", "enabled", "updated_at", "schema", "meta"]
bad = [f"{c.get('id')} 缺 {f}" for c in caps for f in FIELDS if f not in c]
need(not bad, f"{len(caps)} 条能力字段齐全（共查 {len(caps)}x{len(FIELDS)} 项）")
for b in bad[:6]:
    print("    -", b)

trusts = {c.get("trust") for c in caps}
need(trusts <= {"read", "write", "dangerous"}, f"trust 取值在组件映射表内（实际 {trusts}）")
need(all(isinstance(c.get("requires_confirm"), bool) for c in caps),
     "requires_confirm 全是布尔")
need(all(isinstance(c.get("enabled"), bool) for c in caps), "enabled 全是布尔")
need(all(isinstance(c.get("schema"), dict) for c in caps), "schema 全是对象")
need(all(isinstance(c.get("meta"), dict) for c in caps), "meta 全是对象")


def method_of(c):
    """复刻组件 methodOf()"""
    declared = ((c.get("meta") or {}).get("http_method") or "").upper()
    if declared in ("GET", "POST"):
        return declared, "meta声明"
    props = (c.get("schema") or {}).get("properties") or {}
    return ("POST" if props else "GET"), "按schema推断"


read_caps = [c for c in caps if c.get("trust") == "read"]
print()
print(f"=== 组件「测试」按钮真实调用（复刻 methodOf），共 {len(read_caps)} 条 read ===")
ok_cnt = 0
for c in read_caps:
    props = (c.get("schema") or {}).get("properties") or {}
    method, why = method_of(c)
    ep = c["endpoint"]
    try:
        if method == "GET":
            url = ep + "?" + urlencode({k: "" for k in props}) if props else ep
            req = urllib.request.Request(BASE + url)
        else:
            req = urllib.request.Request(
                BASE + ep, data=json.dumps({k: "" for k in props}).encode(),
                headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            r.read(200)
        extra = (" 入参 " + ",".join(props)) if props and method == "POST" else ""
        print(f"  OK   {method:4s} {ep} -> {r.status}  [{why}{extra}]")
        ok_cnt += 1
    except urllib.error.HTTPError as e:
        print(f"  FAIL {method:4s} {ep} -> HTTP {e.code} {e.reason}  [{why}]")
    except Exception as e:
        print(f"  FAIL {method:4s} {ep} -> {type(e).__name__}  [{why}]")
need(ok_cnt == len(read_caps), f"全部 {len(read_caps)} 条 read 能力按组件逻辑可达")

print()
print("=== write 能力（组件必须禁用直接测试）===")
write_caps = [c for c in caps if c.get("trust") == "write"]
for c in write_caps:
    print(f"  {c['id']}: trust=write requires_confirm={c.get('requires_confirm')}")
need(all(c.get("requires_confirm") for c in write_caps),
     "write 能力都标了 requires_confirm")

print()
print(f"总计失败 {len(fails)} 项")
for f in fails:
    print("  FAIL:", f)
sys.exit(1 if fails else 0)