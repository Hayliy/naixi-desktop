"""探针：启动 setup /S，等结束，全盘搜索今天生成的 exe 以定位真实安装路径。"""
import subprocess
import os
import time

SETUP = r"D:\naixi_desktop\src-tauri\target\release\bundle\nsis\奶昔_0.1.0_x64-setup.exe"
print("launch setup /S ...", flush=True)
t0 = time.time()
p = subprocess.Popen([SETUP, "/S"])
p.wait()
print("setup exit code =", p.returncode, "elapsed = %.1fs" % (time.time() - t0), flush=True)

roots = [
    os.path.expandvars("%LOCALAPPDATA%"),
    os.path.expandvars("%APPDATA%"),
    os.environ.get("ProgramFiles", r"C:\Program Files"),
    os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    os.path.expanduser("~"),
]
hits = []
for root in roots:
    if not os.path.exists(root):
        continue
    for dp, dn, fn in os.walk(root):
        depth = dp.count(os.sep) - root.count(os.sep)
        if depth > 5:
            dn[:] = []
            continue
        for f in fn:
            if f.lower().endswith(".exe"):
                pp = os.path.join(dp, f)
                try:
                    m = os.path.getmtime(pp)
                except Exception:
                    continue
                if time.strftime("%m-%d", time.localtime(m)) == "07-23" and time.localtime(m).tm_hour >= 13:
                    hits.append((pp, time.strftime("%H:%M", time.localtime(m)), os.path.getsize(pp)))

for h in hits[:40]:
    print(h)
print("TOTAL today exe hits:", len(hits), flush=True)
# 也直接检查默认位置
local_naixi = os.path.expandvars(r"%LOCALAPPDATA%\奶昔")
print("default LOCALAPPATA\\奶昔 exists =", os.path.exists(local_naixi), flush=True)
