#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成完整第三方许可证清单（合规用）——NOTICE 只写 4 个组件是远远不够的。

为什么需要它：安装包实际随附 100+ 个第三方依赖（python-embed 118 条 + 前端生产依赖 200+ 条），
其中存在有**分发义务**的许可证：
  · LGPL-3.0（PySide6 / Qt / shiboken6）：须随分发提供许可证文本，并说明可替换（本项目为动态链接）；
  · GPL-3.0（espeakng-loader 内嵌的 espeak-ng.dll + 语音数据）：须提供许可证文本与源码获取途径；
  · MPL-2.0（certifi / easy-live2d / tqdm）：须提供许可证文本；
  · AGPL-3.0（SearXNG，独立组件非 pip 依赖）：随安装包分发，须提供源码获取途径。
人工维护必然漏 → 从安装包**真实内容**自动生成，并优先依据包内实际随附的许可证原文判定（而非仅看元数据）。

产出：
  THIRD_PARTY_LICENSES.md   —— 人读清单（分发义务说明 + copyleft 明细 + 全量表格）
  licenses/SUMMARY.json     —— 机读清单（含每个包的判定依据 license_source）
  licenses/<生态>/<包>/…    —— 许可证原文（copyleft 与未识别项，便于审计取证）

用法：
  python scripts/gen_third_party_licenses.py
注：依赖本地已存在 python-embed 与 node_modules（都不入库），故 CI 跑不了，由发版机构建时生成，
    产物随 Release 一起分发。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COPYLEFT = re.compile(r"\b(A?GPL|LGPL|MPL|EUPL|CDDL|SSPL)\b", re.I)
LICENSE_FILE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|COPYRIGHT|COPYING\.)", re.I)

# 许可证原文里的特征句 → 许可证标识（比元数据字段可靠：很多包只带文件、不带字段）
# 带 {0} 的模板会从原文里抓版本号，避免把 LGPL-2.1 报成 LGPL-3.0 这类粗判。
TEXT_PATTERNS = [
    (r"GNU AFFERO GENERAL PUBLIC LICENSE\s*Version\s*(\d(?:\.\d)?)", "AGPL-{0}"),
    (r"GNU LESSER GENERAL PUBLIC LICENSE\s*Version\s*(\d(?:\.\d)?)", "LGPL-{0}"),
    (r"GNU GENERAL PUBLIC LICENSE\s*Version\s*(\d(?:\.\d)?)", "GPL-{0}"),
    (r"Mozilla Public License\s*Version\s*(\d(?:\.\d)?)", "MPL-{0}"),
    (r"Apache License\s*Version\s*(\d(?:\.\d)?)", "Apache-{0}"),
    (r"Permission is hereby granted, free of charge", "MIT"),
    (r"Redistribution and use in source and binary forms", "BSD"),
    (r"Python Software Foundation License", "PSF-2.0"),
]

# 元数据确实没有许可证声明的包：人工核对后登记（必须写明依据，否则下个维护者会当成自动识别结果）
OVERRIDES = {
    "espeakng-loader": {
        "license": "GPL-3.0（内嵌 espeak-ng 运行时与语音数据）",
        "homepage": "https://github.com/thewh1teagle/espeakng-loader",
        "reason": "wheel 内既无许可证文件、METADATA 也无 License 字段；但随包附带 espeak-ng.dll "
                  "与 espeak-ng-data/，二者来自 espeak-ng（GPL-3.0）",
    },
}


def md_field(text: str, field: str) -> str:
    m = re.search(rf"^{re.escape(field)}:\s*(.*)$", text, re.M)
    return m.group(1).strip() if m else ""


def detect_from_text(path: str) -> str:
    try:
        head = open(path, encoding="utf-8", errors="replace").read(8000)
    except Exception:
        return ""
    flat = re.sub(r"\s+", " ", head)
    for pat, tmpl in TEXT_PATTERNS:
        m = re.search(pat, flat, re.I)
        if not m:
            continue
        if "{0}" in tmpl:
            if m.groups():
                v = m.group(1)
                return tmpl.format(v if "." in v else v + ".0")
            return tmpl.replace("-{0}", "")   # 抓不到版本号就不写死版本
        return tmpl
    return ""


def license_family(lic: str) -> str:
    """取许可证族名（LGPL/GPL/MPL/…），用于判断「声明的许可证」与「子组件检出的许可证」是否同族。"""
    m = re.match(r"\s*([A-Za-z]+)", lic or "")
    return (m.group(1) if m else "").upper()


