# Transfer latest bench_scan session from Pi to engineering PC for grading

param(
    [string]$PiUser = "Kuit87",
    [string]$PiHost = "192.168.2.11",
    [string]$DestinationPath = "C:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture\captures_review"
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Transferring capture session from Pi..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Find latest bench_scan directory on Pi
Write-Host "Finding latest session on Pi..." -ForegroundColor Yellow
$findCmd = "ls -td ~/PiVisionCapture/captures/bench_scan_* 2>/dev/null | head -1"
$latestSession = ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$PiUser@$PiHost" $findCmd 2>$null

if (-not $latestSession) {
    Write-Host "✗ No bench_scan sessions found on Pi" -ForegroundColor Red
    exit 1
}

$latestSession = $latestSession.Trim()
Write-Host "Latest session: $latestSession" -ForegroundColor Green
Write-Host ""

# Create destination
$dest = Join-Path $DestinationPath (Split-Path $latestSession -Leaf)
Write-Host "Destination: $dest" -ForegroundColor Green
New-Item -ItemType Directory -Force -Path $dest | Out-Null

# Transfer
Write-Host ""
Write-Host "Transferring files..." -ForegroundColor Yellow
& scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -r `
  "$PiUser@$PiHost`:$latestSession/*" `
  "$dest\"

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Transfer failed" -ForegroundColor Red
    exit 1
}

# Verify
Write-Host ""
Write-Host "Verifying transfer..." -ForegroundColor Cyan
$jpgCount = (Get-ChildItem -Path $dest -Filter "*.jpg" -Recurse).Count
$jsonCount = (Get-ChildItem -Path $dest -Filter "*.json" -Recurse).Count
$totalSize = (Get-ChildItem -Path $dest -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "✓ Transfer complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "Location:  $dest" -ForegroundColor Cyan
Write-Host "JPG files: $jpgCount" -ForegroundColor Cyan
Write-Host "JSON files: $jsonCount" -ForegroundColor Cyan
Write-Host "Total size: $([Math]::Round($totalSize, 2)) MB" -ForegroundColor Cyan
Write-Host ""
