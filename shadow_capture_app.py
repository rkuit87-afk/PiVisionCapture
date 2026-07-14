"""
shadow_capture_app.py — READ-ONLY operator-shadow recorder.

Purpose: run ~100 boards while the OPERATOR makes every trim decision, and
record — per board, matched by the saw-done pulse, never by time — what the
operator did versus what our vision measurement would have commanded. Nothing
is written to the PLC; this app is invisible to the machine.

Per-board flow:
  1. Board-in-position trigger (DB1 bTrigger, or %I4.6 directly)
       -> grab LEFT+RIGHT frames, run measure_dual_camera()
       -> OUR prediction (saw word, length, width) is PUSHED onto a FIFO
       -> stop-position deviation vs the calibration board's reference frames
  2. Saw-done pulse (DB1 bSawDownCompare, or DB4 SawDone)
       -> read the ACTUAL applied profile (DB1 wCompareWord) + raw saw
          outputs (%QB0-1) + the PLC's own buffer state (DB4)
       -> POP the oldest prediction; write the matched comparison record.

The FIFO mirrors the PLC's own board buffer (DB4 CutData[0..3]): boards
between the vision trigger point and the saws are in flight; the saw-done
pulse retires exactly one from both buffers, keeping us aligned without any
clock assumptions.

Usage:
  python shadow_capture_app.py --session baseline --notes "operator only, no changes"
  python shadow_capture_app.py --session after_change1 --boards 100 --notes "..."
  python shadow_capture_app.py ... --replay L.jpg R.jpg     # canned frames (testing)

Stop with Ctrl+C at any time — the session report is written on exit.
"""

import argparse
import csv
import json
import logging
import os
import struct
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import snap7
import yaml

from dual_camera_measure import (
    ERR_NONE, MeasureConfig, SAW_CALIBRATION, measure_dual_camera, probe_width_px,
)
from vision_host_app import ReplaySource, grab_frame, measure_cfg_from

try:
    from snap7.type import Areas
except ImportError:  # older python-snap7
    from snap7.types import Areas

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("shadow")


# --------------------------------------------------------------------------
# Read-only PLC monitor. Deliberately has NO write methods.
# Offsets: openness/exports/2026-07-12_153302/db_layouts.json (verified live).
# --------------------------------------------------------------------------
class PlcMonitor:
    # DB1 currently ends at byte 23. iTriggerDelay is an optional INT at
    # byte 24 after the TIA DB member is added and downloaded.
    DB1_SIZE = 24
    DB4_SIZE = 40
    DB13_SIZE = 10

    def __init__(self, ip, rack=0, slot=1, tcp_port=102,
                 reconnect_delay_s=3.0, read_io=True,
                 db_vission=1, db_datahandler=4, db_mesurements=13):
        self.ip = ip
        self.rack = rack
        self.slot = slot
        self.tcp_port = tcp_port
        self.reconnect_delay_s = reconnect_delay_s
        self.read_io = read_io
        self.db1 = db_vission
        self.db4 = db_datahandler
        self.db13 = db_mesurements
        self._client = snap7.client.Client()
        self._connected = False
        self._delay_field_available = None

    @property
    def connected(self):
        return self._connected

    def ensure_connected(self) -> bool:
        if self._connected:
            return True
        try:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client.connect(self.ip, self.rack, self.slot, self.tcp_port)
            self._connected = bool(self._client.get_connected())
            if self._connected:
                logger.info("PLC connected (READ-ONLY): %s:%d", self.ip, self.tcp_port)
        except Exception as exc:
            self._connected = False
            logger.warning("PLC connect failed: %s", exc)
        if not self._connected:
            time.sleep(self.reconnect_delay_s)
        return self._connected

    def snapshot(self) -> dict:
        """One read pass over everything we observe. Raises on comms error."""
        try:
            d1 = self._client.db_read(self.db1, 0, self.DB1_SIZE)
            delay_ms = None
            if self._delay_field_available is not False:
                try:
                    delay_ms = struct.unpack(">h", self._client.db_read(self.db1, 24, 2))[0]
                    self._delay_field_available = True
                except Exception:
                    if self._delay_field_available is None:
                        logger.info("DB1.iTriggerDelay is not present; using YAML frame delay")
                    self._delay_field_available = False
            d4 = self._client.db_read(self.db4, 0, self.DB4_SIZE)
            d13 = self._client.db_read(self.db13, 0, self.DB13_SIZE)
            io = {}
            if self.read_io:
                ib4 = self._client.read_area(Areas.PE, 0, 4, 1)
                qb = self._client.read_area(Areas.PA, 0, 0, 2)
                io = {
                    "pe_trigger": bool(ib4[0] & 0x40),  # PE_VissionTrigger %I4.6
                    "q_saw_bytes": [qb[0], qb[1]],
                    # %Q0.0-%Q1.4 -> saw bits 0..10 in tape-table order
                    "q_saw_word": qb[0] | ((qb[1] & 0x1F) << 8),
                }
        except Exception:
            self._connected = False
            raise
        return {
            "db1": {
                "bTrigger": bool(d1[0] & 0x01),
                "iBoardWidth": struct.unpack_from(">h", d1, 2)[0],
                "bAck": bool(d1[4] & 0x01),
                "bResultValid": bool(d1[4] & 0x02),
                "bError": bool(d1[4] & 0x04),
                "wSawWord": struct.unpack_from(">H", d1, 6)[0],
                "iLengthMM": struct.unpack_from(">h", d1, 8)[0],
                "iWidthMM": struct.unpack_from(">h", d1, 10)[0],
                "iBoardCount": struct.unpack_from(">h", d1, 12)[0],
                "iHeartbeat": struct.unpack_from(">h", d1, 16)[0],
                "wCompareWord": struct.unpack_from(">H", d1, 20)[0],
                "bSawDownCompare": bool(d1[22] & 0x01),
                "iTriggerDelay": delay_ms,
            },
            "db4": {
                "ProfileSelectrion": struct.unpack_from(">H", d4, 0)[0],
                "ProfileRead": struct.unpack_from(">H", d4, 2)[0],
                "Exception": bool(d4[4] & 0x01),
                "ProfileEn": bool(d4[4] & 0x02),
                "CountBuffer": [struct.unpack_from(">H", d4, 6 + 2 * i)[0] for i in range(4)],
                "CutData": [
                    {"dist": struct.unpack_from(">i", d4, 14 + 6 * i)[0],
                     "profile": struct.unpack_from(">H", d4, 18 + 6 * i)[0]}
                    for i in range(4)
                ],
                "SawDone": bool(d4[38] & 0x01),
            },
            "db13": {
                "thickness_raw": struct.unpack_from(">h", d13, 0)[0],
                "thickness_scaled": struct.unpack_from(">f", d13, 2)[0],
                "proxy_count": struct.unpack_from(">i", d13, 6)[0],
            },
            "io": io,
        }

    def disconnect(self):
        try:
            self._client.disconnect()
        except Exception:
            pass
        self._connected = False


