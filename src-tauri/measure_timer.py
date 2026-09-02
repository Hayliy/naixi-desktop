import subprocess, time, os
EXE = r"D:\naixi_desktop\src-tauri\gt_timer2.exe"
LOG = os.path.join(os.environ.get("TEMP", os.environ.get("TMP", "C:\\Temp")), "gt_count.log")
if os.path.exists(LOG): os.remove(LOG)
p = subprocess.Popen([EXE])
time.sleep(4.0)
p.terminate()
time.sleep(0.3)
try:
    with open(LOG, encoding="utf-8", errors="ignore") as f:
        lines = f.read().splitlines()
    print("TICK COUNT in 4s =", len(lines))
    print("first/last:", lines[:3], lines[-3:])
except Exception as e:
    print("read err:", e)
