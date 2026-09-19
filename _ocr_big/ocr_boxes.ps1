# Extract text WITH bounding boxes from PNG via Windows built-in OCR (WinRT).
# Output per line:  x,y,w,h<TAB>text   (coordinates in the (2x-upscaled) image pixels)
# PS 5.1 cannot GetAwaiter() WinRT async -> bridge via AsTask() reflection.
# ASCII-only paths.
param(
    [string]$Dir = "D:\naixi_desktop\_ocr_big",
    [string]$Out = "D:\naixi_desktop\_ocr_big\boxes.txt"
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime] | Out-Null

$AsTaskMethod = $null
foreach ($m in [System.WindowsRuntimeSystemExtensions].GetMethods()) {
    if ($m.Name -ne 'AsTask' -or -not $m.IsGenericMethod) { continue }
    $psx = $m.GetParameters()
    if ($psx.Count -ne 1) { continue }
    $pt = $psx[0].ParameterType
    if ($pt.IsGenericType -and $pt.GetGenericTypeDefinition().Name -eq 'IAsyncOperation`1') { $AsTaskMethod = $m; break }
}
if (-not $AsTaskMethod) { Write-Output "ERROR: AsTask(IAsyncOperation<T>) not found"; exit 1 }

function Await-Op {
    param([object]$op, [type]$resultType)
    $m = $AsTaskMethod.MakeGenericMethod($resultType)
    $task = $m.Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    return $task.Result
}

$lines = New-Object System.Collections.ArrayList
function Add-Line([string]$s) { [void]$lines.Add($s) }

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new("zh-Hans-CN"))
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $engine) { Add-Line "ERROR: no OCR engine (install zh-Hans-CN language pack)"; [System.IO.File]::WriteAllLines($Out, $lines); exit 1 }
Add-Line "ENGINE_OK lang=zh-Hans-CN"

Get-ChildItem -Path $Dir -Filter *.png | Sort-Object Name | ForEach-Object {
    Add-Line ""
    Add-Line ("===== FILE: " + $_.Name + " =====")
    try {
        $file = Await-Op ([Windows.Storage.StorageFile]::GetFileFromPathAsync($_.FullName)) ([Windows.Storage.StorageFile])
        $stream = Await-Op ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder = Await-Op ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Await-Op ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        if ($bitmap.BitmapPixelFormat -ne 'Bgra8') { $c = [Windows.Graphics.Imaging.SoftwareBitmap]::Convert($bitmap, 'Bgra8', 'Premultiplied'); $bitmap.Dispose(); $bitmap = $c }
        try { $bitmap.SetDpi(96, 96) } catch { }
        $result = Await-Op ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        foreach ($ln in $result.Lines) {
            $r = $ln.BoundingRect
            if (($r.Width -eq 0) -and ($r.Height -eq 0) -and ($ln.Words.Count -gt 0)) { $r = $ln.Words[0].BoundingRect }
            Add-Line (("{0},{1},{2},{3}" -f [int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height) + "`t" + $ln.Text)
        }
        $bitmap.Dispose(); $stream.Dispose()
    }
    catch { Add-Line ("OCR_FAILED: " + $_.Exception.Message) }
}
[System.IO.File]::WriteAllLines($Out, $lines, [System.Text.UTF8Encoding]::new($false))
Write-Output ("DONE -> " + $Out + "  lines=" + $lines.Count)
