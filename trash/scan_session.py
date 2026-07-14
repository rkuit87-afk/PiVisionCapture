"""
scan_session.py — Manual dual-camera bench scan session.

Standalone tool, separate from the production pipeline (main.py / camera_stream.py /
trigger_handler.py are untouched). Shows monitor camera feed live; press 'C' key
captures the current frame from capture camera as the next board, saved via storage.save_frame()
so the file format matches production exactly.

Usage:
  python scan_session.py --cam-monitor "rtsp://root:pass@192.168.3.146/live1s1.sdp" \
                          --cam-capture "rtsp://root:pass@192.168.3.145/live1s1.sdp"

Controls:
  C key - capture current frame from capture camera as the next board
  Q / ESC - quit, prints total boards captured
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


def make_thumb(frame, label: str, connected: bool, target_h: int = 360):
    """Creates a labeled thumbnail for one camera feed."""
    import numpy as np
    h, w = frame.shape[:2] if frame is not None else (target_h, int(target_h * 16 / 9))
    scale = target_h / h
    target_w = int(w * scale)
    if frame is not None:
        thumb = cv2.resize(frame, (target_w, target_h))
    else:
        thumb = np.zeros((target_h, target_w, 3), dtype="uint8")
        cv2.putText(thumb, "NO FRAME", (20, target_h // 2), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (0, 0, 255), 2)

    status = "LIVE" if connected else "RECONNECTING"
    color = (0, 200, 0) if connected else (0, 0, 255)
    cv2.rectangle(thumb, (0, 0), (thumb.shape[1], 40), (0,0,0), -1)
    cv2.putText(thumb, f"{label} [{status}]", (10, 28), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, color, 2)
    return thumb

def add_hud(frame, board_num: int, captured_count: int):
    """Adds help text overlay to the combined view."""
    cv2.rectangle(frame, (0, frame.shape[0] - 50), (frame.shape[1], frame.shape[0]), (0,0,0), -1)
    cv2.putText(thumb, f"Boards captured: {captured_count}  (next: board_{board_num:04d})",
                (10, frame.shape[0] - 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
    cv2.putText(thumb, "Press C to capture  Q to quit",
                (10, frame.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)


def main():
    parser = argparse.ArgumentParser(description="Dual-camera manual bench scan session")
    parser.add_argument("--cam-monitor", required=True, help="RTSP URL for monitor camera (e.g. left, shows position)")
    parser.add_argument("--cam-capture", required=True, help="RTSP URL for capture camera (e.g. right, snapped on SPACEBAR)")
    parser.add_argument("--monitor-name", default="monitor")
    parser.add_argument("--capture-name", default="capture")
    parser.add_argument("--base-path", default="./captures")
    parser.add_argument("--jpg-quality", type=int, default=95)
    parser.add_argument("--start-num", type=int, default=1, help="First board number this session")
    args = parser.parse_args()

    session_date = datetime.now().strftime("%Y-%m-%d")
    base_path = str(Path(args.base_path) / f"bench_scan_{session_date}")

    monitor = CameraReader(args.monitor_name, args.cam_monitor).start()
    capture = CameraReader(args.capture_name, args.cam_capture).start()

    board_num = args.start_num
    captured_count = 0

    window = "Bench Scan — CLICK or Press C to capture  Q to quit"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, 1920, 540)

    logger.info("Ready. Monitoring %s. CLICK image or press C to capture for board_%04d, Q to quit.",
                args.monitor_name, board_num)

    def on_mouse(event, x, y, flags, param):
        nonlocal board_num, captured_count
        if event == cv2.EVENT_LBUTTONDOWN:
            ts = datetime.now()
            board_id = f"board_{board_num:04d}"
            logger.info("[SCAN] CLICK detected for %s", board_id)
            f_capture = capture.get_latest_frame()

            if f_capture is not None:
                try:
                    storage.save_frame(f_capture, ts, board_id, base_path,
                                        args.jpg_quality, args.cam_capture)
                    logger.info("[SCAN] ✓ %s captured from %s", board_id, args.capture_name)
                    captured_count += 1
                    board_num += 1
                except Exception as e:
                    logger.error("[SCAN] ✗ Failed to save %s: %s", board_id, e, exc_info=True)
            else:
                logger.warning("[SCAN] ✗ %s skipped — no frame available from %s", board_id, args.capture_name)

    cv2.setMouseCallback(window, on_mouse)

    try:
        while True:
            f_monitor = monitor.get_latest_frame()
            f_capture = capture.get_latest_frame()

            # Create side-by-side view
            thumb_h = 540
            t_monitor = make_thumb(f_monitor, f"LEFT: {args.monitor_name}", monitor.connected, target_h=thumb_h)
            t_capture = make_thumb(f_capture, f"RIGHT: {args.capture_name}", capture.connected, target_h=thumb_h)
            
            import numpy as np
            combined_view = np.hstack((t_monitor, t_capture))

            add_hud(combined_view, board_num, captured_count)

            cv2.imshow(window, combined_view)
            key = cv2.waitKey(30) & 0xFF

            if key == ord("q") or key == 27:
                break

            elif key == ord("c") or key == ord("C"):
                ts = datetime.now()
                board_id = f"board_{board_num:04d}"
                logger.info("[SCAN] KEY 'C' pressed for %s", board_id)
                f_capture = capture.get_latest_frame()

                if f_capture is not None:
                    try:
                        storage.save_frame(f_capture, ts, board_id, base_path,
                                            args.jpg_quality, args.cam_capture)
                        logger.info("[SCAN] ✓ %s captured from %s", board_id, args.capture_name)
                        captured_count += 1
                        board_num += 1
                    except Exception as e:
                        logger.error("[SCAN] ✗ Failed to save %s: %s", board_id, e, exc_info=True)
                else:
                    logger.warning("[SCAN] ✗ %s skipped — no frame available from %s", board_id, args.capture_name)

    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Shutting down. Total boards captured this session: %d", captured_count)
        monitor.stop()
        capture.stop()
        cv2.destroyAllWindows()
        time.sleep(0.3)


if __name__ == "__main__":
    main()
