# Morning Setup — Vision Host POC (2026-07-12)

## What changed overnight (TL;DR)

The Pi is OUT of the measurement loop. The new **vision host** app runs on the
engineering PC (later: the server PC, unchanged) and does everything:

```
PLC bTrigger (DB10, via snap7)  ->  grab LEFT+RIGHT camera frames (RTSP)
    ->  measure (background-subtract presence, width @ 0.9 line, length ->
        standard saw)  ->  write wSawWord/iLengthMM/iWidthMM back to DB10
```

New files: `vision_host_app.py`, `vision_host.yaml`, `plc_sim_tool.py`,
`calibrate_from_lines.py`, rebuilt `dual_camera_measure.py`.

**Proven live tonight** (RIGHT camera + real positioned board):
presence BOARD, saw word `0x0081` (datum + 4.8 m), full trigger->re-arm
handshake cycle in simulation. What remains is calibration + the PLC side.

The Pi's GPIO trigger service is stopped AND disabled — the physical sensor
moves to a PLC input; the PLC sets bTrigger in DB10.

---

## Checklist (in order)

### 1. Physical
- [ ] Plug LEFT camera back into the mill switch — it must answer at
      `192.168.3.146` (it was unplugged all of yesterday; RIGHT `.145` is fine).
- [ ] Wire the board-in-position sensor to a PLC input (replaces Pi GPIO 17;
      the noisy trigger line to the Pi is retired for good).
- [ ] This PC needs its static IP (survives reboot only if re-added):
      `New-NetIPAddress -InterfaceAlias "Ethernet" -IPAddress 192.168.3.148 -PrefixLength 24`
      (admin PowerShell; skip if `ping 192.168.3.151` already answers)

### 2. TIA Portal (the ONE blocker found overnight)
`db_read` fails with S7 error 0x81/0x04 — the classic signature of PUT/GET
not active (TCP connect succeeding proves nothing, I was wrong about that
earlier). Do all three:
- [ ] CPU Properties -> Protection & Security -> Connection mechanisms ->
      **check "Permit access with PUT/GET communication from remote partner"**
- [ ] Create **DB10 "VisionExchange"**, 18 bytes per `PLC_DB_LAYOUT.md`,
      and **uncheck "Optimized block access"** (DB Properties -> Attributes)
- [ ] Compile + **download hardware config AND the DB**, CPU back to RUN
- [ ] PLC program: map the new sensor input -> `DB10.DBX0.0` (bTrigger),
      and on `bResultValid` consume `wSawWord` then reset bTrigger
      (full handshake spec in `PLC_DB_LAYOUT.md`)

Verify from this PC (takes 5 s):
```
python plc_sim_tool.py status          # decodes all DB10 fields = PUT/GET + DB OK
```

### 3. Fresh empty references (30 seconds, do BEFORE boards run)
Shadows moved since the current refs (2026-07-10) — refresh with NO board:
```
python - << "EOF"
import cv2
for name, url in [("L", "rtsp://root:aLTDANJOSH%404878@192.168.3.146/live1s1.sdp"),
                  ("R", "rtsp://root:Altdanjosh%404878@192.168.3.145/live1s1.sdp")]:
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    ok, f = False, None
    for _ in range(5): ok, f = cap.read()
    cap.release()
    if ok: cv2.imwrite("D:/board_captures/empty_ref_%s.jpg" % name, f)
    print(name, "ok" if ok else "FAILED")
EOF
```
Then point `vision_host.yaml` -> `empty_ref_left/right` at these two files.

### 4. Marked-board calibration (your line idea — it's the right one)
Draw thick dark lines across the board face at known distances FROM THE
FENCE (tape measure, board seated against the fence). Include **860 mm**
(the 0.9 saw) for the LEFT view. 3-5 lines per view, ~1 m apart is fine.
Board in the normal stop position, then per camera:
```
python calibrate_from_lines.py --rtsp "rtsp://root:aLTDANJOSH%404878@192.168.3.146/live1s1.sdp" --mm 500 860 1500 2500 --save-debug D:/board_captures/calib_L_debug.jpg
python calibrate_from_lines.py --rtsp "rtsp://root:Altdanjosh%404878@192.168.3.145/live1s1.sdp" --mm 4000 5000 6000    --save-debug D:/board_captures/calib_R_debug.jpg
```
It prints the exact `vision_host.yaml` values:
- LEFT:  `px_per_mm_left`, `width_line_px_left`, `board_y_range_left`
- RIGHT: `px_per_mm_right`, `right_view_x0_mm` (the printed `view_x0_mm`),
         `board_y_range_right`
Aim for residuals < 3 px; check the debug jpgs that lines were found right.

### 5. If boards are blown-out white (they were on 07-10)
Drop exposure on the cameras (Vivotek web UI: Media -> Image -> Exposure,
lower exposure level / enable WDR) with a board in view until grain is
visible instead of clipped white. Better pixels beat clever code.

### 6. Run
```
cd C:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture
python vision_host_app.py                 # live: waits on DB10 bTrigger
```
No PLC program logic yet? Drive the handshake yourself from a 2nd terminal:
```
python plc_sim_tool.py trigger --width 114    # acts as the PLC (sets bTrigger)
python plc_sim_tool.py status                 # see wSawWord/length/width land
python plc_sim_tool.py clear                  # completes handshake, app re-arms
```
Offline sanity (no PLC, no cameras):
```
python vision_host_app.py --no-plc --replay <L.jpg> <R.jpg>    # Enter = trigger
```

---

## Open decisions (need your call, not blocking)
1. **Saw word semantics**: app sets exactly TWO bits (datum + standard saw),
   per PLC_DB_LAYOUT.md. But the 07-09 grading JSON sometimes dropped BOTH
   6.0 and 6.6 past the wood end. If the PLC wants "all saws beyond the far
   end also drop", say so — one-line change.
2. **WIDTH RULE**: boards < 114 mm skip the origin (0.0) trim per the grading
   tool notes. Currently NOT enforced (saw 0 always drops). Confirm and I
   wire it in.
3. **Fishtail**: detection present but skipped when overexposure prevents a
   clean blob; after the exposure fix it activates by itself. Tear-out still
   stubbed by design.

## Status of yesterday's kit
- Pi: `pivision-gpio-trigger` stopped + disabled (survives reboot). The REST
  API service still runs (harmless). Pi eth1 (192.168.3.147) unplugged and
  now unnecessary — leave or repurpose.
- PLC CPU `192.168.3.151`: reachable, S7 connect OK. ET200 `192.168.3.152`:
  reachable, PROFINET to CPU (no direct connection needed).
- Hardware map + credentials: `PI_CONNECTION.md`.
