import argparse
import csv
from pathlib import Path

import cv2
import numpy as np
import yaml


def load_gray(path):
    img = cv2.imread(str(path))
    if img is None:
        raise FileNotFoundError(path)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), img


def changed_extent(frame_gray, ref_gray, y_range, diff_min=25.0):
    y0, y1 = y_range
    now = frame_gray[y0:y1, :].astype(np.int16)
    ref = ref_gray[y0:y1, :].astype(np.int16)
    diff = np.abs(now - ref)
    col_diff = diff.mean(axis=0)
    row_diff = diff.mean(axis=1)
    col_mask = np.convolve(col_diff, np.ones(9) / 9.0, mode="same") >= diff_min
    row_mask = np.convolve(row_diff, np.ones(5) / 5.0, mode="same") >= diff_min
    xs = np.flatnonzero(col_mask)
    ys = np.flatnonzero(row_mask)
    return {
        "x0": int(xs[0]) if xs.size else None,
        "x1": int(xs[-1]) if xs.size else None,
        "y0": int(y0 + ys[0]) if ys.size else None,
        "y1": int(y0 + ys[-1]) if ys.size else None,
        "cols": int(xs.size),
        "rows": int(ys.size),
        "mean_diff": float(diff.mean()) if diff.size else 0.0,
    }


def bright_run_extent(frame_gray, y_range, threshold=125, min_h=15, max_h=280):
    y0, y1 = y_range
    win = frame_gray[y0:y1, :]
    bright = win >= threshold
    xs = []
    centers = []
    heights = []
    for x in range(0, bright.shape[1], 4):
        col = bright[:, x]
        if not col.any():
            continue
        edges = np.flatnonzero(np.diff(np.concatenate(([0], col.view(np.int8), [0]))))
        runs = edges.reshape(-1, 2)
        lengths = runs[:, 1] - runs[:, 0]
        k = int(np.argmax(lengths))
        if min_h <= lengths[k] <= max_h:
            xs.append(x)
            centers.append(y0 + (runs[k, 0] + runs[k, 1]) / 2)
            heights.append(lengths[k])
    if not xs:
        return None
    return {
        "x0": int(xs[0]),
        "x1": int(xs[-1]),
        "y_center": float(np.median(centers)),
        "height_median": float(np.median(heights)),
        "span": int(len(xs) * 4),
    }


def annotate(out_path, img, cfg, side, bg, bright):
    ann = img.copy()
    saws = cfg.get("saw_lines", {}).get("left" if side == "L" else "right", {})
    y_range = cfg["measurement"]["board_y_range_left" if side == "L" else "board_y_range_right"]
    cv2.rectangle(ann, (0, y_range[0]), (ann.shape[1] - 1, y_range[1]), (255, 0, 0), 2)
    if bg and bg["x0"] is not None and bg["y0"] is not None:
        cv2.rectangle(ann, (bg["x0"], bg["y0"]), (bg["x1"], bg["y1"]), (0, 255, 255), 2)
    if bright:
        cv2.line(ann, (bright["x0"], int(bright["y_center"])), (bright["x1"], int(bright["y_center"])), (0, 255, 0), 2)
    for bit, x in saws.items():
        cv2.line(ann, (int(x), 0), (int(x), ann.shape[0] - 1), (0, 0, 255), 1)
        cv2.putText(ann, str(bit), (int(x) + 4, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    cv2.imwrite(str(out_path), ann)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="shadow_sessions/2026-07-13_111327_operator_baseline_50")
    ap.add_argument("--config", default="vision_host.yaml")
    ap.add_argument("--boards", type=int, default=12)
    args = ap.parse_args()

    session = Path(args.session)
    frames = session / "frames"
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    m = cfg["measurement"]
    ref_l, _ = load_gray(m["empty_ref_left"])
    ref_r, _ = load_gray(m["empty_ref_right"])

    out_dir = session / "analysis"
    out_dir.mkdir(exist_ok=True)
    rows = []
    for i in range(1, args.boards + 1):
        for side, ref, y_key in (
            ("L", ref_l, "board_y_range_left"),
            ("R", ref_r, "board_y_range_right"),
        ):
            path = frames / f"board_{i:04d}_{side}.jpg"
            if not path.exists():
                continue
            gray, img = load_gray(path)
            y_range = tuple(m[y_key])
            bg = changed_extent(gray, ref, y_range, float(m.get("empty_diff_min", 25.0)))
            br = bright_run_extent(
                gray,
                y_range,
                threshold=125,
                min_h=int(m.get("presence_min_height_px", 15)),
                max_h=int(m.get("presence_max_height_px", 280)),
            )
            annotate(out_dir / f"board_{i:04d}_{side}_analysis.jpg", img, cfg, side, bg, br)
            rows.append({
                "board": i,
                "side": side,
                "bg_x0": bg["x0"],
                "bg_x1": bg["x1"],
                "bg_y0": bg["y0"],
                "bg_y1": bg["y1"],
                "bg_cols": bg["cols"],
                "bg_rows": bg["rows"],
                "bg_mean_diff": f"{bg['mean_diff']:.1f}",
                "bright_x0": br["x0"] if br else "",
                "bright_x1": br["x1"] if br else "",
                "bright_y_center": f"{br['y_center']:.1f}" if br else "",
                "bright_height_median": f"{br['height_median']:.1f}" if br else "",
                "bright_span": br["span"] if br else "",
            })

    csv_path = out_dir / "analysis.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"analysis -> {csv_path}")
    for side in ("L", "R"):
        sx = [r for r in rows if r["side"] == side]
        bg_cols = [int(r["bg_cols"]) for r in sx if r["bg_cols"]]
        br_heights = [float(r["bright_height_median"]) for r in sx if r["bright_height_median"]]
        br_spans = [int(r["bright_span"]) for r in sx if r["bright_span"]]
        print(side, "bg_cols median", np.median(bg_cols) if bg_cols else None,
              "bright_height median", np.median(br_heights) if br_heights else None,
              "bright_span median", np.median(br_spans) if br_spans else None)


if __name__ == "__main__":
    main()
