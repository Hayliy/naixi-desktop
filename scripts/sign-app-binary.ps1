<#
  在 bundler 打包【之前】给主程序 exe 打 Authenticode 签名。

  为什么要这一步：实测 Tauri 的 bundle.windows.certificateThumbprint 并未把签名落到主程序上
  （安装后 exe 仍是 NotSigned），而安装包内嵌的正是这个 exe —— 只签安装包不够。
  build.beforeBundleCommand 恰好位于「Rust 产物已生成、bundler 尚未打包」之间，是官方支持的接口。

  行为约定（不阻断普通构建）：
    · 未配置证书（没跑过 gen-selfsign-cert.ps1 且无 NAIXI_CODESIGN_THUMB）→ 提示并退出 0
    · 找不到 signtool → 提示并退出 0
    · 找到则签名 + RFC3161 时间戳 + 自检；**自检不通过则退出 1**（签了却没签上必须让构建暴露）

  本文件含中文注释，必须是 UTF-8 BOM。
#>
param(
  [string]$Exe = "",
  [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
if (-not $Exe) { $Exe = Join-Path $root "src-tauri/target/release/naixi-desktop.exe" }

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

# 证书指纹：优先环境变量（由 build-release.ps1 注入），否则读本机登记的自签名证书信息
$thumb = $env:NAIXI_CODESIGN_THUMB
if (-not $thumb) {
  $info = Join-Path $root "src-tauri/codesign/selfsign.json"
  if (Test-Path $info) { $thumb = (Get-Content $info -Raw | ConvertFrom-Json).thumbprint }
}
if (-not $thumb) {
  Write-Host "[sign-app] 未配置代码签名证书，跳过（本次产物不带签名）"
  exit 0
}
$thumb = ($thumb -replace '\s', '').ToUpper()

if (-not (Test-Path $Exe)) {
  Write-Host "[sign-app] 未找到主程序 $Exe，跳过"
  exit 0
}
$signtool = Find-SignTool
if (-not $signtool) {
  Write-Host "[sign-app] 未找到 signtool.exe，跳过（装了 Windows SDK 后即可签名）"
  exit 0
}

Write-Host "[sign-app] 签名 $Exe （指纹 $thumb）"
& $signtool sign /fd SHA256 /sha1 $thumb /tr $TimestampUrl /td SHA256 $Exe
$s = Get-AuthenticodeSignature $Exe
if ($s.SignerCertificate -and $s.SignerCertificate.Thumbprint.ToUpper() -eq $thumb) {
  Write-Host "[sign-app] 已签名，自检通过：$($s.SignerCertificate.Subject)"
  exit 0
}
Write-Host "[sign-app] 签名自检未通过（status=$($s.Status)），构建应当失败以免交付未签名产物"
exit 1
