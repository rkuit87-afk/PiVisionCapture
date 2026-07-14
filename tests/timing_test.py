"""
timing_test.py — Poll both cameras at a fast fixed rate for a fixed duration
and save every frame from both, so a run can be reviewed/graded afterwards
to see how many boards passed and how quickly.

No PLC/GPIO trigger required — this is a brute-force interval capture used
because the hardware trigger isn't wired up yet. Uses persistent RTSP
connections (not reconnect-per-frame) so it can keep up with a fast line.

Usage (run ON the Pi, cameras are link-local to its adapter):
  python3 timing_test.py --duration 60 --interval 0.3

Output:
  ~/PiVisionCapture/captures/timing_test_<YYYY-MM-DD_HHMMSS>/
    left_0001.jpg  right_0001.jpg
    left_0002.jpg  right_0002.jpg
    ...
    manifest.json   (per-frame timestamps, elapsed time, connection status)
"""

import argparse
import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(threadName)-10.10s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class CameraReader:
    """Non-blocking camera frame reader (persistent connection)."""

    def __init__(self, name: str, rtsp_url: str, reconnect_timeout: int = 3):
        self.name = name
        self.rtsp_url = rtsp_url
        self.reconnect_timeout = reconnect_timeout
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._connected = False
        self._thread = threading.Thread(target=self._reader_loop, daemon=True, name=f"cam-{name}")

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def get_latest_frame(self):
        with self._lock:
            return (self._frame.copy(), self._connected) if self._frame is not None else (None, self._connected)

    @property
    def connected(self):
        return self._connected

    def _reader_loop(self):
        while not self._stop.is_set():
            logger.info("[%s] connecting...", self.name)
            cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                logger.warning("[%s] failed to open — retrying in %ds", self.name, self.reconnect_timeout)
                self._connected = False
                time.sleep(self.reconnect_timeout)
                continue

            logger.info("[%s] connected", self.name)
            self._connected = True
            try:
                while not self._stop.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        logger.warning("[%s] stream lost — reconnecting", self.name)
                        break
                    with self._lock:
                        self._frame = frame
            finally:
                self._connected = False
                cap.release()

            if not self._stop.is_set():
                time.sleep(self.reconnect_timeout)


def main():
    parser = argparse.ArgumentParser(description="Timed dual-camera polling capture")
    parser.add_argument("--duration", type=float, default=60.0, help="Total seconds to run")
    parser.add_argument("--interval", type=float, default=0.3, help="Seconds between saved frame pairs")
    parser.add_argument("--left-rtsp", default=os.environ.get("CAM_LEFT_RTSP_URL", ""))
    parser.add_argument("--right-rtsp", default=os.environ.get("CAM_RIGHT_RTSP_URL", ""))
    parser.add_argument("--base-path", default=str(Path.home() / "PiVisionCapture" / "captures"))
    parser.add_argument("--jpg-quality", type=int, default=90)
    args = parser.parse_args()

    if not args.left_rtsp or not args.right_rtsp:
        logger.error("Missing RTSP URL(s). Set CAM_LEFT_RTSP_URL / CAM_RIGHT_RTSP_URL env vars "
                     "or pass --left-rtsp/--right-rtsp.")
        return 1

    session_name = f"timing_test_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    out_dir = Path(args.base_path) / session_name
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Session dir: %s", out_dir)
    logger.info("Duration=%.0fs interval=%.2fs (~%d frame pairs expected)",
                args.duration, args.interval, int(args.duration / args.interval))

    left_cam = CameraReader("left", args.left_rtsp).start()
    right_cam = CameraReader("right", args.right_rtsp).start()

    logger.info("Warming up connections (3s)...")
    time.sleep(3.0)

    manifest = []
    frame_num = 0
    start = time.time()

    try:
        while (time.time() - start) < args.duration:
            loop_start = time.time()
            frame_num += 1
            ts = datetime.now()
            elapsed = loop_start - start

            left_frame, left_ok = left_cam.get_latest_frame()
            right_frame, right_ok = right_cam.get_latest_frame()

            left_name = f"left_{frame_num:04d}.jpg"
            right_name = f"right_{frame_num:04d}.jpg"

            if left_frame is not None:
                cv2.imwrite(str(out_dir / left_name), left_frame, [cv2.IMWRITE_JPEG_QUALITY, args.jpg_quality])
            if right_frame is not None:
                cv2.imwrite(str(out_dir / right_name), right_frame, [cv2.IMWRITE_JPEG_QUALITY, args.jpg_quality])

            manifest.append({
                "frame_num": frame_num,
                "elapsed_s": round(elapsed, 3),
                "timestamp": ts.isoformat(),
                "left_file": left_name if left_frame is not None else None,
                "right_file": right_name if right_frame is not None else None,
                "left_connected": left_ok,
                "right_connected": right_ok,
            })

            if frame_num % 10 == 0:
                logger.info("Frame %d  t=%.1fs  left_ok=%s right_ok=%s",
                           frame_num, elapsed, left_ok, right_ok)

            sleep_left = args.interval - (time.time() - loop_start)
            if sleep_left > 0:
                time.sleep(sleep_left)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        left_cam.stop()
        right_cam.stop()

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps({
        "session": session_name,
        "duration_s": args.duration,
        "interval_s": args.interval,
        "frame_pairs": frame_num,
        "frames": manifest,
    }, indent=2), encoding="utf-8")

    logger.info("Done. %d frame pairs saved to %s", frame_num, out_dir)
    logger.info("Manifest: %s", manifest_path)
    print(f"\nSESSION_DIR={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
