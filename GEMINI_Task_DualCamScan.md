# GEMINI TASK — Dual-Camera Manual Scan Session (bench rehearsal before field mount)

**Project location:** `C:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture\`

## Context

Today's goal is a full rehearsal on the bench of the workflow we'll repeat at the trimmer:
connect both cameras, confirm they're both live, then manually capture ~100 boards with a
spacebar trigger so we have a dataset to grade later. The point of doing this here first is to
make sure the whole connect → verify → capture cycle is solid *before* anyone is up a ladder at
the actual infeed — nothing here should require being on-site to debug.

Two Vivotek IB9369 cameras are already on the network:
- `169.254.9.152` — user `root`, password `Altdanjosh@4878`
- `169.254.9.172` — user `root`, password `aLTDANJOSH@4878` (yes, that odd casing is correct —
  caps lock was on when it was set)

Both use RTSP path `live1s1.sdp` (confirmed working pattern: `rtsp://root:<password>@<ip>/live1s1.sdp`).

**Important:** do not modify `main.py`, `camera_stream.py`, `trigger_handler.py`, or `storage.py`.
Production headless behavior on those files is intentional (Pi deployment already relies on it).
This is a new, separate, throwaway-friendly script.

## What to build

### `scan_session.py` (new file, standalone)

- Connect to **both** cameras via OpenCV RTSP (`cv2.VideoCapture`, same pattern as
  `camera_stream.py`'s reader loop — background thread per camera, single-slot latest-frame
  buffer, auto-reconnect on drop, don't duplicate that logic verbatim, but the same approach)
- Show **both live feeds side by side** in one window (or two adjacent windows — whichever is
  simpler to get right), each labeled with its camera IP so it's obvious which is which
- On **SPACEBAR**: capture the current latest frame from *both* cameras at (as close to)
  the same instant as possible, and save both:
  - Reuse `storage.py`'s `save_frame()` function directly (import it) so the file format
    (jpg + JSON sidecar) matches production exactly — don't reimplement saving logic
  - Save under a **new subfolder** so this doesn't mix with production captures:
    `./captures/bench_scan_<today's date>/board_XXXX/` where `XXXX` is a zero-padded
    sequential number starting at `0001`, incrementing once per spacebar press (shared
    counter across both cameras — one board = one number, two images)
  - Each camera's image for that board gets a suffix so they don't collide, e.g.
    `board_0001_cam152.jpg` / `board_0001_cam152.json` and `board_0001_cam172.jpg` / `.json`
  - Log to console: `[SCAN] board_0001 captured (both cameras)` — or note if one camera's
    frame wasn't available (don't crash, just log a warning and save what you have)
- On **Q** or **ESC**: quit cleanly, print total boards captured this session
- On startup, print clear status for each camera as it connects (reuse the "connecting...
  connected" log style from `camera_stream.py`), so it's obvious at a glance both cameras are
  live before starting to capture — this is the "verify before mounting" check, make it visible
- Show a running counter on-screen (overlay text on the preview window) of how many boards have
  been captured so far this session, so the person at the keyboard doesn't have to track it
  manually while handling boards

## Hard constraints

- Standalone script — must not require or modify the production HTTP trigger pipeline
- No PLC, no HTTP server needed for this — pure local keypress-triggered capture
- Reuse `storage.py`'s save function for file format consistency; don't hand-roll a different
  JSON schema
- All console logging via Python `logging`, not bare `print`, matching the rest of the project's
  style
- Handle either camera being briefly unavailable (reconnect) without crashing the whole session
  — if we're going to trust this rehearsal, it needs to survive a camera hiccup gracefully, same
  as production does

## Definition of done

- Running `python scan_session.py` shows both camera feeds live, clearly labeled
- Pressing spacebar repeatedly produces sequentially-numbered board folders under
  `./captures/bench_scan_<date>/`, each with two jpg+json pairs (one per camera)
- Q/ESC exits cleanly and reports the total captured
- Can realistically run for ~100 consecutive captures without crashing or leaking memory/threads
