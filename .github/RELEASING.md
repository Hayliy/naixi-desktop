# 发布手册（RELEASING）——从代码到 GitHub Release 的完整流程

> 本文是 v1.1.1 发布（2026-10-09）实战沉淀的**端到端 SOP**，与
> [RELEASE_TEMPLATE.md](RELEASE_TEMPLATE.md)（正文格式）配套：本文管「怎么做、什么顺序、
> 坑在哪」，模板管「正文长什么样」。两者发布时都要对照。
> 标注 🖥 的条目是**本机 / WorkBuddy 环境特有**的坑，换机器不一定遇到，但遇到了能对号入座。

## 0. 发布前检查（决定后面所有动作）

- **上一版是否真的发过 Release**：`gh api repos/<owner>/<repo>/releases` 或看 Releases 页。
  **只有 tag ≠ 有 Release**——v1.1.0 就只有 tag，导致 v1.1.1 正文必须把 1.1.0 的功能一并写上
  （用户视角是跨版本直跳，新功能不写就隐形）。
- **版本号决策**：目标 tag 已被占用 → bump（PATCH 修复 / MINOR 功能）。只改
  `src-tauri/tauri.conf.json` 的 `version`，跑 `npm run sync:version` 同步五处 +
  README 徽章；**`Cargo.lock` 会跟着变，一并提交**。
- **文档预检**：CHANGELOG 新版本段、README 中英的下载名 / 徽章 / 规模数字是否要同步
  （规模数字用实测：`git rev-list --count HEAD`、严格按 `router.add_*` 数端点，不瞎填）。

## 1. 构建前清场

- **杀掉正在运行的应用与后端**：运行中的 `naixi_api.py` / MCP 子进程会锁住
  `resources/` 里的 python-embed，7z 打包必失败（os error 32）。PowerShell：
  `Get-CimInstance Win32_Process` 按 CommandLine 找齐杀掉，复核 9845 / 18400 / 11436 释放。
- 清构建残留：删 `.cargo-build-lock`，确认无遗留 `cargo` / `rustc` 进程。

## 2. 构建

```bash
npm run tauri build
```

- 🖥 WorkBuddy 环境：vite 清空 `dist/` 会触发 safe-delete 护栏（>50 文件拦截）。
  `dist` 是纯构建产物，针对该命令设 `CODEBUDDY_SAFE_DELETE_ENABLED=0`。
- 后台跑 + 完成后**核对产物 mtime 与字节数**（避免拿到上一次的旧包）。
- ⚠ **直接 `tauri build` 只给内部主程序签名**（beforeBundleCommand 的
  `sign-app-binary.ps1`），**NSIS 安装包本体不会签**——完整管线里的安装包签名在
  `build-release.ps1`。不走该脚本就得按第 3 节补签，否则 `release_guard.py` FAIL。

## 3. 安装包签名（跳过 build-release.ps1 时必须补）

```powershell
& "D:\Windows Kits\10\bin\<版本>\x64\signtool.exe" sign /fd SHA256 `
  /sha1 <证书指纹> /tr http://timestamp.digicert.com /td SHA256 <setup.exe>
