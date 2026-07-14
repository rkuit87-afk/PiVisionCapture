"""
measure_offline.py — Run the board measurement on a saved image (no camera,
no PLC, no GPIO). Works on the engineering PC — use it to tune thresholds and
calibrate mm_per_px before deploying to the Pi.

Examples:
  # Measure an image with the settings in plc_vision.yaml:
  python measure_offline.py captures_review/board_0001.jpg

  # Calibrate: the board in this image is 6700 mm end-to-end (including
  # fishtail). Prints the mm_per_px to paste into plc_vision.yaml:
  python measure_offline.py reference_board.jpg --calibrate 6700

Output: prints the measurement and writes <image>_measured.jpg next to the
input with the detection overlay (blue contour, red = raw extent,
green = usable span after fishtail/tear-out exclusion).
"""

import argparse
import logging
import sys
from pathlib import Path

import cv2
import yaml

from board_measure import MeasureConfig, measure_board, select_saws

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Offline board measurement / calibration")
    parser.add_argument("image", help="Path to a captured board image")
    parser.add_argument("--config", default="plc_vision.yaml")
    parser.add_argument("--calibrate", type=float, metavar="KNOWN_MM",
                        help="Known full length of the board in this image (mm). "
                             "Prints the mm_per_px to put in the config.")
    args = parser.parse_args()

    frame = cv2.imread(args.image)
    if frame is None:
        logger.error("Could not read image: %s", args.image)
        sys.exit(1)

    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    m = cfg["measurement"]

    mcfg = MeasureConfig(
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

    if args.calibrate:
        # Measure with mm_per_px = 1 so raw_length_mm == raw length in pixels
        mcfg.mm_per_px = 1.0
        mcfg.mm_per_px_y = 1.0
        result = measure_board(frame, mcfg)
        if not result.ok:
            logger.error("Board not detected (error %d) — cannot calibrate. "
                         "Adjust threshold/roi in %s first.", result.error, args.config)
            sys.exit(1)
        raw_px = result.raw_length_mm  # pixels, since scale was 1.0
        mm_per_px = args.calibrate / raw_px
        print()
        print(f"Board raw extent : {raw_px} px")
        print(f"Known length     : {args.calibrate:.0f} mm")
        print(f"==> mm_per_px    : {mm_per_px:.4f}")
        print()
        print(f"Paste into {args.config}:  measurement.mm_per_px: {mm_per_px:.4f}")
        # Re-measure at the calibrated scale so the overlay shows real mm
        mcfg.mm_per_px = mm_per_px
        mcfg.mm_per_px_y = None
        result = measure_board(frame, mcfg)
    else:
        result = measure_board(frame, mcfg)

    if not result.ok:
        logger.error("Measurement failed, error code %d (%s)", result.error,
                     {1: "no board", 2: "no frame", 3: "measure failed"}.get(result.error, "?"))
        sys.exit(1)

    print()
    print(f"Usable length : {result.length_mm} mm   (raw incl. defects: {result.raw_length_mm} mm)")
    print(f"Width         : {result.width_mm} mm")
    print(f"Usable span   : {result.good_start_mm:.0f} .. {result.good_end_mm:.0f} mm (machine coords)")

    saw_word, lead, trail = select_saws(result.good_start_mm, result.good_end_mm,
                                        cfg["saws"]["positions_m"])
    if saw_word:
        positions = cfg["saws"]["positions_m"]
        print(f"Trim saws     : saw {lead} @ {positions[lead]} m  +  saw {trail} @ {positions[trail]} m")
        print(f"Saw word      : 0x{saw_word:04X}  (binary {saw_word:016b})")
        print(f"Product length: {(positions[trail] - positions[lead]) * 1000:.0f} mm")
    else:
        print("Trim saws     : NO VALID PRODUCT inside saw range")

    out_path = Path(args.image).with_name(Path(args.image).stem + "_measured.jpg")
    cv2.imwrite(str(out_path), result.annotated)
    print(f"\nOverlay saved : {out_path}")


if __name__ == "__main__":
    main()
