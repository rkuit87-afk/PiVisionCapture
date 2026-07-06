# GEMINI TASK — Deploy Pi Vision Capture to the Raspberry Pi

**Project location (dev machine):** `C:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture\`

## Status — read this first

The scaffold from `GEMINI_Task_Scaffold.md` is complete and has been verified working on the
Windows dev machine:

- `config.yaml`'s `camera.rtsp_url` is now correct: `rtsp://root:Altdanjosh%404878@169.254.9.152/live1s1.sdp`
  (the original `/live.sdp` path was wrong — 404 from the camera. The real RTSP access name,
  confirmed via the camera's `getparam.cgi?network_rtsp`, is `live1s1.sdp`.)
- End-to-end smoke test passed: camera thread connects, `POST /trigger` queues a frame,
  `storage.py` writes `board_<ts>.jpg` + `.json` under `captures/<date>/<board_id>/`.
- Architecture decision confirmed with the customer: the board moves **continuously** through
  the trimmer saw with **no dwell/pause**, so the always-on RTSP buffer in `camera_stream.py`
  (single-slot, overwrite-on-new-frame) is the right approach — do NOT replace it with a
  snapshot-per-trigger HTTP call, latency would risk missing/blurring the shot.

**Your job now:** get this running as a persistent, unattended service on the actual Raspberry
Pi, not just the PC test version.

---

## Context

- Hardware: Raspberry Pi 4/5, 64-bit Raspberry Pi OS (Bookworm)
- Camera: Vivotek IB9369, reachable at `169.254.9.152` (link-local — confirm the Pi and camera
  are on the same subnet/segment once wired on site)
- The Pi must run headless — `main.py` currently has a `cv2.imshow` live-preview loop marked
  "PC only — remove on Pi if headless" (main.py:72). Strip that on the Pi deployment; keep the
  SPACEBAR/imshow path only for the Windows dev copy.
- No ML, no web UI, no database — capture + storage only, same constraints as the scaffold task.

## What to do

1. **Provision the Pi**
   - Raspberry Pi OS 64-bit, headless (SSH enabled)
   - Install Python 3, `pip install -r requirements.txt` (opencv-python, pyyaml) — note OpenCV
     wheel install on Pi may need `libgl1`/`libglib2.0-0` system packages; document whatever you
     actually needed
2. **Deploy the code**
   - Copy the 5 project files to the Pi (e.g. `/home/pi/pivision/`)
   - Create a **headless variant of `main.py`** (or a `--headless` flag) that skips `cv2.imshow`/
     `cv2.waitKey`/the SPACEBAR path entirely and just blocks on `threading.Event` per the
     original spec's shutdown design — don't touch `camera_stream.py`, `trigger_handler.py`, or
     `storage.py`, they're already headless-safe
   - Confirm `config.yaml` on the Pi points at the camera's real RTSP URL (same
     `live1s1.sdp` path — verify it resolves from the Pi's network position, not just the dev PC)
3. **Run as a persistent service**
   - Add a `systemd` unit (e.g. `pivision.service`) that runs `python3 main.py --config config.yaml`
     on boot, restarts on failure, logs to journal
   - Confirm `GET http://<pi-ip>:8888/health` responds after a fresh boot with no manual steps
4. **Verify on site**
   - `POST http://<pi-ip>:8888/trigger` with `{"board_id": "PITEST01"}` from another machine on
     the network produces `PITEST01/board_<ts>.jpg` + `.json` under the Pi's `base_path`
   - Confirm reconnect behavior: briefly kill the camera connection (or unplug/replug) and confirm
     `camera_stream.py` logs the retry and recovers without restarting the service

## Hard constraints (same as scaffold task)

- No GPIO — trigger stays HTTP-only, PLC will POST to `/trigger`
- No web UI, no database, no ML, no Flask, no SQLite
- RTSP buffer stays single-slot, overwrite-on-new-frame
- All logging via Python `logging` at INFO, not `print`
- Don't change `camera_stream.py`, `trigger_handler.py`, or `storage.py`'s public behavior —
  only add the headless entrypoint and deployment plumbing (systemd unit, provisioning notes)

## Definition of Done

- `systemctl status pivision` shows active/running after a fresh Pi reboot with no manual
  intervention
- `GET http://<pi-ip>:8888/health` → `{"status": "ok"}` from a machine on the same network
- `POST http://<pi-ip>:8888/trigger` produces a real jpg+json pair on the Pi's disk within a
  couple seconds
- Reconnect-on-drop verified once, live, with the actual camera

---

## Handoff to Claude Code (write this when you're done)

When you're finished, append a `## Gemini Handoff — Pi Deploy` section to this file (or a new
`HANDOFF.md` in the project root — your call) covering:

- Exact steps you took to provision the Pi (OS version, system packages installed, any gotchas)
- Final `systemd` unit file content and its install location
- The Pi's IP/hostname on the shop network, and the camera's confirmed reachability from the Pi
- Any deviation from this task doc and why
- Open issues / things you couldn't verify on site (e.g. if you didn't have physical PLC access)

Once that's in place, Claude Code will pick up:
- Wiring the actual PLC → Pi trigger call (TIA Portal HTTP client block vs Modbus TCP poll —
  method still TBD, Roelof to confirm)
- A minimal manual-grading web UI (list last N captures, assign grade/defect tags)
- Tying capture metadata into JustAutomate project records if required
