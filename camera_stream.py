"""
camera_stream.py — Threaded RTSP frame reader for Vivotek IB9369.

Maintains a single-slot frame buffer: newest frame overwrites the previous one.
Never queues frames — the trigger handler always gets the freshest image.
Auto-reconnects on drop without raising to the main thread.
"""

import logging
import threading
import time

import cv2

logger = logging.getLogger(__name__)

_frame = None
_frame_lock = threading.Lock()
_stop_event = threading.Event()


def get_latest_frame():
    """Return the most recent decoded frame, or None if not yet connected."""
    with _frame_lock:
        return _frame.copy() if _frame is not None else None


def _reader_loop(rtsp_url: str, reconnect_timeout: int) -> None:
    global _frame
    while not _stop_event.is_set():
        logger.info("Camera connecting to %s", rtsp_url)
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            logger.warning("Camera failed to open — retrying in %ds", reconnect_timeout)
            time.sleep(reconnect_timeout)
            continue

        logger.info("Camera connected")
        try:
            while not _stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    logger.warning("Camera stream lost — reconnecting")
                    break
                with _frame_lock:
                    _frame = frame
        except Exception as e:
            logger.error("Exception in camera reader loop: %s", e, exc_info=True)
        finally:
            logger.info("Releasing camera capture")
            cap.release()

        if not _stop_event.is_set():
            logger.info("Sleeping for %ds before reconnect", reconnect_timeout)
            time.sleep(reconnect_timeout)

    logger.info("Camera thread stopped")


def start(rtsp_url: str, reconnect_timeout: int = 5) -> threading.Thread:
    """Start the background reader thread. Returns the thread object."""
    t = threading.Thread(
        target=_reader_loop,
        args=(rtsp_url, reconnect_timeout),
        daemon=True,
        name="camera-reader",
    )
    t.start()
    return t


def stop() -> None:
    """Signal the reader loop to exit."""
    _stop_event.set()
