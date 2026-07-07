"""
gpio_trigger.py — Capture frames on GPIO relay trigger (no CPU load from display).

Listens for rising edge on GPIO 17 (dry contact relay). When triggered, captures
one frame from the right camera and saves with metadata.

Wiring:
  - Relay dry contact pin 1 → GPIO 17 (Pin 11)
  - Relay dry contact pin 2 → Ground (Pin 6 or 9)
  - When relay closes, GPIO 17 goes HIGH → triggers capture

Usage:
  python gpio_trigger.py --cam-capture "rtsp://root:pass@169.254.9.152/live1s1.sdp"

GPIO Pin Reference (Raspberry Pi):
  Pin 1: 3.3V
  Pin 2: 5V
  Pin 3: SDA (I2C)
  Pin 4: 5V
  Pin 5: SCL (I2C)
  Pin 6: Ground ← Connect relay pin 2 here
  Pin 7: GPIO 4
  Pin 8: GPIO 14 (TX)
  Pin 9: Ground ← Or connect relay pin 2 here
  Pin 10: GPIO 15 (RX)
  Pin 11: GPIO 17 ← Connect relay pin 1 here
  Pin 12: GPIO 18 (PWM)
  ...
"""

import argparse
import logging
import signal
import sys
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

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    logger.warning("RPi.GPIO not available — running in test mode")


class CameraReader:
    """Non-blocking camera frame reader."""

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


def main():
    parser = argparse.ArgumentParser(description="GPIO relay trigger for board capture")
    parser.add_argument("--cam-capture", required=True, help="RTSP URL for capture camera")
    parser.add_argument("--gpio-pin", type=int, default=17, help="GPIO pin for relay trigger (default: 17)")
    parser.add_argument("--base-path", default="./captures")
    parser.add_argument("--jpg-quality", type=int, default=95)
    args = parser.parse_args()

    session_date = datetime.now().strftime("%Y-%m-%d")
    base_path = str(Path(args.base_path) / f"gpio_scan_{session_date}")

    logger.info("Starting GPIO trigger on GPIO %d", args.gpio_pin)
    logger.info("Capture camera: %s", args.cam_capture)
    logger.info("Base path: %s", base_path)

    # Setup GPIO
    if GPIO_AVAILABLE:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(args.gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        logger.info("✓ GPIO %d configured (Pull-down enabled)", args.gpio_pin)
    else:
        logger.warning("GPIO not available — trigger will not work")

    # Start camera reader
    camera = CameraReader("capture", args.cam_capture).start()

    board_num = 1
    captured_count = 0

    def signal_handler(sig, frame):
        nonlocal captured_count
        logger.info("Shutting down. Total boards captured: %d", captured_count)
        camera.stop()
        if GPIO_AVAILABLE:
            GPIO.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    logger.info("Ready. Waiting for GPIO %d trigger (relay close)...", args.gpio_pin)

    DEBOUNCE_STABLE_S = 0.05    # signal must hold HIGH continuously this long to count as a real trigger
    RELEASE_STABLE_S = 0.05     # signal must hold LOW continuously this long to count as released
    SAMPLE_INTERVAL_S = 0.005

    WAIT_TIMEOUT_S = 1.0        # give up waiting for full stability after this long and proceed anyway

    def wait_stable(target_state, stable_for_s, timeout_s=WAIT_TIMEOUT_S):
        """Block until GPIO reads target_state continuously for stable_for_s seconds,
        or until timeout_s elapses (returns best-effort so we never hang forever)."""
        wait_start = time.time()
        stable_start = None
        while True:
            if GPIO.input(args.gpio_pin) == target_state:
                if stable_start is None:
                    stable_start = time.time()
                elif time.time() - stable_start >= stable_for_s:
                    return True
            else:
                stable_start = None
            if time.time() - wait_start >= timeout_s:
                return False
            time.sleep(SAMPLE_INTERVAL_S)

    try:
        while True:
            if not camera.connected:
                time.sleep(0.5)
                continue

            if GPIO_AVAILABLE:
                if GPIO.input(args.gpio_pin) == GPIO.HIGH:
                    # Confirm it's a real trigger, not a noise/bounce spike
                    clean = wait_stable(GPIO.HIGH, DEBOUNCE_STABLE_S)

                    ts = datetime.now()
                    board_id = f"board_{board_num:04d}"
                    if clean:
                        logger.info("[TRIGGER] GPIO %d HIGH (debounced) — capturing %s", args.gpio_pin, board_id)
                    else:
                        logger.warning("[TRIGGER] GPIO %d never held stable HIGH (noisy) — capturing %s anyway", args.gpio_pin, board_id)

                    f_capture = camera.get_latest_frame()

                    if f_capture is not None:
                        try:
                            storage.save_frame(f_capture, ts, board_id, base_path,
                                                args.jpg_quality, args.cam_capture)
                            logger.info("[CAPTURE] ✓ %s saved", board_id)
                            captured_count += 1
                            board_num += 1
                        except Exception as e:
                            logger.error("[CAPTURE] ✗ Failed to save %s: %s", board_id, e, exc_info=True)
                    else:
                        logger.warning("[CAPTURE] ✗ No frame available")

                    # Wait for a clean, stable release before re-arming (never blocks forever)
                    released = wait_stable(GPIO.LOW, RELEASE_STABLE_S)
                    if released:
                        logger.info("[DEBOUNCE] Released. Waiting for next trigger...")
                    else:
                        logger.warning("[DEBOUNCE] Line never settled LOW within %.1fs — re-arming anyway", WAIT_TIMEOUT_S)
                else:
                    time.sleep(SAMPLE_INTERVAL_S)
            else:
                time.sleep(1)

    except KeyboardInterrupt:
        pass
    finally:
        logger.info("GPIO trigger stopped. Total captured: %d", captured_count)
        camera.stop()
        if GPIO_AVAILABLE:
            GPIO.cleanup()


if __name__ == "__main__":
    main()
