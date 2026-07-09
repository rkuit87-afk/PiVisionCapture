"""
board_alignment_test.py — Quick GPIO-triggered paired capture for alignment testing.

Captures exactly 2 boards (L + R paired) and saves with fixed names:
  L1.jpg, R1.jpg, L2.jpg, R2.jpg
Each run overwrites the previous test. Save to fixed location so you can
compare alignment across multiple attempts.

Usage:
  python board_alignment_test.py \
    --cam-left "rtsp://root:pass@169.254.9.172/live1s1.sdp" \
    --cam-right "rtsp://root:pass@169.254.9.152/live1s1.sdp"

Or rely on env vars (CAM_LEFT_RTSP_URL, CAM_RIGHT_RTSP_URL).
Or run with no args to use hardcoded defaults.

Listens on GPIO 17 for relay trigger. On each clean trigger (held 60ms),
captures the latest L+R frames and saves them immediately. After 2 boards,
exits and prints the output path.
"""

import argparse
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from collections import deque

import cv2

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class CameraReader:
    """Non-blocking camera frame reader."""

    def __init__(self, name: str, rtsp_url: str, reconnect_timeout: int = 5):
        self.name = name
        self.rtsp_url = rtsp_url
        self.reconnect_timeout = reconnect_timeout
        self._frame = None
        self._frame_ts = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._connected = False
        self._frame_history = deque(maxlen=50)  # Keep last 50 frames (~1.6s at 30fps) for position matching
        self._thread = threading.Thread(
            target=self._reader_loop, daemon=True, name=f"cam-{name}"
        )

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def get_latest_frame(self):
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def get_recent_frames(self):
        """Return list of (frame, timestamp) tuples from the last few captures."""
        with self._lock:
            return [(f.copy() if f is not None else None, ts) for f, ts in self._frame_history]

    @property
    def connected(self):
        return self._connected

    def _reader_loop(self):
        while not self._stop.is_set():
            logger.info("[%s] connecting to %s", self.name, self.rtsp_url)
            cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                logger.warning(
                    "[%s] failed to open — retrying in %ds",
                    self.name,
                    self.reconnect_timeout,
                )
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
                    ts = time.time()
                    with self._lock:
                        self._frame = frame
                        self._frame_ts = ts
                        self._frame_history.append((frame.copy() if frame is not None else None, ts))
            finally:
                self._connected = False
                cap.release()

            if not self._stop.is_set():
                time.sleep(self.reconnect_timeout)

        logger.info("[%s] reader stopped", self.name)


def detect_board_position(frame):
    """Detect board position in frame. Returns x-coordinate of board centroid, or None if not found."""
    if frame is None:
        return None

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # Board is light colored, background is dark
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None

    # Find largest contour (should be the board)
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 5000:  # min board area
        return None

    M = cv2.moments(largest)
    if M["m00"] > 0:
        cx = int(M["m10"] / M["m00"])
        return cx
    return None


def find_best_position_match(left_frames, right_frames):
    """Find L/R frame pair with best matching board position.

    Args:
        left_frames: list of (frame, timestamp) tuples
        right_frames: list of (frame, timestamp) tuples

    Returns:
        (left_frame, right_frame, position_diff_px)
    """
    if not left_frames or not right_frames:
        return None, None, float('inf')

    # Analyze positions
    left_pos = [(f, ts, detect_board_position(f)) for f, ts in left_frames]
    right_pos = [(f, ts, detect_board_position(f)) for f, ts in right_frames]

    best_diff = float('inf')
    best_pair = (None, None)

    for l_frame, l_ts, l_pos_x in left_pos:
        if l_pos_x is None or l_frame is None:
            continue
        for r_frame, r_ts, r_pos_x in right_pos:
            if r_pos_x is None or r_frame is None:
                continue
            diff = abs(l_pos_x - r_pos_x)
            if diff < best_diff:
                best_diff = diff
                best_pair = (l_frame, r_frame)

    return best_pair[0], best_pair[1], best_diff


