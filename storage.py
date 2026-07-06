"""
storage.py — Saves triggered frames to disk with a JSON sidecar.

Directory layout:
  {base_path}/{YYYY-MM-DD}/{board_id}/board_{timestamp}.jpg
                                      board_{timestamp}.json
"""

import json
import logging
import queue
import threading
from datetime import datetime
from pathlib import Path

import cv2

logger = logging.getLogger(__name__)


def _ts_filename(ts: datetime) -> str:
    """ISO timestamp safe for filenames — colons replaced with dashes."""
    return ts.strftime("%Y-%m-%dT%H-%M-%S")


def save_frame(
    frame,
    timestamp: datetime,
    board_id: str,
    base_path: str,
    jpg_quality: int,
    rtsp_url: str,
) -> Path:
    date_str = timestamp.strftime("%Y-%m-%d")
    folder = Path(base_path) / date_str / board_id
    folder.mkdir(parents=True, exist_ok=True)

    stem = f"board_{_ts_filename(timestamp)}"
    img_path  = folder / f"{stem}.jpg"
    json_path = folder / f"{stem}.json"

    cv2.imwrite(str(img_path), frame, [cv2.IMWRITE_JPEG_QUALITY, jpg_quality])

    meta = {
        "timestamp":      timestamp.isoformat(),
        "board_id":       board_id,
        "camera_rtsp":    rtsp_url,
        "trigger_source": "http",
        "frame_shape":    list(frame.shape),
    }
    json_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    logger.info("[STORAGE] Saved %s", img_path)
    return img_path


def _storage_loop(q: queue.Queue, base_path: str, jpg_quality: int, rtsp_url: str,
                  stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            frame, board_id, ts = q.get(timeout=1.0)
        except queue.Empty:
            continue
        try:
            save_frame(frame, ts, board_id, base_path, jpg_quality, rtsp_url)
        except Exception as exc:
            logger.error("[STORAGE] Failed to save frame: %s", exc)
    logger.info("Storage thread stopped")


def start(q: queue.Queue, base_path: str, jpg_quality: int,
          rtsp_url: str, stop: threading.Event) -> threading.Thread:
    Path(base_path).mkdir(parents=True, exist_ok=True)
    t = threading.Thread(
        target=_storage_loop,
        args=(q, base_path, jpg_quality, rtsp_url, stop),
        daemon=True,
        name="storage",
    )
    t.start()
    logger.info("Storage thread started — base_path=%s", base_path)
    return t
