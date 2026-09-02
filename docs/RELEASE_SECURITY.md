# 发布安全与完整性规范（防伪造 / 防投毒 / 防银狐类攻击）

本规范定义 `naixi-desktop` 的安装包发布流程，目标是让最终用户**只可能拿到作者发布的、未被篡改的版本**。
银狐（Silver Fox）等木马的典型手法是：伪造开源项目的安装包 / 在第三方渠道投毒 / 篡改 README 里的下载链接诱导到假站点。
下面从「代码 → 仓库 → 发布 → 用户侧」四层闭环防御。

---

## 1. 威胁模型

| 攻击面 | 手法 | 本仓库的防御 |
| --- | --- | --- |
| fork 换收款码 | 复制仓库，把 `public/sponsor/*.png` 换成自己的收款码重新发包，赞助款进攻击者腰包 | 应用内 SHA-256 自检（见 §2）+ 收款人实名双核对 |
| 伪造安装包 | 重新编译注入木马，改名「奶昔」在各网盘/群发布 | 代码签名（§4）+ 仅官方渠道（§5）+ 哈希清单（§3） |
| 依赖投毒 | 在 `npm install` 时拉入恶意包 | 锁定依赖版本 + Dependabot + 发布前 `npm ci` 审计 |
| 恶意 PR | 提 PR 改收款码/构建脚本 | 分支保护 + CODEOWNERS（§6），owner 审核才合并 |
| fork 投毒含银狐下载器 | 复制仓库，在构建/资源里塞银狐 Bun 下载器重新发包 | 分支保护 + CODEOWNERS（§6）+ 依赖/构建审计（§1） |
| 本机已感染银狐 | 用户机器已被种马，桌宠运行环境被利用 | 应急哨兵检测 + 一键急救（见下条） |

**威胁边界（必须说清）**：纯软件手段无法防住「攻击者拿到你机器权限后重编译整个应用并替换哈希」——
那种情况已超出应用自证范畴，由**代码签名 + 用户只从官方 Releases 下载**兜底。本规范覆盖的是「用户从外部拿到一个安装包，如何确认它没被篡改」。

---

## 2. 应用内收款码完整性（已实现）

- 收款码以 base64 内联 + SHA-256 固化进已编译前端 bundle（`src/lib/sponsorIntegrity.ts` 的 `SPONSOR_QR`）。
- `SettingsPage` 在「赞助支持」区块挂载时，对每张码做：`atob → Uint8Array → crypto.subtle.digest('SHA-256')`，与固化哈希比对；不一致则显示红色告警「收款码完整性校验未通过，可能被篡改」。
- 同时固定显示 `SPONSOR_REAL_NAME`（收款人实名）做**图片 + 文字双核对**——这是人工最后一道防线。
- **更新收款码流程**：把真实微信/支付宝码命名为 `wechat.png` / `alipay.png` 放入 `public/sponsor/`，运行：
  ```bash
  npm run gen:sponsor-hash
  ```
  脚本保留你手填的 `SPONSOR_REAL_NAME`，只重写 `SPONSOR_QR`。随后重新打包发布。
- 占位说明：当前仓库内为占位图（logo），`SPONSOR_REAL_NAME` 为占位名，**发布前必须替换真实码与真实实名**。

---

## 3. Release 哈希清单（发布时生成）

每次 `npm run tauri build` 后，生成安装包哈希清单：

```bash
npm run gen:release-hashes
```

产物 `src-tauri/target/release/bundle/sha256sums.txt` 随安装包**一同上传 GitHub Releases**。

> `src-tauri/target/` 已被 `.gitignore` 排除，若要提交到仓库，复制到仓库根：
> `cp src-tauri/target/release/bundle/sha256sums.txt ./sha256sums.txt`

清单含**两组**哈希，一律用**纯文件名**（用户的下载目录里没有 msi/ nsis/ 子目录）：

- `[安装包]`：下载后立刻验，确认下载到的就是官方文件
- `[主程序]`：装完后验——对应应用内「设置 → 安全 → 安装包完整性 · 本程序哈希」显示的那串 SHA-256

