"""
calibrate_from_lines.py — derive pixel<->mm calibration from a marked board.

Procedure (per camera):
  1. Draw thick dark lines straight across the board face at KNOWN distances
     from the fence (measured with a tape from the board's fence end, board
     seated against the fence). Include one line at 860 mm (the 0.9 saw) in
     the LEFT view. 3-5 lines per view; 1 m spacing is fine.
  2. Put the board in the normal stopped position, snap a frame (this tool
     can snap it for you with --rtsp), or pass a saved image.
  3. Run:
       python calibrate_from_lines.py --image left.jpg  --mm 500 860 1500 2500
       python calibrate_from_lines.py --image right.jpg --mm 4000 5000 6000
     Add --y0/--y1 to restrict to the board's y-window if auto-find struggles.

The tool finds the dark line centres crossing the board, pairs them with the
given mm positions (left-to-right), fits px = a*mm + b, and prints the yaml
values: px_per_mm_<side>, right_view_x0_mm / width_line_px_left, plus fit
residuals so you can judge quality (aim < 3 px).
"""

import argparse
import sys

import cv2
import numpy as np


def snap(rtsp: str):
    cap = cv2.VideoCapture(rtsp, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        print("Could not open stream:", rtsp)
        sys.exit(1)
    ok, frame = False, None
    for _ in range(5):
        ok, frame = cap.read()
    cap.release()
    if not ok:
        print("No frame from stream")
        sys.exit(1)
    return frame


def find_board_band(gray: np.ndarray):
    """Rough board y-window: the row band with the highest brightness
    variance profile in the middle half of the frame (board = bright with
    dark marker lines = high variance)."""
    h, w = gray.shape
    rows = gray[:, w // 4: 3 * w // 4].astype(np.float32)
    var = rows.var(axis=1)
    var = np.convolve(var, np.ones(31) / 31.0, mode="same")
    yc = int(np.argmax(var[int(h * 0.1):int(h * 0.8)])) + int(h * 0.1)
    return max(0, yc - 70), min(h, yc + 70)


def find_dark_lines(gray: np.ndarray, y0: int, y1: int, n_expected: int):
    """Column positions of dark lines crossing the (bright) board band."""
    band = gray[y0:y1, :].astype(np.float32)
    prof = band.mean(axis=0)
    prof_s = np.convolve(prof, np.ones(7) / 7.0, mode="same")
    # dark dips below the local baseline
    baseline = np.convolve(prof_s, np.ones(151) / 151.0, mode="same")
    dip = baseline - prof_s
    thr = max(12.0, float(dip.max()) * 0.4)
    cand = dip > thr
    xs = np.flatnonzero(cand)
    if xs.size == 0:
        return []
    # group contiguous candidates into line centres
    groups = np.split(xs, np.flatnonzero(np.diff(xs) > 10) + 1)
    centres = [int(round(g.mean())) for g in groups if g.size >= 2]
    # strongest n_expected dips
    centres.sort(key=lambda c: -float(dip[c]))
    centres = sorted(centres[:n_expected])
    return centres


def main():
    ap = argparse.ArgumentParser(description="Pixel<->mm calibration from marked board")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--image", help="saved frame of the marked board in stop position")
    src.add_argument("--rtsp", help="snap a live frame from this RTSP url instead")
    ap.add_argument("--mm", type=float, nargs="+", required=True,
                    help="line positions in mm from the fence, left-to-right in the image")
    ap.add_argument("--y0", type=int, help="board band top (px); auto if omitted")
    ap.add_argument("--y1", type=int, help="board band bottom (px); auto if omitted")
    ap.add_argument("--save-debug", default=None, help="write annotated debug jpg here")
    args = ap.parse_args()

    frame = cv2.imread(args.image) if args.image else snap(args.rtsp)
    if frame is None:
        print("Could not load image")
        sys.exit(1)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    if args.y0 is not None and args.y1 is not None:
        y0, y1 = args.y0, args.y1
    else:
        y0, y1 = find_board_band(gray)
    print("board band: y=%d..%d" % (y0, y1))

    centres = find_dark_lines(gray, y0, y1, len(args.mm))
    print("detected line centres (px):", centres)
    if len(centres) != len(args.mm):
        print("ERROR: expected %d lines, found %d. Re-run with --y0/--y1 set to "
              "the board band, or thicken the marker lines." % (len(args.mm), len(centres)))
        if args.save_debug:
            dbg = frame.copy()
            for c in centres:
                cv2.line(dbg, (c, y0), (c, y1), (0, 0, 255), 2)
            cv2.rectangle(dbg, (0, y0), (frame.shape[1] - 1, y1), (0, 255, 255), 2)
            cv2.imwrite(args.save_debug, dbg)
            print("debug ->", args.save_debug)
        sys.exit(2)

    mm = np.array(sorted(args.mm), dtype=np.float64)
    px = np.array(centres, dtype=np.float64)

    # fit px = a*mm + b
    a, b = np.polyfit(mm, px, 1)
    fit = a * mm + b
    resid = px - fit
    print()
    print("fit: px = %.5f * mm + %.2f" % (a, b))
    print("residuals (px):", [round(float(r), 1) for r in resid],
          " max=%.1f" % float(np.abs(resid).max()))
    print()
    print("=== yaml values ===")
    print("px_per_mm (this camera): %.5f" % a)
    print("view_x0_mm (mm at pixel x=0): %.1f" % (-b / a))
    for m, p in zip(mm, px):
        print("  line %6.0f mm -> pixel x=%d" % (m, int(round(p))))
    if 860 in [round(v) for v in mm.tolist()]:
        i = [round(v) for v in mm.tolist()].index(860)
        print("width_line_px_left: %d   (the 860 mm / 0.9-saw line)" % int(round(px[i])))
    print("board_y_range for this view: [%d, %d]" % (max(0, y0 - 15), y1 + 15))

    if args.save_debug:
        dbg = frame.copy()
        for c, m in zip(centres, mm):
            cv2.line(dbg, (int(c), y0), (int(c), y1), (0, 0, 255), 2)
            cv2.putText(dbg, "%.0fmm" % m, (int(c) - 40, y0 - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.rectangle(dbg, (0, y0), (frame.shape[1] - 1, y1), (0, 255, 255), 2)
        cv2.imwrite(args.save_debug, dbg)
        print("debug ->", args.save_debug)


if __name__ == "__main__":
    main()
