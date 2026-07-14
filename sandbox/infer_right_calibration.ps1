param(
    [string]$Session = "shadow_sessions/2026-07-13_111327_operator_baseline_50"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

& py sandbox/infer_right_calibration.py --session $Session
