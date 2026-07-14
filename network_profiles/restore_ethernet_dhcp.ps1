# Restore Ethernet to normal DHCP.
#
# Run in an elevated PowerShell window.

param(
    [string]$EthernetAlias = "Ethernet"
)

$ErrorActionPreference = "Stop"

Write-Host "Restoring $EthernetAlias to DHCP..."

Get-NetIPAddress -InterfaceAlias $EthernetAlias -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Remove-NetIPAddress -Confirm:$false

Set-NetIPInterface -InterfaceAlias $EthernetAlias -AddressFamily IPv4 -Dhcp Enabled
Set-DnsClientServerAddress -InterfaceAlias $EthernetAlias -ResetServerAddresses

ipconfig /renew $EthernetAlias

Write-Host ""
Write-Host "Done. Ethernet is back on DHCP."
