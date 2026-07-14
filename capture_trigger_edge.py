#!/usr/bin/env python3
"""capture_trigger_edge.py — one-shot alignment check.

Watches DB1.bTrigger (bit 0.0) for a HIGH -> LOW (negative) transition and,
on that edge, grabs a single frame from each camera and saves them. Read-only
on the PLC (only reads bTrigger, never writes) and a passive RTSP read on
both cameras. For confirming board stop position visually, not for scoring.

Usage:
  python capture_trigger_edge.py [--out D:/board_captures/alignment_check]
"""

import argparse
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import cv2
import yaml

from plc_exchange import PlcExchange

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)


def grab_frame(rtsp_url: str, tag: str, warmup_reads: int = 5):
    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        logger.error("[%s] failed to open stream", tag)
        return None
    frame = None
    for _ in range(warmup_reads):
        ok, frame = cap.read()
        if not ok:
            frame = None
    cap.release()
    if frame is None:
        logger.error("[%s] failed to read a frame", tag)
    return frame


def main():
    parser = argparse.ArgumentParser(description="Snap L/R frames on bTrigger falling edge")
    parser.add_argument("--out", default="D:/board_captures/alignment_check",
                        help="Output directory")
    parser.add_argument("--config", default="vision_host.yaml")
    parser.add_argument("--timeout", type=float, default=120.0,
                        help="Give up after this many seconds with no edge")
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

    logger.info("Watching DB1.bTrigger for a HIGH -> LOW transition (timeout %.0fs)...",
                args.timeout)
    last = plc.read_trigger()
    logger.info("Initial bTrigger = %s", last)
    start = time.monotonic()
    edge_seen = False
    while time.monotonic() - start < args.timeout:
        try:
            now = plc.read_trigger()
        except Exception as exc:
            logger.warning("PLC read failed: %s — retrying", exc)
            time.sleep(plc_cfg.get("reconnect_delay_s", 3.0))
            plc.ensure_connected()
            continue
        if last and not now:
            edge_seen = True
            logger.info("Falling edge detected (bTrigger 1 -> 0) — capturing")
            break
        last = now
        time.sleep(plc_cfg.get("poll_interval_s", 0.05))

    if not edge_seen:
        logger.error("No falling edge seen within %.0fs — nothing captured", args.timeout)
        plc.disconnect()
        return

    left_frame = grab_frame(left_url, "LEFT")
    right_frame = grab_frame(right_url, "RIGHT")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if left_frame is not None:
        left_path = out_dir / f"LEFT_{stamp}.jpg"
        cv2.imwrite(str(left_path), left_frame)
        logger.info("Saved %s", left_path)
    if right_frame is not None:
        right_path = out_dir / f"RIGHT_{stamp}.jpg"
        cv2.imwrite(str(right_path), right_frame)
        logger.info("Saved %s", right_path)

    plc.disconnect()
    logger.info("Done.")


if __name__ == "__main__":
    main()
