"""
Capture LEFT/RIGHT camera frames on a PLC trigger edge for board alignment.

Read-only: this script reads PLC state and camera streams only. It performs no
PLC writes. Use it to prove where the board physically lives at a chosen edge
of bTrigger or PE_VissionTrigger.
"""

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shadow_capture_app import PlcMonitor, board_position  # noqa: E402
from vision_host_app import CameraReader, grab_frame, measure_cfg_from  # noqa: E402


def read_trigger(snapshot, source):
    if source == "pe_input":
        return snapshot["io"].get("pe_trigger", False)
    return snapshot["db1"]["bTrigger"]


def draw_overlay(frame, side, pos, mcfg, saw_lines):
    ann = frame.copy()
    y_range = mcfg.board_y_range_left if side == "L" else mcfg.board_y_range_right
    cv2.rectangle(ann, (0, y_range[0]), (ann.shape[1] - 1, y_range[1]), (255, 0, 0), 2)
    if pos:
        cv2.rectangle(
            ann,
            (pos["x0"], int(pos["y_center"] - 12)),
            (pos["x1"], int(pos["y_center"] + 12)),
            (0, 255, 0),
            2,
        )
        cv2.line(ann, (pos["x0"], int(pos["y_center"])), (pos["x1"], int(pos["y_center"])), (0, 255, 0), 2)
    for bit, x in saw_lines.items():
        x = int(x)
        cv2.line(ann, (x, 0), (x, ann.shape[0] - 1), (0, 0, 255), 1)
        cv2.putText(ann, str(bit), (x + 4, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    return ann


def main():
    ap = argparse.ArgumentParser(description="Read-only edge-triggered alignment capture")
    ap.add_argument("--config", default="shadow_capture.yaml")
    ap.add_argument("--edge", choices=["falling", "rising"], default="falling")
    ap.add_argument("--source", choices=["bTrigger", "pe_input"], default="bTrigger")
    ap.add_argument("--captures", type=int, default=10)
    ap.add_argument("--out-root", default="sandbox/alignment_captures")
    ap.add_argument("--min-interval-s", type=float, default=0.5)
    ap.add_argument("--stop-threshold", type=int, default=None)
    args = ap.parse_args()

    scfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    vcfg = yaml.safe_load(Path(scfg["vision_config"]).read_text(encoding="utf-8"))
    mcfg = measure_cfg_from(vcfg)

    p = scfg["plc"]
    plc = PlcMonitor(
        ip=p["ip"],
        rack=p.get("rack", 0),
        slot=p.get("slot", 1),
        tcp_port=p.get("tcp_port", 102),
        reconnect_delay_s=p.get("reconnect_delay_s", 3.0),
        read_io=bool(p.get("read_io", True)),
        db_vission=p.get("db_vission", 1),
        db_datahandler=p.get("db_datahandler", 4),
        db_mesurements=p.get("db_mesurements", 13),
    )

    cam_l = CameraReader("left", vcfg["cameras"]["left_rtsp"]).start()
    cam_r = CameraReader("right", vcfg["cameras"]["right_rtsp"]).start()

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = Path(args.out_root) / f"{stamp}_{args.source}_{args.edge}"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    prev = None
    last_capture = 0.0
    n = 0
    poll_s = float(p.get("poll_interval_s", 0.02))
    threshold = args.stop_threshold or int(scfg.get("stop_position", {}).get("scan_threshold", 125))
    saws = vcfg.get("saw_lines", {})

    print(f"Alignment capture: source={args.source} edge={args.edge} captures={args.captures}")
    print(f"Output: {out_dir}")
    print("READ-ONLY: no PLC writes.")

    try:
        while n < args.captures:
            if not plc.ensure_connected():
                prev = None
                continue
            snap = plc.snapshot()
            trig = read_trigger(snap, args.source)
            now = time.monotonic()
            hit = False
            if prev is not None and (now - last_capture) >= args.min_interval_s:
                hit = (prev and not trig) if args.edge == "falling" else (trig and not prev)
            prev = trig
            if not hit:
                time.sleep(poll_s)
                continue

            last_capture = now
            n += 1
            ts = datetime.now().isoformat(timespec="milliseconds")
            left = grab_frame(cam_l)
            right = grab_frame(cam_r)
            rec = {"capture": n, "timestamp": ts, "source": args.source, "edge": args.edge}

            for side, frame, y_range, side_saws in (
                ("L", left, mcfg.board_y_range_left, saws.get("left", {})),
                ("R", right, mcfg.board_y_range_right, saws.get("right", {})),
            ):
                if frame is None:
                    rec[f"{side}_ok"] = False
                    continue
                pos = board_position(frame, y_range, mcfg, threshold)
                cv2.imwrite(str(out_dir / f"capture_{n:03d}_{side}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
                cv2.imwrite(
                    str(out_dir / f"capture_{n:03d}_{side}_overlay.jpg"),
                    draw_overlay(frame, side, pos, mcfg, side_saws),
                    [cv2.IMWRITE_JPEG_QUALITY, 90],
                )
                rec[f"{side}_ok"] = True
                rec[f"{side}_x0"] = pos["x0"] if pos else ""
                rec[f"{side}_x1"] = pos["x1"] if pos else ""
                rec[f"{side}_y_center"] = round(pos["y_center"], 1) if pos else ""
                rec[f"{side}_span_px"] = pos["span_px"] if pos else ""
            rows.append(rec)
            print(
                f"[{n}/{args.captures}] {ts} "
                f"L y={rec.get('L_y_center', '?')} span={rec.get('L_span_px', '?')} | "
                f"R y={rec.get('R_y_center', '?')} span={rec.get('R_span_px', '?')}"
            )

        csv_path = out_dir / "alignment.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            fields = sorted({k for row in rows for k in row.keys()})
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        print(f"Done. CSV: {csv_path}")
    finally:
        cam_l.stop()
        cam_r.stop()
        plc.disconnect()


if __name__ == "__main__":
    main()
