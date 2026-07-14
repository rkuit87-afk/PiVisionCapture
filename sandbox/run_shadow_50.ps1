# Run a 50-board read-only shadow comparison.
#
# This script does not write to the PLC. It launches shadow_capture_app.py,
# which reads PLC/camera state and records our prediction vs operator decision.

param(
    [string]$Session = "operator_baseline_50",
    [string]$Notes = "operator decision comparison, 50 boards",
    [string]$TriggerSource = "bTrigger",
    [string]$SawDoneSource = "bSawDownCompare"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "PiVisionCapture shadow run readiness check"
Write-Host "Root: $Root"
Write-Host ""

$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) {
    throw "Python launcher 'py' was not found. Install Python or add it to PATH before running the shadow app."
}

$pyCheck = & py --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Python launcher exists, but no Python interpreter is registered: $pyCheck"
}
Write-Host "Python: $pyCheck"

$plc = Test-NetConnection 192.168.3.151 -Port 102 -WarningAction SilentlyContinue
if (-not $plc.TcpTestSucceeded) {
    throw "PLC ping may work, but TCP port 102 is not reachable. snap7 cannot read the PLC until S7/PUT-GET access is available."
}
Write-Host "PLC S7 port: OK"

Write-Host ""
Write-Host "Starting 50-board shadow run..."
Write-Host "Session: $Session"
Write-Host "Trigger source: $TriggerSource"
Write-Host "Saw-done source: $SawDoneSource"
Write-Host ""

& py shadow_capture_app.py `
    --session $Session `
    --boards 50 `
    --notes $Notes `
    --trigger-source $TriggerSource `
    --sawdone-source $SawDoneSource
