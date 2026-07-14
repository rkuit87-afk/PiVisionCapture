"""
dual_camera_measure.py — Dual-camera board measurement and saw selection.

Runs on the vision host (engineering PC now, server PC later). No Pi, no GPIO.

Pipeline per trigger:
  1. Validate a board is actually present in each frame (geometry + wood
     colour) — rejects empty-deck frames (2026-07-10 false-trigger lesson:
     a bright sunlit deck must NOT be measured as a board).
  2. Measure width at the configured pixel column (a fixed 860 mm reference,
     from the fence — safe from origin-side fishtails), snap to the nearest
     standard width (76 / 114 / 152 mm).
  3. Measure board length from the far-end position in the RIGHT view
     (fence-datum design: origin end rests against the fence at saw 0.0).
  4. Always drop saw 0.0 (18 mm fence datum — squares the end grain), and
     the standard-length saw nearest the measured length.
  5. Fishtail detection on both ends (edge convergence); tear-out stubbed.

Saw calibration (tape-measured from the fence, 2026-07-09):
  Bit  Saw  Actual(mm)   Final length after 0.0 cut
   0   0.0       18       (datum cut)
   1   0.3      270        252
   2   0.6      560        542
   3   3.0     3057       3039
   4   3.6     3670       3652
   5   4.2     4249       4231
   6   4.8     4813       4795
   7   5.4     5490       5472
   8   6.0     6023       6005
   9   6.6     6660       6642
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Actual saw positions (mm from fence) — 2026-07-09 tape calibration
SAW_CALIBRATION = {
    0: {"label": "0.0", "mm": 18, "camera": "LEFT"},
    1: {"label": "0.3", "mm": 270, "camera": "LEFT"},
    2: {"label": "0.6", "mm": 560, "camera": "LEFT"},
    3: {"label": "3.0", "mm": 3057, "camera": "LEFT"},
    4: {"label": "3.6", "mm": 3670, "camera": "RIGHT"},
    5: {"label": "4.2", "mm": 4249, "camera": "RIGHT"},
    6: {"label": "4.8", "mm": 4813, "camera": "RIGHT"},
    7: {"label": "5.4", "mm": 5490, "camera": "RIGHT"},
    8: {"label": "6.0", "mm": 6023, "camera": "RIGHT"},
    9: {"label": "6.6", "mm": 6660, "camera": "RIGHT"},
}

# Standard-length saws (bit -> final length in mm after the 18 mm datum cut)
STANDARD_LENGTH_SAWS = {
    3: 3039,   # 3.0
    4: 3652,   # 3.6
    5: 4231,   # 4.2
    6: 4795,   # 4.8
    7: 5472,   # 5.4
    8: 6005,   # 6.0
    9: 6642,   # 6.6
}

STANDARD_WIDTHS_MM = (76, 114, 152)

# Error codes shared with the PLC (iErrorCode in DB10)
ERR_NONE = 0
ERR_NO_BOARD = 1
ERR_NO_FRAME = 2
ERR_MEASURE_FAILED = 3
ERR_NO_PRODUCT = 4


@dataclass
class MeasureConfig:
    # -- segmentation --
    threshold: object = "otsu"       # "otsu" or fixed 0-255
    board_is_light: bool = True
    blur_ksize: int = 5
    min_board_area_px: int = 8000
    # Vertical band (fraction of frame height) searched for the board.
    # Excludes the bright metal chute at the bottom of both views.
    band_y_frac: Tuple[float, float] = (0.10, 0.65)

    # -- board presence validation (rejects empty-deck frames) --
    presence_min_width_px: int = 400        # board must span at least this
    presence_min_height_px: int = 40        # ~40 px = ~40 mm at 1 px/mm
    presence_max_height_px: int = 280       # taller blob = merged background
    presence_aspect_min: float = 2.5        # boards are long and flat
    # Wood is warm: mean(R) - mean(B) inside the blob must exceed this.
    # Grey deck/machinery is neutral (R≈B); blown-out white sky fails too.
    wood_min_rb_diff: float = 8.0

    # -- empty-scene rejection (optional, recommended) --
    # Grayscale images of the EMPTY deck per camera (confirmed empty frames).
    # A candidate blob must differ from the empty scene to count as a board.
    empty_ref_left: Optional[str] = None
    empty_ref_right: Optional[str] = None
    empty_diff_min: float = 25.0     # mean abs gray diff inside blob bbox
    # Do not guess from bright pixels when the current-camera empty reference
    # is unavailable.  The production views contain fixed pale timber/rails
    # in the board windows, which otherwise look exactly like a long board.
    require_empty_reference: bool = True

    # -- calibration (per camera, pixel domain) --
    # Pixel x of the width-measurement reference (860 mm) in each view.
    # CALIBRATE ON SITE: read off the stop-position reference images.
    width_line_px_left: int = 960
    # Absolute y-windows where the stopped board rests in each view
    # (stop position is repeatable to ±9 px — 2026-07-10). All presence /
    # width / far-end scanning happens inside these windows, which makes it
    # immune to blob merging and overexposure elsewhere in the frame.
    board_y_range_left: Tuple[int, int] = (380, 570)
    board_y_range_right: Tuple[int, int] = (300, 520)
    width_scan_threshold: int = 150
    # Presence via board profile: the (board & not-empty) column span must
    # be at least this many px for a board to count as present.
    presence_min_span_px: int = 350
    profile_step_px: int = 4
    # px per mm along the board, per camera (for far-end length estimate).
    # CALIBRATE ON SITE (previous rough estimate ~1.07 px/mm at 1080p).
    px_per_mm_left: float = 1.0
    px_per_mm_right: float = 1.0
    # Machine mm of the LEFT edge of the RIGHT camera's view (frame x=0).
    right_view_x0_mm: float = 3400.0
    # mm per px across the board (width axis); None = same as px_per_mm
    px_per_mm_y: Optional[float] = None

    # -- fishtail detection --
    fishtail_convergence_ratio: float = 0.7
    fishtail_span_px: int = 450


@dataclass
class BoardBlob:
    x0: int
    x1: int
    y0: int
    y1: int
    width_px: int      # horizontal extent
    height_px: int     # vertical extent
    mask: np.ndarray   # full-band binary mask (blob only)
    band_y_offset: int


@dataclass
class DualCameraResult:
    ok: bool = False
    error: int = ERR_MEASURE_FAILED

    width_mm: int = 0            # snapped standard width
    width_raw_mm: float = 0.0    # as measured, pre-snap
    length_mm: int = 0           # final length (trailing saw mm - 18)
    measured_length_mm: float = 0.0

    left_saw_index: Optional[int] = None
    right_saw_index: Optional[int] = None
    saw_word: int = 0

    left_board_present: bool = False
    right_board_present: bool = False
    left_has_fishtail: bool = False
    right_has_fishtail: bool = False
    left_has_tearout: bool = False    # STUB
    right_has_tearout: bool = False   # STUB

    annotated_left: Optional[np.ndarray] = None
    annotated_right: Optional[np.ndarray] = None
    notes: List[str] = field(default_factory=list)


def _make_mask(gray: np.ndarray, cfg: MeasureConfig) -> np.ndarray:
    k = max(1, cfg.blur_ksize) | 1
    blurred = cv2.GaussianBlur(gray, (k, k), 0)
    flags = cv2.THRESH_BINARY if cfg.board_is_light else cv2.THRESH_BINARY_INV
    if cfg.threshold == "otsu":
        _, mask = cv2.threshold(blurred, 0, 255, flags + cv2.THRESH_OTSU)
    else:
        _, mask = cv2.threshold(blurred, int(cfg.threshold), 255, flags)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    return mask


_EMPTY_REF_CACHE: dict = {}


def _load_empty_ref(path: Optional[str]) -> Optional[np.ndarray]:
    if not path:
        return None
    if path not in _EMPTY_REF_CACHE:
        img = cv2.imread(path)
        _EMPTY_REF_CACHE[path] = (
            cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img is not None else None)
        if img is None:
            logger.warning("[PRESENCE] empty reference failed to load: %s", path)
    return _EMPTY_REF_CACHE[path]


def _find_board_blob(frame: np.ndarray, cfg: MeasureConfig,
                     empty_ref_path: Optional[str] = None) -> Optional[BoardBlob]:
    """Locate the board as the widest flat bright blob in the search band,
    then validate geometry + wood colour. Returns None if no plausible board."""
    h, w = frame.shape[:2]
    y_lo = int(h * cfg.band_y_frac[0])
    y_hi = int(h * cfg.band_y_frac[1])
    band = frame[y_lo:y_hi]
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY) if band.ndim == 3 else band

    mask = _make_mask(gray, cfg)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best, best_w = None, 0
    for i in range(1, n):
        bw = stats[i, cv2.CC_STAT_WIDTH]
        bh = stats[i, cv2.CC_STAT_HEIGHT]
        area = stats[i, cv2.CC_STAT_AREA]
        if area < cfg.min_board_area_px:
            continue
        if bw < cfg.presence_min_width_px:
            continue
        if not (cfg.presence_min_height_px <= bh <= cfg.presence_max_height_px):
            continue
        if bw < cfg.presence_aspect_min * bh:
            continue
        if bw > best_w:
            best_w, best = bw, i

    if best is None:
        return None

    blob_mask = (labels == best).astype(np.uint8) * 255

    # Wood-colour check: warm (R > B) inside the blob. Empty grey deck and
    # blown-out highlights are colour-neutral and fail this.
    if band.ndim == 3:
        pix = band[blob_mask > 0]
        if pix.size == 0:
            return None
        mean_b = float(pix[:, 0].mean())
        mean_r = float(pix[:, 2].mean())
        if (mean_r - mean_b) < cfg.wood_min_rb_diff:
            logger.info("[PRESENCE] blob rejected: R-B diff %.1f < %.1f (not wood)",
                        mean_r - mean_b, cfg.wood_min_rb_diff)
            return None

    x0 = int(stats[best, cv2.CC_STAT_LEFT])
    bw = int(stats[best, cv2.CC_STAT_WIDTH])
    y0 = int(stats[best, cv2.CC_STAT_TOP])
    bh = int(stats[best, cv2.CC_STAT_HEIGHT])

    # Empty-scene rejection: the blob's region must actually differ from the
    # known empty deck. Static sunlit structure matches the empty reference
    # and is rejected; a board is a large change.
    empty = _load_empty_ref(empty_ref_path)
    if empty is not None and empty.shape[:2] == frame.shape[:2]:
        region_now = gray[y0:y0 + bh, x0:x0 + bw]
        region_empty = empty[y0 + y_lo:y0 + y_lo + bh, x0:x0 + bw]
        if region_empty.shape == region_now.shape and region_now.size:
            diff = float(np.mean(cv2.absdiff(region_now, region_empty)))
            if diff < cfg.empty_diff_min:
                logger.info("[PRESENCE] blob rejected: diff vs empty scene "
                            "%.1f < %.1f (static background)", diff, cfg.empty_diff_min)
                return None

    return BoardBlob(x0=x0, x1=x0 + bw - 1, y0=y0 + y_lo, y1=y0 + bh - 1 + y_lo,
                     width_px=bw, height_px=bh, mask=blob_mask, band_y_offset=y_lo)


def _width_at_column(blob: BoardBlob, col_px: int) -> Optional[int]:
    """Board thickness (vertical pixel count of the blob) at a pixel column."""
    if not (0 <= col_px < blob.mask.shape[1]):
        return None
    col = blob.mask[:, col_px]
    ys = np.flatnonzero(col > 0)
    if ys.size == 0:
        return None
    return int(ys[-1] - ys[0] + 1)


def _column_run(gray: np.ndarray, col_px: int, y_range: Tuple[int, int],
                threshold: int, min_h: int, max_h: int) -> Optional[int]:
    """Longest contiguous bright run of plausible board height at one column
    inside the stopped-board y-window. Raw pixels, no morphology — immune to
    overexposure merging elsewhere in the frame. Returns run height or None."""
    h, w = gray.shape[:2]
    if not (0 <= col_px < w):
        return None
    y0, y1 = max(0, y_range[0]), min(h, y_range[1])
    cols = gray[y0:y1, max(0, col_px - 2):col_px + 3]
    col = np.median(cols, axis=1)
    bright = col >= threshold
    if not bright.any():
        return None
    edges = np.flatnonzero(np.diff(np.concatenate(([0], bright.view(np.int8), [0]))))
    runs = edges.reshape(-1, 2)
    best = int((runs[:, 1] - runs[:, 0]).max())
    if min_h <= best <= max_h:
        return best
    return None


def probe_width_px(frame: Optional[np.ndarray], reference_x: int,
                   y_range: Tuple[int, int], threshold: int,
                   offsets: Tuple[int, ...] = (-10, -8, -6, -4, -2, 0, 2, 4, 6, 8, 10),
                   min_h: int = 8, max_h: int = 130) -> Tuple[Optional[int], int]:
    """Return a robust raw board-width probe in pixels.

    This deliberately has no millimetre conversion or product classification.
    It samples a narrow column fan around a calibrated distance from the fence,
    rather than the origin edge, so a fishtail cannot set the result.
    """
    if frame is None:
        return None, 0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    runs = [
        run for offset in offsets
        if (run := _column_run(gray, reference_x + offset, y_range,
                               threshold, min_h, max_h)) is not None
    ]
    if not runs:
        return None, 0
    return int(round(float(np.median(runs)))), len(runs)


def _board_profile(gray: np.ndarray, y_range: Tuple[int, int],
                   cfg: MeasureConfig) -> np.ndarray:
    """Boolean per sampled column: does a plausible board run exist here?
    Sampled every cfg.profile_step_px across the frame width."""
    w = gray.shape[1]
    xs = np.arange(0, w, cfg.profile_step_px)
    prof = np.zeros(xs.size, dtype=bool)
    for i, x in enumerate(xs):
        prof[i] = _column_run(gray, int(x), y_range, cfg.width_scan_threshold,
                              cfg.presence_min_height_px,
                              cfg.presence_max_height_px) is not None
    return prof


def _presence_and_extent(frame: np.ndarray, empty_gray: Optional[np.ndarray],
                         y_range: Tuple[int, int], cfg: MeasureConfig
                         ) -> Tuple[bool, Optional[int], Optional[int]]:
    """Board presence + horizontal extent inside the stopped-board y-window.

    Primary detector: background subtraction against the empty-deck
    reference — a column belongs to the board where its pixels CHANGED.
    This works regardless of exposure, wood colour, grain shadows, or
    bright static structure behind the board (the classic fixed-camera
    stopped-object answer). Falls back to bright-run profiling when no
    empty reference is configured.

    Returns (present, x_start_px, x_end_px).
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    h = gray.shape[0]
    y0, y1 = max(0, y_range[0]), min(h, y_range[1])

    if empty_gray is not None and empty_gray.shape == gray.shape:
        win_now = gray[y0:y1, :].astype(np.int16)
        win_ref = empty_gray[y0:y1, :].astype(np.int16)
        col_diff = np.abs(win_now - win_ref).mean(axis=0)
        # smooth over ~9 px so single hot pixels / wires don't count
        kernel = np.ones(9) / 9.0
        col_diff = np.convolve(col_diff, kernel, mode="same")
        board_cols = col_diff >= cfg.empty_diff_min
        mode = "bg-subtract"
    elif cfg.require_empty_reference:
        logger.warning("[PRESENCE] no usable empty reference: measurement held")
        return False, None, None
    else:
        prof = _board_profile(gray, (y0, y1), cfg)
        board_cols = np.repeat(prof, cfg.profile_step_px)[:gray.shape[1]]
        mode = "bright-run (no empty ref)"

    xs = np.flatnonzero(board_cols)
    if xs.size == 0:
        logger.info("[PRESENCE] %s: no changed columns -> no board", mode)
        return False, None, None
    filled_px = int(xs.size)
    present = filled_px >= cfg.presence_min_span_px
    x0, x1 = int(xs[0]), int(xs[-1])
    logger.info("[PRESENCE] %s: filled=%d px (min %d) -> %s  extent=%d..%d",
                mode, filled_px, cfg.presence_min_span_px,
                "BOARD" if present else "no board", x0, x1)
    return present, x0, x1


