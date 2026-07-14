#!/usr/bin/env python3
"""One-off: measure actual board y-position in the confirmed-correct 0.75s
reference frames, using the same board_position() detector shadow_capture_app.py
uses live, so the numbers are directly comparable to board_y_range_left/right."""

import cv2
import yaml

from shadow_capture_app import board_position
from vision_host_app import measure_cfg_from

vcfg = yaml.safe_load(open("vision_host.yaml", encoding="utf-8"))
mcfg = measure_cfg_from(vcfg)

pairs = [
    ("LEFT", "captures/alignment_check/LEFT_20260713_141322.jpg", mcfg.board_y_range_left, 150),
    ("RIGHT", "captures/alignment_check/RIGHT_20260713_141322.jpg", mcfg.board_y_range_right, 125),
]

for tag, path, configured_range, threshold in pairs:
    frame = cv2.imread(path)
    h = frame.shape[0]
    lo, hi = configured_range
    pad = 150
    window = (max(0, lo - pad), min(h, hi + pad))
    pos = board_position(frame, window, mcfg, threshold)
    print(f"\n{tag}  ({path})")
    print(f"  configured board_y_range: {configured_range}  (searched {window})")
    if pos is None:
        print("  NOT FOUND in padded window at threshold", threshold)
        continue
    print(f"  measured: x={pos['x0']}..{pos['x1']}  y_center={pos['y_center']:.1f}  span_px={pos['span_px']}")
    in_range = lo <= pos["y_center"] <= hi
    print(f"  y_center {'INSIDE' if in_range else 'OUTSIDE'} configured range {configured_range}")