def main():
    parser = argparse.ArgumentParser(
        description="GPIO-triggered dual-camera alignment test (2 boards)"
    )
    parser.add_argument(
        "--cam-left",
        default=os.environ.get("CAM_LEFT_RTSP_URL", "rtsp://root:pass@169.254.9.172/live1s1.sdp"),
        help="LEFT camera RTSP URL (env: CAM_LEFT_RTSP_URL)",
    )
    parser.add_argument(
        "--cam-right",
        default=os.environ.get("CAM_RIGHT_RTSP_URL", "rtsp://root:pass@169.254.9.152/live1s1.sdp"),
        help="RIGHT camera RTSP URL (env: CAM_RIGHT_RTSP_URL)",
    )
    parser.add_argument(
        "--gpio-pin", type=int, default=17, help="GPIO pin for relay (default: 17)"
    )
    parser.add_argument(
        "--stable-ms",
        type=int,
        default=60,
        help="Trigger must hold this long to be real, not noise (default: 60)",
    )
    parser.add_argument(
        "--release-ms",
        type=int,
        default=120,
        help="After capture, require release for this long before next (default: 120)",
    )
    parser.add_argument(
        "--jpg-quality", type=int, default=95, help="JPEG quality (default: 95)"
    )
    parser.add_argument(
        "--output-dir",
        default="/home/pi/board_alignment_test",
        help="Output directory for L1/R1/L2/R2 files (default: /home/pi/board_alignment_test)",
    )
    parser.add_argument(
        "--capture-delay-ms",
        type=int,
        default=0,
        help="Delay (ms) after GPIO trigger confirmed before capturing frames (default: 0)",
    )
    args = parser.parse_args()

    # Setup output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== Board Alignment Test ===")
    logger.info("Output: %s", output_dir)
    logger.info("LEFT camera:  %s", args.cam_left)
    logger.info("RIGHT camera: %s", args.cam_right)
    logger.info("Waiting for 2 GPIO triggers...")

    if not GPIO_AVAILABLE:
        logger.error("RPi.GPIO not available — this must run on a Raspberry Pi")
        sys.exit(1)

    # Setup GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(args.gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    logger.info("✓ GPIO %d configured (active HIGH)", args.gpio_pin)

    # Start camera readers
    left = CameraReader("left", args.cam_left).start()
    right = CameraReader("right", args.cam_right).start()

    captured = 0
    jq = [cv2.IMWRITE_JPEG_QUALITY, args.jpg_quality]

    def signal_handler(sig, frame):
        nonlocal captured
        logger.info("Interrupted. Captured %d boards.", captured)
        left.stop()
        right.stop()
        GPIO.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    SAMPLE_INTERVAL_S = 0.001
    TRIGGER_LEVEL = GPIO.HIGH

    def held_continuously(target_state, stable_ms):
        """Pin must read target_state continuously for stable_ms without a break."""
        deadline = time.time() + stable_ms / 1000.0
        while time.time() < deadline:
            if GPIO.input(args.gpio_pin) != target_state:
                return False
            time.sleep(SAMPLE_INTERVAL_S)
        return True

    try:
        while captured < 2:
            # Wait for both cameras to be ready
            if not left.connected or not right.connected:
                time.sleep(0.5)
                continue

            # Idle cheaply until pin hits trigger level
            if GPIO.input(args.gpio_pin) != TRIGGER_LEVEL:
                time.sleep(SAMPLE_INTERVAL_S)
                continue

            # Confirm real board (held for stable_ms)
            if not held_continuously(TRIGGER_LEVEL, args.stable_ms):
                continue

            captured += 1
            board_num = captured
            logger.info(
                "[TRIGGER #%d] GPIO %d held HIGH for %dms — capturing",
                board_num,
                args.gpio_pin,
                args.stable_ms,
            )

            # Grab recent frames from both cameras and find best temporal match
            left_history = left.get_recent_frames()
            right_history = right.get_recent_frames()

            # Simple temporal sync - just grab latest frames from each camera
            f_left = left_history[-1][0] if left_history and left_history[-1][0] is not None else None
            f_right = right_history[-1][0] if right_history and right_history[-1][0] is not None else None

            if f_left is not None and f_right is not None:
                logger.info("[CAPTURE] Grabbed latest frames from both cameras")
            else:
                logger.warning("[CAPTURE] Frame missing from one or both cameras")

            # Save with fixed names (L1/R1, L2/R2)
            l_path = output_dir / f"L{board_num}.jpg"
            r_path = output_dir / f"R{board_num}.jpg"

            if f_left is not None:
                cv2.imwrite(str(l_path), f_left, jq)
                logger.info("[SAVE] ✓ %s", l_path.name)
            else:
                logger.warning("[SAVE] ✗ LEFT frame missing for board #%d", board_num)

            if f_right is not None:
                cv2.imwrite(str(r_path), f_right, jq)
                logger.info("[SAVE] ✓ %s", r_path.name)
            else:
                logger.warning("[SAVE] ✗ RIGHT frame missing for board #%d", board_num)

            # Wait for board to leave before re-arming
            gone_since = None
            hold_start = time.time()
            while True:
                if held_continuously(TRIGGER_LEVEL, args.stable_ms):
                    gone_since = None
                    if time.time() - hold_start >= 30.0:
                        logger.warning("Board held >30s — forcing re-arm")
                        break
                else:
                    if gone_since is None:
                        gone_since = time.time()
                    elif (time.time() - gone_since) * 1000.0 >= args.release_ms:
                        break
            logger.info("[RE-ARM] Board cleared")

        logger.info("\n✓ Done! Captured 2 boards.")
        logger.info("  L1.jpg / R1.jpg")
        logger.info("  L2.jpg / R2.jpg")
        logger.info("  Location: %s", output_dir)
        logger.info("\nTo pull to Windows D:\\board_alignment:")
        logger.info("  scp <pi-user>@<pi-ip>:%s/* D:\\board_alignment\\", output_dir)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        left.stop()
        right.stop()
        GPIO.cleanup()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()
