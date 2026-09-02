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
用户下载后校验：

```bash
sha256sum -c sha256sums.txt
```

只有清单里的哈希通过，才说明安装包与作者构建的一致。

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

---

## 7. 发布检查清单（每次发版前）

- [ ] `public/sponsor/*.png` 已是真实收款码（非占位 logo）
- [ ] `src/lib/sponsorIntegrity.ts` 的 `SPONSOR_REAL_NAME` 已是真实收款实名
- [ ] 已运行 `npm run gen:sponsor-hash` 并重打包
- [ ] 已运行 `npm run gen:release-hashes`，`sha256sums.txt` 随 Releases 上传
- [ ] 构建机已配置代码签名证书环境变量
- [ ] 确认 Releases 资产只有官方安装包 + `sha256sums.txt`，无其他外部链接
- [ ] 在 GitHub 发布说明里写明「只从本 Releases 下载，并校验 sha256sums.txt」
