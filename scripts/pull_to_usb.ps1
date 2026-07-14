# pull_to_usb.ps1 - Transfer paired board images from the Pi to USB drive D:,
# verify each file landed with a matching size, then delete ONLY the verified
# files from the Pi. Safe to run repeatedly; drains whatever pairs are present.
#
#   - Never deletes a Pi file unless its copy on D: exists AND size matches.
#   - A file still being written (size changes between listing and copy) fails
#     verification and is left on the Pi for the next run - no data loss.

$ErrorActionPreference = "Stop"
$pi        = "Kuit87@192.168.2.11"
$remoteDir = "PiVisionCapture/captures/paired_2026-07-08"
$dest      = "D:\board_captures"

New-Item -ItemType Directory -Force $dest | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# 1. List remote files with byte sizes (name<space>size), captured BEFORE copy.
$listing = ssh -o StrictHostKeyChecking=no $pi "cd $remoteDir; stat -c '%n %s' *.jpg 2>/dev/null"
if (-not $listing) { Write-Host "[$stamp] No files on Pi - nothing to do."; return }

$remote = @{}
foreach ($line in ($listing -split "`n")) {
    $line = $line.Trim()
    if (-not $line) { continue }
    $sp = $line.LastIndexOf(' ')
    if ($sp -lt 1) { continue }
    $name = $line.Substring(0, $sp)
    $size = [int64]$line.Substring($sp + 1)
    $remote[$name] = $size
}
Write-Host "[$stamp] $($remote.Count) files on Pi. Copying to $dest ..."

# 2. Bulk copy all jpgs in one scp call.
scp -o StrictHostKeyChecking=no "${pi}:${remoteDir}/*.jpg" $dest 2>$null

# 3. Verify each: exists on D: and size matches the pre-copy size.
$verified = New-Object System.Collections.Generic.List[string]
foreach ($name in $remote.Keys) {
    $local = Join-Path $dest $name
    if ((Test-Path $local) -and ((Get-Item $local).Length -eq $remote[$name])) {
        $verified.Add($name)
    }
}
Write-Host "[$stamp] Verified $($verified.Count)/$($remote.Count) on D:."

# 4. Delete ONLY verified files from the Pi.
if ($verified.Count -gt 0) {
    $quoted = ($verified | ForEach-Object { "'$_'" }) -join " "
    ssh -o StrictHostKeyChecking=no $pi "cd $remoteDir; rm -f $quoted"
    Write-Host "[$stamp] Deleted $($verified.Count) verified files from Pi."
}
$skipped = $remote.Count - $verified.Count
if ($skipped -gt 0) { Write-Host "[$stamp] Left $skipped unverified file(s) on Pi for next run." }
