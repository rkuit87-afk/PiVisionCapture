"""
vision_host_app.py — PLC-triggered dual-camera board measurement (no Pi).

Runs on the vision host: the engineering PC today, the server PC later.
The Pi's GPIO trigger is retired — the physical sensor lands on a PLC input
and reaches us as bTrigger in the shared DB (see PLC_DB_LAYOUT.md).

Flow per board:
  1. Poll DB10 bTrigger (set by the CPU when a board is in position).
  2. On trigger: set bAck, grab the latest frame from BOTH cameras.
  3. measure_dual_camera(): presence check, width @ 0.9 line, length from
     far end, fishtails; picks saw 0.0 (datum) + the standard-length saw.
  4. Write wSawWord / iLengthMM / iWidthMM / iBoardCount to DB10, set
     bResultValid (or bError + iErrorCode).
  5. Wait for the PLC to drop bTrigger, clear our bits, re-arm.

Simulation modes (combinable):
  --no-plc               SimulatedPlc; press Enter to fire a trigger.
  --replay L.jpg R.jpg   Use these saved images instead of live cameras
                         (repeatable offline testing of the whole pipeline;
                         with a real PLC this exercises the full DB loop
                         with a canned board).

Usage:
  python vision_host_app.py                          # live, uses vision_host.yaml
  python vision_host_app.py --no-plc                 # no PLC yet
  python vision_host_app.py --no-plc --replay \
      D:\\board_captures\\stop_position_reference_2026-07-10\\LEFT_stop_reference.jpg \
      D:\\board_captures\\stop_position_reference_2026-07-10\\RIGHT_stop_reference.jpg
"""

import argparse
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import yaml

from dual_camera_measure import (
    ERR_NO_FRAME, ERR_NONE, MeasureConfig, measure_dual_camera,
)
from plc_exchange import PlcExchange, SimulatedPlc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(threadName)-10.10s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

FRAME_RETRIES = 10
FRAME_RETRY_DELAY_S = 0.1


class CameraReader:
    """Background RTSP reader holding the latest frame (auto-reconnect)."""

    def __init__(self, name: str, rtsp_url: str, reconnect_timeout: int = 5):
        self.name = name
        self.rtsp_url = rtsp_url
        self.reconnect_timeout = reconnect_timeout
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._connected = False
        self._thread = threading.Thread(target=self._reader_loop, daemon=True,
                                        name=f"cam-{name}")

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
                logger.warning("[%s] failed to open — retry in %ds",
                               self.name, self.reconnect_timeout)
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


class ReplaySource:
    """Camera stand-in that always serves one fixed image."""

    def __init__(self, name: str, path: str):
        self.name = name
        self._frame = cv2.imread(path)
        if self._frame is None:
            logger.error("[%s] replay image failed to load: %s", name, path)
        self.connected = self._frame is not None

    def start(self):
        return self

    def stop(self):
        pass

    def get_latest_frame(self):
        return self._frame.copy() if self._frame is not None else None


