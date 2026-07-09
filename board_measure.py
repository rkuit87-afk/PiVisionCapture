"""
board_measure.py — Measure a board in 2D (length × width) from a single frame,
excluding fishtails and tear-out from the usable length, then pick trim saws.

Approach:
  1. Crop to ROI (the band of the deck where the board sits).
  2. Threshold (Otsu or fixed) — light wood vs. dark/green deck background.
  3. Morphological clean-up, keep the largest connected component (the board).
  4. Build a per-column width profile (pixels of board in each image column).
  5. Body width = median profile over the central region of the board.
  6. Usable span = longest run of columns whose width >= min_width_ratio ×
     body width. Fishtails (tapering splinters) and tear-out (missing chunks
     at the ends) fall below the ratio and are excluded.
  7. Convert pixels → machine mm using mm_per_px and origin_px_x calibration.
  8. select_saws(): choose the leading + trailing trim saw inside the usable
     span and pack them into a 16-bit word (bit i = saw i).

This module has NO snap7 or GPIO dependency, so it runs anywhere OpenCV does
(engineering PC included) — see measure_offline.py for offline tuning.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Error codes shared with the PLC (iErrorCode in the exchange DB)
ERR_NONE = 0
ERR_NO_BOARD = 1
ERR_NO_FRAME = 2
ERR_MEASURE_FAILED = 3
ERR_NO_PRODUCT = 4


@dataclass
class MeasureConfig:
    # Region of interest [x, y, w, h] in pixels; None = full frame
    roi: Optional[Tuple[int, int, int, int]] = None
    # Calibration: millimetres per pixel along the board (x axis)
    mm_per_px: float = 1.0
    # Millimetres per pixel across the board (y axis); None = same as mm_per_px
    mm_per_px_y: Optional[float] = None
    # Pixel x (in ROI coordinates) that corresponds to machine position 0.0 m
    origin_px_x: int = 0
    # Mirror x axis first (camera sees machine 0.0 on the right-hand side)
    flip_x: bool = False
    # Threshold: "otsu" or an int 0-255 for a fixed threshold
    threshold: object = "otsu"
    # Board is lighter than background (True for wood on dark/green deck)
    board_is_light: bool = True
    # Gaussian blur kernel (odd)
    blur_ksize: int = 5
    # Minimum blob area in px² to accept as a board
    min_board_area_px: int = 5000
    # Column counts as "good wood" if width >= this fraction of body width
    min_width_ratio: float = 0.6
    # Small gaps (px) inside the good run to tolerate (knots, shadows)
    gap_tolerance_px: int = 15


@dataclass
class MeasureResult:
    ok: bool = False
    error: int = ERR_MEASURE_FAILED
    length_mm: int = 0            # usable length (fishtail/tear-out excluded)
    width_mm: int = 0             # body width
    raw_length_mm: int = 0        # full extent including defects
    good_start_mm: float = 0.0    # machine coordinate of usable-wood start
    good_end_mm: float = 0.0      # machine coordinate of usable-wood end
    body_width_px: float = 0.0
    annotated: Optional[np.ndarray] = None
    notes: List[str] = field(default_factory=list)


def _make_mask(gray: np.ndarray, cfg: MeasureConfig) -> np.ndarray:
    k = max(1, cfg.blur_ksize) | 1
    blurred = cv2.GaussianBlur(gray, (k, k), 0)

    flags = cv2.THRESH_BINARY if cfg.board_is_light else cv2.THRESH_BINARY_INV
    if cfg.threshold == "otsu":
        _, mask = cv2.threshold(blurred, 0, 255, flags + cv2.THRESH_OTSU)
    else:
        _, mask = cv2.threshold(blurred, int(cfg.threshold), 255, flags)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    return mask


def _largest_component(mask: np.ndarray, min_area: int) -> Optional[np.ndarray]:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n < 2:
        return None
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[idx, cv2.CC_STAT_AREA] < min_area:
        return None
    return (labels == idx).astype(np.uint8) * 255


def _good_run(good: np.ndarray, gap_tolerance: int) -> Optional[Tuple[int, int]]:
    """Longest run of True columns, tolerating short False gaps inside it."""
    cols = np.flatnonzero(good)
    if cols.size == 0:
        return None
    breaks = np.flatnonzero(np.diff(cols) > gap_tolerance)
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks, [cols.size - 1]))
    lengths = cols[ends] - cols[starts]
    best = int(np.argmax(lengths))
    return int(cols[starts[best]]), int(cols[ends[best]])


def measure_board(frame: np.ndarray, cfg: MeasureConfig) -> MeasureResult:
    res = MeasureResult()
    if frame is None or frame.size == 0:
        res.error = ERR_NO_FRAME
        return res

    x0, y0 = 0, 0
    roi = frame
    if cfg.roi is not None:
        x0, y0, w, h = [int(v) for v in cfg.roi]
        roi = frame[y0:y0 + h, x0:x0 + w]

    if cfg.flip_x:
        roi = cv2.flip(roi, 1)

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    mask = _make_mask(gray, cfg)
    board = _largest_component(mask, cfg.min_board_area_px)
    if board is None:
        res.error = ERR_NO_BOARD
        res.notes.append("no blob above min_board_area_px")
        return res

    # Per-column width profile (pixel count is robust to splinters/holes)
    profile = (board > 0).sum(axis=0).astype(np.float64)
    occupied = np.flatnonzero(profile > 0)
    left_px, right_px = int(occupied[0]), int(occupied[-1])

    # Body width from the central half of the board — ends may be defective
    span = right_px - left_px + 1
    c0 = left_px + span // 4
    c1 = right_px - span // 4
    body_width_px = float(np.median(profile[c0:c1 + 1])) if c1 > c0 else float(np.median(profile[occupied]))
    if body_width_px <= 0:
        res.error = ERR_NO_BOARD
        return res

    good = profile >= cfg.min_width_ratio * body_width_px
    run = _good_run(good, cfg.gap_tolerance_px)
    if run is None:
        res.error = ERR_NO_BOARD
        return res
    g0, g1 = run

    mm = cfg.mm_per_px
    mm_y = cfg.mm_per_px_y if cfg.mm_per_px_y else mm
    res.good_start_mm = (g0 - cfg.origin_px_x) * mm
    res.good_end_mm = (g1 - cfg.origin_px_x) * mm
    res.length_mm = int(round((g1 - g0) * mm))
    res.raw_length_mm = int(round((right_px - left_px) * mm))
    res.width_mm = int(round(float(np.median(profile[g0:g1 + 1])) * mm_y))
    res.body_width_px = body_width_px
    res.ok = True
    res.error = ERR_NONE

    # ---- Annotated overlay for review/tuning ----
    ann = roi.copy() if roi.ndim == 3 else cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR)
    contours, _ = cv2.findContours(board, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(ann, contours, -1, (255, 200, 0), 2)
    h_ann = ann.shape[0]
    for x_px, color in ((left_px, (0, 0, 255)), (right_px, (0, 0, 255)),
                        (g0, (0, 255, 0)), (g1, (0, 255, 0))):
        cv2.line(ann, (x_px, 0), (x_px, h_ann - 1), color, 2)
    label = f"usable {res.length_mm} mm  width {res.width_mm} mm  raw {res.raw_length_mm} mm"
    cv2.putText(ann, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    res.annotated = ann

    logger.info("[MEASURE] usable=%d mm width=%d mm raw=%d mm span=%.0f..%.0f mm",
                res.length_mm, res.width_mm, res.raw_length_mm,
                res.good_start_mm, res.good_end_mm)
    return res


def select_saws(good_start_mm: float, good_end_mm: float,
                saw_positions_m: List[float]) -> Tuple[int, Optional[int], Optional[int]]:
    """
    Pick the leading trim saw (first saw at/inside the usable start) and the
    trailing trim saw (last saw at/inside the usable end).

    Returns (saw_word, leading_index, trailing_index). Bit i of saw_word is
    saw i in saw_positions_m. saw_word == 0 means no valid product.
    """
    positions_mm = [p * 1000.0 for p in saw_positions_m]
    leading = None
    trailing = None
    for i, p in enumerate(positions_mm):
        if p >= good_start_mm and leading is None:
            leading = i
        if p <= good_end_mm:
            trailing = i
    if leading is None or trailing is None or trailing <= leading:
        return 0, None, None
    word = (1 << leading) | (1 << trailing)
    logger.info("[SAWS] leading=saw%d (%.1f m) trailing=saw%d (%.1f m) word=0x%04X",
                leading, saw_positions_m[leading],
                trailing, saw_positions_m[trailing], word)
    return word, leading, trailing
