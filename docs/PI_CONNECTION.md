# Raspberry Pi Connection Info

## SSH
```
ssh justdo-pi
```
This uses the host alias defined in `C:\Users\PSM-LPT-PLC\.ssh\config`:
- Host: `justdo-pi` -> `192.168.2.11`
- User: `Kuit87`  (NOT `pi` — this Pi's login user is `Kuit87`)
- Key: `C:\Users\PSM-LPT-PLC\.ssh\id_rsa`

## VNC
```
192.168.2.11:5900
```

## Hardware map — 192.168.3.0/24 (mill OT network)
NOTE: this range is only reachable from a host with a REAL address inside
192.168.3.0/24 — a DHCP address from the wider 192.168.2.0/23 (e.g. this PC's
normal 192.168.2.14x) is NOT enough, even though it looks like the same
network by subnet math. See "IMPORTANT" section below.

| Device              | IP            | Status (2026-07-11)              |
|---------------------|---------------|-----------------------------------|
| PLC CPU             | 192.168.3.151 | Reachable, S7comm confirmed (snap7 connect() succeeds, PUT/GET enabled) |
| Remote IO (ET200)   | 192.168.3.152 | Reachable via ping. PROFINET-connected to CPU — no direct app connection needed, its I/O comes through the CPU's DBs |
| Camera RIGHT        | 192.168.3.145 | Reachable |
| Camera LEFT         | 192.168.3.146 | NOT reachable — cable still needs to move to mill switch |
| Trimmer             | UNKNOWN       | TODO — get IP from user/TIA |
| Pi eth0             | 192.168.2.11  | Reachable (DHCP, office/general range only — cannot reach 3.x devices) |
| Pi eth1             | 192.168.3.147 | NOT reachable — USB-Ethernet leg not yet patched into switch/router |
| This engineering PC | 192.168.3.148 | Static, added manually, working |

Other unidentified Siemens-OUI (00-02-d1-xx) devices seen on ARP sweep,
possibly the trimmer or other automation gear:
192.168.3.5, .43, .59, .93, .130, .169, .195

## Cameras (Vivotek IB9369) — re-addressed 2026-07-10
- RIGHT / capture:  `192.168.3.145`  (user `root`, pw `Altdanjosh@4878`)
- LEFT  / monitor:  `192.168.3.146`  (user `root`, pw `aLTDANJOSH@4878` — note different case!)
- Static, subnet `255.255.254.0` (/23), gateway `192.168.3.254` — same /23 as the mill LAN
- RTSP: `rtsp://root:<pw-urlencoded>@<ip>/live1s1.sdp` (`@` in pw = `%40`)
- Old link-local addresses 169.254.9.152/.172 are RETIRED. The cameras must be
  patched into the mill switch (they used to hang off the Pi's eth1); Pi eth1
  is then unused.

## Pi filesystem layout
- Project root: `/home/Kuit87/PiVisionCapture`
- Physical desktop display: `:0` (user `Kuit87` logged in on tty7)

## Known running processes (as of 2026-07-10)
- `/usr/bin/python3 app.py` (PID varies) — started Jul07
- `/usr/bin/python3 api.py --port 8000` — started Jul07
- `plc_vision_app.py` is NOT running by default — must be started manually
- Nothing listens on 8888 (trigger) or 8090 (mjpeg_relay) until started

## Useful commands
Start MJPEG relay for LEFT camera (view in any browser, lighter than full app):
```
cd ~/PiVisionCapture
python3 mjpeg_relay.py --rtsp "rtsp://root:pass@192.168.3.146/live1s1.sdp" --port 8090
# then open http://<pi-ip>:8090/ or http://localhost:8090/ on the Pi itself
```

Open a stream in a browser ON THE PI'S OWN DESKTOP (not remotely) — Chromium is at
`/usr/bin/chromium-browser`:
```
DISPLAY=:0 chromium-browser --new-window http://localhost:8090 &
```

Start the full vision app (trigger listener on :8888):
```
cd ~/PiVisionCapture
python3 plc_vision_app.py --no-plc
```
