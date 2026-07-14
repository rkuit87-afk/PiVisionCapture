# Use Ethernet for PLC/cameras only, and Wi-Fi for internet.
#
# Run in an elevated PowerShell window.
#
# Why:
# - The PLC/camera network is 192.168.2.0/23, including:
#   - PLC:          192.168.3.151
#   - RIGHT camera: 192.168.3.145
#   - LEFT camera:  192.168.2.246 or 192.168.3.146, depending on site state
# - Ethernet must NOT have a default gateway in this profile.
# - Wi-Fi should keep DHCP, DNS, and the internet default route.

param(
    [string]$EthernetAlias = "Ethernet",
    [string]$WifiAlias = "Wi-Fi",
    [string]$StaticIp = "192.168.3.148",
    [int]$PrefixLength = 24
)

$ErrorActionPreference = "Stop"

Write-Host "Configuring $EthernetAlias for PLC/camera local access only..."

# Remove existing IPv4 addresses from the Ethernet adapter.
Get-NetIPAddress -InterfaceAlias $EthernetAlias -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Remove-NetIPAddress -Confirm:$false

# Remove default routes on the Ethernet adapter so it cannot steal internet.
Get-NetRoute -InterfaceAlias $EthernetAlias -AddressFamily IPv4 -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
    Remove-NetRoute -Confirm:$false

# Add a static on-link address for the PLC/camera side.
New-NetIPAddress -InterfaceAlias $EthernetAlias -IPAddress $StaticIp -PrefixLength $PrefixLength | Out-Null

# No DNS on the PLC Ethernet profile. DNS belongs to Wi-Fi/internet.
Set-DnsClientServerAddress -InterfaceAlias $EthernetAlias -ResetServerAddresses

# Prefer Wi-Fi for default/internet routes.
Set-NetIPInterface -InterfaceAlias $WifiAlias -AddressFamily IPv4 -InterfaceMetric 10
Set-NetIPInterface -InterfaceAlias $EthernetAlias -AddressFamily IPv4 -InterfaceMetric 25

# Pin the PLC and known camera addresses to Ethernet. This matters because
# site Wi-Fi and PLC Ethernet can both sit in 192.168.2.0/23.
$PinnedHosts = @(
    "192.168.3.151", # PLC
    "192.168.3.145", # RIGHT camera
    "192.168.2.246", # LEFT camera DHCP address seen on site
    "192.168.3.146"  # LEFT camera intended static address
)

foreach ($HostIp in $PinnedHosts) {
    Get-NetRoute -DestinationPrefix "$HostIp/32" -ErrorAction SilentlyContinue |
        Remove-NetRoute -Confirm:$false
    New-NetRoute -DestinationPrefix "$HostIp/32" -InterfaceAlias $EthernetAlias -NextHop "0.0.0.0" -RouteMetric 1 | Out-Null
}

Write-Host ""
Write-Host "Done."
Write-Host "Expected result:"
Write-Host "- Ethernet has $StaticIp/$PrefixLength and no default gateway."
Write-Host "- Wi-Fi keeps internet/DNS."
Write-Host "- PLC/camera host routes are pinned to Ethernet."
Write-Host ""
Write-Host "Quick checks:"
Write-Host "  ping 192.168.3.151"
Write-Host "  Test-NetConnection 192.168.3.151 -Port 102"
Write-Host "  ping 8.8.8.8"
Write-Host "  nslookup openai.com"
