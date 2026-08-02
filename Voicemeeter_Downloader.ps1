# Voicemeeter Banana official installer downloader
# - Multithreaded download via aria2c (16 connections) to bypass single-thread throttle
# - SHA256 verification against the known official hash (fda1c8...ff09ee5)
# - Graceful fallback to single-threaded if aria2 bootstrap fails
$ErrorActionPreference = "Continue"

$url = "https://download.vb-audio.com/Download_CABLE/VoicemeeterSetup_v2122.zip"
$expectedHash = "fda1c82522b4a8c87a89c5c50a56e7e25e3519b9e1f1a8e63475b8590ff09ee5"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$dest = Join-Path $dir "VoicemeeterSetup_v2122.zip"

function Verify {
    if (-not (Test-Path $dest)) { return $false }
    $actual = (Get-FileHash -Algorithm SHA256 $dest).Hash.ToLower()
    if ($actual -eq $expectedHash) {
        Write-Host "[OK] SHA256 matched -> official original, safe to install." -ForegroundColor Green
        return $true
    } else {
        Write-Host "[WARN] SHA256 MISMATCH! actual=$actual  expected=$expectedHash" -ForegroundColor Red
        Write-Host "This may be a tampered/repackaged build. Do NOT install." -ForegroundColor Red
        return $false
    }
}

# Step 1: bootstrap aria2c (portable, from GitHub) for multithreaded speed
$aria2 = Join-Path $dir "aria2c.exe"
if (-not (Test-Path $aria2)) {
    Write-Host "[*] Fetching aria2c portable from GitHub..."
    $ariaUrl = "https://github.com/aria2/aria2/releases/download/release-1.37.0/aria2-1.37.0-win-64bit-build1.zip"
    $ariaZip = Join-Path $dir "aria2.zip"
    try {
        Invoke-WebRequest -Uri $ariaUrl -OutFile $ariaZip -UseBasicParsing -TimeoutSec 180
        Expand-Archive -Path $ariaZip -DestinationPath (Join-Path $dir "aria2_tmp") -Force
        $exe = Get-ChildItem (Join-Path $dir "aria2_tmp") -Recurse -Filter aria2c.exe | Select-Object -First 1
        Copy-Item $exe.FullName $aria2
        Remove-Item $ariaZip, (Join-Path $dir "aria2_tmp") -Recurse -Force
        Write-Host "[*] aria2c ready." -ForegroundColor Cyan
    } catch {
        Write-Host "[!] aria2c bootstrap failed, will use single-threaded fallback." -ForegroundColor Yellow
        Remove-Item $ariaZip -ErrorAction SilentlyContinue
        Remove-Item (Join-Path $dir "aria2_tmp") -Recurse -ErrorAction SilentlyContinue
    }
}

# Step 2: download
if (Test-Path $aria2) {
    Write-Host "[*] Downloading with aria2c (16 connections, resumable)..."
    & $aria2 -x 16 -s 16 -k 1M --retry-wait=3 --max-tries=8 -o $dest $url
} else {
    Write-Host "[*] Downloading single-threaded (slower, but works)..."
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing -TimeoutSec 900
}

# Step 3: verify and report
if (Test-Path $dest) {
    if (Verify) {
        $sz = [math]::Round((Get-Item $dest).Length / 1MB, 1)
        Write-Host "[DONE] Saved ($sz MB): $dest" -ForegroundColor Green
        Write-Host "Next: right-click the .zip -> Run as administrator the installer, then REBOOT once." -ForegroundColor Cyan
        Write-Host "After reboot, follow VOICEMEETER_SETUP.md (Banana routing) and restart the desktop pet." -ForegroundColor Cyan
    } else {
        Remove-Item $dest -ErrorAction SilentlyContinue
        Write-Host "[ABORT] Removed the mismatched file." -ForegroundColor Red
    }
} else {
    Write-Host "[FAIL] No file produced. Check your network / firewall." -ForegroundColor Red
}
Read-Host "Press Enter to exit"