用户把清单与安装包放在同一目录后校验：

```bash
sha256sum -c --ignore-missing sha256sums.txt
```

`--ignore-missing` 用于跳过 `[主程序]` 那一行（它不在下载目录里）。只有清单里的哈希通过，才说明安装包与作者构建的一致。

**每次发版前必须重跑** `npm run gen:release-hashes`——安装包重新构建后哈希会变，旧清单会过期失效（0.2.0 就出现过清单生成后又重新构建，导致清单与产物对不上的情况）。

---

## 4. 代码签名（防伪造安装包的最硬手段）

未签名的 exe 在 Windows 会触发 SmartScreen 拦截，且攻击者也能轻易伪造同名未签名包——**代码签名证书是区分「官方包」与「伪造包」的唯一硬凭证**。

- 申请代码签名证书（Windows Authenticode）：推荐 OV/EV 证书（DigiCert / Sectigo / 国产如沃通），EV 可消除 SmartScreen 警告。
- 在 `src-tauri/tauri.conf.json` 的 `bundle.windows` 已预留签名配置：
  ```jsonc
  "signCommand": "powershell -NoProfile -Command \"& { if ($env:NAIXI_CODESIGN_PFX -and $env:NAIXI_CODESIGN_THUMB) { & '<signtool路径>' sign /fd SHA256 /sha1 $env:NAIXI_CODESIGN_THUMB /tr http://timestamp.digicert.com /td SHA256 $env:NAIXI_CODESIGN_PFX $file } }\"",
  "digestAlgorithm": "sha256"
  ```
- 构建机设置环境变量 `NAIXI_CODESIGN_PFX`（pfx 路径）、`NAIXI_CODESIGN_THUMB`（证书指纹），无需把私钥入库。
- 未配置证书时 `signCommand` 自动跳过，本地构建不受影响。
- 时间戳服务（/tr）保证证书过期后签名仍有效。

---

## 5. 官方渠道唯一性

- README「安全与完整性」章节明确：**本项目只通过 GitHub Releases 分发**，不通过任何网盘、论坛、QQ 群、第三方站点。
- 任何非 `github.com/Hayliy/naixi-desktop/releases` 的下载链接都**不是官方**，请勿下载。
- 仓库内不出现任何外部下载站链接，杜绝「篡改 README 下载链接」诱导。

---

## 6. 仓库层锁定（防恶意 PR）

- `.github/CODEOWNERS`：赞助/构建关键文件标记为 `@Hayliy` 强制 review。
- `main` 分支保护规则（GitHub API 设定）：
  - 禁止直接 push（`allow_force_pushes: false`、`allow_deletions: false`）
  - 合并前必须 PR + 至少 1 个 review
  - `require_code_owner_reviews: true`（改赞助/构建文件必须 owner 审）
  - `enforce_admins: true`（管理员也受约束）
- 任何改动收款码 / 构建脚本的 PR，必须由仓库 owner 亲自审核才合并。

> **个人仓库现实约束**：GitHub 个人仓库不支持 `restrictions`（push 白名单，仅组织支持），且禁止作者 approve 自己的 PR。故本仓库实际采用 `enforce_admins + 禁 force-push/删分支` 的**安全配置**，不强制 required_review（否则会把自己锁死）。组织仓库应补 `require_code_owner_reviews + 至少 1 review`。

---

## 本机银狐应急防护（用户态前哨 + 一键急救）

银狐（Silver Fox / 游蛇 / Void Arachne）2026 猖獗，国家计算机病毒应急处理中心 5–6 月连发预警，且已有「伪造开源安装包 + 滥用 GitHub Release 投毒」实锤（8 月审计出 GitHub 游戏存档修改器 `Setup.exe` 含银狐 Bun 下载器；6 月该团伙注册 400+ 域名滥用 GitHub 资产投 Gh0stRAT）。除「发布侧防篡改」外，应用内置**本机应急防护**，作用户侧最后一道前哨。