def _width_by_bg_subtract(frame: np.ndarray, empty_gray: Optional[np.ndarray],
                          col_px: int, y_range: Tuple[int, int],
                          cfg: MeasureConfig) -> Optional[int]:
    """Board thickness at one column as the vertical extent of CHANGED pixels
    vs the empty scene — robust to grain shadows fragmenting bright runs."""
    if empty_gray is None:
        return None
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    if empty_gray.shape != gray.shape:
        return None
    h, w = gray.shape
    if not (0 <= col_px < w):
        return None
    y0, y1 = max(0, y_range[0]), min(h, y_range[1])
    now = gray[y0:y1, max(0, col_px - 3):col_px + 4].astype(np.int16)
    ref = empty_gray[y0:y1, max(0, col_px - 3):col_px + 4].astype(np.int16)
    row_diff = np.abs(now - ref).mean(axis=1)
    changed = row_diff >= cfg.empty_diff_min
    ys = np.flatnonzero(changed)
    if ys.size < cfg.presence_min_height_px:
        return None
    height = int(ys[-1] - ys[0] + 1)
    if height > cfg.presence_max_height_px:
        return None
    return height


def _snap_width(width_mm: float) -> int:
    return min(STANDARD_WIDTHS_MM, key=lambda s: abs(s - width_mm))


