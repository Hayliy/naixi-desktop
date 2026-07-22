Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class WAPI {
  public delegate bool EnumDelegate(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumDelegate lpEnumFunc, IntPtr lParam);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$exe = $args[0]
$out = $args[1]
Start-Process $exe
Start-Sleep -Seconds 4

$script:target = [IntPtr]::Zero
$enumBlock = {
  param($hwnd, $p)
  if (-not [WAPI]::IsWindowVisible($hwnd)) { return $true }
  $sb = New-Object System.Text.StringBuilder 256
  [WAPI]::GetWindowText($hwnd, $sb, 256) | Out-Null
  $t = $sb.ToString()
  if ($t -like "*奶昔*") {
    $script:target = $hwnd
    return $false
  }
  return $true
}
[WAPI]::EnumWindows($enumBlock, [IntPtr]::Zero)

if ($script:target -eq [IntPtr]::Zero) {
  $enumBlock2 = {
    param($hwnd, $p)
    if (-not [WAPI]::IsWindowVisible($hwnd)) { return $true }
    $sb = New-Object System.Text.StringBuilder 256
    [WAPI]::GetWindowText($hwnd, $sb, 256) | Out-Null
    if ($sb.ToString().Length -gt 0) {
      $script:target = $hwnd
      return $false
    }
    return $true
  }
  [WAPI]::EnumWindows($enumBlock2, [IntPtr]::Zero)
}

if ($script:target -eq [IntPtr]::Zero) { Write-Host "WINDOW_NOT_FOUND"; exit 1 }

$rect = New-Object WAPI+RECT
[WAPI]::GetWindowRect($script:target, [ref]$rect)
[WAPI]::SetForegroundWindow($script:target)
Start-Sleep -Milliseconds 400

$w = $rect.Right - $rect.Left
$h = $rect.Bottom - $rect.Top
Write-Host "RECT $($rect.Left),$($rect.Top) ${w}x${h}"
$bmp = New-Object System.Drawing.Bitmap($w, $h)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($rect.Left, $rect.Top, 0, 0, (New-Object System.Drawing.Size($w, $h)))
$bmp.Save($out)
Write-Host "SAVED $out"
