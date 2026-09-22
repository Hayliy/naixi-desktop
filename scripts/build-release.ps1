<#
  一键「带签名构建 + 卡口校验 + 生成构建清单」。

  做四件事：
    1) 确保本机有可用的代码签名证书（默认自签名，见 scripts/gen-selfsign-cert.ps1）
    2) 把证书指纹通过 --config 注入构建（不改动入库的 tauri.conf.json：指纹是本机相关的）
    3) 构建后显式给安装包补签名 + RFC3161 时间戳，并自检签名
    4) 跑 scripts/release_guard.py（版本契约 / 产物断言 / 构建清单）

  用法：
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-release.ps1
    powershell ... -File scripts/build-release.ps1 -SkipGuard      # 只构建不校验（不推荐）
    powershell ... -File scripts/build-release.ps1 -Thumbprint XX  # 用已装好的正式证书指纹
#>
param(
  [string]$Thumbprint = "",
  [string]$TimestampUrl = "http://timestamp.digicert.com",
  [switch]$SkipGuard
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Find-SignTool {
  $roots = @(
    "${env:ProgramFiles(x86)}\Windows Kits\10\bin",
    "D:\Windows Kits\10\bin",
    "$env:ProgramFiles\Windows Kits\10\bin"
  )
  foreach ($r in $roots) {
    if (-not (Test-Path $r)) { continue }
    $hit = Get-ChildItem $r -Directory -ErrorAction SilentlyContinue |
      Sort-Object Name -Descending |
      ForEach-Object { Join-Path $_.FullName "x64\signtool.exe" } |
      Where-Object { Test-Path $_ } |
      Select-Object -First 1
    if ($hit) { return $hit }
  }
  return $null
}

function Find-Python {
  foreach ($c in @("python", "py", "C:\Users\21222\.workbuddy\binaries\python\versions\3.13.12\python.exe")) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
  }
  return $null
}

# ── 1. 签名工具与证书 ─────────────────────────────────────────────
$signtool = Find-SignTool
if (-not $signtool) {
  throw "找不到 signtool.exe。请安装 Windows SDK（Windows Kits\10\bin\<ver>\x64\signtool.exe）后重试。"
}
Write-Host "[sign] signtool = $signtool"
$env:PATH = "$(Split-Path -Parent $signtool);$env:PATH"   # 让 tauri 也能找到 signtool

if (-not $Thumbprint) {
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "gen-selfsign-cert.ps1")
  $infoPath = Join-Path $root "src-tauri/codesign/selfsign.json"
  if (-not (Test-Path $infoPath)) { throw "未生成自签名证书信息：$infoPath" }
  $Thumbprint = (Get-Content $infoPath -Raw | ConvertFrom-Json).thumbprint
}
$Thumbprint = ($Thumbprint -replace '\s', '').ToUpper()
Write-Host "[sign] 使用证书指纹 $Thumbprint"
# 供 build.beforeBundleCommand 的 scripts/sign-app-binary.ps1 使用：
# 主程序必须在 bundler 打包【之前】签好，否则安装包内嵌的是未签名的 exe。
$env:NAIXI_CODESIGN_THUMB = $Thumbprint

# ── 2. 版本与覆盖配置（签名 + 发布版关 devtools；均不改动入库的 tauri.conf.json）──
$conf = Get-Content (Join-Path $root "src-tauri/tauri.conf.json") -Raw | ConvertFrom-Json
$ver = $conf.version
Write-Host "[build] 版本 $ver"

# 发布版关闭开发者工具：从入库配置读取窗口列表后逐个置 devtools=false，避免手工重写配置漂移。
# 注：入库配置里可能没有 devtools 键（Tauri 默认即开启），故用 Add-Member -Force 而非直接赋值。
$wins = @()
foreach ($w in $conf.app.windows) {
  $w | Add-Member -NotePropertyName devtools -NotePropertyValue $false -Force
  $wins += $w
}

$override = @{
  bundle = @{
    windows = @{
      certificateThumbprint = $Thumbprint
      digestAlgorithm       = "sha256"
    }
  }
  app    = @{ windows = $wins }
} | ConvertTo-Json -Depth 8
$ovPath = Join-Path $env:TEMP "naixi-sign-override.json"
Set-Content -Path $ovPath -Value $override -Encoding utf8
Write-Host "[build] 注入签名配置 + 发布版 devtools=false: $ovPath"

# ── 3. 构建（targets 已收为 nsis，故只出 NSIS 安装包）──────────────
& npm run tauri build -- --config $ovPath
if ($LASTEXITCODE -ne 0) { throw "构建失败（npm run tauri build 退出码 $LASTEXITCODE）" }

# ── 4. 定位产物 + 补签名 + 自检 ───────────────────────────────────
$nsisDir = Join-Path $root "src-tauri/target/release/bundle/nsis"
$installer = Get-ChildItem $nsisDir -Filter "*$ver*x64-setup.exe" -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $installer) { throw "未找到安装包产物（$nsisDir\*$ver*x64-setup.exe）" }
Write-Host "[build] 安装包: $($installer.FullName) ($([math]::Round($installer.Length/1MB,1)) MB)"