def _select_standard_saw(measured_length_mm: float) -> int:
    """Standard saw whose final length is closest to the measured length,
    without exceeding the raw board (can't cut wood that isn't there):
    prefer the longest standard <= measured; fall back to nearest."""
    fits = {b: L for b, L in STANDARD_LENGTH_SAWS.items() if L <= measured_length_mm + 30}
    pool = fits if fits else STANDARD_LENGTH_SAWS
    best = min(pool, key=lambda b: abs(pool[b] - measured_length_mm))
    logger.info("[STANDARD] measured=%.0f mm -> saw bit %d (%s, final %d mm)",
                measured_length_mm, best, SAW_CALIBRATION[best]["label"],
                STANDARD_LENGTH_SAWS[best])
    return best


def _detect_fishtail(blob: BoardBlob, at_start: bool, cfg: MeasureConfig) -> bool:
    """Fishtail = the board thins toward its end (edge convergence)."""
    span = min(cfg.fishtail_span_px, blob.width_px)
    if span < 40:
        return False
    if at_start:
        cols = range(blob.x0, blob.x0 + span)
    else:
        cols = range(blob.x1 - span + 1, blob.x1 + 1)
    widths = [w for c in cols if (w := _width_at_column(blob, c)) is not None]
    if len(widths) < 20:
        return False
    half = len(widths) // 2
    inner = np.mean(widths[half:]) if at_start else np.mean(widths[:half])
    outer = np.mean(widths[:half]) if at_start else np.mean(widths[half:])
    ratio = outer / (inner + 1e-6)
    is_fish = ratio < cfg.fishtail_convergence_ratio
    if is_fish:
        logger.info("[FISHTAIL] %s end: outer/inner %.2f < %.2f",
                    "origin" if at_start else "far", ratio,
                    cfg.fishtail_convergence_ratio)
    return is_fish