- **应急哨兵扫描**（`GET /api/security_scan`）：检测本机银狐类木马的**用户态可见痕迹**——① Defender 排除项被篡改（银狐常把 C:–F: 加排除列表致盲杀软）；② 已知银狐 IOC 进程名（`designaccent.exe` / `gjdluhqzmjsagyw.exe` / `singmusice.exe` / `khdzetmjqmsagyw.exe` / `issueaccentrequest`）；③ 可疑计划任务（Silver Fox 的 `DesignAccent` / `Accent` / `zpaq` 命名）；④ 到已知银狐 C2 网段（`118.107.40.*`）的外连。返回风险等级（safe/warn/danger）+ 逐条明细。设置页「安全急救 · 银狐应急哨兵」面板展示绿/黄/红，命中危险项时给「断网→改密→安全模式查杀」应急指引 + 一键跳转火绒官网 / 国家病毒协同分析平台。
- **一键急救**（`POST /api/security_remediate`）：移除已检测到的银狐**用户态**痕迹——结束已知 IOC 进程（`taskkill`）、删除可疑计划任务（`Unregister-ScheduledTask`）、恢复被篡改的 Defender 整盘排除项（`Remove-MpPreference`）。
  **安全约束**：① 仅处理服务端 IOC 目录内的已知项，绝不通客户端的任意路径/命令（防命令注入）；② 所有动作服务端权威重算，不信任前端传参；③ 计划任务名经 `^[\w\-\. ]{1,120}$` 白名单校验后才执行。
- **安装包完整性自检**（`GET /api/self_hash`）：返回主程序 `naixi-desktop.exe` 的 SHA-256，设置页「安装包完整性 · 本程序哈希」展示（带一键复制），供用户与官方 `sha256sums.txt` 的**「主程序」段**人工比对，识别「安装目录里的程序被替换/篡改」。**注意**：随包携带清单的比对无意义（攻击者连清单一起换），故只暴露哈希让人核对。
  - 清单必须用 `npm run gen:release-hashes`（`scripts/gen-release-hashes.mjs`）生成，它同时产出**两组**哈希：`[安装包]`（下载后校验下载到的文件）与 `[主程序]`（安装后校验 naixi-desktop.exe）。只算安装包是不够的——卡片显示的是安装后主程序的哈希，与安装包哈希不是同一个文件；早期版本缺 `[主程序]` 组，导致用户拿卡片哈希去比对时永远找不到对应行。
  - 定位主程序的实现坑见 `desktop_core/api.py::_locate_main_exe`：Windows PowerShell 5.1 的 `Get-Process` 对象**没有 `ParentProcessId` 成员**（PowerShell 7 才有），旧写法恒返回空使该功能 100% 失效；现改为**纯 ctypes 遍历进程祖先链**（`NtQueryInformationProcess` + `QueryFullProcessImageNameW`）为首选，powershell CIM 与目录回溯依次降级。

**诚实边界（必须说清）**：银狐最新变种用 BYOVD 技术加载 `wnBios` 内核级 rootkit，直接读写物理内存、致盲火绒/360/Defender。这种**内核层**的东西普通**用户态程序（含奶昔桌宠）干不掉**——必须靠专业杀软 + 安全模式全盘查杀。奶昔的急救箱只处理**用户态可见痕迹**，UI 已写明不误导「能杀内核层」。本应用**绝不内置任何「反攻 C2」能力**——对 C2 发起 DoS / 未授权访问属违法行为且无效（C2 域名随时轮换）。

---

## 7. 发布检查清单（每次发版前）

- [ ] `public/sponsor/*.png` 已是真实收款码（非占位 logo）
- [ ] `src/lib/sponsorIntegrity.ts` 的 `SPONSOR_REAL_NAME` 已是真实收款实名
- [ ] 已运行 `npm run gen:sponsor-hash` 并重打包
- [ ] 已运行 `npm run gen:release-hashes`，`sha256sums.txt` 随 Releases 上传
- [ ] 构建机已配置代码签名证书环境变量
- [ ] 确认 Releases 资产只有官方安装包 + `sha256sums.txt`，无其他外部链接
- [ ] 在 GitHub 发布说明里写明「只从本 Releases 下载，并校验 sha256sums.txt」
