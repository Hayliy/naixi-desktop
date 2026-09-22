#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布卡口（release guard）——发版前必须全绿，任一不过即非零退出。

为什么需要它：0.2.10 的事故形态是「tag 指向的提交比本地构建产物早」，导致用户下到的包
和版本号承诺的内容不是一回事；0.2.5 则是有产物却从没建 tag。这些都是"靠人记"就会重犯的错，
所以做成脚本卡口，跨机器可跑。

检查项：
  1. 工作区干净（可 --allow-dirty 跳过，仅用于本地演练）
  2. HEAD 已推送到远端 main（可 --offline 跳过）
  3. 五处版本号一致（tauri.conf.json / Cargo.toml / package.json / src/lib/version.ts / desktop_core/version.json）
  4. 安装包产物存在，且产物目录内不存在 .msi（MSI 模板不解 7z 聚合卷，是装不出东西的产物）
  5. 安装包已签名（Authenticode），并记录签名主体与指纹
  6. 生成 build-manifest.json（提交 / 版本 / 依赖清单哈希 / 产物 SHA256 / 签名信息）

用法：
  python scripts/release_guard.py [--allow-dirty] [--offline] [--expect-thumbprint XX]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

try:  # 中文 Windows 控制台是 GBK，符号/中文会触发 UnicodeEncodeError（见仓库既有教训）
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OK, BAD, WARN = "[PASS]", "[FAIL]", "[WARN]"
failures: list[str] = []


def say(tag: str, msg: str) -> None:
    print(f"{tag} {msg}")


def run(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=timeout)
    except Exception as e:  # 命令不存在/超时
        return 127, str(e)
    out = (p.stdout or b"").decode("utf-8", errors="replace").strip()
    err = (p.stderr or b"").decode("utf-8", errors="replace").strip()
    return p.returncode, (out + ("\n" + err if err else "")).strip()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_version_sources() -> dict[str, str]:
    """返回 {文件: 该文件声明的版本}，任一读取失败记为 ''。"""
    vs: dict[str, str] = {}

    conf = os.path.join(ROOT, "src-tauri", "tauri.conf.json")
    try:
        vs["src-tauri/tauri.conf.json"] = json.load(open(conf, encoding="utf-8"))["version"]
    except Exception:
        vs["src-tauri/tauri.conf.json"] = ""

    cargo = os.path.join(ROOT, "src-tauri", "Cargo.toml")
    try:
        m = re.search(r'^version\s*=\s*"([^"]+)"', open(cargo, encoding="utf-8").read(), re.M)
        vs["src-tauri/Cargo.toml"] = m.group(1) if m else ""
    except Exception:
        vs["src-tauri/Cargo.toml"] = ""

    pkg = os.path.join(ROOT, "package.json")
    try:
        vs["package.json"] = json.load(open(pkg, encoding="utf-8"))["version"]
    except Exception:
        vs["package.json"] = ""

    ts = os.path.join(ROOT, "src", "lib", "version.ts")
    try:
        m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', open(ts, encoding="utf-8").read())
        vs["src/lib/version.ts"] = m.group(1) if m else ""
    except Exception:
        vs["src/lib/version.ts"] = ""

    core = os.path.join(ROOT, "desktop_core", "version.json")
    try:
        vs["desktop_core/version.json"] = json.load(open(core, encoding="utf-8"))["version"]
    except Exception:
        vs["desktop_core/version.json"] = ""

    return vs


