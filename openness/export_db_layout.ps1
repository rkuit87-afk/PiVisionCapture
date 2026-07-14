# export_db_layout.ps1 -- READ-ONLY dump of the live TIA project's DBs + PLC tags.
#
# Attaches to the running TIA Portal (or opens the latest Trimmer project
# without GUI if none is running), exports every Global DB to SimaticML XML
# and every PLC tag table to JSON, then detaches. NO Save(), NO compile,
# NO download -- the project is never modified.
#
# Output: openness\exports\<timestamp>\
#   db_index.json    all DBs: name / number / layout / consistency
#   DB_<n>_<name>.xml   SimaticML per DB (parse with parse_db_xml.py)
#   plc_tags.json    every tag: name / datatype / address / table
#
# Usage:  powershell -ExecutionPolicy Bypass -File export_db_layout.ps1

param(
    [string]$ProjectHint = "Trimmer.G2.VissionAdded",
    [string]$FallbackProject = "C:\Users\PSM-LPT-PLC\Desktop\siemens 2.0\Trimmer.G2.VissionAdded\Trimmer.G2.VissionAdded.ap20",
    [string]$OutRoot = "$PSScriptRoot\exports"
)

$ErrorActionPreference = "Stop"
# Add-Type eagerly loads all types and fails on Openness dependencies;
# LoadFrom resolves dependencies from the DLL's own directory.
$apiDir = "C:\Program Files\Siemens\Automation\Portal V20\PublicAPI\V20"
[void][System.Reflection.Assembly]::LoadFrom((Join-Path $apiDir "Siemens.Engineering.dll"))

function Get-Service2($obj, [type]$serviceType) {
    $m = $obj.GetType().GetMethod("GetService")
    $g = $m.MakeGenericMethod($serviceType)
    return $g.Invoke($obj, $null)
}

$stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$outDir = Join-Path $OutRoot $stamp
New-Item -ItemType Directory -Force $outDir | Out-Null

# ---- attach to running portal, or open headless as fallback ----
$tia = $null
$openedHere = $false
$procs = [Siemens.Engineering.TiaPortal]::GetProcesses()
$target = $procs | Where-Object { "$($_.ProjectPath)" -like "*$ProjectHint*" } | Select-Object -First 1
if (-not $target -and $procs.Count -gt 0) { $target = $procs[0] }

if ($target) {
    Write-Host ("Attaching to running TIA Portal PID={0} Project={1}" -f $target.Id, $target.ProjectPath)
    $tia = $target.Attach()
} else {
    Write-Host "No running TIA Portal - opening $FallbackProject headless (takes minutes)..."
    $tia = New-Object Siemens.Engineering.TiaPortal([Siemens.Engineering.TiaPortalMode]::WithoutUserInterface)
    $openedHere = $true
    $fi = New-Object System.IO.FileInfo($FallbackProject)
    [void]$tia.Projects.Open($fi)
}

$project = $tia.Projects[0]
Write-Host ("Project: {0}" -f $project.Name)

# ---- locate PLC software ----
$plcSoftware = $null
foreach ($device in $project.Devices) {
    foreach ($di in $device.DeviceItems) {
        $swc = Get-Service2 $di ([Siemens.Engineering.HW.Features.SoftwareContainer])
        if ($swc -and $swc.Software -is [Siemens.Engineering.SW.PlcSoftware]) {
            $plcSoftware = $swc.Software
            Write-Host ("PLC software: {0} (device {1} / {2})" -f $plcSoftware.Name, $device.Name, $di.Name)
            break
        }
    }
    if ($plcSoftware) { break }
}
if (-not $plcSoftware) { Write-Host "ERROR: no PlcSoftware found"; exit 1 }

# ---- walk all block groups, collect Global DBs ----
$dbs = New-Object System.Collections.ArrayList
function Walk-Group($group, $path) {
    foreach ($blk in $group.Blocks) {
        if ($blk -is [Siemens.Engineering.SW.Blocks.GlobalDB]) {
            [void]$dbs.Add(@{ Block = $blk; Path = $path })
        }
    }
    foreach ($sub in $group.Groups) { Walk-Group $sub "$path/$($sub.Name)" }
}
Walk-Group $plcSoftware.BlockGroup ""

$index = @()
foreach ($entry in $dbs) {
    $blk = $entry.Block
    $info = [ordered]@{
        name = $blk.Name
        number = [int]$blk.Number
        group = $entry.Path
        memory_layout = "$($blk.MemoryLayout)"
        is_consistent = $blk.IsConsistent
        modified = $null
        xml = $null
        export_error = $null
    }
    try { $info.modified = "$($blk.ModifiedDate)" } catch {}

    $safe = ($blk.Name -replace '[^\w\.-]', '_')
    $xmlPath = Join-Path $outDir ("DB_{0}_{1}.xml" -f $blk.Number, $safe)
    try {
        if (Test-Path $xmlPath) { Remove-Item $xmlPath -Force }
        $fi = New-Object System.IO.FileInfo($xmlPath)
        $blk.Export($fi, [Siemens.Engineering.ExportOptions]::WithDefaults)
        $info.xml = $fi.Name
        Write-Host ("Exported DB{0} '{1}'  layout={2}  -> {3}" -f $blk.Number, $blk.Name, $info.memory_layout, $fi.Name)
    } catch {
        $info.export_error = $_.Exception.Message
        Write-Host ("EXPORT FAILED DB{0} '{1}': {2}" -f $blk.Number, $blk.Name, $_.Exception.Message)
    }
    $index += [pscustomobject]$info
}

$index | ConvertTo-Json -Depth 4 | Out-File (Join-Path $outDir "db_index.json") -Encoding utf8
Write-Host ("db_index.json written: {0} DBs" -f $index.Count)

# ---- dump every PLC tag (name / type / address) ----
$tags = New-Object System.Collections.ArrayList
function Walk-TagGroup($group, $path) {
    foreach ($table in $group.TagTables) {
        foreach ($tag in $table.Tags) {
            $comment = ""
            try { $comment = "$($tag.Comment.Items[0].Text)" } catch { $comment = "" }
            [void]$tags.Add([pscustomobject]@{
                table = "$path/$($table.Name)"
                name = $tag.Name
                datatype = $tag.DataTypeName
                address = $tag.LogicalAddress
                comment = $comment
            })
        }
    }
    foreach ($sub in $group.Groups) { Walk-TagGroup $sub "$path/$($sub.Name)" }
}
Walk-TagGroup $plcSoftware.TagTableGroup ""
$tags | ConvertTo-Json -Depth 3 | Out-File (Join-Path $outDir "plc_tags.json") -Encoding utf8
Write-Host ("plc_tags.json written: {0} tags" -f $tags.Count)

if ($openedHere) {
    Write-Host "Closing headless portal (project was never saved)..."
    $tia.Dispose()
}
Write-Host ""
Write-Host "DONE. Output: $outDir"