def load_config(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
    except FileNotFoundError:
        logger.error("Config file not found: %s", path)
        sys.exit(1)
    for key in ("plc", "cameras", "measurement", "storage"):
        if key not in cfg:
            logger.error("Config %s missing section '%s'", path, key)
            sys.exit(1)
    return cfg


def measure_cfg_from(cfg: dict) -> MeasureConfig:
    m = cfg["measurement"]
    return MeasureConfig(
        threshold=m.get("threshold", "otsu"),
        board_is_light=bool(m.get("board_is_light", True)),
        blur_ksize=int(m.get("blur_ksize", 5)),
        min_board_area_px=int(m.get("min_board_area_px", 8000)),
        band_y_frac=tuple(m.get("band_y_frac", (0.10, 0.65))),
        presence_min_width_px=int(m.get("presence_min_width_px", 400)),
        presence_min_height_px=int(m.get("presence_min_height_px", 40)),
        presence_max_height_px=int(m.get("presence_max_height_px", 280)),
        presence_aspect_min=float(m.get("presence_aspect_min", 2.5)),
        wood_min_rb_diff=float(m.get("wood_min_rb_diff", 8.0)),
        empty_ref_left=m.get("empty_ref_left"),
        empty_ref_right=m.get("empty_ref_right"),
        empty_diff_min=float(m.get("empty_diff_min", 25.0)),
        require_empty_reference=bool(m.get("require_empty_reference", True)),
        width_line_px_left=int(m.get("width_line_px_left", 960)),
        board_y_range_left=tuple(m.get("board_y_range_left", (380, 570))),
        board_y_range_right=tuple(m.get("board_y_range_right", (300, 520))),
        width_scan_threshold=int(m.get("width_scan_threshold", 150)),
        presence_min_span_px=int(m.get("presence_min_span_px", 350)),
        profile_step_px=int(m.get("profile_step_px", 4)),
        px_per_mm_left=float(m.get("px_per_mm_left", 1.0)),
        px_per_mm_right=float(m.get("px_per_mm_right", 1.0)),
        right_view_x0_mm=float(m.get("right_view_x0_mm", 3400.0)),
        px_per_mm_y=float(m["px_per_mm_y"]) if m.get("px_per_mm_y") else None,
        fishtail_convergence_ratio=float(m.get("fishtail_convergence_ratio", 0.7)),
        fishtail_span_px=int(m.get("fishtail_span_px", 450)),
    )


def heartbeat_loop(plc, stop: threading.Event):
    n = 0
    while not stop.is_set():
        try:
            if plc.connected:
                plc.write_heartbeat(n)
                n += 1
        except Exception as exc:
            logger.warning("Heartbeat write failed: %s", exc)
        stop.wait(1.0)


def enter_key_loop(sim: SimulatedPlc, stop: threading.Event):
    print("\n*** --no-plc: press Enter to simulate a PLC trigger, Ctrl+C to quit ***\n")
    while not stop.is_set():
        try:
            input()
        except EOFError:
            return
        sim.fire()


def grab_frame(source, retries=FRAME_RETRIES):
    for _ in range(retries):
        f = source.get_latest_frame()
        if f is not None:
            return f
        time.sleep(FRAME_RETRY_DELAY_S)
    return None


def handle_trigger(plc, cam_left, cam_right, mcfg, cfg, board_count: int) -> int:
    ts = datetime.now()
    board_count += 1
    board_id = f"board_{board_count:04d}"
    logger.info("[TRIGGER] PLC trigger — %s", board_id)

    plc.write_status(ack=True)

    f_left = grab_frame(cam_left)
    f_right = grab_frame(cam_right)

    # Optional upstream width from the PLC (0 = not provided)
    expected_width = None
    try:
        w = plc.read_board_width()
        expected_width = w if w and w > 0 else None
    except Exception:
        pass

    st = cfg["storage"]
    out_dir = Path(st["base_path"]) / ts.strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    jq = [cv2.IMWRITE_JPEG_QUALITY, int(st.get("jpg_quality", 95))]

    for tag, frame in (("L", f_left), ("R", f_right)):
        if frame is not None:
            cv2.imwrite(str(out_dir / f"{board_id}_{tag}.jpg"), frame, jq)

    if f_left is None and f_right is None:
        logger.error("[CAPTURE] no frames from either camera")
        plc.write_results(0, 0, 0, board_count, ERR_NO_FRAME)
        plc.write_status(ack=True, error=True)
    else:
        result = measure_dual_camera(f_left, f_right, expected_width, mcfg)
        ok = result.ok and result.error == ERR_NONE
        plc.write_results(result.saw_word, result.length_mm, result.width_mm,
                          board_count, result.error)
        plc.write_status(ack=True, result_valid=ok, error=not ok)
        logger.info("[RESULT] %s valid=%s saw_word=0x%04X len=%d width=%d err=%d %s",
                    board_id, ok, result.saw_word, result.length_mm,
                    result.width_mm, result.error,
                    ("| " + "; ".join(result.notes)) if result.notes else "")
        if st.get("save_annotated"):
            for tag, ann in (("L", result.annotated_left), ("R", result.annotated_right)):
                if ann is not None:
                    cv2.imwrite(str(out_dir / f"{board_id}_{tag}_annotated.jpg"), ann, jq)

    # Wait for the PLC to consume the result and drop the trigger
    while plc.read_trigger():
        time.sleep(0.05)
    plc.write_status()  # all clear
    logger.info("[HANDSHAKE] trigger released — ready for next board")
    return board_count


def main():
    parser = argparse.ArgumentParser(description="PLC-triggered dual-camera measurement (vision host)")
    parser.add_argument("--config", default="vision_host.yaml")
    parser.add_argument("--no-plc", action="store_true",
                        help="SimulatedPlc: Enter fires a trigger, writes are logged")
    parser.add_argument("--replay", nargs=2, metavar=("LEFT_JPG", "RIGHT_JPG"),
                        help="Serve these images instead of live camera streams")
    args = parser.parse_args()

    cfg = load_config(args.config)
    mcfg = measure_cfg_from(cfg)
    stop = threading.Event()

    if args.no_plc:
        plc = SimulatedPlc()
    else:
        p = cfg["plc"]
        plc = PlcExchange(p["ip"], p.get("rack", 0), p.get("slot", 1),
                          p.get("db_number", 10), p.get("reconnect_delay_s", 3.0))

    if args.replay:
        cam_left = ReplaySource("left-replay", args.replay[0]).start()
        cam_right = ReplaySource("right-replay", args.replay[1]).start()
    else:
        left_url = os.environ.get("CAM_LEFT_RTSP_URL") or cfg["cameras"]["left_rtsp"]
        right_url = os.environ.get("CAM_RIGHT_RTSP_URL") or cfg["cameras"]["right_rtsp"]
        cam_left = CameraReader("left", left_url).start()
        cam_right = CameraReader("right", right_url).start()

    threading.Thread(target=heartbeat_loop, args=(plc, stop),
                     daemon=True, name="heartbeat").start()
    if args.no_plc:
        threading.Thread(target=enter_key_loop, args=(plc, stop),
                         daemon=True, name="sim-key").start()

    poll_s = float(cfg["plc"].get("poll_interval_s", 0.05))
    board_count = 0
    cleared = False

    logger.info("Vision host started (%s)%s",
                "SIMULATED PLC" if args.no_plc else f"PLC {cfg['plc']['ip']}",
                " [REPLAY MODE]" if args.replay else "")

    try:
        while True:
            if not plc.ensure_connected():
                cleared = False
                continue
            if not cleared:
                try:
                    plc.clear_pi_area()
                    cleared = True
                    logger.info("Host area of DB cleared — handshake armed")
                except Exception as exc:
                    logger.warning("Could not clear DB area: %s", exc)
                    time.sleep(1.0)
                    continue
            try:
                if plc.read_trigger():
                    board_count = handle_trigger(plc, cam_left, cam_right,
                                                 mcfg, cfg, board_count)
                else:
                    time.sleep(poll_s)
            except Exception as exc:
                logger.error("PLC comms error — reconnecting: %s", exc)
                cleared = False

    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Shutting down. Boards processed: %d", board_count)
        stop.set()
        cam_left.stop()
        cam_right.stop()
        plc.disconnect()


if __name__ == "__main__":
    main()
