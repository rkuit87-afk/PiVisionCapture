# GEMINI TASK — Scaffold Pi Vision Capture for Trimmer Fishtail Detection

**Project location:** `C:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture\`
(New standalone project — NOT inside JustAutomate)

**Your job:** Write the full scaffold exactly as specified below. No ML, no web UI,
no database. Files only. Every module must be runnable and logged.

---

## Context

- Hardware: Raspberry Pi 4/5, 64-bit Raspberry Pi OS
- Camera: Vivotek IB9369 IP camera (2MP, 1920×1080), RTSP stream
- Goal: Capture board images as each board passes the trimmer saw, store to disk
  for manual grading proof-of-concept
- PLC trigger: **PLC communicates to Pi over the network** (no GPIO wiring).
  The Pi exposes an HTTP endpoint; the TIA Portal PLC hits it when a board is in frame.
  Exact PLC-side method (HTTP client block or Modbus TCP) is TBD — Pi side is always HTTP.
- No ML inference yet — capture + storage only

---

## Files to Create

### `config.yaml`
```yaml
camera:
  rtsp_url: "rtsp://user:pass@192.168.x.x:554/live.sdp"
  reconnect_timeout: 5    # seconds before reconnect attempt

trigger:
  http_port: 8888         # Pi listens here; PLC POSTs to /trigger

storage:
  base_path: "/data/captures"
  jpg_quality: 95
```

### `camera_stream.py`
- Connect to `config.camera.rtsp_url` via OpenCV RTSP
- Run in a background daemon thread
- Keep only the **latest frame** (single-slot buffer — overwrite, never queue frames)
- On connection drop: log the error, sleep `reconnect_timeout` seconds, retry indefinitely
- Expose `get_latest_frame() -> np.ndarray | None`

### `trigger_handler.py`
- Start a minimal HTTP server (`http.server.BaseHTTPRequestHandler`) on `config.trigger.http_port`
- Accept `POST /trigger`
  - Optional JSON body: `{"board_id": "B123"}` — use if present, default to `"unknown"`
  - Grab `get_latest_frame()`, enqueue `(frame, board_id, datetime.now())`
  - Respond `200 OK` with `{"status": "queued", "timestamp": "<iso>"}`
  - Log: `"[TRIGGER] POST /trigger — board_id={board_id} at {timestamp}"`
- Accept `GET /health` — respond `200 OK {"status": "ok"}` (useful for PLC watchdog)
- Run server in a daemon thread; expose the queue for the storage thread to consume

### `storage.py`
- `save_frame(frame: np.ndarray, timestamp: datetime, board_id: str = "unknown")`
- Create directory: `{base_path}/{YYYY-MM-DD}/{board_id}/` (mkdir -p, handle existing)
- Image file: `board_{timestamp_iso}.jpg` (JPEG at `config.storage.jpg_quality`)
  - Sanitise timestamp for filename: replace `:` with `-`, drop microseconds
- Sidecar JSON: `board_{timestamp_iso}.json`
  ```json
  {
    "timestamp": "2026-07-03T14:22:15.123456",
    "board_id": "B123",
    "camera_rtsp": "rtsp://...",
    "trigger_source": "http",
    "frame_shape": [1080, 1920, 3]
  }
  ```
- Log: `"[STORAGE] Saved {filepath}"`
- Run in a daemon thread consuming the trigger queue (blocking `queue.get()` with timeout)

### `main.py`
```
Usage:
  python main.py [--config config.yaml]

Startup sequence:
  1. Load config.yaml (argparse --config, default "config.yaml")
  2. Start camera thread   → log "Camera thread started, connecting to {rtsp_url}"
  3. Start trigger server  → log "Trigger server listening on port {http_port}"
  4. Start storage thread  → log "Storage thread started, base_path={base_path}"
  5. Log "Ready. Waiting for PLC trigger..."
  6. Block forever (signal.pause() or threading.Event.wait())

On KeyboardInterrupt / SIGTERM:
  Log "Shutting down gracefully..."
  Set stop event, join threads with timeout
```

### `requirements.txt`
```
opencv-python>=4.8
pyyaml>=6.0
```
*(stdlib only for HTTP server and threading — no extra packages needed)*

---

## Hard Constraints

- Create every file in `C:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture\`
- **No GPIO** — trigger is always network/HTTP
- No web UI, no database, no ML, no Flask, no SQLite
- RTSP buffer is **single-slot, overwrite-on-new-frame** — never accumulate
- HTTP server must handle concurrent requests safely (use `ThreadingMixIn`)
- All logging via Python `logging` module at INFO level, not `print`
- `base_path` directory is created at startup if it does not exist

## Definition of Done

- `python main.py --config config.yaml` starts without errors (camera connect failure is fine — log and retry)
- `GET http://localhost:8888/health` returns `{"status": "ok"}`
- `POST http://localhost:8888/trigger` with body `{"board_id": "TEST01"}` returns `{"status": "queued", ...}` and produces `TEST01/board_<timestamp>.jpg` + `.json` under `base_path`
- All five files importable without syntax errors on a Windows dev machine

---

## Handoff to Claude Code (after scaffold is done)

Once scaffolded and the HTTP trigger is confirmed working:
- Claude Code will wire the specific PLC communication method (TIA Portal HTTP client block vs Modbus TCP poll — Roelof to confirm)
- Add a minimal manual grading UI (web page: show last N captures, assign grade/defect tags)
- Integrate capture metadata with JustAutomate project records if required
- Test with live IB9369 camera + Trimmer PLC trigger on site