# Tauri 已按 certificateThumbprint 给主程序签名；这里再显式签一次安装包（带时间戳），确保覆盖
& $signtool sign /fd SHA256 /sha1 $Thumbprint /tr $TimestampUrl /td SHA256 /v $installer.FullName
if ($LASTEXITCODE -ne 0) { throw "安装包签名失败（signtool 退出码 $LASTEXITCODE）" }

$s = Get-AuthenticodeSignature $installer.FullName
if (-not $s.SignerCertificate) { throw "签名自检失败：安装包没有签名" }
if ($s.SignerCertificate.Thumbprint.ToUpper() -ne $Thumbprint) {
  throw "签名自检失败：指纹不匹配（$($s.SignerCertificate.Thumbprint) != $Thumbprint）"
}
Write-Host "[sign] 安装包签名自检通过（status=$($s.Status) 自签名下非 Valid 属预期）"
Write-Host "[sign] signer = $($s.SignerCertificate.Subject)"

$appExe = Join-Path $root "src-tauri/target/release/naixi-desktop.exe"
if (Test-Path $appExe) {
  $s2 = Get-AuthenticodeSignature $appExe
  if ($s2.SignerCertificate) {
    Write-Host "[sign] 主程序已签名 signer=$($s2.SignerCertificate.Subject)"
  } else {
    Write-Host "[sign] 警告：主程序未见签名（安装后从快捷方式启动仍会显示未知发布者）"
  }
}

# ── 4.4 生成上传用 ASCII 别名（GitHub Releases 会清洗资产名里的非 ASCII 字符）
# 说明：Release 资产名只能可靠地是 ASCII（奶昔_1.0.1_... 传到 GitHub 上会变成 _1.0.1_...）。
# 这里**每次构建都重建**别名副本，避免上一轮的旧别名留在目录里与新包哈希不一致
# （真机实测过：清单里出现同名两行不同哈希，用户 sha256sum -c 必然 FAILED）。
$aliasName = ($installer.Name -replace '奶昔', 'naixi-desktop') -replace '[^\x20-\x7E]', ''
$aliasPath = Join-Path $installer.DirectoryName $aliasName
Copy-Item $installer.FullName $aliasPath -Force
Write-Host "[assets] 上传用 ASCII 别名已重建：$aliasName"

# ── 4.5 产出发布资产（哈希清单 + 签名公钥）──────────────────────
# 缺这两样，README 教用户的「下载后校验」与「核验签名主体」就无从执行
# （v0.2.10 实测只上传了 exe，用户按文档找不到清单与公钥）。
$assetDir = Join-Path $root "src-tauri/target/release/bundle"
$hashFile = Join-Path $assetDir "SHA256SUMS.txt"
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { throw "找不到 node，无法生成哈希清单（scripts/gen-release-hashes.mjs）" }
Push-Location $root
try {
  & $node.Source (Join-Path $root "scripts/gen-release-hashes.mjs")
  if ($LASTEXITCODE -ne 0) { throw "生成哈希清单失败（退出码 $LASTEXITCODE）" }
} finally { Pop-Location }
if (-not (Test-Path $hashFile)) { throw "未生成哈希清单：$hashFile" }
Write-Host "[assets] 哈希清单: $hashFile"

$cerSrc = Join-Path $root "src-tauri/codesign/naixi-selfsign.cer"
if (Test-Path $cerSrc) {
  Copy-Item $cerSrc (Join-Path $assetDir "naixi-selfsign.cer") -Force
  Write-Host "[assets] 签名公钥已就位（用户可导入后核验签名主体）"
} else {
  Write-Host "[assets] 警告：未找到公钥 $cerSrc —— 用户将无法导入证书核验签名主体"
}

# ── 5. 卡口校验 ───────────────────────────────────────────────────
if (-not $SkipGuard) {
  $py = Find-Python
  if (-not $py) { throw "找不到 python，无法运行 release_guard.py" }
  & $py (Join-Path $PSScriptRoot "release_guard.py")
  if ($LASTEXITCODE -ne 0) { throw "发布卡口未通过（release_guard.py 退出码 $LASTEXITCODE）" }
}

Write-Host ""
Write-Host "构建 + 签名 + 卡口 全部完成：$($installer.Name)"
Write-Host "上传到 GitHub Release 的资产（name 为上传后 GitHub 上的实际 ASCII 文件名）："
# ★ 注意：安装包在 bundle\nsis\ 下，而清单与公钥在 bundle\ 根 —— 早先这里统一按 bundle\ 根
#   做 Test-Path，导致安装包永远显示 [缺失]（真机实测），汇总信息失去作用。
$assetList = @(
  @{ Name = $aliasName; Path = $aliasPath },
  @{ Name = "SHA256SUMS.txt"; Path = (Join-Path $assetDir "SHA256SUMS.txt") },
  @{ Name = "naixi-selfsign.cer"; Path = (Join-Path $assetDir "naixi-selfsign.cer") }
)
foreach ($a in $assetList) {
  if (Test-Path $a.Path) {
    Write-Host ("  - {0}  ({1} bytes)" -f $a.Name, (Get-Item $a.Path).Length)
  } else {
    Write-Host ("  - {0}  [缺失]  <- {1}" -f $a.Name, $a.Path)
  }
}
