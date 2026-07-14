# Requires an elevated PowerShell session.
# Restores the known-good July 13 split-network setup:
#   Ethernet (onboard)    = DHCP internet path
#   Realtek USB GbE       = PLC/camera-only path, 192.168.3.148/23
# No PLC, camera, or machine setting is written by this script.

[CmdletBinding()]
param(
    [string]$OnboardAlias = "Ethernet",
    [string]$UsbMac = "00-E0-4C-68-05-7C",
    [string]$PlcIp = "192.168.3.151",
    [string[]]$CameraIps = @("192.168.3.145", "192.168.3.146", "192.168.2.246"),
    [string]$UsbIp = "192.168.3.148",
    [int]$PrefixLength = 23
)

$ErrorActionPreference = "Stop"

if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell window (Run as administrator)."
}

$onboard = Get-NetAdapter -Name $OnboardAlias -ErrorAction Stop
$usb = Get-NetAdapter -IncludeHidden | Where-Object {
    $_.MacAddress -eq $UsbMac -or $_.InterfaceDescription -match "Realtek USB.*GbE"
} | Select-Object -First 1

if (-not $usb) {
    throw "USB PLC adapter not found. Reconnect the Realtek USB-to-Ethernet adapter (MAC $UsbMac), then rerun. No settings were changed."
}
if ($usb.Status -ne "Up") {
    throw "USB PLC adapter '$($usb.Name)' is detected but link is $($usb.Status). Check its cable to the PLC/camera switch, then rerun. No settings were changed."
}

Write-Host "Onboard internet adapter: $($onboard.Name)"
Write-Host "USB PLC adapter: $($usb.Name) [$($usb.MacAddress)]"

# Onboard Ethernet stays DHCP/internet. Remove only stale PLC host routes that
# could win because the office and PLC networks overlap at 192.168.2.0/23.
Set-NetIPInterface -InterfaceAlias $onboard.Name -AddressFamily IPv4 -Dhcp Enabled
Set-DnsClientServerAddress -InterfaceAlias $onboard.Name -ResetServerAddresses
Set-NetIPInterface -InterfaceAlias $onboard.Name -AddressFamily IPv4 -InterfaceMetric 10

$targets = @($PlcIp) + $CameraIps
foreach ($ip in $targets) {
    $prefix = "$ip/32"
    Get-NetRoute -InterfaceAlias $onboard.Name -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.DestinationPrefix -eq $prefix } |
        Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
}

# USB adapter is strictly local PLC/camera traffic: fixed address, no gateway,
# no DNS, then explicit /32 routes so it wins over the overlapping DHCP range.
Get-NetIPAddress -InterfaceAlias $usb.Name -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.PrefixOrigin -ne "WellKnown" } |
    Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
Get-NetRoute -InterfaceAlias $usb.Name -AddressFamily IPv4 -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
    Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
Set-NetIPInterface -InterfaceAlias $usb.Name -AddressFamily IPv4 -Dhcp Disabled
New-NetIPAddress -InterfaceAlias $usb.Name -IPAddress $UsbIp -PrefixLength $PrefixLength | Out-Null
Set-DnsClientServerAddress -InterfaceAlias $usb.Name -ResetServerAddresses
Set-NetIPInterface -InterfaceAlias $usb.Name -AddressFamily IPv4 -InterfaceMetric 25

foreach ($ip in $targets) {
    $prefix = "$ip/32"
    Get-NetRoute -InterfaceAlias $usb.Name -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.DestinationPrefix -eq $prefix } |
        Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
    New-NetRoute -InterfaceAlias $usb.Name -DestinationPrefix $prefix -NextHop "0.0.0.0" -RouteMetric 1 | Out-Null
}

Write-Host ""
Write-Host "Restored:"
Get-NetIPConfiguration -InterfaceAlias $onboard.Name |
    Format-List InterfaceAlias, IPv4Address, IPv4DefaultGateway, DNSServer
Get-NetIPConfiguration -InterfaceAlias $usb.Name |
    Format-List InterfaceAlias, IPv4Address, IPv4DefaultGateway, DNSServer
Get-NetRoute -InterfaceAlias $usb.Name -AddressFamily IPv4 |
    Where-Object { $_.DestinationPrefix -in ($targets | ForEach-Object { "$_/32" }) } |
    Format-Table InterfaceAlias, DestinationPrefix, NextHop, RouteMetric -AutoSize

$test = Test-NetConnection $PlcIp -Port 102 -WarningAction SilentlyContinue
Write-Host "PLC $PlcIp TCP/102: $($test.TcpTestSucceeded) via $($test.InterfaceAlias)"
