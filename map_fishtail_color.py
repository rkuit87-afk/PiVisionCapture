#!/usr/bin/env python3
"""map_fishtail_color.py — visualize the R-B "warmth" signal across a board,
to see where overexposure clips color information vs where real wood color
survives (the fishtail/taper zones).

Does NOT use dual_camera_measure's wood-color gate (that's the exact check
that fails on overexposed frames — this script exists to look inside that
failure). Instead: brightness-only mask to find the board-shaped bright
region, then per-pixel R-B difference painted as a heatmap, overlaid on the
original photo.

Usage:
  python map_fishtail_color.py <image.jpg> [--out out.jpg]
"""

import argparse
from pathlib import Path

import cv2
import numpy as np


def board_brightness_mask(img, band_y_frac=(0.10, 0.65), brightness_thr=120, y_range=None):
    h, w = img.shape[:2]
    if y_range is not None:
        y0, y1 = max(0, y_range[0]), min(h, y_range[1])
    else:
        y0, y1 = int(h * band_y_frac[0]), int(h * band_y_frac[1])
    band = img[y0:y1]
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, brightness_thr, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return None, y0
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    full_mask = np.zeros((h, w), dtype=np.uint8)
    full_mask[y0:y1] = (labels == best).astype(np.uint8) * 255
    return full_mask, y0


def warmth_heatmap(img, mask):
    b = img[:, :, 0].astype(np.int16)
    r = img[:, :, 2].astype(np.int16)
    warmth = np.clip(r - b, -30, 90)  # R-B: >0 warm (real wood colour), ~0 clipped/neutral
    norm = ((warmth + 30) / 120.0 * 255).astype(np.uint8)  # map [-30,90] -> [0,255]
    heat = cv2.applyColorMap(norm, cv2.COLORMAP_TURBO)  # blue=cold/clipped, red/yellow=warm
    heat[mask == 0] = (30, 30, 30)
    overlay = img.copy()
    board_only = mask > 0
    overlay[board_only] = cv2.addWeighted(img, 0.35, heat, 0.65, 0)[board_only]
    return overlay, heat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--out")
    ap.add_argument("--brightness-thr", type=int, default=120)
    ap.add_argument("--y-range", type=int, nargs=2, default=None,
                    help="restrict to this y band (e.g. board_y_range_right from vision_host.yaml)")
    args = ap.parse_args()

    img = cv2.imread(args.image)
    if img is None:
        print(f"failed to load {args.image}")
        return

    mask, y0 = board_brightness_mask(img, brightness_thr=args.brightness_thr, y_range=args.y_range)
    if mask is None:
        print("no bright board-shaped region found")
        return

    overlay, heat_full = warmth_heatmap(img, mask)

    out_path = args.out or str(Path(args.image).with_name(Path(args.image).stem + "_warmth_overlay.jpg"))
    heat_path = str(Path(out_path).with_name(Path(out_path).stem + "_heatonly.jpg"))
    cv2.imwrite(out_path, overlay)
    cv2.imwrite(heat_path, heat_full)

    ys, xs = np.where(mask > 0)
    print(f"{args.image}")
    print(f"  board mask: x={xs.min()}..{xs.max()}  y={ys.min()}..{ys.max()}  px={len(xs)}")
    print(f"  saved overlay -> {out_path}")
    print(f"  saved heat-only -> {heat_path}")


if __name__ == "__main__":
    main()