def authenticode(path: str) -> dict:
    """通过 PowerShell 取 Authenticode 签名信息（自签名下 Status 非 Valid 属预期）。"""
    ps = (
        "$s = Get-AuthenticodeSignature -LiteralPath '%s'; "
        "$c = $s.SignerCertificate; "
        "@{ status = \"$($s.Status)\"; subject = \"$($c.Subject)\"; "
        "thumbprint = \"$($c.Thumbprint)\"; notAfter = \"$($c.NotAfter)\" } | ConvertTo-Json -Compress"
    ) % path.replace("'", "''")
    rc, out = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps])
    if rc != 0 or not out:
        return {}
    try:
        return json.loads(out.strip().splitlines()[-1])
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-dirty", action="store_true", help="允许工作区有未提交改动（本地演练用）")
    ap.add_argument("--offline", action="store_true", help="跳过远端提交比对")
    ap.add_argument("--expect-thumbprint", default="", help="期望的签名证书指纹")
    args = ap.parse_args()

    print("=" * 68)
    print("发布卡口 release_guard  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 68)

    # ── 1. 工作区干净 ──────────────────────────────────────────────
    rc, dirty = run(["git", "status", "--porcelain"])
    if rc != 0:
        say(WARN, "无法执行 git status（跳过干净性检查）")
        dirty = ""
    elif dirty:
        if args.allow_dirty:
            say(WARN, f"工作区有未提交改动（--allow-dirty 已放行）：\n{dirty}")
        else:
            failures.append("工作区不干净：发版前必须 commit（或加 --allow-dirty 仅做本地演练）")
            say(BAD, "工作区有未提交改动：\n" + dirty)
    else:
        say(OK, "工作区干净")

    rc, head = run(["git", "rev-parse", "HEAD"])
    head = head.strip() if rc == 0 else ""
    rc, branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    branch = branch.strip() if rc == 0 else ""
    if head:
        say(OK, f"HEAD = {head[:10]}（{branch}）")

    # ── 2. 远端是否已含该提交 ─────────────────────────────────────
    if args.offline:
        say(WARN, "已跳过远端提交比对（--offline）")
        remote_main = ""
    else:
        remote_main = ""
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/Hayliy/naixi-desktop/commits/main",
                headers={"User-Agent": "naixi-release-guard", "Accept": "application/vnd.github+json"},
            )
            remote_main = json.load(urllib.request.urlopen(req, timeout=45))["sha"]
        except Exception as e:
            say(WARN, f"取远端 main 失败（跳过比对）：{e}")
            remote_main = ""
        if remote_main:
            if remote_main == head:
                say(OK, f"远端 main == HEAD（{remote_main[:10]}）")
            else:
                failures.append(
                    f"远端 main({remote_main[:10]}) != HEAD({head[:10]})：tag 会落在默认分支 HEAD，"
                    "与本次构建内容不一致（这正是 0.2.10 事故成因）"
                )
                say(BAD, f"远端 main({remote_main[:10]}) != HEAD({head[:10]})")

    # ── 3. 版本号一致 ─────────────────────────────────────────────
    print()
    srcs = read_version_sources()
    uniq = sorted({v for v in srcs.values() if v})
    for f, v in srcs.items():
        say(OK if v else BAD, f"{f:<32} {v or '<未读到>'}")
    if len(uniq) != 1 or "" in srcs.values():
        failures.append(f"版本号不一致：{srcs}（应统一由 tauri.conf.json 得出，跑 npm run sync:version）")
        say(BAD, "版本号不一致，请跑 npm run sync:version")
    version = uniq[0] if len(uniq) == 1 else ""

    # ── 4. 产物断言 ───────────────────────────────────────────────
    print()
    bundle = os.path.join(ROOT, "src-tauri", "target", "release", "bundle")
    nsis_dir = os.path.join(bundle, "nsis")
    installer = ""
    if version and os.path.isdir(nsis_dir):
        cands = [
            os.path.join(nsis_dir, f)
            for f in os.listdir(nsis_dir)
            if f.endswith("x64-setup.exe") and version in f
        ]
        if cands:
            installer = max(cands, key=os.path.getmtime)
    if installer:
        size_mb = os.path.getsize(installer) / 1024 / 1024
        say(OK, f"安装包存在：{os.path.basename(installer)}（{size_mb:.1f} MB）")
    else:
        failures.append(f"未找到安装包：{nsis_dir}\\*{version}*x64-setup.exe")
        say(BAD, f"未找到安装包（{nsis_dir}）")

    msi = []
    for dirpath, _dirs, files in os.walk(bundle):
        msi += [os.path.join(dirpath, f) for f in files if f.lower().endswith(".msi")]
    if msi:
        failures.append("产物目录里存在 .msi：WiX 模板不解 7z 聚合卷，MSI 装不出 desktop_core/python-embed")
        say(BAD, "产物目录里存在 MSI（属未完成品）：\n  " + "\n  ".join(msi))
    else:
        say(OK, "产物目录无 .msi（targets 已收为 nsis）")

    # ── 5. 签名 ───────────────────────────────────────────────────
    sig: dict = {}
    if installer:
        sig = authenticode(installer)
        if not sig or not sig.get("thumbprint"):
            failures.append("安装包未签名：用户会看到「未知发布者」，且无法核验完整性")
            say(BAD, "安装包未签名")
        else:
            say(OK, f"安装包已签名：{sig.get('subject')}  thumbprint={sig.get('thumbprint')}")
            if args.expect_thumbprint:
                want = re.sub(r"\s", "", args.expect_thumbprint).upper()
                got = re.sub(r"\s", "", str(sig.get("thumbprint"))).upper()
                if want != got:
                    failures.append(f"签名指纹与期望不符：{got} != {want}")
                    say(BAD, "签名指纹与 --expect-thumbprint 不符")
                else:
                    say(OK, "签名指纹与期望一致")

    # ── 6. 构建清单 ───────────────────────────────────────────────
    print()
    manifest = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version": version,
        "commit": head,
        "branch": branch,
        "remote_main": remote_main,
        "working_tree_dirty": bool(dirty),
        "deps_python_sha256": sha256_file(os.path.join(ROOT, "scripts", "requirements-embed.txt"))
        if os.path.isfile(os.path.join(ROOT, "scripts", "requirements-embed.txt"))
        else None,
        "deps_npm_lock_sha256": sha256_file(os.path.join(ROOT, "package-lock.json"))
        if os.path.isfile(os.path.join(ROOT, "package-lock.json"))
        else None,
        "artifact": None,
        "signature": sig or None,
        "guard_result": "FAIL" if failures else "PASS",
    }
    if installer:
        manifest["artifact"] = {
            "name": os.path.basename(installer),
            "size": os.path.getsize(installer),
            "sha256": sha256_file(installer),
        }
        say(OK, f"产物 SHA256 = {manifest['artifact']['sha256']}")

    out_path = os.path.join(bundle, "build-manifest.json")
    try:
        os.makedirs(bundle, exist_ok=True)
        json.dump(manifest, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        say(OK, f"已写出构建清单：{out_path}")
    except Exception as e:
        say(WARN, f"构建清单写入失败：{e}")

    # ── 汇总 ─────────────────────────────────────────────────────
    print()
    if failures:
        print(f"卡口未通过（{len(failures)} 项）：")
        for i, f in enumerate(failures, 1):
            print(f"  {i}. {f}")
        return 1
    print("卡口全部通过：可以发布。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
