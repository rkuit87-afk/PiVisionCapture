import argparse
import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dual_camera_measure import SAW_CALIBRATION


def word_int(value):
    text = str(value)
    return int(text, 16) if text.startswith("0x") else int(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="shadow_sessions/2026-07-13_111327_operator_baseline_50")
    ap.add_argument("--px-per-mm-right", type=float, default=0.31057)
    args = ap.parse_args()

    session = Path(args.session)
    boards_csv = session / "boards.csv"
    analysis_csv = session / "analysis" / "analysis.csv"

    right_x1 = {}
    with analysis_csv.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["side"] == "R" and row["bright_x1"]:
                right_x1[int(row["board"])] = int(row["bright_x1"])

    estimates = []
    with boards_csv.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            board = int(row["board"])
            if board not in right_x1:
                continue
            actual = word_int(row["actual_word"])
            bits = [b for b in SAW_CALIBRATION if actual & (1 << b)]
            right_bits = [b for b in bits if SAW_CALIBRATION[b]["camera"] == "RIGHT"]
            if not right_bits:
                continue
            trailing = max(right_bits, key=lambda b: SAW_CALIBRATION[b]["mm"])
            saw_mm = SAW_CALIBRATION[trailing]["mm"]
            inferred_x0 = saw_mm - (right_x1[board] / args.px_per_mm_right)
            estimates.append((board, trailing, SAW_CALIBRATION[trailing]["label"], right_x1[board], inferred_x0))

    if not estimates:
        print("No right-side operator saws matched to analysis rows.")
        return

    vals = np.array([e[4] for e in estimates], dtype=float)
    print("board,trailing_bit,trailing_saw,right_bright_x1,inferred_right_view_x0_mm")
    for e in estimates:
        print(f"{e[0]},{e[1]},{e[2]},{e[3]},{e[4]:.1f}")
    print()
    print(f"n={len(vals)} median={np.median(vals):.1f} mean={np.mean(vals):.1f} stdev={np.std(vals):.1f}")
    print("Current vision_host.yaml right_view_x0_mm is 3241.8")


if __name__ == "__main__":
    main()
