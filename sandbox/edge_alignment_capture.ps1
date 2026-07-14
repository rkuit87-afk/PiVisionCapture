param(
    [ValidateSet("falling", "rising")]
    [string]$Edge = "falling",
    [ValidateSet("bTrigger", "pe_input")]
    [string]$Source = "bTrigger",
    [int]$Captures = 10
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

& py sandbox/edge_alignment_capture.py --edge $Edge --source $Source --captures $Captures
