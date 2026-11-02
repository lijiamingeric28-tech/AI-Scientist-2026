# 截图工具（视觉闭环用：截图 → qwen vision 审查 → 修复 → 再截图）
# 用法:
#   powershell -ExecutionPolicy Bypass -File scripts\screenshot.ps1 <输出.png>            # 截主屏
#   powershell -ExecutionPolicy Bypass -File scripts\screenshot.ps1 <输出.png> -Title "AstroQuery"  # 截指定窗口(后台也可)
param(
    [string]$Out = "E:\work\AI-Scientist-2026\astroquery_frontend\output\screen.png",
    [string]$Title = ""
)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Shot {
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hwnd, IntPtr hdcBlt, uint nFlags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd, out RECT rect);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

if ($Title) {
    $proc = Get-Process | Where-Object { $_.MainWindowTitle -like "*$Title*" } | Select-Object -First 1
    if (-not $proc) { Write-Output "NO_WINDOW: $Title"; exit 1 }
    $hwnd = $proc.MainWindowHandle
    $rect = New-Object Win32Shot+RECT
    [Win32Shot]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
    $w = $rect.Right - $rect.Left; $h = $rect.Bottom - $rect.Top
    if ($w -le 0 -or $h -le 0) { Write-Output "BAD_RECT: $w x $h"; exit 1 }
    $bmp = New-Object System.Drawing.Bitmap($w, $h)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $hdc = $g.GetHdc()
    [Win32Shot]::PrintWindow($hwnd, $hdc, 2) | Out-Null   # 2 = PW_RENDERFULLCONTENT
    $g.ReleaseHdc($hdc)
    $bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    Write-Output "saved: $Out ($w x $h) window=$($proc.MainWindowTitle)"
} else {
    $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
    $bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    Write-Output "saved: $Out (screen)"
}
