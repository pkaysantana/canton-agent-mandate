# Agent Mandate — MP4 export via PowerPoint COM.
#   powershell -File make_video.ps1
# Applies per-slide timings from timeline.json to demo_timeline.pptx,
# then renders Agent_Mandate_Cantor8_Demo.mp4 at 1920x1080/30fps.

$ErrorActionPreference = "Stop"
$dir = $PSScriptRoot
$timings = (Get-Content (Join-Path $dir "timeline.json") | ConvertFrom-Json)
$mp4 = Join-Path $dir "Agent_Mandate_Cantor8_Demo.mp4"
if (Test-Path $mp4) { Remove-Item $mp4 -Force }

$ppt = New-Object -ComObject PowerPoint.Application
$pres = $ppt.Presentations.Open((Join-Path $dir "demo_timeline.pptx"), $false, $false, $false)

if ($pres.Slides.Count -ne $timings.Count) {
  throw "slide count $($pres.Slides.Count) != timings $($timings.Count)"
}

for ($i = 1; $i -le $pres.Slides.Count; $i++) {
  $t = $pres.Slides.Item($i).SlideShowTransition
  $t.EntryEffect = 3585        # ppEffectFadeSmoothly
  $t.Duration = 0.5
  $t.AdvanceOnClick = 0
  $t.AdvanceOnTime = -1        # msoTrue
  $t.AdvanceTime = [double]$timings[$i - 1]
}
$pres.Save()

# CreateVideo(FileName, UseTimingsAndNarrations, DefaultSlideDuration,
#             VertResolution, FramesPerSecond, Quality)
$pres.CreateVideo($mp4, $true, 5, 1080, 30, 85)

# ppMediaTaskStatus: 1 InProgress, 2 Queued, 3 Done, 4 Failed
while ($pres.CreateVideoStatus -eq 1 -or $pres.CreateVideoStatus -eq 2) {
  Start-Sleep -Seconds 3
}
$status = $pres.CreateVideoStatus
$pres.Close()
$ppt.Quit()
if ($status -ne 3) { throw "CreateVideo failed with status $status" }

$item = Get-Item $mp4
Write-Output "wrote $($item.Name) $([math]::Round($item.Length/1MB,1)) MB"
