"""Capture current, confirmed-empty camera references for board measurement.

This tool reads RTSP only.  It never contacts the PLC and never changes camera
configuration.  Its default output is a review candidate.  `--activate` only
updates vision_host.yaml when the operator has explicitly confirmed the deck is
clear with `--confirm-empty`.
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml


def read_samples(name: str, url: str, count: int) -> list[np.ndarray]:
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        raise RuntimeError(f"{name}: could not open RTSP stream")
    frames = []
    deadline = time.monotonic() + max(30.0, count * 2.0)
    try:
        while len(frames) < count and time.monotonic() < deadline:
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.1)
                continue
            frames.append(frame)
            time.sleep(0.12)
    finally:
        cap.release()
    if len(frames) != count:
        raise RuntimeError(f"{name}: received only {len(frames)}/{count} frames")
    return frames


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture an empty-deck RTSP reference pair")
    ap.add_argument("--config", default="vision_host.yaml")
    ap.add_argument("--frames", type=int, default=25)
    ap.add_argument("--out-dir", default="captures/empty_references")
    ap.add_argument("--confirm-empty", action="store_true",
                    help="operator confirms there is no production board in either view")
    ap.add_argument("--activate", action="store_true",
                    help="write the captured paths into measurement.empty_ref_*")
    args = ap.parse_args()
    if args.frames < 5:
        ap.error("--frames must be at least 5")
    if args.activate and not args.confirm_empty:
        ap.error("--activate requires --confirm-empty")

    cfg_path = Path(args.config).resolve()
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cams = cfg["cameras"]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = cfg_path.parent / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        left = read_samples("LEFT", cams["left_rtsp"], args.frames)
        right = read_samples("RIGHT", cams["right_rtsp"], args.frames)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outputs = {}
    for name, frames in (("left", left), ("right", right)):
        median = np.median(np.stack(frames, axis=0), axis=0).astype(np.uint8)
        path = out_dir / f"empty_{name}_{stamp}.jpg"
        if not cv2.imwrite(str(path), median, [cv2.IMWRITE_JPEG_QUALITY, 95]):
            print(f"ERROR: could not write {path}", file=sys.stderr)
            return 1
        outputs[name] = path
        gray_stack = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames])
        print(f"{name.upper()}: {path}  temporal variation={gray_stack.std(axis=0).mean():.2f}")

    if args.activate:
        measurement = cfg["measurement"]
        measurement["empty_ref_left"] = outputs["left"].relative_to(cfg_path.parent).as_posix()
        measurement["empty_ref_right"] = outputs["right"].relative_to(cfg_path.parent).as_posix()
        cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
        print(f"Activated current empty references in {cfg_path}")
    else:
        print("Review these images. When the deck was confirmed empty, rerun with --confirm-empty --activate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