def detect_all_from_text(path: str) -> list[str]:
    """返回文件里检出的**全部**许可证。

    一个 LICENSE 文件常常内嵌多个第三方许可证文本（实例：Pillow 的 LICENSE 里同时有
    HPND、FTL、GPLv2、Apache-2.0、PNG 等），只报第一条会漏掉分发义务。
    """
    try:
        head = open(path, encoding="utf-8", errors="replace").read(60000)
    except Exception:
        return []
    flat = re.sub(r"\s+", " ", head)
    found: list[str] = []
    for pat, tmpl in TEXT_PATTERNS:
        for m in re.finditer(pat, flat, re.I):
            if "{0}" in tmpl:
                if m.groups():
                    v = m.group(1)
                    name = tmpl.format(v if "." in v else v + ".0")
                else:
                    name = tmpl.replace("-{0}", "")
            else:
                name = tmpl
            if name not in found:
                found.append(name)
    return found


def detect_copyleft_in_files(files: list[str]) -> list[tuple[str, list[str]]]:
    """从随附的许可证原文里找出 copyleft 命中（文件 → 检出的 copyleft 许可证列表）。

    用途：发现「包元数据声明的是宽松许可证、但随包附带了某个 copyleft 子组件」的情况
    （实例：pywin32 元数据是 PSF，却附带 adodbapi 的 LGPL-2.1 文本）。
    """
    hits: list[tuple[str, list[str]]] = []
    for f in files:
        lics = [d for d in detect_all_from_text(f) if COPYLEFT.search(d)]
        if lics:
            hits.append((f, lics))
    return hits


def license_from_metadata(text: str) -> str:
    expr = md_field(text, "License-Expression")
    if expr:
        return expr
    classes = re.findall(r"^Classifier:\s*License\s*::\s*(.+)$", text, re.M)
    if classes:
        return classes[0].split("::")[-1].strip()
    lic = md_field(text, "License")
    if lic:
        return "(见附带的许可证原文)" if (len(lic) > 60 or "\n" in lic) else lic
    return ""


def homepage_from_metadata(text: str) -> str:
    for label, url in re.findall(r"^Project-URL:\s*([^,]+),\s*(https?://\S+)$", text, re.M):
        if label.strip().lower() in ("homepage", "source", "repository", "source code"):
            return url
    v = md_field(text, "Home-page")
    return v if v.startswith("http") else ""


def collect_license_files(dist_dir: str, pkg_dir: str, metadata_text: str) -> list[str]:
    """收集该包随附的许可证原文（PEP 639 的 licenses/ 子目录、License-File 声明、包目录）。"""
    found: list[str] = []

    for rel in re.findall(r"^License-File:\s*(.+)$", metadata_text, re.M):
        for base in (pkg_dir, os.path.dirname(pkg_dir), dist_dir):
            cand = os.path.join(base, rel.strip())
            if os.path.isfile(cand):
                found.append(cand)
                break

    licdir = os.path.join(dist_dir, "licenses")
    if os.path.isdir(licdir):
        for root, _d, files in os.walk(licdir):
            found += [os.path.join(root, f) for f in files]

    for f in os.listdir(dist_dir):
        p = os.path.join(dist_dir, f)
        if os.path.isfile(p) and LICENSE_FILE.match(f):
            found.append(p)

    if os.path.isdir(pkg_dir):
        base_depth = pkg_dir.rstrip(os.sep).count(os.sep)
        for root, _d, files in os.walk(pkg_dir):
            if root.count(os.sep) - base_depth > 1:
                continue
            for f in files:
                if LICENSE_FILE.match(f):
                    found.append(os.path.join(root, f))

    out: list[str] = []
    for p in found:
        if p not in out:
            out.append(p)
    return out