def _stub_tearout(blob: BoardBlob, at_start: bool) -> bool:
    """STUB — tear-out follows fishtails; implement as calibration data grows."""
    return False


def measure_dual_camera(
    left_frame: Optional[np.ndarray],
    right_frame: Optional[np.ndarray],
    expected_width_mm: Optional[int],
    cfg: MeasureConfig,
) -> DualCameraResult:
    """
    Measure one board from the two stopped-position views.

    LEFT view: origin end against the fence (saws 0.0-3.0 visible).
    RIGHT view: far end (saws 3.6-6.6 visible).
    Either frame may be None (camera down) — measurement degrades gracefully
    but requires at least the RIGHT view for length.
    """
    res = DualCameraResult()

    if left_frame is None and right_frame is None:
        res.error = ERR_NO_FRAME
        res.notes.append("no frames from either camera")
        return res

    empty_l = _load_empty_ref(cfg.empty_ref_left)
    empty_r = _load_empty_ref(cfg.empty_ref_right)

    if cfg.require_empty_reference and (empty_l is None or empty_r is None):
        res.error = ERR_MEASURE_FAILED
        missing = []
        if empty_l is None:
            missing.append("LEFT")
        if empty_r is None:
            missing.append("RIGHT")
        res.notes.append("current empty-deck reference missing for " + "/".join(missing))
        return res

    # ---- presence + extent from stopped-position profiles (primary) ----
    l_present, l_x0, l_x1 = (False, None, None)
    r_present, r_x0, r_x1 = (False, None, None)
    if left_frame is not None:
        l_present, l_x0, l_x1 = _presence_and_extent(
            left_frame, empty_l, cfg.board_y_range_left, cfg)
    if right_frame is not None:
        r_present, r_x0, r_x1 = _presence_and_extent(
            right_frame, empty_r, cfg.board_y_range_right, cfg)
    res.left_board_present = l_present
    res.right_board_present = r_present

    if not l_present and not r_present:
        res.error = ERR_NO_BOARD
        res.notes.append("no board detected in either view (presence profiles)")
        return res

    # ---- width at the fixed 860 mm reference (LEFT view), snapped to standard ----
    width_raw_mm = 0.0
    if left_frame is not None and l_present:
        # Primary: changed-pixel extent vs empty scene; fallback: bright run
        wpx = _width_by_bg_subtract(left_frame, empty_l, cfg.width_line_px_left,
                                    cfg.board_y_range_left, cfg)
        if wpx is None:
            gray_l = cv2.cvtColor(left_frame, cv2.COLOR_BGR2GRAY) \
                if left_frame.ndim == 3 else left_frame
            wpx = _column_run(gray_l, cfg.width_line_px_left,
                              cfg.board_y_range_left, cfg.width_scan_threshold,
                              cfg.presence_min_height_px, cfg.presence_max_height_px)
        if wpx:
            ppm_y = cfg.px_per_mm_y or cfg.px_per_mm_left
            width_raw_mm = wpx / ppm_y
    if width_raw_mm <= 0 and expected_width_mm:
        width_raw_mm = float(expected_width_mm)
        res.notes.append("width fell back to PLC-provided value")
    if width_raw_mm > 0:
        res.width_raw_mm = round(width_raw_mm, 1)
        res.width_mm = _snap_width(width_raw_mm)
    else:
        res.notes.append("width not measurable (LEFT view) and no PLC width hint")
    logger.info("[WIDTH] raw=%.1f mm -> standard %d mm", width_raw_mm, res.width_mm)

    # ---- length from far-end position (RIGHT view) ----
    if not r_present:
        res.notes.append("RIGHT view missing/empty — cannot measure length")
        res.error = ERR_MEASURE_FAILED
        return res
    far_end_mm = cfg.right_view_x0_mm + r_x1 / max(cfg.px_per_mm_right, 1e-6)
    measured_length_mm = far_end_mm - SAW_CALIBRATION[0]["mm"]
    res.measured_length_mm = round(measured_length_mm, 0)

    # ---- fishtails / tear-out (blob-based; best effort under overexposure) ----
    blob_l = _find_board_blob(left_frame, cfg, cfg.empty_ref_left) \
        if (left_frame is not None and l_present) else None
    blob_r = _find_board_blob(right_frame, cfg, cfg.empty_ref_right) \
        if r_present else None
    if blob_l is not None:
        res.left_has_fishtail = _detect_fishtail(blob_l, at_start=True, cfg=cfg)
        res.left_has_tearout = _stub_tearout(blob_l, at_start=True)
    if blob_r is not None:
        res.right_has_fishtail = _detect_fishtail(blob_r, at_start=False, cfg=cfg)
        res.right_has_tearout = _stub_tearout(blob_r, at_start=False)
    if blob_l is None and blob_r is None:
        res.notes.append("fishtail check skipped (no clean blob under current exposure)")

    # ---- saw selection ----
    # Saw 0.0 always drops: squares the end grain and establishes the datum
    # every standard length is measured from. (WIDTH RULE exception — boards
    # narrower than 114 mm skip the origin trim — is enforced by the caller
    # via cfg once confirmed with real batches; grading tool only WARNS.)
    left_saw = 0
    right_saw = _select_standard_saw(measured_length_mm)
    res.left_saw_index = left_saw
    res.right_saw_index = right_saw
    res.saw_word = (1 << left_saw) | (1 << right_saw)
    res.length_mm = STANDARD_LENGTH_SAWS[right_saw]

    res.ok = True
    res.error = ERR_NONE

    # ---- annotations ----
    def _annotate(frame, blob, label):
        ann = frame.copy()
        if blob is not None:
            cv2.rectangle(ann, (blob.x0, blob.y0), (blob.x1, blob.y1), (0, 255, 255), 2)
        cv2.putText(ann, label, (10, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
        return ann

    if left_frame is not None:
        res.annotated_left = _annotate(
            left_frame, blob_l,
            "W:%d mm  saw0(datum)  fish:%s" % (res.width_mm, "Y" if res.left_has_fishtail else "N"))
    if right_frame is not None:
        res.annotated_right = _annotate(
            right_frame, blob_r,
            "L:%.0f->%d mm  saw%d(%s)  fish:%s" % (
                measured_length_mm, res.length_mm, right_saw,
                SAW_CALIBRATION[right_saw]["label"],
                "Y" if res.right_has_fishtail else "N"))

    logger.info("[RESULT] ok width=%d mm length=%d mm saws=0+%d word=0x%04X",
                res.width_mm, res.length_mm, right_saw, res.saw_word)
    return res
