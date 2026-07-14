"""
gpio_trigger.py — Capture frames on GPIO relay trigger (no CPU load from display).

Listens for rising edge on GPIO 17 (dry contact relay). When triggered, captures
one frame from the right camera and saves with metadata.

Wiring:
  - Relay dry contact pin 1 → GPIO 17 (Pin 11)
  - Relay dry contact pin 2 → Ground (Pin 6 or 9)
  - When relay closes, GPIO 17 goes HIGH → triggers capture

Usage:
  python gpio_trigger.py --cam-capture "rtsp://root:pass@192.168.3.145/live1s1.sdp"

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
    parser.add_argument("--cam-capture", required=True, help="RTSP URL for capture (RIGHT) camera")
    parser.add_argument("--cam-monitor", default=None,
                         help="RTSP URL for the second (LEFT) camera. When set, every trigger saves a "
                              "matched pair: R<n>.jpg from --cam-capture and L<n>.jpg from --cam-monitor.")
    parser.add_argument("--pair-dir", default=None,
                         help="Output directory for paired L<n>/R<n> images (default: "
                              "<base-path>/paired_<date>). Only used when --cam-monitor is set.")
    parser.add_argument("--gpio-pin", type=int, default=17, help="GPIO pin for relay trigger (default: 17)")
    parser.add_argument("--base-path", default="./captures")
    parser.add_argument("--jpg-quality", type=int, default=95)
    parser.add_argument("--active-low", action="store_true",
                         help="Trigger on LOW instead of HIGH (use for pins with a fixed hardware "
                              "pull-up, e.g. GPIO 2/3, where relay's other leg goes to Ground)")
    parser.add_argument("--stable-ms", type=int, default=60,
                         help="A real board must hold the trigger level CONTINUOUSLY (no break) for this "
                              "many ms to count (default: 60). Measured VFD noise on this line can only "
                              "hold a state for ~28ms max, while a real board holds 400ms+, so anything "
                              "above ~40ms cleanly separates board from noise. Raise if noise still slips "
                              "through; lower if fast boards are being missed.")
    parser.add_argument("--capture-delay-ms", type=int, default=0,
                         help="Extra delay (ms) after a trigger is confirmed before the frame is grabbed. "
                              "Use this to center the board under the camera relative to sensor position "
                              "(default: 0 = capture immediately)")
    parser.add_argument("--release-ms", type=int, default=120,
                         help="After capturing, the line must STOP being solidly held (board has left) "
                              "for this many ms before the next trigger can fire (default: 120). Prevents "
                              "one board from being captured twice.")
    parser.add_argument("--max-hold-s", type=float, default=30.0,
                         help="Safety valve: if the line stays solidly held this long (e.g. a genuinely "
                              "stuck contact), force re-arm and warn rather than blocking forever (default: 30).")
    args = parser.parse_args()

    session_date = datetime.now().strftime("%Y-%m-%d")
    base_path = str(Path(args.base_path) / f"gpio_scan_{session_date}")

    paired = args.cam_monitor is not None
    pair_dir = Path(args.pair_dir) if args.pair_dir else Path(args.base_path) / f"paired_{session_date}"
    if paired:
        pair_dir.mkdir(parents=True, exist_ok=True)

    TRIGGER_LEVEL = GPIO.LOW if (GPIO_AVAILABLE and args.active_low) else GPIO.HIGH if GPIO_AVAILABLE else None
    IDLE_LEVEL = GPIO.HIGH if (GPIO_AVAILABLE and args.active_low) else GPIO.LOW if GPIO_AVAILABLE else None

    logger.info("Starting GPIO trigger on GPIO %d (active-%s)", args.gpio_pin, "low" if args.active_low else "high")
    logger.info("Capture (RIGHT) camera: %s", args.cam_capture)
    if paired:
        logger.info("Monitor (LEFT) camera:  %s", args.cam_monitor)
        logger.info("Paired output dir: %s  (files: L<n>.jpg / R<n>.jpg)", pair_dir)
    else:
        logger.info("Base path: %s", base_path)

    # Setup GPIO
    if GPIO_AVAILABLE:
        GPIO.setmode(GPIO.BCM)
        pud = GPIO.PUD_UP if args.active_low else GPIO.PUD_DOWN
        GPIO.setup(args.gpio_pin, GPIO.IN, pull_up_down=pud)
        logger.info("✓ GPIO %d configured (%s)", args.gpio_pin, "Pull-up enabled" if args.active_low else "Pull-down enabled")
    else:
        logger.warning("GPIO not available — trigger will not work")

    # Start camera reader(s)
    camera = CameraReader("capture", args.cam_capture).start()
    monitor = CameraReader("monitor", args.cam_monitor).start() if paired else None

    board_num = 1
    captured_count = 0

    def signal_handler(sig, frame):
        nonlocal captured_count
        logger.info("Shutting down. Total boards captured: %d", captured_count)
        camera.stop()
        if monitor is not None:
            monitor.stop()
        if GPIO_AVAILABLE:
            GPIO.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    logger.info("Ready. Waiting for GPIO %d trigger (relay close)...", args.gpio_pin)
    logger.info("Continuous-stability trigger: need %dms unbroken %s · capture delay: %dms · release: %dms",
                args.stable_ms, "LOW" if args.active_low else "HIGH", args.capture_delay_ms, args.release_ms)

    SAMPLE_INTERVAL_S = 0.001
    CAPTURE_DELAY_S = args.capture_delay_ms / 1000.0

    def held_continuously(target_state, stable_ms):
        """Return True only if the pin reads target_state CONTINUOUSLY, with no break,
        for stable_ms milliseconds. Returns False the instant a non-target sample appears.

        This is the key noise rejector: measured VFD ripple on this line flips every
        1-2ms and can never hold one state longer than ~28ms, so it cannot satisfy a
        60ms continuous requirement. A real board hard-closes the contact onto 3.3V and
        holds solid for 400ms+, which passes easily."""
        deadline = time.time() + stable_ms / 1000.0
        while time.time() < deadline:
            if GPIO.input(args.gpio_pin) != target_state:
                return False
            time.sleep(SAMPLE_INTERVAL_S)
        return True

    try:
        while True:
            if not camera.connected:
                time.sleep(0.5)
                continue

            if not GPIO_AVAILABLE:
                time.sleep(1)
                continue

            # Only bother running the stability check when the pin is momentarily at
            # the trigger level; otherwise idle cheaply.
            if GPIO.input(args.gpio_pin) != TRIGGER_LEVEL:
                time.sleep(SAMPLE_INTERVAL_S)
                continue

            # Confirm a REAL board: the trigger level must hold unbroken for stable_ms.
            # Noise fails this within ~28ms; a board sails through.
            if not held_continuously(TRIGGER_LEVEL, args.stable_ms):
                continue  # was just noise — ignore, keep watching

            board_id = f"board_{board_num:04d}"
            logger.info("[TRIGGER] GPIO %d held %s for %dms — real board #%d",
                        args.gpio_pin, "LOW" if args.active_low else "HIGH", args.stable_ms, board_num)

            if CAPTURE_DELAY_S > 0:
                time.sleep(CAPTURE_DELAY_S)

            ts = datetime.now()
            jq = [cv2.IMWRITE_JPEG_QUALITY, args.jpg_quality]

            if paired:
                # Matched pair: L<n>.jpg (monitor/left) + R<n>.jpg (capture/right)
                f_right = camera.get_latest_frame()
                f_left = monitor.get_latest_frame() if monitor and monitor.connected else None
                r_path = pair_dir / f"R{board_num}.jpg"
                l_path = pair_dir / f"L{board_num}.jpg"
                saved = []
                if f_right is not None:
                    cv2.imwrite(str(r_path), f_right, jq)
                    saved.append(r_path.name)
                else:
                    logger.warning("[CAPTURE] ✗ No RIGHT frame available for board #%d", board_num)
                if f_left is not None and monitor is not None:
                    cv2.imwrite(str(l_path), f_left, jq)
                    saved.append(l_path.name)
                else:
                    logger.warning("[CAPTURE] ✗ No LEFT frame for board #%d", board_num)
                if saved:
                    logger.info("[CAPTURE] ✓ pair #%d saved: %s", board_num, " + ".join(saved))
                    captured_count += 1
                board_num += 1
            else:
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

            # Re-arm only once the board has LEFT. A present board keeps the line solidly
            # held; a departed board returns to noise (can't hold the level for stable_ms).
            # Require the "not solidly held" condition to persist for release_ms so a brief
            # mid-board dip doesn't re-arm early. Safety timeout guards a genuinely stuck line.
            hold_start = time.time()
            gone_since = None
            while True:
                if held_continuously(TRIGGER_LEVEL, args.stable_ms):
                    gone_since = None  # board still here
                    if time.time() - hold_start >= args.max_hold_s:
                        logger.warning("[RE-ARM] Line stuck held >%.0fs — forcing re-arm (check for stuck contact)",
                                       args.max_hold_s)
                        break
                else:
                    if gone_since is None:
                        gone_since = time.time()
                    elif (time.time() - gone_since) * 1000.0 >= args.release_ms:
                        break  # board confirmed gone
            logger.info("[RE-ARM] Board cleared — watching for next.")

    except KeyboardInterrupt:
        pass
    finally:
        logger.info("GPIO trigger stopped. Total captured: %d", captured_count)
        camera.stop()
        if monitor is not None:
            monitor.stop()
        if GPIO_AVAILABLE:
            GPIO.cleanup()


if __name__ == "__main__":
    main()
