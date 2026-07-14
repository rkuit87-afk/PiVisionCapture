"""
test_measure_poc.py — Load captured board images and demonstrate fishtail detection + cut decisions.

This is a POC test tool: load L/R images, measure the board, pick trim saws, show results.
No hardware dependency — runs on the engineering PC.

Usage:
  python test_measure_poc.py D:/board_alignment/L1.jpg --mm-per-px 3.5 --origin-px 0
"""

import argparse
import logging
from pathlib import Path

import cv2

import board_measure
from board_measure import MeasureConfig, measure_board, select_saws

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Test board measurement: detect fishtails, measure length/width, pick saws"
    )
    parser.add_argument(
        "image",
        help="Path to board image (L*.jpg or R*.jpg from board_alignment test)",
    )
    parser.add_argument(
        "--mm-per-px",
        type=float,
        default=3.5,
        help="Calibration: mm per pixel (default: 3.5)",
    )
    parser.add_argument(
        "--origin-px",
        type=int,
        default=0,
        help="Pixel x (in ROI) that corresponds to machine 0.0m (default: 0)",
    )
    parser.add_argument(
        "--roi",
        type=int,
        nargs=4,
        metavar=("X", "Y", "W", "H"),
        help="Region of interest [x y w h] in pixels (default: full frame)",
    )
    parser.add_argument(
        "--saw-positions",
        type=float,
        nargs="+",
        default=[0.0, 0.6, 0.9, 3.0, 3.6, 4.2, 4.8, 5.4, 6.0, 6.6],
        help="Saw positions in metres (default: trimmer saw positions)",
    )
    parser.add_argument(
        "--output-annotated",
        help="Save annotated overlay to this path",
    )
    args = parser.parse_args()

    # Load image
    img_path = Path(args.image)
    if not img_path.exists():
        logger.error("Image not found: %s", img_path)
        return

    frame = cv2.imread(str(img_path))
    if frame is None:
        logger.error("Failed to load image: %s", img_path)
        return

    logger.info("Loaded: %s (%d×%d)", img_path.name, frame.shape[1], frame.shape[0])

    # Configure measurement
    cfg = MeasureConfig(
        roi=tuple(args.roi) if args.roi else None,
        mm_per_px=args.mm_per_px,
        origin_px_x=args.origin_px,
        threshold="otsu",
        board_is_light=True,
        blur_ksize=5,
        min_board_area_px=5000,
        min_width_ratio=0.6,
        gap_tolerance_px=15,
    )

    # Measure board
    logger.info("Measuring board...")
    result = measure_board(frame, cfg)

    if not result.ok:
        logger.error("Measurement failed: error code %d", result.error)
        if result.notes:
            for note in result.notes:
                logger.error("  - %s", note)
        return

    logger.info("✓ Board detected and measured")
    logger.info("  Usable length: %d mm (raw: %d mm)", result.length_mm, result.raw_length_mm)
    logger.info("  Width: %d mm", result.width_mm)
    logger.info("  Good span: %.1f..%.1f mm", result.good_start_mm, result.good_end_mm)

    # Pick saws
    logger.info("Selecting trim saws...")
    saw_word, leading_idx, trailing_idx = select_saws(
        result.good_start_mm, result.good_end_mm, args.saw_positions
    )

    if saw_word == 0:
        logger.warning("No valid product span — no saws selected")
    else:
        logger.info("✓ Trim saws selected")
        if leading_idx is not None:
            logger.info(
                "  Leading trim: saw %d at %.1f m",
                leading_idx,
                args.saw_positions[leading_idx],
            )
        if trailing_idx is not None:
            logger.info(
                "  Trailing trim: saw %d at %.1f m",
                trailing_idx,
                args.saw_positions[trailing_idx],
            )
        logger.info("  Saw word (bit mask): 0x%04X", saw_word)

    # Save annotated overlay if requested
    if args.output_annotated and result.annotated is not None:
        out_path = Path(args.output_annotated)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_path), result.annotated)
        logger.info("Annotated overlay saved: %s", out_path)

    logger.info("\n✓ POC test complete")


if __name__ == "__main__":
    main()
