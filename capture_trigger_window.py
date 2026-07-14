#!/usr/bin/env python3
"""capture_trigger_window.py — timestamp-aligned L/R snapshot over a bTrigger window.

The line never actually stops; DB1.bTrigger marks a virtual "in position"
window while the board keeps moving. Both camera feeds are buffered
continuously (JPEG-encoded, time-pruned — NOT full-res in memory) from the
bTrigger RISING edge to the FALLING edge. Once the window closes, we pick
the LEFT/RIGHT frame pair whose timestamps are closest to each other,
instead of grabbing a fresh frame from a cold RTSP connection per camera
(which adds real connection-setup latency and skews LEFT vs RIGHT).

Read-only on the PLC — only reads bTrigger, never writes.

Usage:
  python capture_trigger_window.py [--out captures/alignment_check]
"""

import argparse
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml

from plc_exchange import PlcExchange

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)


class BufferedReader:
    """Continuously reads an RTSP stream, keeping a time-pruned JPEG history
    (small memory footprint) instead of raw frames, so it can safely buffer
    tens of seconds without exhausting RAM."""

    def __init__(self, name: str, rtsp_url: str, max_seconds: float = 45.0,
                jpeg_quality: int = 90, reconnect_delay_s: float = 3.0):
        self.name = name
        self.rtsp_url = rtsp_url
        self.max_seconds = max_seconds
        self.jpeg_quality = jpeg_quality
        self.reconnect_delay_s = reconnect_delay_s
        self._history = deque()  # (jpg_bytes, ts)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.connected = False
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"cam-{name}")

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            logger.info("[%s] connecting to %s", self.name, self.rtsp_url)
            cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                logger.warning("[%s] failed to open — retrying in %ds", self.name, self.reconnect_delay_s)
                self.connected = False
                time.sleep(self.reconnect_delay_s)
                continue
            logger.info("[%s] connected", self.name)
            self.connected = True
            try:
                while not self._stop.is_set():
                    ok, frame = cap.read()
                    ts = time.time()
                    if not ok:
                        logger.warning("[%s] stream lost — reconnecting", self.name)
                        break
                    ok2, buf = cv2.imencode(".jpg", frame,
                                            [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
                    if not ok2:
                        continue
                    with self._lock:
                        self._history.append((buf.tobytes(), ts))
                        cutoff = ts - self.max_seconds
                        while self._history and self._history[0][1] < cutoff:
                            self._history.popleft()
            finally:
                self.connected = False
                cap.release()
            if not self._stop.is_set():
                time.sleep(self.reconnect_delay_s)

    def get_window(self, t0: float, t1: float):
        """Decode and return (frame, ts) pairs with t0 <= ts <= t1."""
        with self._lock:
            snapshot = [(b, ts) for b, ts in self._history if t0 <= ts <= t1]
        out = []
        for b, ts in snapshot:
            arr = np.frombuffer(b, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is not None:
                out.append((frame, ts))
        return out


def wait_for_edge(plc: PlcExchange, plc_cfg: dict, want_rising: bool, timeout_s: float, last_known=None):
    """Blocks until bTrigger transitions the requested way. Returns the
    wall-clock time.time() of the transition, or None on timeout."""
    last = plc.read_trigger() if last_known is None else last_known
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        try:
            now = plc.read_trigger()
        except Exception as exc:
            logger.warning("PLC read failed: %s — retrying", exc)
            time.sleep(plc_cfg.get("reconnect_delay_s", 3.0))
            plc.ensure_connected()
            continue
        edge = (not last and now) if want_rising else (last and not now)
        if edge:
            return time.time()
        last = now
        time.sleep(plc_cfg.get("poll_interval_s", 0.05))
    return None


def main():
    parser = argparse.ArgumentParser(description="Timestamp-aligned L/R snapshot over a bTrigger window")
    parser.add_argument("--out", default="captures/alignment_check")
    parser.add_argument("--config", default="vision_host.yaml")
    parser.add_argument("--rise-timeout", type=float, default=180.0,
                        help="Give up if no rising edge within this many seconds")
    parser.add_argument("--max-window-s", type=float, default=45.0,
                        help="Safety cap on how long to buffer after the rising edge")
    parser.add_argument("--delay-s", type=float, default=0.0,
                        help="Sample the pair closest to (rising_edge_ts + delay_s) instead "
                             "of the closest-matched pair at the start of the window. Lets the "
                             "board travel further before the frame is taken, without touching "
                             "the PLC trigger timing.")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    plc_cfg = cfg["plc"]
    cam_cfg = cfg["cameras"]
    left_url = os.environ.get("CAM_LEFT_RTSP_URL", cam_cfg["left_rtsp"])
    right_url = os.environ.get("CAM_RIGHT_RTSP_URL", cam_cfg["right_rtsp"])

    plc = PlcExchange(plc_cfg["ip"], plc_cfg["rack"], plc_cfg["slot"],
                      db_number=plc_cfg["db_number"],
                      reconnect_delay_s=plc_cfg.get("reconnect_delay_s", 3.0))

    logger.info("Connecting to PLC %s DB%d ...", plc_cfg["ip"], plc_cfg["db_number"])
    if not plc.ensure_connected():
        logger.error("Could not connect to PLC — aborting")
        return

    logger.info("Starting camera readers (continuous buffering, JPEG history)...")
    left = BufferedReader("left", left_url, max_seconds=args.max_window_s + 5).start()
    right = BufferedReader("right", right_url, max_seconds=args.max_window_s + 5).start()

    wait_start = time.time()
    while (not left.connected or not right.connected) and time.time() - wait_start < 15:
        time.sleep(0.2)
    if not left.connected or not right.connected:
        logger.warning("One or both cameras not yet connected (left=%s right=%s) — continuing anyway",
                       left.connected, right.connected)

    logger.info("Watching DB1.bTrigger for rising edge (timeout %.0fs)...", args.rise_timeout)
    rise_ts = wait_for_edge(plc, plc_cfg, want_rising=True, timeout_s=args.rise_timeout)
    if rise_ts is None:
        logger.error("No rising edge seen within %.0fs — nothing captured", args.rise_timeout)
        left.stop(); right.stop(); plc.disconnect()
        return
    logger.info("Rising edge at %.3f — buffering both cameras", rise_ts)

    logger.info("Watching for falling edge (max window %.0fs)...", args.max_window_s)
    fall_ts = wait_for_edge(plc, plc_cfg, want_rising=False, timeout_s=args.max_window_s, last_known=True)
    if fall_ts is None:
        fall_ts = time.time()
        logger.warning("No falling edge within %.0fs — closing window anyway at %.3f",
                       args.max_window_s, fall_ts)
    else:
        logger.info("Falling edge at %.3f — window closed (%.1fs)", fall_ts, fall_ts - rise_ts)

    target_ts = rise_ts + args.delay_s
    window_end = max(fall_ts, target_ts) + 0.2
    if target_ts > time.time():
        wait_s = target_ts + 0.2 - time.time()
        logger.info("Delay requested (%.0f ms) — keeping buffers alive %.2fs longer", args.delay_s * 1000, wait_s)
        time.sleep(wait_s)

    left_hist = left.get_window(rise_ts, window_end)
    right_hist = right.get_window(rise_ts, window_end)
    left.stop(); right.stop()

    logger.info("Buffered in window: LEFT=%d frames  RIGHT=%d frames", len(left_hist), len(right_hist))
    if not left_hist or not right_hist:
        logger.error("No buffered frames in window for one or both cameras — "
                     "window may be shorter than a camera's keyframe interval")
        plc.disconnect()
        return

    if args.delay_s > 0:
        lf, lts = min(left_hist, key=lambda ft: abs(ft[1] - target_ts))
        rf, rts = min(right_hist, key=lambda ft: abs(ft[1] - target_ts))
        logger.info("Delay-targeted sample: target=%.3f (rise+%.0fms)  LEFT t=%.3f (%.0fms off)  "
                    "RIGHT t=%.3f (%.0fms off)  L/R dt=%.1f ms",
                    target_ts, args.delay_s * 1000, lts, (lts - target_ts) * 1000,
                    rts, (rts - target_ts) * 1000, abs(lts - rts) * 1000)
    else:
        best_pair = None
        best_dt = float("inf")
        for lf, lts in left_hist:
            for rf, rts in right_hist:
                dt = abs(lts - rts)
                if dt < best_dt:
                    best_dt = dt
                    best_pair = (lf, lts, rf, rts)
        lf, lts, rf, rts = best_pair
        logger.info("Best timestamp match: LEFT t=%.3f  RIGHT t=%.3f  dt=%.1f ms", lts, rts, best_dt * 1000)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    left_path = out_dir / f"LEFT_{stamp}.jpg"
    right_path = out_dir / f"RIGHT_{stamp}.jpg"
    cv2.imwrite(str(left_path), lf)
    cv2.imwrite(str(right_path), rf)
    logger.info("Saved %s", left_path)
    logger.info("Saved %s", right_path)

    plc.disconnect()
    logger.info("Done.")


if __name__ == "__main__":
    main()
