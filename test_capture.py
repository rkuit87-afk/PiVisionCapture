"""
Quick test: grab one frame from right camera and save it via storage.
Verifies the capture + save pipeline works before full testing.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

import cv2

import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

if len(sys.argv) < 2:
    print("Usage: python test_capture.py <rtsp_url> [base_path]")
    print("Example: python test_capture.py \"rtsp://root:pass@169.254.9.152/live1s1.sdp\"")
    sys.exit(1)

rtsp_url = sys.argv[1]
base_path = sys.argv[2] if len(sys.argv) > 2 else "./captures"

logger.info("Connecting to %s...", rtsp_url)
cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)

if not cap.isOpened():
    logger.error("Failed to open camera")
    sys.exit(1)

logger.info("Reading frame...")
ok, frame = cap.read()
if not ok:
    logger.error("Failed to read frame")
    cap.release()
    sys.exit(1)

logger.info("Frame: %s", frame.shape)

try:
    path = storage.save_frame(
        frame,
        datetime.now(),
        "test_board",
        base_path,
        jpg_quality=95,
        rtsp_url=rtsp_url
    )
    logger.info("✓ Saved to %s", path)

    # Verify file exists
    if Path(path).exists():
        size = Path(path).stat().st_size
        logger.info("✓ File verified: %d bytes", size)
    else:
        logger.error("✗ File doesn't exist at %s", path)
        sys.exit(1)

except Exception as e:
    logger.error("✗ Failed: %s", e, exc_info=True)
    sys.exit(1)
finally:
    cap.release()

logger.info("✓ Test passed!")
