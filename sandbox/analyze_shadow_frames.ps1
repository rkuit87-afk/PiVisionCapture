param(
    [string]$Session = "shadow_sessions/2026-07-13_111327_operator_baseline_50",
    [int]$Boards = 12
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

& py sandbox/analyze_shadow_frames.py --session $Session --boards $Boards