def scan_python(site_packages: str, out_dir: str) -> list[dict]:
    rows: list[dict] = []
    if not os.path.isdir(site_packages):
        print(f"[warn] 找不到 python site-packages：{site_packages}")
        return rows
    for name in sorted(os.listdir(site_packages)):
        if not name.endswith(".dist-info"):
            continue
        dist_dir = os.path.join(site_packages, name)
        meta = os.path.join(dist_dir, "METADATA")
        if not os.path.isfile(meta):
            continue
        text = open(meta, encoding="utf-8", errors="replace").read()
        pkg = md_field(text, "Name") or name[:-10].split("-")[0]
        ver = md_field(text, "Version")
        pkg_dir = os.path.join(site_packages, pkg)

        lic_files = collect_license_files(dist_dir, pkg_dir, text)
        meta_lic = license_from_metadata(text)
        text_lic = ""
        for lf in lic_files:
            text_lic = detect_from_text(lf)
            if text_lic:
                break
        sub_copyleft = detect_copyleft_in_files(lic_files)
        ov = OVERRIDES.get(pkg) or OVERRIDES.get(pkg.lower())

        # 判定优先级：元数据（机器可读且精确）> 包内原文启发式 > 人工登记 > 未声明。
        # 反例教训：反过来先看原文时，Pillow 因 LICENSE 内附带提到 GPL 被误判为 GPL-3.0
        # （实际 License-Expression: MIT-CMU），所以必须元数据优先。
        if meta_lic:
            lic, source = meta_lic, "METADATA"
        elif text_lic:
            lic, source = text_lic, "包内许可证原文"
        elif ov:
            lic, source = ov["license"], "人工登记（OVERRIDES）"
        else:
            lic, source = "UNKNOWN", "未声明"

        homepage = homepage_from_metadata(text) or (ov or {}).get("homepage", "")
        bundled: list[dict] = []
        for f, lics in sub_copyleft:
            keep = [d for d in lics if license_family(d) not in (lic or "").upper()]
            if keep:
                bundled.append({
                    "file": os.path.relpath(f, site_packages).replace(os.sep, "/"),
                    "licenses": keep,
                })
        row = {
            "ecosystem": "python", "name": pkg, "version": ver, "license": lic,
            "license_source": source, "homepage": homepage,
            "copyleft": bool(COPYLEFT.search(lic)) or bool(bundled),
            "bundled_copyleft": bundled,
            "license_files": [],
        }

        # 取证：copyleft 与未识别项都留下许可证原文
        if lic_files and (row["copyleft"] or row["license"] == "UNKNOWN"):
            dst = os.path.join(out_dir, "python", f"{pkg}-{ver or 'unknown'}")
            for f in lic_files:
                rel = os.path.relpath(f, site_packages).replace(os.sep, "__")
                try:
                    os.makedirs(dst, exist_ok=True)
                    shutil.copy2(f, os.path.join(dst, rel))
                    row["license_files"].append(f"python/{pkg}-{ver or 'unknown'}/{rel}")
                except Exception:
                    pass
        rows.append(row)
    return rows


def scan_npm(lock_path: str, out_dir: str) -> list[dict]:
    rows: list[dict] = []
    if not os.path.isfile(lock_path):
        print(f"[warn] 找不到 package-lock.json：{lock_path}")
        return rows
    try:
        lock = json.load(open(lock_path, encoding="utf-8"))
    except Exception as e:
        print(f"[warn] package-lock.json 解析失败：{e}")
        return rows
    for path, info in (lock.get("packages") or {}).items():
        if not path.startswith("node_modules/") or info.get("dev"):
            continue
        pkg = path.split("node_modules/")[-1]
        ver = info.get("version", "")
        lic = info.get("license", "") or ""
        homepage = ""
        abs_dir = os.path.join(ROOT, path)
        pj = os.path.join(abs_dir, "package.json")
        if os.path.isfile(pj):
            try:
                d = json.load(open(pj, encoding="utf-8"))
                if isinstance(d.get("license"), dict):
                    lic = lic or d["license"].get("type", "")
                else:
                    lic = lic or (d.get("license") or "")
                homepage = d.get("homepage") or ""
            except Exception:
                pass
        # 元数据缺许可证时，退回读包内原文
        source = "package.json" if lic else "未声明"
        if not lic and os.path.isdir(abs_dir):
            for f in sorted(os.listdir(abs_dir)):
                if LICENSE_FILE.match(f):
                    det = detect_from_text(os.path.join(abs_dir, f))
                    if det:
                        lic, source = det, "包内许可证原文"
                        break
        row = {
            "ecosystem": "npm", "name": pkg, "version": ver,
            "license": lic or "UNKNOWN", "license_source": source,
            "homepage": homepage, "copyleft": bool(COPYLEFT.search(lic or "")),
            "license_files": [],
        }
        if row["copyleft"] and os.path.isdir(abs_dir):
            dst = os.path.join(out_dir, "npm", f"{pkg}-{ver}")
            for f in sorted(os.listdir(abs_dir)):
                if LICENSE_FILE.match(f) and os.path.isfile(os.path.join(abs_dir, f)):
                    try:
                        os.makedirs(dst, exist_ok=True)
                        shutil.copy2(os.path.join(abs_dir, f), os.path.join(dst, f))
                        row["license_files"].append(f"npm/{pkg}-{ver}/{f}")
                    except Exception:
                        pass
        rows.append(row)
    return rows


