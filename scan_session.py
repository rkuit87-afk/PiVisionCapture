"""
scan_session.py — Manual dual-camera bench scan session.

Standalone tool, separate from the production pipeline (main.py / camera_stream.py /
trigger_handler.py are untouched). Shows both camera feeds live side by side; SPACEBAR
captures the current frame from both cameras as one board, saved via storage.save_frame()
so the file format matches production exactly.

Usage:
  python scan_session.py --cam1 "rtsp://root:pass@169.254.9.152/live1s1.sdp" \
                          --cam2 "rtsp://root:pass@169.254.9.172/live1s1.sdp"

Controls:
  SPACEBAR - capture current frame from both cameras as the next board
  Q / ESC  - quit, prints total boards captured
"""

import argparse
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2

import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(threadName)-10.10s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class CameraReader:
    """Single-slot latest-frame reader for one camera, independent of camera_stream.py
    so multiple instances don't share global state."""

    def __init__(self, name: str, rtsp_url: str, reconnect_timeout: int = 5):
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
            return self._frame.copy() if self._frame is not None else None

    @property
    def connected(self):
        return self._connected

    def _reader_loop(self):
        while not self._stop.is_set():
            logger.info("[%s] connecting to %s", self.name, self.rtsp_url)
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

        logger.info("[%s] reader stopped", self.name)


def make_thumb(frame, label: str, connected: bool, target_h: int = 540):
    h, w = frame.shape[:2] if frame is not None else (target_h, int(target_h * 16 / 9))
    scale = target_h / h
    target_w = int(w * scale)
    if frame is not None:
        thumb = cv2.resize(frame, (target_w, target_h))
    else:
        import numpy as np
        thumb = np.zeros((target_h, target_w, 3), dtype="uint8")
        cv2.putText(thumb, "NO FRAME", (20, target_h // 2), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (0, 0, 255), 2)

    status = "LIVE" if connected else "RECONNECTING"
    color = (0, 200, 0) if connected else (0, 0, 255)
    cv2.putText(thumb, f"{label} [{status}]", (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                0.8, color, 2)
    return thumb


def main():
    parser = argparse.ArgumentParser(description="Dual-camera manual bench scan session")
    parser.add_argument("--cam1", required=True, help="RTSP URL for camera 1 (e.g. left end)")
    parser.add_argument("--cam2", required=True, help="RTSP URL for camera 2 (e.g. right end)")
    parser.add_argument("--cam1-name", default="cam1")
    parser.add_argument("--cam2-name", default="cam2")
    parser.add_argument("--base-path", default="./captures")
    parser.add_argument("--jpg-quality", type=int, default=95)
    parser.add_argument("--start-num", type=int, default=1, help="First board number this session")
    args = parser.parse_args()

    session_date = datetime.now().strftime("%Y-%m-%d")
    base_path = str(Path(args.base_path) / f"bench_scan_{session_date}")

    cam1 = CameraReader(args.cam1_name, args.cam1).start()
    cam2 = CameraReader(args.cam2_name, args.cam2).start()

    board_num = args.start_num
    captured_count = 0

    window = "Bench Scan — SPACE=capture  Q=quit"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)

    logger.info("Ready. SPACEBAR to capture board_%04d, Q to quit.", board_num)

    try:
        while True:
            f1 = cam1.get_latest_frame()
            f2 = cam2.get_latest_frame()

            t1 = make_thumb(f1, args.cam1_name, cam1.connected)
            t2 = make_thumb(f2, args.cam2_name, cam2.connected)
            combined = cv2.hconcat([t1, t2])
            cv2.putText(combined, f"Boards captured: {captured_count}  (next: board_{board_num:04d})",
                        (10, combined.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)
            cv2.imshow(window, combined)

            key = cv2.waitKey(30) & 0xFF

            if key == ord("q") or key == 27:
                break

            elif key == ord(" "):
                ts = datetime.now()
                board_id = f"board_{board_num:04d}"
                any_saved = False

                if f1 is not None:
                    storage.save_frame(f1, ts, f"{board_id}_{args.cam1_name}", base_path,
                                        args.jpg_quality, args.cam1)
                    any_saved = True
                else:
                    logger.warning("[SCAN] %s: no frame available from %s", board_id, args.cam1_name)

                if f2 is not None:
                    storage.save_frame(f2, ts, f"{board_id}_{args.cam2_name}", base_path,
                                        args.jpg_quality, args.cam2)
                    any_saved = True
                else:
                    logger.warning("[SCAN] %s: no frame available from %s", board_id, args.cam2_name)

                if any_saved:
                    logger.info("[SCAN] %s captured", board_id)
                    captured_count += 1
                    board_num += 1
                else:
                    logger.error("[SCAN] %s skipped — neither camera had a frame", board_id)

    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Shutting down. Total boards captured this session: %d", captured_count)
        cam1.stop()
        cam2.stop()
        cv2.destroyAllWindows()
        time.sleep(0.3)


if __name__ == "__main__":
    main()
