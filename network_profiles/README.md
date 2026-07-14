# Network Profiles

Use these when the laptop needs internet access and local PLC/camera access at the same time.

## Recommended Profile

Run PowerShell as Administrator:

```powershell
cd C:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture
.\network_profiles\use_plc_ethernet_wifi_internet.ps1
```

This makes:

- Ethernet = PLC/camera network only, no default gateway.
- Wi-Fi = internet and DNS.

The Ethernet static IP is `192.168.3.148/23`, which covers both `192.168.2.x` and `192.168.3.x`.

## Restore DHCP

Run PowerShell as Administrator:

```powershell
cd C:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture
.\network_profiles\restore_ethernet_dhcp.ps1
```

## Checks

```powershell
ping 192.168.3.151
Test-NetConnection 192.168.3.151 -Port 102
ping 8.8.8.8
nslookup openai.com
```

## Current Finding

On 2026-07-13, Ethernet was on DHCP as `192.168.2.147/23` with default gateway `192.168.3.254`.

Observed:

- Internet routing by IP worked: `ping 8.8.8.8` passed.
- DNS timed out against `10.255.253.208`, `8.8.8.8`, `192.168.3.254`, and `192.168.3.3`.
- PLC `192.168.3.151` appeared in ARP, but ping and TCP port `102` did not respond from this shell.

If this profile is active and the PLC still does not respond, the issue is likely PLC state, switch/VLAN/firewall, or CPU communication settings rather than Windows default routing.
