# Crop zoom regions out of the 2x captures for the video slides.
#   powershell -File crop.ps1
Add-Type -AssemblyName System.Drawing
$dir = Join-Path $PSScriptRoot "captures"

function Crop($srcName, $outName, $x, $y, $w, $h) {
  $src = [System.Drawing.Image]::FromFile((Join-Path $dir $srcName))
  $bmp = New-Object System.Drawing.Bitmap($w, $h)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.DrawImage($src, (New-Object System.Drawing.Rectangle(0, 0, $w, $h)),
    (New-Object System.Drawing.Rectangle($x, $y, $w, $h)),
    [System.Drawing.GraphicsUnit]::Pixel)
  $g.Dispose()
  $bmp.Save((Join-Path $dir $outName), [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose(); $src.Dispose()
  Write-Output "wrote $outName ($w x $h)"
}

# Coordinates are 2x device pixels (CSS px * 2) in the 3840x2160 captures.
Crop "idle2x.png"     "auth_idle.png"    556 150  684  460
Crop "accepted2x.png" "auth_after.png"   556 150  684  460
Crop "idle2x.png"     "pipe.png"        1260 400 1320  120
Crop "accepted2x.png" "decision_acc.png" 1260 500 1320  490
Crop "rejected2x.png" "decision_rej.png" 1260 500 1320  760
Crop "rejected2x.png" "checks_rej.png"  1280 900 1300  340
