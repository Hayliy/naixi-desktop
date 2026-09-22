<#
  生成 / 复用「自签名」Authenticode 代码签名证书（本机构建用）。

  为什么用自签名、以及它的边界（务必同步告知用户）：
    · 自签名证书的根不被 Windows 信任 ⇒ SmartScreen 仍会提示「未知发布者」，这不会因为自签名而消失；
    · 它真正买到的是：① 包体带可核验的签名与固定指纹；② 包被改动后签名立即失效（完整性可验证）；
      ③ 与将来换成受信任 CA 证书时**流程完全一致**，只需替换证书，不改流水线。
  换正式证书时：把证书装进当前用户证书库（或云端签名客户端），把指纹交给 scripts/build-release.ps1 即可。

  用法：
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/gen-selfsign-cert.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/gen-selfsign-cert.ps1 -ExportPfx
#>
param(
  [string]$Subject = "CN=Naixi Desktop (Self-Signed), O=Naixi, C=CN",
  [int]$Years = 3,
  [string]$OutDir = "src-tauri/codesign",
  [switch]$ExportPfx
)

$ErrorActionPreference = "Stop"

# 1) 复用已有证书：同主题 + 有私钥 + 剩余有效期 > 30 天（避免每次构建都往证书库里塞新证书）
$existing = Get-ChildItem Cert:\CurrentUser\My |
  Where-Object { $_.Subject -eq $Subject -and $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date).AddDays(30) } |
  Sort-Object NotAfter -Descending | Select-Object -First 1

if ($existing) {
  $cert = $existing
  Write-Host "[cert] 复用已有自签名证书 thumbprint=$($cert.Thumbprint)"
} else {
  # Code Signing EKU = 1.3.6.1.5.5.7.3.3；2.5.29.19 = basicConstraints（自签名不为 CA）
  $cert = New-SelfSignedCertificate -Type Custom -Subject $Subject `
    -KeyUsage DigitalSignature -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 `
    -CertStoreLocation "Cert:\CurrentUser\My" -NotAfter (Get-Date).AddYears($Years) `
    -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}")
  Write-Host "[cert] 新建自签名证书 thumbprint=$($cert.Thumbprint)"
}

# 2) 导出公钥证书（.cer）——可入库：用户导入后即可在文件属性里核验签名主体
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$cerPath = Join-Path $OutDir "naixi-selfsign.cer"
Export-Certificate -Cert $cert -FilePath $cerPath -Type CERT | Out-Null
Write-Host "[cert] 公钥已导出: $cerPath"

# 3) 可选导出私钥 pfx（给 CI / 其它机器用；含私钥，已在 .gitignore 中排除）
if ($ExportPfx) {
  $pwPath = Join-Path $OutDir "pfx-password.txt"
  if (Test-Path $pwPath) {
    $pw = (Get-Content $pwPath -Raw).Trim()
  } else {
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $pw = [Convert]::ToBase64String($bytes)
    Set-Content -Path $pwPath -Value $pw -Encoding ascii
  }
  $pfxPath = Join-Path $OutDir "naixi-selfsign.pfx"
  $sec = ConvertTo-SecureString -String $pw -Force -AsPlainText
  Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $sec | Out-Null
  Write-Host "[cert] 私钥已导出: $pfxPath （口令见 $pwPath；两者都不入库）"
}

# 4) 机器可读信息，供 build-release.ps1 / CI 取用
$info = [ordered]@{
  thumbprint = $cert.Thumbprint
  subject    = $cert.Subject
  notAfter   = $cert.NotAfter.ToString("yyyy-MM-dd")
  cer        = (Resolve-Path $cerPath).Path
  selfSigned = $true
}
$info | ConvertTo-Json | Set-Content -Path (Join-Path $OutDir "selfsign.json") -Encoding utf8

Write-Host ""
Write-Host "自签名证书就绪："
Write-Host "  thumbprint : $($cert.Thumbprint)"
Write-Host "  subject    : $($cert.Subject)"
Write-Host "  有效期至   : $($cert.NotAfter.ToString('yyyy-MM-dd'))"
Write-Host "注意：自签名不消除 SmartScreen 的「未知发布者」提示，它提供的是完整性校验与固定指纹。"