class BufferedCameraReader:
    """Keep a timestamped JPEG history so trigger-relative frames are selectable.

    The RTSP session stays open. Trigger handling only chooses frames already in
    the history (or waits briefly for a configured positive offset), avoiding
    connection startup latency in the measurement timing.
    """

    def __init__(self, name, rtsp_url, history_s=5.0, jpeg_quality=90,
                 reconnect_delay_s=3.0):
        self.name = name
        self.rtsp_url = rtsp_url
        self.history_s = float(history_s)
        self.jpeg_quality = int(jpeg_quality)
        self.reconnect_delay_s = float(reconnect_delay_s)
        self._history = deque()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._connected = False
        self._thread = threading.Thread(target=self._reader_loop, daemon=True,
                                        name=f"cam-{name}")

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    @property
    def connected(self):
        return self._connected

    def nearest_frame(self, target_t, max_skew_s):
        with self._lock:
            if not self._history:
                return None, None
            jpg, captured_t = min(self._history, key=lambda item: abs(item[1] - target_t))
        if abs(captured_t - target_t) > max_skew_s:
            return None, captured_t
        frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
        return frame, captured_t

    def _reader_loop(self):
        while not self._stop.is_set():
            logger.info("[%s] connecting to %s", self.name, self.rtsp_url)
            cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                logger.warning("[%s] failed to open - retry in %.0fs", self.name,
                               self.reconnect_delay_s)
                time.sleep(self.reconnect_delay_s)
                continue
            logger.info("[%s] connected", self.name)
            self._connected = True
            try:
                while not self._stop.is_set():
                    ok, frame = cap.read()
                    captured_t = time.monotonic()
                    if not ok:
                        logger.warning("[%s] stream lost - reconnecting", self.name)
                        break
                    ok, jpg = cv2.imencode(".jpg", frame,
                                            [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
                    if not ok:
                        continue
                    with self._lock:
                        self._history.append((jpg.tobytes(), captured_t))
                        cutoff = captured_t - self.history_s
                        while self._history and self._history[0][1] < cutoff:
                            self._history.popleft()
            finally:
                self._connected = False
                cap.release()
            if not self._stop.is_set():
                time.sleep(self.reconnect_delay_s)


# --------------------------------------------------------------------------
# Stop-position measurement (bright-run based; no empty reference needed, so
# it works identically on the reference frames and on live frames)
# --------------------------------------------------------------------------
def board_position(frame, y_search, mcfg: MeasureConfig, threshold=None):
    """Locate the board inside a generous y-window using per-column bright
    runs. Returns dict(x0, x1, y_center, span_px) or None.

    threshold: stop-position scans use a LOWER bar than width scans — the
    RIGHT view sits darker than the LEFT (measured 2026-07-12: board columns
    peak ~130-250 there, so 150 misses it)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    h, w = gray.shape
    y0, y1 = max(0, int(y_search[0])), min(h, int(y_search[1]))
    win = gray[y0:y1, :]
    step = max(2, mcfg.profile_step_px)
    xs, centers = [], []
    bright = win >= (threshold if threshold else mcfg.width_scan_threshold)
    for x in range(0, w, step):
        col = bright[:, x]
        if not col.any():
            continue
        idx = np.flatnonzero(np.diff(np.concatenate(([0], col.view(np.int8), [0]))))
        runs = idx.reshape(-1, 2)
        lengths = runs[:, 1] - runs[:, 0]
        k = int(np.argmax(lengths))
        if mcfg.presence_min_height_px <= lengths[k] <= mcfg.presence_max_height_px:
            xs.append(x)
            centers.append(y0 + (runs[k, 0] + runs[k, 1]) / 2.0)
    if len(xs) * step < mcfg.presence_min_span_px:
        return None
    return {
        "x0": int(xs[0]), "x1": int(xs[-1]),
        "y_center": float(np.median(centers)),
        "span_px": int(len(xs) * step),
    }


class StopReference:
    """Calibration-board resting position, measured once from the reference
    frames with the same detector used on live frames."""

    def __init__(self, left_path, right_path, mcfg: MeasureConfig, threshold=None):
        self.threshold = threshold
        self.left = self._load(left_path, mcfg.board_y_range_left, mcfg, "LEFT", threshold)
        self.right = self._load(right_path, mcfg.board_y_range_right, mcfg, "RIGHT", threshold)

    @staticmethod
    def _load(path, y_range, mcfg, tag, threshold=None):
        img = cv2.imread(str(path)) if path else None
        if img is None:
            logger.warning("[STOPREF] %s reference image missing: %s", tag, path)
            return None
        pad = 60  # search a little beyond the configured resting band
        pos = board_position(img, (y_range[0] - pad, y_range[1] + pad), mcfg, threshold)
        if pos:
            logger.info("[STOPREF] %s reference: x=%d..%d y_center=%.1f",
                        tag, pos["x0"], pos["x1"], pos["y_center"])
        else:
            logger.warning("[STOPREF] %s: no board found in reference image", tag)
        return pos

    def deviation(self, side, pos, mcfg: MeasureConfig):
        ref = self.left if side == "L" else self.right
        if ref is None or pos is None:
            return None
        ppm = mcfg.px_per_mm_left if side == "L" else mcfg.px_per_mm_right
        return {
            "dy_px": round(pos["y_center"] - ref["y_center"], 1),
            "dx_fence_px": pos["x0"] - ref["x0"],
            "dx_far_px": pos["x1"] - ref["x1"],
            "dx_far_mm": round((pos["x1"] - ref["x1"]) / max(ppm, 1e-6), 1),
        }


# --------------------------------------------------------------------------
# Session recording
# --------------------------------------------------------------------------
CSV_FIELDS = [
    "board", "t_trigger", "t_candidate", "t_commit", "t_sawdone", "candidate_word", "commit_word", "our_word", "actual_word", "q_saw_word",
    "match", "our_length_mm", "our_width_mm", "our_error",
    "our_saws", "actual_saws", "dy_left_px", "dy_right_px",
    "dx_far_right_px", "dx_far_right_mm", "left_frame_offset_s",
    "right_frame_offset_s", "proxy_count", "profile_read",
    "delay_requested_ms", "delay_source",
    "width_probe_px", "width_probe_samples", "width_probe_reference_x",
    "width_under_100_candidate",
    "notes",
]


def word_to_saws(word):
    return "+".join(SAW_CALIBRATION[b]["label"] for b in range(16)
                    if word & (1 << b) and b in SAW_CALIBRATION) or "-"


def classify(our, actual):
    if our == actual:
        return "EXACT"
    both = bin(our & actual).count("1")
    if both and bin(our ^ actual).count("1") <= 2:
        return "CLOSE"  # shares a saw, differs by at most one saw each way
    return "MISS"


def render_profile_comparison(session_dir, board, our_word, actual_word, q_word,
                              verdict, saw_lines):
    """Render a visual record of the decision actually applied to one board."""
    frames_dir = Path(session_dir) / "frames"
    left = cv2.imread(str(frames_dir / f"board_{board:04d}_L.jpg"))
    right = cv2.imread(str(frames_dir / f"board_{board:04d}_R.jpg"))
    if left is None and right is None:
        return None

    def mark(frame, side):
        if frame is None:
            return None
        out = frame.copy()
        h, _ = out.shape[:2]
        for raw_bit, raw_x in (saw_lines.get(side, {}) or {}).items():
            bit, x = int(raw_bit), int(raw_x)
            ours = bool(our_word is not None and our_word & (1 << bit))
            actual = bool(actual_word & (1 << bit))
            if not ours and not actual:
                continue
            color = (0, 220, 255) if ours and actual else \
                ((0, 210, 0) if ours else (0, 0, 255))
            label = SAW_CALIBRATION.get(bit, {"label": str(bit)})["label"]
            cv2.line(out, (x, 0), (x, h - 1), color, 3)
            cv2.putText(out, label, (max(2, x - 18), 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2, cv2.LINE_AA)
        return out

    left, right = mark(left, "left"), mark(right, "right")
    if left is None:
        left = np.zeros_like(right)
    if right is None:
        right = np.zeros_like(left)
    if left.shape[0] != right.shape[0]:
        right = cv2.resize(right, (int(right.shape[1] * left.shape[0] / right.shape[0]), left.shape[0]))
    canvas = cv2.hconcat([left, right])
    header_h = 155
    header = np.zeros((header_h, canvas.shape[1], 3), dtype=np.uint8)
    verdict_color = {"EXACT": (0, 210, 0), "CLOSE": (0, 220, 255),
                     "MISS": (0, 0, 255), "CAPTURED": (0, 220, 255)}[verdict]
    operator_line = f"OPERATOR / PLC: {word_to_saws(actual_word)}  (0x{actual_word:04X})"
    if q_word is not None:
        operator_line += f"   OUTPUTS: 0x{q_word:04X}"
    title = f"BOARD {board:04d}  {verdict}"
    cv2.putText(header, title, (30, 44),
                cv2.FONT_HERSHEY_SIMPLEX, 1.15, verdict_color, 3, cv2.LINE_AA)
    if our_word is None:
        cv2.putText(header, "CAPTURE-ONLY: applied PLC profile shown", (30, 88),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 220, 255), 2, cv2.LINE_AA)
    else:
        cv2.putText(header, f"COMMITTED: {word_to_saws(our_word)}  (0x{our_word:04X})", (30, 88),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 210, 0), 2, cv2.LINE_AA)
    cv2.putText(header, operator_line, (30, 132),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2, cv2.LINE_AA)
    legend = "red=PLC applied profile" if our_word is None else "green=committed  red=applied  yellow=both"
    cv2.putText(header, legend, (canvas.shape[1] - 610, 42),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (230, 230, 230), 1, cv2.LINE_AA)
    out_path = frames_dir / f"board_{board:04d}_profile.jpg"
    cv2.imwrite(str(out_path), cv2.vconcat([header, canvas]),
                [cv2.IMWRITE_JPEG_QUALITY, 92])
    return out_path


class Session:
    def __init__(self, out_root, name, notes, config_snapshot):
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.dir = Path(out_root) / f"{stamp}_{name}"
        (self.dir / "frames").mkdir(parents=True, exist_ok=True)
        self.events_path = self.dir / "events.jsonl"
        self.csv_path = self.dir / "boards.csv"
        self.meta = {
            "session": name,
            "started": datetime.now().isoformat(timespec="seconds"),
            "notes": notes,
            "config": config_snapshot,
        }
        (self.dir / "session_meta.yaml").write_text(
            yaml.safe_dump(self.meta, sort_keys=False), encoding="utf-8")
        self._csv = open(self.csv_path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._csv, fieldnames=CSV_FIELDS)
        self._writer.writeheader()

    def event(self, kind, payload):
        rec = {"t": datetime.now().isoformat(timespec="milliseconds"),
               "kind": kind, **payload}
        with open(self.events_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")

    def board_row(self, row):
        self._writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})
        self._csv.flush()

    def close(self):
        try:
            self._csv.close()
        except Exception:
            pass


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Read-only operator shadow recorder")
    ap.add_argument("--config", default="shadow_capture.yaml")
    ap.add_argument("--session", default="observe")
    ap.add_argument("--notes", default="")
    ap.add_argument("--boards", type=int, default=None,
                    help="stop after N completed comparisons (default from yaml)")
    ap.add_argument("--out-root", default=None,
                    help="override session output root (tests/local replay)")
    ap.add_argument("--replay", nargs=2, metavar=("LEFT_JPG", "RIGHT_JPG"),
                    help="serve canned frames instead of live cameras")
    ap.add_argument("--plc-ip", default=None, help="override PLC IP (tests)")
    ap.add_argument("--plc-port", type=int, default=None, help="override PLC port (tests)")
    ap.add_argument("--trigger-source", choices=["bTrigger", "pe_input"], default=None)
    ap.add_argument("--sawdone-source", choices=["bSawDownCompare", "SawDone"], default=None)
    ap.add_argument("--max-seconds", type=float, default=None,
                    help="stop after this many seconds regardless of boards (smoke tests)")
    args = ap.parse_args()

    scfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    vcfg = yaml.safe_load(Path(scfg["vision_config"]).read_text(encoding="utf-8"))
    mcfg = measure_cfg_from(vcfg)

    p = scfg["plc"]
    plc = PlcMonitor(
        ip=args.plc_ip or p["ip"], rack=p.get("rack", 0), slot=p.get("slot", 1),
        tcp_port=args.plc_port or p.get("tcp_port", 102),
        reconnect_delay_s=p.get("reconnect_delay_s", 3.0),
        read_io=bool(p.get("read_io", True)),
        db_vission=p.get("db_vission", 1),
        db_datahandler=p.get("db_datahandler", 4),
        db_mesurements=p.get("db_mesurements", 13),
    )

    trig_src = args.trigger_source or scfg["trigger"]["source"]
    trig_min_s = float(scfg["trigger"].get("min_interval_s", 2.0))
    done_src = args.sawdone_source or scfg["saw_done"]["source"]
    done_min_s = float(scfg["saw_done"].get("min_interval_s", 1.0))
    max_depth = int(scfg["buffer"].get("max_depth", 8))
    capture_only = bool(scfg.get("comparison", {}).get("capture_only", False))
    commit_source = scfg.get("comparison", {}).get("commit_source", "profile_selection_candidate")
    commit_min_s = float(scfg.get("comparison", {}).get("commit_min_interval_s", 0.15))
    target_boards = args.boards or int(scfg["session"].get("boards", 100))
    align_cfg = scfg.get("frame_alignment", {})
    history_s = float(align_cfg.get("history_s", 5.0))
    left_offset_s = float(align_cfg.get("left_offset_s", 0.0))
    right_offset_s = float(align_cfg.get("right_offset_s", 0.0))
    frame_max_skew_s = float(align_cfg.get("max_skew_s", 0.75))
    delay_db_cfg = align_cfg.get("delay_from_db1", {})
    delay_db_enabled = bool(delay_db_cfg.get("enabled", True))
    delay_db_min_ms = int(delay_db_cfg.get("min_ms", 1))
    delay_db_max_ms = int(delay_db_cfg.get("max_ms", int(history_s * 1000)))
    width_probe_cfg = scfg.get("width_probe", {})
    width_probe_enabled = bool(width_probe_cfg.get("enabled", False))
    width_probe_x = int(width_probe_cfg.get("reference_x_left", 0))
    width_probe_y_range = tuple(width_probe_cfg.get("y_range_left", mcfg.board_y_range_left))
    width_probe_threshold = int(width_probe_cfg.get("scan_threshold", 125))
    width_probe_offsets = tuple(int(v) for v in width_probe_cfg.get(
        "sample_offsets_px", [-10, -8, -6, -4, -2, 0, 2, 4, 6, 8, 10]))
    width_probe_min_h = int(width_probe_cfg.get("min_run_px", 8))
    width_probe_max_h = int(width_probe_cfg.get("max_run_px", 130))
    width_probe_cutoff = width_probe_cfg.get("under_100_cutoff_px")

    if args.replay:
        cam_l = ReplaySource("left-replay", args.replay[0]).start()
        cam_r = ReplaySource("right-replay", args.replay[1]).start()
    else:
        left_url = os.environ.get("CAM_LEFT_RTSP_URL") or vcfg["cameras"]["left_rtsp"]
        right_url = os.environ.get("CAM_RIGHT_RTSP_URL") or vcfg["cameras"]["right_rtsp"]
        cam_l = BufferedCameraReader("left", left_url, history_s=history_s).start()
        cam_r = BufferedCameraReader("right", right_url, history_s=history_s).start()

    stop_thr = int(scfg.get("stop_position", {}).get("scan_threshold", 125))
    ref = StopReference(scfg["stop_reference"].get("left_image"),
                        scfg["stop_reference"].get("right_image"), mcfg, stop_thr)

    session = Session(args.out_root or scfg["session"].get("out_root", "./shadow_sessions"),
                      args.session, args.notes,
                      {"shadow": scfg, "vision_measurement": vcfg["measurement"],
                       "saw_lines": vcfg.get("saw_lines")})
    logger.info("Session dir: %s", session.dir)
    logger.info("Trigger source: %s | saw-done source: %s | target boards: %d",
                trig_src, done_src, target_boards)
    logger.info("Frame alignment: LEFT %+0.3fs | RIGHT %+0.3fs | history %.1fs",
                left_offset_s, right_offset_s, history_s)
    if delay_db_enabled:
        logger.info("Frame delay control: DB1.iTriggerDelay (ms), valid range %d..%d; YAML is fallback",
                    delay_db_min_ms, delay_db_max_ms)
    logger.info("SHADOW MODE: no PLC writes will be performed. capture_only=%s commit=%s",
                capture_only, commit_source)
    if width_probe_enabled:
        logger.info("WIDTH PROBE: raw pixels at %d mm reference / x=%d; under-100 classification=%s",
                    width_probe_cfg.get("reference_mm_from_fence", "configured"), width_probe_x,
                    "armed" if width_probe_cutoff is not None else "not calibrated")

    fifo = deque()   # our in-flight predictions, oldest first
    poll_s = float(p.get("poll_interval_s", 0.02))
    prev_trig = prev_done = None   # unknown until first snapshot
    last_trig_t = last_done_t = last_commit_t = 0.0
    n_triggers = n_compared = 0
    tally = {"EXACT": 0, "CLOSE": 0, "MISS": 0, "CAPTURED": 0, "UNMATCHED": 0}

    def read_trigger(snap):
        return snap["io"].get("pe_trigger", False) if trig_src == "pe_input" \
            else snap["db1"]["bTrigger"]

    def read_done(snap):
        return snap["db4"]["SawDone"] if done_src == "SawDone" \
            else snap["db1"]["bSawDownCompare"]

    def aligned_frames(trigger_t, left_delay_s, right_delay_s):
        """Return trigger-relative camera frames and their actual offsets."""
        latest_target = trigger_t + max(left_delay_s, right_delay_s)
        if latest_target > time.monotonic():
            time.sleep(latest_target - time.monotonic())

        def choose(camera, offset):
            target_t = trigger_t + offset
            if isinstance(camera, BufferedCameraReader):
                frame, captured_t = camera.nearest_frame(target_t, frame_max_skew_s)
            else:  # ReplaySource for deterministic local tests.
                frame, captured_t = grab_frame(camera), time.monotonic()
            relative_t = None if captured_t is None else round(captured_t - trigger_t, 3)
            return frame, relative_t

        f_left, left_relative_t = choose(cam_l, left_delay_s)
        f_right, right_relative_t = choose(cam_r, right_delay_s)
        return f_left, f_right, {"left_frame_offset_s": left_relative_t,
                                  "right_frame_offset_s": right_relative_t,
                                  "left_target_offset_s": left_delay_s,
                                  "right_target_offset_s": right_delay_s}

    def handle_trigger(snap):
        nonlocal n_triggers
        n_triggers += 1
        bid = n_triggers
        t0 = datetime.now()
        t0_mono = time.monotonic()
        delay_ms = snap["db1"].get("iTriggerDelay")
        if (delay_db_enabled and delay_ms is not None and
                delay_db_min_ms <= delay_ms <= delay_db_max_ms):
            left_delay_s = right_delay_s = delay_ms / 1000.0
            delay_source = "DB1.iTriggerDelay"
        else:
            left_delay_s, right_delay_s = left_offset_s, right_offset_s
            delay_ms = int(round(max(left_offset_s, right_offset_s) * 1000))
            delay_source = "shadow_capture.yaml"
        f_l, f_r, frame_timing = aligned_frames(t0_mono, left_delay_s, right_delay_s)
        result = None if capture_only else measure_dual_camera(f_l, f_r, None, mcfg)
        width_probe, width_probe_samples = (None, 0)
        if width_probe_enabled:
            width_probe, width_probe_samples = probe_width_px(
                f_l, width_probe_x, width_probe_y_range, width_probe_threshold,
                width_probe_offsets, width_probe_min_h, width_probe_max_h)
        width_under_100 = (
            width_probe is not None and width_probe_cutoff is not None and
            width_probe <= float(width_probe_cutoff))

        pos_l = board_position(f_l, mcfg.board_y_range_left, mcfg, stop_thr) if f_l is not None else None
        pos_r = board_position(f_r, mcfg.board_y_range_right, mcfg, stop_thr) if f_r is not None else None
        dev_l = ref.deviation("L", pos_l, mcfg)
        dev_r = ref.deviation("R", pos_r, mcfg)

        for tag, frame in (("L", f_l), ("R", f_r)):
            if frame is not None:
                cv2.imwrite(str(session.dir / "frames" / f"board_{bid:04d}_{tag}.jpg"),
                            frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        for tag, ann in (("L", result.annotated_left if result else None),
                         ("R", result.annotated_right if result else None)):
            if ann is not None:
                cv2.imwrite(str(session.dir / "frames" / f"board_{bid:04d}_{tag}_ann.jpg"),
                            ann, [cv2.IMWRITE_JPEG_QUALITY, 88])

        pred = {
            "board": bid,
            "t_trigger": t0.isoformat(timespec="milliseconds"),
            "our_word": None if capture_only else result.saw_word,
            "candidate_word": None,
            "t_candidate": None,
            "commit_word": None,
            "t_commit": None,
            "our_length_mm": 0 if capture_only else result.length_mm,
            "our_width_mm": 0 if capture_only else result.width_mm,
            "our_error": 0 if capture_only else result.error,
            "measured_length_mm": 0 if capture_only else result.measured_length_mm,
            "dev_left": dev_l, "dev_right": dev_r,
            "frame_timing": frame_timing,
            "delay_requested_ms": delay_ms,
            "delay_source": delay_source,
            "proxy_count_at_trigger": snap["db13"]["proxy_count"],
            "db4_at_trigger": snap["db4"],
            "width_probe_px": width_probe,
            "width_probe_samples": width_probe_samples,
            "width_probe_reference_x": width_probe_x if width_probe_enabled else None,
            "width_under_100_candidate": width_under_100 if width_probe_cutoff is not None else None,
            "notes": "capture-only; no image measurement" if capture_only else "; ".join(result.notes),
        }
        fifo.append(pred)
        session.event("trigger", pred)
        left_frame_t = frame_timing["left_frame_offset_s"]
        right_frame_t = frame_timing["right_frame_offset_s"]
        width_log = (" width-probe=%spx/%d samples" % (width_probe, width_probe_samples)) \
            if width_probe_enabled else ""
        logger.info("[BOARD %d IN] %s%s | delay=%dms (%s) | frames L=%+0.3fs R=%+0.3fs | fifo=%d",
                    bid, "capture-only" if capture_only else
                    f"our=0x{result.saw_word:04X} ({word_to_saws(result.saw_word)}) len={result.length_mm} err={result.error}",
                    width_log,
                    delay_ms, delay_source,
                    left_frame_t if left_frame_t is not None else float("nan"),
                    right_frame_t if right_frame_t is not None else float("nan"), len(fifo))
        if len(fifo) > max_depth:
            logger.warning("FIFO depth %d > %d — saw-done pulses may be missed!",
                           len(fifo), max_depth)

    def handle_commit(snap):
        """Record the falling-edge candidate without treating it as a commit."""
        if commit_source == "disabled":
            return
        if commit_source != "profile_selection_candidate":
            logger.info("Commit source %s is not mapped; no candidate recorded", commit_source)
            return
        # FIFO is oldest-first: the first uncommitted board is due first.
        pred = next((p for p in fifo if p["candidate_word"] is None), None)
        if pred is None:
            session.event("candidate_unmatched", {"db4": snap["db4"]})
            logger.warning("[CANDIDATE] profile=0x%04X but capture FIFO has no pending board",
                           snap["db4"]["ProfileSelectrion"])
            return
        word = snap["db4"]["ProfileSelectrion"]
        pred["candidate_word"] = word
        pred["t_candidate"] = datetime.now().isoformat(timespec="milliseconds")
        pred["db4_at_candidate"] = snap["db4"]
        session.event("candidate", {"board": pred["board"], "t_trigger": pred["t_trigger"],
                                     "t_candidate": pred["t_candidate"], "candidate_word": word,
                                     "db4": snap["db4"]})
        logger.info("[CANDIDATE] board %d: profile=0x%04X (%s); not treated as committed", pred["board"], word,
                    word_to_saws(word))

    def handle_saw_done(snap):
        nonlocal n_compared
        t1 = datetime.now()
        actual = snap["db1"]["wCompareWord"]
        q_word = snap["io"].get("q_saw_word")
        if not fifo:
            tally["UNMATCHED"] += 1
            session.event("saw_done_unmatched", {
                "actual_word": actual, "q_saw_word": q_word, "db4": snap["db4"]})
            logger.warning("[SAW DONE] actual=0x%04X but our FIFO is EMPTY "
                           "(board fed before session start?)", actual)
            return
        pred = fifo.popleft()
        n_compared += 1
        committed = pred["commit_word"]
        verdict = classify(committed, actual) if committed is not None else "CAPTURED"
        tally[verdict] += 1
        row = {
            "board": pred["board"],
            "t_trigger": pred["t_trigger"],
            "t_candidate": pred["t_candidate"] or "",
            "t_commit": pred["t_commit"] or "",
            "t_sawdone": t1.isoformat(timespec="milliseconds"),
            "candidate_word": f"0x{pred['candidate_word']:04X}" if pred["candidate_word"] is not None else "",
            "commit_word": f"0x{committed:04X}" if committed is not None else "",
            "our_word": f"0x{pred['our_word']:04X}" if pred["our_word"] is not None else "",
            "actual_word": f"0x{actual:04X}",
            "q_saw_word": f"0x{q_word:04X}" if q_word is not None else "",
            "match": verdict,
            "our_length_mm": pred["our_length_mm"],
            "our_width_mm": pred["our_width_mm"],
            "our_error": pred["our_error"],
            "our_saws": word_to_saws(pred["our_word"]) if pred["our_word"] is not None else "",
            "actual_saws": word_to_saws(actual),
            "dy_left_px": (pred["dev_left"] or {}).get("dy_px", ""),
            "dy_right_px": (pred["dev_right"] or {}).get("dy_px", ""),
            "dx_far_right_px": (pred["dev_right"] or {}).get("dx_far_px", ""),
            "dx_far_right_mm": (pred["dev_right"] or {}).get("dx_far_mm", ""),
            "left_frame_offset_s": pred["frame_timing"]["left_frame_offset_s"],
            "right_frame_offset_s": pred["frame_timing"]["right_frame_offset_s"],
            "proxy_count": snap["db13"]["proxy_count"],
            "profile_read": f"0x{snap['db4']['ProfileRead']:04X}",
            "delay_requested_ms": pred["delay_requested_ms"],
            "delay_source": pred["delay_source"],
            "width_probe_px": pred["width_probe_px"] if pred["width_probe_px"] is not None else "",
            "width_probe_samples": pred["width_probe_samples"],
            "width_probe_reference_x": pred["width_probe_reference_x"] or "",
            "width_under_100_candidate": (
                "yes" if pred["width_under_100_candidate"] else "no"
                if pred["width_under_100_candidate"] is not None else ""),
            "notes": pred["notes"],
        }
        profile_path = render_profile_comparison(
            session.dir, pred["board"], pred["our_word"], actual, q_word, verdict,
            vcfg.get("saw_lines", {}))
        if profile_path:
            row["profile_image"] = str(profile_path.relative_to(session.dir))
        session.board_row(row)
        session.event("comparison", {**row, "db4_at_sawdone": snap["db4"]})
        logger.info("[COMPARE %d/%d] board %d: %s applied=%s  -> %s   "
                    "(EXACT %d | CLOSE %d | MISS %d)",
                    n_compared, target_boards, pred["board"],
                    "commit unavailable;" if committed is None else f"committed={word_to_saws(committed)};", word_to_saws(actual),
                    verdict, tally["EXACT"], tally["CLOSE"], tally["MISS"])

    last_status_t = time.monotonic()
    t_start = time.monotonic()
    try:
        while n_compared < target_boards:
            if args.max_seconds and (time.monotonic() - t_start) >= args.max_seconds:
                logger.info("--max-seconds %.0f reached — stopping.", args.max_seconds)
                break
            if time.monotonic() - last_status_t >= 30.0:
                last_status_t = time.monotonic()
                logger.info("[STATUS] waiting… triggers=%d compared=%d fifo=%d plc=%s",
                            n_triggers, n_compared, len(fifo),
                            "up" if plc.connected else "DOWN")
            if not plc.ensure_connected():
                prev_trig = prev_done = None
                continue
            try:
                snap = plc.snapshot()
            except Exception as exc:
                logger.error("PLC read failed — reconnecting: %s", exc)
                prev_trig = prev_done = None
                continue

            trig = read_trigger(snap)
            done = read_done(snap)
            now = time.monotonic()
            if prev_trig is not None:
                if trig and not prev_trig and (now - last_trig_t) >= trig_min_s:
                    last_trig_t = now
                    handle_trigger(snap)
                if (commit_source != "disabled" and not trig and prev_trig and
                        (now - last_commit_t) >= commit_min_s):
                    last_commit_t = now
                    handle_commit(snap)
                if done and not prev_done and (now - last_done_t) >= done_min_s:
                    last_done_t = now
                    handle_saw_done(snap)
            prev_trig, prev_done = trig, done
            time.sleep(poll_s)
        if n_compared >= target_boards:
            logger.info("Target of %d boards reached.", target_boards)
    except KeyboardInterrupt:
        logger.info("Interrupted — finalizing session.")
    finally:
        session.meta["ended"] = datetime.now().isoformat(timespec="seconds")
        session.meta["stats"] = {
            "triggers": n_triggers, "compared": n_compared,
            "pending_in_fifo": len(fifo), **tally,
        }
        (session.dir / "session_meta.yaml").write_text(
            yaml.safe_dump(session.meta, sort_keys=False), encoding="utf-8")
        for pred in fifo:
            session.event("pending_at_exit", pred)
        session.close()
        cam_l.stop()
        cam_r.stop()
        plc.disconnect()
        try:
            import shadow_report
            shadow_report.generate(session.dir)
        except Exception as exc:
            logger.warning("Report generation failed (rerun shadow_report.py): %s", exc)
        print(f"\nSession finished: {session.dir}")
        print(f"  triggers={n_triggers} compared={n_compared} "
              f"EXACT={tally['EXACT']} CLOSE={tally['CLOSE']} MISS={tally['MISS']} "
              f"unmatched_sawdone={tally['UNMATCHED']}")


if __name__ == "__main__":
    main()