```

- 指纹与证书见 `src-tauri/codesign/`（gen-selfsign-cert.ps1 生成，已在证书库）。
- 自签名下 `Get-AuthenticodeSignature` 返回 **UnknownError（非受信根）属预期**，
  SignerCertificate.Subject 有值 = 签名成功。
- ⚠ **签名会改变文件哈希** ⇒ 顺序必须是：签名 → `npm run gen:release-hashes` →
  再把新哈希写进发布正文。顺序反了卡口必 FAIL（哈希清单与安装包不一致）。

## 4. 发布卡口（全绿才准发）

```bash
npm run gen:release-hashes          # 生成 SHA256SUMS.txt + build-manifest.json（签名后跑）
python scripts/release_guard.py     # 工作区干净 / HEAD 已推 / 五处版本一致 / 产物存在且已签名 / 清单一致
node scripts/check-release-body.mjs <正文.md>   # 正文门禁（见第 6 节）
```

## 5. 真机验证（VM 挂盘交付法）

Hyper-V 虚拟机交付安装包，**用离线挂盘，不要用 Copy-VMFile**（集成服务通信不可靠，
实测连报「虚拟机处于其当前状态」）：

1. `Stop-VM`（优雅关机，轮询到 Off）；
2. `Mount-VHD -Path <磁盘>.avhdx`——**必须挂 avhdx 本体**（有检查点时它才是当前状态，
   写入落差分盘；写父 VHDX 会毁快照链）；
3. 找 Windows 卷（`Test-Path X:\Windows\System32`），拷安装包到来宾 Desktop；
4. **`Get-FileHash` 与源包逐字节比对**——挂载卷上新 exe 可能被 Defender 短暂锁定导致
   Copy-Item 静默失败（报错被吞），哈希不一致就重拷；
5. `Dismount-VHD` → `Start-VM` → 手动走一遍安装 + 核心功能。

## 6. 发布正文

按 [RELEASE_TEMPLATE.md](RELEASE_TEMPLATE.md) 五段写（开头引用块 / 变更内容 / 验证 / 下载 /
升级说明），跑门禁。门禁的高频违规：

- 资产名必须是 ASCII `naixi-desktop_X.Y.Z_x64-setup.exe`（上传资产也用这个名）；
- 条目优先级标签只认 `（P1 / P2 / QA）`，P0 会被判 warn；
- 下载段必须写实际资产名并提及 `SHA256SUMS.txt`；
- 禁止 H1、首行须引用块、五段齐全顺序固定。

## 7. 发布到 GitHub

- **推送顺序**：`git push origin main` → `git tag -a vX.Y.Z` → `git push origin vX.Y.Z`。
- 🖥 本机无 `gh` CLI，且 **`urllib`（Python）请求 api.github.com 会被代理改写请求体**
  （`Problems parsing JSON`，与内容无关）→ **用 Windows 自带 `curl.exe`**：
  token 来自 `git credential fill`（不要回显），创建 Release 后可再 PATCH 正文：
  `curl.exe -X POST https://api.github.com/repos/<owner>/<repo>/releases --data-binary @payload.json`
- **上传 4 个资产**（POST `uploads.github.com/.../releases/<id>/assets?name=<名>`）：
  安装包（ASCII 名）、`SHA256SUMS.txt`、`build-manifest.json`、`naixi-selfsign.cer`。
  438MB 走代理约 4 分钟，`-w "%{http_code}"` 收 201 为成功，传完按 tag 拉一遍核对 size/state。
- **临时脚本 / 负载 / 安装包副本用完即删**。

## 8. 发布后文档同步（易漏）

- CHANGELOG 新版本段（修复前 / 后 + 量化数据）；
- README **中英两份**都要：功能、截图（放 `docs/screenshots/NN-名称.png` 并在「界面一览」表格
  引用）、规模数字；对照上一版检查有没有「绝对化承诺」被新功能打破
  （例：加了对外端口后，「不对外暴露端口」必须改成带例外的说法）；
- 相关专项文档时效审查（互联 / 本地模型 → `GATEWAY_跨机互联.md`、`MCP_INTEGRATION.md`、
  `PRIVACY.md`、`TROUBLESHOOTING.md` 新增对应排查条目）；
- 新增的坑回填到本文。

## 9. 一页纸顺序

> 查上一版 Release → 定版本 + sync:version → 杀应用清场 → build → 补签安装包 →
> gen:release-hashes → release_guard 全绿 → VM 挂盘交付真机测 → 写正文过门禁 →
> push + tag → curl 创建 Release + PATCH 正文 + 传 4 资产 → CHANGELOG/README 中英 +
> 专项文档审查 → 临时文件清理 → 新坑回填本文。
