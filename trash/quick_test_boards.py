#!/usr/bin/env python3
"""Quick offline test: load captured images and show what saws would be selected."""

from pathlib import Path
import cv2
import board_measure
from board_measure import MeasureConfig, measure_board, select_saws

SAW_POSITIONS = [0.0, 0.6, 0.9, 3.0, 3.6, 4.2, 4.8, 5.4, 6.0, 6.6]

cfg = MeasureConfig(
    roi=None,
    mm_per_px=3.5,
    origin_px_x=0,
    threshold="otsu",
    board_is_light=True,
    blur_ksize=5,
    min_board_area_px=5000,
    min_width_ratio=0.6,
    gap_tolerance_px=15,
)

# Find images
image_dir = Path("captures/plc_vision")
images = []
if image_dir.exists():
    for subdir in sorted(image_dir.iterdir()):
        if subdir.is_dir():
            for img_file in sorted(subdir.glob("*.jpg")):
                if "_annotated" not in img_file.name:
                    images.append(img_file)

print("\n" + "=" * 70)
print("BOARD MEASUREMENT TEST - SAW SELECTION")
print("=" * 70)

results = []
for img_path in images:
    frame = cv2.imread(str(img_path))
    if frame is None:
        continue

    result = measure_board(frame, cfg)
    if not result.ok:
        print("SKIP: %s (no board)" % img_path.parent.name)
        continue

    saw_word, leading_idx, trailing_idx = select_saws(
        result.good_start_mm, result.good_end_mm, SAW_POSITIONS
    )

    print("\nOK: %s" % img_path.parent.name)
    print("   Length: %dmm  Width: %dmm" % (result.length_mm, result.width_mm))

    if saw_word > 0:
        print("   -> Saw %d (%.1fm) to Saw %d (%.1fm)" % (
            leading_idx, SAW_POSITIONS[leading_idx],
            trailing_idx, SAW_POSITIONS[trailing_idx]
        ))
        results.append((img_path.parent.name, leading_idx, trailing_idx))

print("\n" + "=" * 70)
print("Processed %d valid boards" % len(results))
for name, lead, trail in results:
    print("  %s: saw %d to %d" % (name, lead, trail))
