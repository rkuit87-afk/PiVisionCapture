"""
plc_vision_app.py — PLC-triggered board measurement.

Flow:
  1. Poll the shared DB on the S7-1200 for bTrigger (set by the CPU when a
     board is in position).
  2. On trigger: set bAck, grab the latest camera frame, save it, measure the
     board (length × width, fishtails/tear-out excluded — board_measure.py).
  3. Pick the trim saws, write wSawWord + iLengthMM + iWidthMM to the DB and
     set bResultValid (or bError + iErrorCode on failure).
  4. Wait for the PLC to drop bTrigger, clear our status bits, re-arm.

A heartbeat int in the DB increments every second so the PLC can watchdog us.

Usage (on the Pi):
  python plc_vision_app.py                        # uses plc_vision.yaml
  python plc_vision_app.py --no-plc               # PLC not connected yet:
                                                  # press Enter to simulate a
                                                  # trigger, results are logged
  python plc_vision_app.py --config other.yaml

Config: plc_vision.yaml (PLC ip/rack/slot/DB, camera RTSP, calibration,
saw positions, storage paths).
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

import board_measure
import storage
from board_measure import MeasureConfig, measure_board, select_saws
from gpio_trigger import CameraReader
from plc_exchange import PlcExchange, SimulatedPlc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(threadName)-10.10s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

FRAME_RETRIES = 10
FRAME_RETRY_DELAY_S = 0.1


def load_config(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
    except FileNotFoundError:
        logger.error("Config file not found: %s", path)
        sys.exit(1)
    for key in ("plc", "camera", "measurement", "saws", "storage"):
        if key not in cfg:
            logger.error("Config %s is missing required section '%s'", path, key)
            sys.exit(1)
    return cfg


def measure_cfg_from(cfg: dict) -> MeasureConfig:
    m = cfg["measurement"]
    return MeasureConfig(
        roi=tuple(m["roi"]) if m.get("roi") else None,
        mm_per_px=float(m["mm_per_px"]),
        mm_per_px_y=float(m["mm_per_px_y"]) if m.get("mm_per_px_y") else None,
        origin_px_x=int(m.get("origin_px_x", 0)),
        flip_x=bool(m.get("flip_x", False)),
        threshold=m.get("threshold", "otsu"),
        board_is_light=bool(m.get("board_is_light", True)),
        blur_ksize=int(m.get("blur_ksize", 5)),
        min_board_area_px=int(m.get("min_board_area_px", 5000)),
        min_width_ratio=float(m.get("min_width_ratio", 0.6)),
        gap_tolerance_px=int(m.get("gap_tolerance_px", 15)),
    )


def resolve_rtsp_url(cfg: dict) -> str:
    """Env var wins over config so credentials stay out of the repo."""
    return os.environ.get("CAM_RIGHT_RTSP_URL") or cfg["camera"]["rtsp_url"]


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
    print("\n*** --no-plc mode: press Enter to simulate a PLC trigger, Ctrl+C to quit ***\n")
    while not stop.is_set():
        try:
            input()
        except EOFError:
            return
        sim.fire()


def handle_trigger(plc, camera, mcfg: MeasureConfig, cfg: dict, board_count: int) -> int:
    """Full capture → measure → respond cycle. Returns updated board_count."""
    ts = datetime.now()
    board_count += 1
    board_id = f"board_{board_count:04d}"
    logger.info("[TRIGGER] PLC trigger received — %s", board_id)

    plc.write_status(ack=True)

    frame = None
    for _ in range(FRAME_RETRIES):
        frame = camera.get_latest_frame()
        if frame is not None:
            break
        time.sleep(FRAME_RETRY_DELAY_S)

    st = cfg["storage"]
    saw_word, length_mm, width_mm = 0, 0, 0

    if frame is None:
        logger.error("[CAPTURE] no frame available from camera")
        err = board_measure.ERR_NO_FRAME
    else:
        try:
            img_path = storage.save_frame(frame, ts, board_id, st["base_path"],
                                          st["jpg_quality"], "plc_trigger")
        except Exception as exc:
            logger.error("[STORAGE] save failed (continuing): %s", exc)
            img_path = None

        result = measure_board(frame, mcfg)
        err = result.error
        if result.ok:
            length_mm, width_mm = result.length_mm, result.width_mm
            saw_word, lead, trail = select_saws(
                result.good_start_mm, result.good_end_mm,
                cfg["saws"]["positions_m"])
            if saw_word == 0:
                err = board_measure.ERR_NO_PRODUCT
                logger.warning("[SAWS] no valid product span inside saw range")

        if img_path is not None and st.get("save_annotated") and result.annotated is not None:
            ann_path = Path(img_path).with_name(Path(img_path).stem + "_annotated.jpg")
            cv2.imwrite(str(ann_path), result.annotated,
                        [cv2.IMWRITE_JPEG_QUALITY, st["jpg_quality"]])

    ok = err == board_measure.ERR_NONE
    plc.write_results(saw_word, length_mm, width_mm, board_count, err)
    plc.write_status(ack=True, result_valid=ok, error=not ok)
    logger.info("[RESULT] %s: valid=%s saw_word=0x%04X length=%d mm width=%d mm err=%d",
                board_id, ok, saw_word, length_mm, width_mm, err)

    # Wait for the PLC to consume the result and drop the trigger
    while plc.read_trigger():
        time.sleep(0.05)
    plc.write_status()  # all clear — re-armed
    logger.info("[HANDSHAKE] trigger released, ready for next board")
    return board_count


def main():
    parser = argparse.ArgumentParser(description="PLC-triggered board measurement")
    parser.add_argument("--config", default="plc_vision.yaml")
    parser.add_argument("--no-plc", action="store_true",
                        help="Run without a PLC: Enter key simulates the trigger, "
                             "results are logged instead of written to a DB")
    args = parser.parse_args()

    cfg = load_config(args.config)
    mcfg = measure_cfg_from(cfg)
    stop = threading.Event()

    if args.no_plc:
        plc = SimulatedPlc()
    else:
        p = cfg["plc"]
        plc = PlcExchange(p["ip"], p.get("rack", 0), p.get("slot", 1),
                          p.get("db_number", 10),
                          p.get("reconnect_delay_s", 3.0))

    camera = CameraReader("capture", resolve_rtsp_url(cfg)).start()

    threading.Thread(target=heartbeat_loop, args=(plc, stop),
                     daemon=True, name="heartbeat").start()
    if args.no_plc:
        threading.Thread(target=enter_key_loop, args=(plc, stop),
                         daemon=True, name="sim-key").start()

    poll_s = float(cfg["plc"].get("poll_interval_s", 0.05))
    board_count = 0
    cleared = False

    logger.info("PLC vision app started (%s). Saw positions: %s m",
                "SIMULATED PLC" if args.no_plc else f"PLC {cfg['plc']['ip']}",
                cfg["saws"]["positions_m"])

    try:
        while True:
            if not plc.ensure_connected():
                cleared = False
                continue
            if not cleared:
                try:
                    plc.clear_pi_area()
                    cleared = True
                    logger.info("Pi area of DB cleared — handshake armed")
                except Exception as exc:
                    logger.warning("Could not clear DB area: %s", exc)
                    continue

            try:
                if plc.read_trigger():
                    board_count = handle_trigger(plc, camera, mcfg, cfg, board_count)
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
        camera.stop()
        plc.disconnect()


if __name__ == "__main__":
    main()
