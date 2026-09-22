# 代码签名说明（当前：自签名）

本文说明奶昔桌面端的签名现状、怎么构建带签名的包、用户怎么核验，以及将来换成受信任
CA 证书时需要改什么。

## 1. 现状与边界（如实说明）

当前使用**自签名证书**（Authenticode，Code Signing EKU + SHA-256），由
`scripts/gen-selfsign-cert.ps1` 生成本机证书并导出公钥 `src-tauri/codesign/naixi-selfsign.cer`。

**自签名能做到的：**

- 安装包与主程序带可核验的数字签名，签名主体与指纹固定、可公开比对；
- 包体被任何改动后签名立即失效 —— 完整性可被系统与用户直接验证（比只比 Hash 更直观）；
- 与将来换成受信任证书时**流程完全一致**：只换证书指纹，不改流水线。

**自签名做不到的（不要误解）：**

- **不会消除 SmartScreen 的「未知发布者」提示** —— 自签名的根不在 Windows 受信任根库里，
  系统把它与攻击者自签名视为同一类（都不受信任）。要消除提示只有两条路：受信任 CA 签发的
  OV/EV 证书，或上架 Microsoft Store（Store 会替你重签）。
- 不产生 SmartScreen 信誉积累（信誉跟"受信任的签名主体 + 下载量"走）。

因此：**签名与哈希校验不是二选一，而是互补** —— 发布页仍必须提供 `SHA256SUMS.txt`。

## 2. 构建带签名的安装包

```powershell
# 一键：确保证书 -> 注入指纹构建 -> 给安装包补签名+时间戳 -> 跑发布卡口 -> 生成构建清单
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-release.ps1
```

脚本做的事：

1. 复用本机已有自签名证书（没有则新建，3 年有效期，RSA-3072 + SHA-256）；
2. 把证书指纹通过 `--config` **注入**构建 —— 入库的 `tauri.conf.json` 里不写指纹（指纹是本机相关的，
   写进仓库会导致别人构建失败或签错证书）；
3. 构建后显式给安装包打一次签名并加 RFC 3161 时间戳（`/tr` + `/td SHA256`）；
   时间戳的意义：证书过期后签名依然可验证；
4. 自检签名（主体 + 指纹），然后跑 `scripts/release_guard.py`。

依赖：`signtool.exe`（Windows SDK，脚本会自动在 `Windows Kits\10\bin\<ver>\x64\` 下查找）。

### 只构建签名、不做校验

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-release.ps1 -SkipGuard
```

## 3. 用户侧怎么核验签名

1. 从 Release 下载 `naixi-selfsign.cer`；
2. 双击导入「当前用户 → 受信任的根证书颁发机构」（**可选**：导入后签名会显示为有效；
   不导入也能在"数字签名"标签里看到签名主体与指纹，只是状态显示为不受信任）；
3. 右键安装包 → 属性 → **数字签名** 标签 → 查看签名主体与指纹，与 Release 页公布的指纹比对；
4. 命令行核验：

```powershell
Get-AuthenticodeSignature .\naixi-desktop_<版本>_x64-setup.exe | Format-List Status,SignerCertificate
```

## 4. 换成受信任证书时要改什么

只有一步：把证书装进本机证书库（或云端签名客户端），然后把指纹传给构建脚本。

```powershell
powershell ... -File scripts/build-release.ps1 -Thumbprint <新证书指纹>
```

代码、卡口、清单格式都不用动。

可选路线（2026-09 现状，详见记忆与审计报告）：

| 路线 | 成本 | 能否用 | 说明 |
|---|---|---|---|
| Certum 个人版 OV | 约 800 元/年（3 年 1500） | 可以 | 材料只要身份证 + 一张缴费发票；云端 HSM，证书写本人姓名 |
| SignPath Foundation | 免费 | 有条件 | 开源项目免费，但证书签发给 SignPath Foundation（发布者名显示为它），且需满足许可/流程合规条件 |
| Azure Artifact Signing | $9.99/月 | **不可以** | 地区限制：个人仅美/加，组织仅美加欧英 |

### 为什么不能用 `.pfx` 文件签名

CA/Browser Forum 自 2023-06-01 起要求代码签名私钥必须存放在 FIPS 140-2 Level 2 以上的
HSM 或硬件令牌中，CA 不再签发可自由拷贝的 `.pfx`。因此正式证书一律走"证书库 / 云端签名客户端
按指纹取用"的方式 —— 这也是上面用指纹而不是用 pfx 路径的原因。

### 证书有效期新规

CA/B 新规：自 2026-02-27 起单张代码签名证书最长有效期 **459 天**。多年期产品会包含免费重签发，
属正常流程。

## 5. 与自动更新的关系（未完成项）

Tauri updater 尚未接入（`plugins` 里目前只有 `shell`）。接入时需要额外一套**更新签名密钥**
（minisign 密钥对，与 Authenticode 证书是两回事），用于校验下载到的更新包没被替换。
在接入之前，应用的更新检查只做"比对版本号 + 跳转 Release 页"，不做静默更新。
