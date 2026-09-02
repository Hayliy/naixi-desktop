#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VRM 桌宠安全启动护栏（单实例 + 资源护栏 + 强制清理）。

防止多实例叠加跑 SwiftShader 渲染把 CPU/内存挤爆卡崩主机。
用法：
  python vrm_run_guard.py [--max-seconds N] [--max-rss-mb N] [--max-cpu-pct N] -- <vrm_pet.py 参数...>
例如：
  python vrm_run_guard.py --max-seconds 40 --max-rss-mb 2500 -- vrm_pet.py --no-ws --diag 24 --noskirt --loop Squat
"""
from __future__ import annotations
import sys, os, time, json, signal
import subprocess
import argparse
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG_DIR = os.path.join(ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOCK = os.path.join(LOG_DIR, "vrm_guard.lock")
EMBEDDED = os.path.join(ROOT, "src-tauri", "resources", "python-embed", "python.exe")
VRM_PET = os.path.join(HERE, "vrm_pet.py")

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = "[guard %s] %s" % (ts, msg)
    print(line, flush=True)

def kill_tree(pid):
    try:
        import psutil
        p = psutil.Process(pid)
        for c in p.children(recursive=True):
            try: c.kill()
            except Exception: pass
        try: p.kill()
        except Exception: pass
    except Exception:
        try: os.kill(pid, signal.SIGTERM)
        except Exception: pass

def read_lock():
    if not os.path.exists(LOCK): return None
    try:
        with open(LOCK) as f:
            d = json.load(f)
        return d.get("pid")
    except Exception:
        return None

def write_lock(pid):
    with open(LOCK, "w") as f:
        json.dump({"pid": pid, "ts": time.time()}, f)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-seconds", type=int, default=60)
    ap.add_argument("--max-rss-mb", type=int, default=2800)
    ap.add_argument("--max-cpu-pct", type=int, default=85)
    ap.add_argument("rest", nargs=argparse.REMAINDER)  # 透传给 vrm_pet.py
    args = ap.parse_args()
    child_args = args.rest
    if child_args and child_args[0] == "--":
        child_args = child_args[1:]
    # 兼容 `guard -- vrm_pet.py ...` 写法：去掉多余的 vrm_pet.py 标记后再拼绝对路径
    if child_args and os.path.basename(child_args[0]) == "vrm_pet.py":
        child_args = child_args[1:]
    if not child_args:
        child_args = ["--no-ws"]

    exe = EMBEDDED if os.path.exists(EMBEDDED) else sys.executable
    cmd = [exe, VRM_PET] + child_args
    log("target cmd: %s" % " ".join(cmd))

    # 单实例：先清掉已有实例（避免堆叠）
    old = read_lock()
    if old:
        log("发现旧护栏/实例 pid=%s，先清理..." % old)
        kill_tree(old)
        try: os.remove(LOCK)
        except Exception: pass
        time.sleep(1)

    log("启动子进程 ...")
    proc = subprocess.Popen(cmd, cwd=ROOT)
    write_lock(proc.pid)
    log("子进程 pid=%s，开始监控（上限 %ds / %dMB / %d%%CPU）" % (proc.pid, args.max_seconds, args.max_rss_mb, args.max_cpu_pct))

    deadline = time.time() + args.max_seconds
    stop = False
    peak_rss = 0
    peak_cpu = 0
    warmup = 6.0  # 启动宽限：WebGL/SwiftShader 初始化会瞬间拉满，不计入上限
    OVER_N = 4    # 连续多次超阈值才判定为失控，避免误杀
    try:
        import psutil
        ps = psutil.Process(proc.pid)
        def tree_stats():
            rss = 0
            cpu = 0.0
            try:
                rss += ps.memory_info().rss
                cpu += ps.cpu_percent(interval=0)
            except Exception:
                pass
            for c in ps.children(recursive=True):
                try:
                    rss += c.memory_info().rss
                    cpu += c.cpu_percent(interval=0)
                except Exception:
                    pass
            return rss // (1024 * 1024), int(cpu)
        def monitor():
            nonlocal peak_rss, peak_cpu, stop
            over_count = 0
            while not stop:
                try:
                    rss, cpu = tree_stats()
                    peak_rss = max(peak_rss, rss)
                    peak_cpu = max(peak_cpu, cpu)
                    elapsed = time.time() - start_ts
                    flag = ""
                    if elapsed > warmup and (rss > args.max_rss_mb or cpu > args.max_cpu_pct):
                        over_count += 1
                        flag = " (OVER %d/%d)" % (over_count, OVER_N)
                    else:
                        over_count = 0
                    log("monitor rss=%dMB cpu=%d%%%s" % (rss, cpu, flag))
                    if over_count >= OVER_N:
                        log("!! 连续超出资源上限，强制终止子进程树")
                        stop = True
                        kill_tree(proc.pid)
                        return
                except Exception:
                    break
                if time.time() > deadline:
                    break
                time.sleep(2)
        start_ts = time.time()
        t = threading.Thread(target=monitor, daemon=True)
        t.start()
        try:
            proc.wait(timeout=args.max_seconds + 5)
        except subprocess.TimeoutExpired:
            log("!! 超过墙钟上限，强制终止")
            kill_tree(proc.pid)
        t.join(timeout=3)
    except ImportError:
        log("psutil 不可用，仅按墙钟限制运行")
        try:
            proc.wait(timeout=args.max_seconds)
        except subprocess.TimeoutExpired:
            kill_tree(proc.pid)
    finally:
        try: proc.wait(timeout=5)
        except Exception: kill_tree(proc.pid)
        try: os.remove(LOCK)
        except Exception: pass
        log("结束。峰值 rss=%dMB 峰值 cpu=%d%%" % (peak_rss, int(peak_cpu)))

if __name__ == "__main__":
    main()