def md_table(rows: list[dict]) -> str:
    out = ["| 组件 | 版本 | 许可证 | 判定依据 | 来源 |", "|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: x["name"].lower()):
        home = r["homepage"] or ""
        link = f"[链接]({home})" if home else "-"
        flag = " **(copyleft)**" if r["copyleft"] else ""
        out.append(f"| {r['name']}{flag} | {r['version'] or '-'} | {r['license']} | {r['license_source']} | {link} |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python-root", default=os.path.join(
        ROOT, "src-tauri", "resources", "python-embed", "Lib", "site-packages"))
    ap.add_argument("--out", default=ROOT)
    args = ap.parse_args()

    out_dir = os.path.join(args.out, "licenses")
    os.makedirs(out_dir, exist_ok=True)

    print("[1/3] 扫描 python-embed 依赖…")
    py = scan_python(args.python_root, out_dir)
    print(f"      {len(py)} 个包")
    print("[2/3] 扫描前端生产依赖…")
    npm = scan_npm(os.path.join(ROOT, "package-lock.json"), out_dir)
    print(f"      {len(npm)} 个包")

    allrows = py + npm
    copyleft = [r for r in allrows if r["copyleft"]]
    unknown = [r for r in allrows if r["license"] == "UNKNOWN"]

    print("[3/3] 写清单…")
    json.dump(
        {"generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
         "python_packages": py, "npm_packages": npm, "overrides": OVERRIDES},
        open(os.path.join(out_dir, "SUMMARY.json"), "w", encoding="utf-8"),
        ensure_ascii=False, indent=2)

    md = ["# 第三方许可证清单", "",
          f"本文件由 `scripts/gen_third_party_licenses.py` 从**安装包真实内容**自动生成，"
          f"生成时间 {datetime.now().strftime('%Y-%m-%d %H:%M')}。判定优先依据包内随附的许可证原文，"
          "其次依据包元数据；两者都缺的少量组件在 `licenses/SUMMARY.json` 的 `overrides` 段登记依据。", "",
          f"- 随包第三方组件：**{len(allrows)} 个**（python-embed {len(py)} + 前端生产依赖 {len(npm)}）",
          f"- 有分发义务的 copyleft 组件：**{len(copyleft)} 个**"]
    if unknown:
        md.append(f"- 许可证未识别 {len(unknown)} 个，需人工确认："
                  + "、".join(r["name"] for r in unknown[:20]) + ("…" if len(unknown) > 20 else ""))
    md += ["", "## 分发义务说明", "",
           "- **LGPL-3.0（PySide6 / PySide6_Essentials / PySide6_Addons / shiboken6）**："
           "本项目以**动态链接**方式使用，未修改其源码；随分发提供许可证原文（见 `licenses/`），"
           "用户可自行替换为兼容版本。",
           "- **GPL-3.0（espeakng-loader 内嵌的 espeak-ng.dll 与 espeak-ng-data）**："
           "espeak-ng 本体为 GPL-3.0。本项目未修改其源码，随包以动态链接方式调用；"
           "许可证原文见 `licenses/`，源码获取：https://github.com/espeak-ng/espeak-ng 。",
           "- **MPL-2.0（certifi / easy-live2d / tqdm）**：随分发提供许可证原文（见 `licenses/`）。",
           "- **AGPL-3.0（SearXNG，独立组件、非 pip 依赖）**：本项目未修改 SearXNG 源码，"
           "随安装包分发其二进制；源码获取：https://github.com/searxng/searxng 。",
           "- 其余组件以其自身许可证发布，原文见各自官方仓库。", "",
           "## 子组件许可证提示", ""]
    bundled = [r for r in allrows if r.get("bundled_copyleft")]
    if bundled:
        md.append("以下组件自身许可证不是 copyleft，但随包附带的许可证原文含 copyleft 文件"
                  "（通常为内嵌子组件），分发时需一并遵守：")
        md.append("")
        md.append("| 组件 | 自身许可证 | 随包 copyleft 文件 | 检出 |")
        md.append("|---|---|---|---|")
        for r in bundled:
            for b in r["bundled_copyleft"]:
                md.append(f"| {r['name']} | {r['license']} | {b['file']} | {', '.join(b['licenses'])} |")
    else:
        md.append("_无_")
    md += ["", "## copyleft 组件明细", "", md_table(copyleft) if copyleft else "_无_", "",
           "## python-embed 全部组件", "", md_table(py) if py else "_无_", "",
           "## 前端生产依赖全部组件", "", md_table(npm) if npm else "_无_", "", "---", "",
           "机读版本：`licenses/SUMMARY.json`；许可证原文：`licenses/` 目录。"]

    target = os.path.join(args.out, "THIRD_PARTY_LICENSES.md")
    open(target, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print(f"完成：{target}")
    print(f"      copyleft={len(copyleft)} unknown={len(unknown)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
