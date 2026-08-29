# Agent Mandate — final video: mux the recorded narration onto the
# silent timeline and render Agent_Mandate_Cantor8_Demo_FINAL.mp4.
#   powershell -File make_final.ps1
# Leaves demo_timeline.pptx untouched; works on a copy.

$ErrorActionPreference = "Stop"
$dir = $PSScriptRoot
$timings = (Get-Content (Join-Path $dir "timeline.json") | ConvertFrom-Json)
$audio = Join-Path $dir "narration.m4a"
$srcPptx = Join-Path $dir "demo_timeline.pptx"
$finalPptx = Join-Path $dir "demo_timeline_final.pptx"
$mp4 = Join-Path $dir "Agent_Mandate_Cantor8_Demo_FINAL.mp4"

if (-not (Test-Path $audio)) { throw "narration.m4a missing" }
Copy-Item $srcPptx $finalPptx -Force
if (Test-Path $mp4) { Remove-Item $mp4 -Force }

$ppt = New-Object -ComObject PowerPoint.Application
$pres = $ppt.Presentations.Open($finalPptx, $false, $false, $false)

# Re-apply slide timings (the copy already has them, but be explicit).
for ($i = 1; $i -le $pres.Slides.Count; $i++) {
  $t = $pres.Slides.Item($i).SlideShowTransition
  $t.EntryEffect = 3585        # ppEffectFadeSmoothly
  $t.Duration = 0.5
  $t.AdvanceOnClick = 0
  $t.AdvanceOnTime = -1
  $t.AdvanceTime = [double]$timings[$i - 1]
}

# Narration on slide 1, playing across the whole show.
$s1 = $pres.Slides.Item(1)
$media = $s1.Shapes.AddMediaObject2($audio, 0, -1, 10, 10, 40, 40) # link:no, save:yes
$ps = $media.AnimationSettings.PlaySettings
$ps.PlayOnEntry = -1                    # start automatically
$ps.HideWhileNotPlaying = -1
$ps.PauseAnimation = 0
$ps.StopAfterSlides = $pres.Slides.Count # keep playing across every slide
$pres.Save()

$pres.CreateVideo($mp4, $true, 5, 1080, 30, 85)
while ($pres.CreateVideoStatus -eq 1 -or $pres.CreateVideoStatus -eq 2) {
  Start-Sleep -Seconds 3
}
$status = $pres.CreateVideoStatus
$pres.Close()
$ppt.Quit()
if ($status -ne 3) { throw "CreateVideo failed with status $status" }

$item = Get-Item $mp4
Write-Output "wrote $($item.Name) $([math]::Round($item.Length/1MB,1)) MB"
