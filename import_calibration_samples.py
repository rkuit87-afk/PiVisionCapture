"""Import named LEFT_/RIGHT_ calibration pairs into a browseable shadow session."""

import argparse
import csv
import shutil
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml


def mark_saws(frame, side, saw_lines, active_word=None):
    out = frame.copy()
    height = out.shape[0]
    for bit, x in (saw_lines.get(side, {}) or {}).items():
        if active_word is not None and not (active_word & (1 << int(bit))):
            continue
        x = int(x)
        label = {0: "0.0", 1: "0.3", 2: "0.6", 3: "3.0", 4: "3.6",
                 5: "4.2", 6: "4.8", 7: "5.4", 8: "6.0", 9: "6.6"}.get(int(bit), str(bit))
        color = (0, 0, 255) if active_word is not None else (255, 220, 0)
        cv2.line(out, (x, 0), (x, height - 1), color, 3)
        cv2.putText(out, label, (max(2, x - 18), 30), cv2.FONT_HERSHEY_SIMPLEX,
                    0.75, color, 2, cv2.LINE_AA)
    return out


def overlay(left, right, saw_lines, title="CALIBRATION OVERLAY", subtitle="All saw positions from the measured fence calibration", active_word=None):
    left = mark_saws(left, "left", saw_lines, active_word)
    right = mark_saws(right, "right", saw_lines, active_word)
    if left.shape[0] != right.shape[0]:
        right = cv2.resize(right, (int(right.shape[1] * left.shape[0] / right.shape[0]), left.shape[0]))
    canvas = cv2.hconcat([left, right])
    header = np.zeros((112, canvas.shape[1], 3), dtype=np.uint8)
    cv2.putText(header, title, (28, 43), cv2.FONT_HERSHEY_SIMPLEX,
                1.1, (255, 220, 0), 3, cv2.LINE_AA)
    cv2.putText(header, subtitle, (28, 85),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (230, 230, 230), 2, cv2.LINE_AA)
    return cv2.vconcat([header, canvas])


def main():
    ap = argparse.ArgumentParser(description="Import LEFT_/RIGHT_ calibration samples")
    ap.add_argument("source", type=Path)
    ap.add_argument("--out-root", type=Path, default=Path("shadow_sessions"))
    ap.add_argument("--vision-config", type=Path, default=Path("vision_host.yaml"))
    ap.add_argument("--applied-word", default=None,
                    help="assumed applied saw word, e.g. 0x0F81")
    args = ap.parse_args()
    source = args.source.resolve()
    cfg = yaml.safe_load(args.vision_config.read_text(encoding="utf-8"))
    applied_word = int(args.applied_word, 0) if args.applied_word else None
    pairs = {}
    for path in source.glob("*.jpg"):
        parts = path.stem.split("_", 1)
        if len(parts) == 2 and parts[0] in ("LEFT", "RIGHT"):
            pairs.setdefault(parts[1], {})[parts[0]] = path
    pairs = {stamp: pair for stamp, pair in pairs.items() if set(pair) == {"LEFT", "RIGHT"}}
    if not pairs:
        raise SystemExit("No matching LEFT_/RIGHT_ JPG pairs found.")
    session = args.out_root / f"{datetime.now():%Y-%m-%d_%H%M%S}_calibration_samples"
    frames = session / "frames"
    frames.mkdir(parents=True)
    fields = ["board", "t_trigger", "t_sawdone", "commit_word", "actual_word", "match", "profile_image", "grading_image", "notes"]
    with (session / "boards.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for board, (stamp, pair) in enumerate(sorted(pairs.items()), 1):
            left_out, right_out = frames / f"board_{board:04d}_L.jpg", frames / f"board_{board:04d}_R.jpg"
            shutil.copy2(pair["LEFT"], left_out)
            shutil.copy2(pair["RIGHT"], right_out)
            left, right = cv2.imread(str(left_out)), cv2.imread(str(right_out))
            out = frames / f"board_{board:04d}_profile.jpg"
            title = f"SAMPLE APPLIED PROFILE 0x{applied_word:04X}" if applied_word is not None else "CALIBRATION OVERLAY"
            subtitle = "red = assumed applied saws" if applied_word is not None else "All saw positions from the measured fence calibration"
            cv2.imwrite(str(out), overlay(left, right, cfg["saw_lines"], title, subtitle, applied_word), [cv2.IMWRITE_JPEG_QUALITY, 92])
            pad = 90
            ly0, ly1 = cfg["measurement"]["board_y_range_left"]
            ry0, ry1 = cfg["measurement"]["board_y_range_right"]
            left_band = left[max(0, ly0 - pad):min(left.shape[0], ly1 + pad)]
            right_band = right[max(0, ry0 - pad):min(right.shape[0], ry1 + pad)]
            grading = frames / f"board_{board:04d}_grading.jpg"
            cv2.imwrite(str(grading), overlay(left_band, right_band, cfg["saw_lines"],
                                               "GRADING BAND", subtitle, applied_word),
                        [cv2.IMWRITE_JPEG_QUALITY, 95])
            note = "confirmed 750 ms reference pair" if stamp == "20260713_141322" else "calibration sample"
            writer.writerow({"board": board, "t_trigger": stamp,
                             "actual_word": f"0x{applied_word:04X}" if applied_word is not None else "",
                             "match": "SAMPLE" if applied_word is not None else "CALIBRATION",
                             "profile_image": out.name, "grading_image": grading.name, "notes": note})
    (session / "session_meta.yaml").write_text(yaml.safe_dump({"kind": "calibration_samples", "source": str(source), "pairs": len(pairs)}), encoding="utf-8")
    print(session.resolve())


if __name__ == "__main__":
    main()
