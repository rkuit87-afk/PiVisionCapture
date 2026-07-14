#!/usr/bin/env python3
"""crop_to_board.py — tight crop around the detected board, removing background
noise (chains, gears, wiring) above/below it.

Detects the actual board blob (dual_camera_measure._find_board_blob) rather
than converting a target mm figure to pixels, since the vertical/width axis
isn't independently mm-calibrated the way the length axis is (px_per_mm_left/
right calibrate along the board's length, not across it) — using the real
detected extent is more honest than guessing a scale factor.

Usage:
  python crop_to_board.py LEFT.jpg RIGHT.jpg [--pad-frac 0.25] [--out-suffix _focused]
"""

import argparse
from pathlib import Path

import cv2
import yaml

from dual_camera_measure import MeasureConfig
from shadow_capture_app import board_position
from vision_host_app import measure_cfg_from


def crop_to_blob(frame, mcfg: MeasureConfig, pad_frac: float, y_range, threshold):
    """Anchor the crop to the already-validated board_y_range (confirmed via
    board_position() against real captures) rather than a fresh blob search —
    _find_board_blob's connected-components approach was tried first and
    mis-detected a wiring conduit as the board on this rig, so it's not used
    here. board_position() itself only returns a y_center, not a bounding
    box, so the configured y_range IS the bounding box; we just pad it a
    little and confirm the board's column-run centers actually fall inside."""
    h = frame.shape[0]
    lo, hi = y_range
    pos = board_position(frame, (max(0, lo - 100), min(h, hi + 100)), mcfg, threshold)
    band_h = hi - lo
    pad = max(10, int(band_h * pad_frac))
    y0 = max(0, lo - pad)
    y1 = min(h, hi + pad)
    crop = frame[y0:y1, :]
    y_center = pos["y_center"] if pos else None
    return crop, (y0, y1, lo, hi, y_center)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("left")
    ap.add_argument("right")
    ap.add_argument("--config", default="vision_host.yaml")
    ap.add_argument("--pad-frac", type=float, default=0.25,
                    help="padding above/below the detected board, as a fraction of its own height")
    ap.add_argument("--out-suffix", default="_focused")
    args = ap.parse_args()

    vcfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    mcfg = measure_cfg_from(vcfg)

    ranges = {"LEFT": (mcfg.board_y_range_left, 150), "RIGHT": (mcfg.board_y_range_right, 125)}

    for tag, path in (("LEFT", args.left), ("RIGHT", args.right)):
        frame = cv2.imread(path)
        if frame is None:
            print(f"{tag}: failed to load {path}")
            continue
        y_range, threshold = ranges[tag]
        crop, info = crop_to_blob(frame, mcfg, args.pad_frac, y_range, threshold)
        y0, y1, lo, hi, y_center = info
        out_path = Path(path).with_name(Path(path).stem + args.out_suffix + Path(path).suffix)
        cv2.imwrite(str(out_path), crop)
        center_note = f"y_center={y_center:.1f}" if y_center is not None else "y_center=NOT FOUND"
        print(f"{tag}: configured band y={lo}..{hi}  {center_note}  "
              f"cropped to y={y0}..{y1} ({y1 - y0}px, full width)  -> {out_path}")


if __name__ == "__main__":
    main()
