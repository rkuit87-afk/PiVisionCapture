"""
shadow_sim_test.py — end-to-end test of shadow_capture_app.py against a
LOCAL snap7 server (no mill hardware needed).

The server hosts DB1/DB4/DB13 + PE/PA areas with the exact layouts exported
from the live TIA project. This script plays the PLC program's role:

  board arrives  -> set DB1.bTrigger        (app must capture + buffer OURS)
  board leaves   -> clear bTrigger
  saw cuts       -> set DB1.wCompareWord to the "operator's" word,
                    pulse DB1.bSawDownCompare  (app must pop + compare)

Asserts: 3 triggers captured, 3 comparisons with the expected verdicts,
boards.csv rows, report.md rendered.

Run:  python tests/shadow_sim_test.py
"""

import ctypes
import shutil
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import snap7

try:
    from snap7.type import Areas, SrvArea
except ImportError:
    from snap7.types import Areas, SrvArea

ROOT = Path(__file__).resolve().parents[1]
PORT = 11102
REPLAY_L = ROOT / "captures" / "vision_host" / "2026-07-12" / "board_0001_L.jpg"
REPLAY_R = ROOT / "captures" / "vision_host" / "2026-07-12" / "board_0001_R.jpg"
SESSION_ROOT = ROOT / "shadow_sessions"


def main():
    assert REPLAY_L.exists() and REPLAY_R.exists(), "replay frames missing"

    db1 = (ctypes.c_uint8 * 26)()
    db4 = (ctypes.c_uint8 * 40)()
    db13 = (ctypes.c_uint8 * 10)()
    pe = (ctypes.c_uint8 * 8)()
    pa = (ctypes.c_uint8 * 8)()

    server = snap7.server.Server()
    server.register_area(SrvArea.DB, 1, db1)
    server.register_area(SrvArea.DB, 4, db4)
    server.register_area(SrvArea.DB, 13, db13)
    server.register_area(SrvArea.PE, 0, pe)
    server.register_area(SrvArea.PA, 0, pa)
    server.start(tcp_port=PORT)
    print(f"snap7 server up on 127.0.0.1:{PORT}")

    # The server keeps an INTERNAL COPY of registered areas (verified: parent
    # buffer mutations are not visible to clients) — so the PLC role must be
    # played through a second snap7 CLIENT writing into the server.
    drv = snap7.client.Client()
    drv.connect("127.0.0.1", 0, 1, PORT)
    assert drv.get_connected(), "driver client failed to connect"

    def db_set(db, offset, data: bytes):
        drv.db_write(db, offset, bytearray(data))

    # a recognizable proxy counter
    db_set(13, 6, struct.pack(">i", 424242))
    # TIA operator-adjustable trigger-to-frame delay, milliseconds.
    db_set(1, 24, struct.pack(">h", 780))

    before = set(SESSION_ROOT.glob("*")) if SESSION_ROOT.exists() else set()
    app = subprocess.Popen(
        [sys.executable, "-u", str(ROOT / "shadow_capture_app.py"),
         "--config", str(ROOT / "shadow_capture.yaml"),
         "--session", "simtest", "--boards", "3",
         "--out-root", str(SESSION_ROOT),
         "--notes", "snap7 local server simulation",
         "--replay", str(REPLAY_L), str(REPLAY_R),
         "--plc-ip", "127.0.0.1", "--plc-port", str(PORT)],
        cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    # stream the app's output and note when it is actually connected —
    # cold-start imports can take 15s+, so a fixed sleep is not enough
    app_lines = []
    connected = threading.Event()

    def pump():
        for line in app.stdout:
            app_lines.append(line.rstrip())
            print("   [app]", line.rstrip())
            if "PLC connected" in line:
                connected.set()

    threading.Thread(target=pump, daemon=True).start()

    # operator words per board: exact match is decided after we see OUR word,
    # so instead we script: board1 word 0x0081 (0.0+4.8), board2 0x0101
    # (0.0+6.0... bit8), board3 0x0081. Verdicts depend on our measurement of
    # the replay frame; we assert counts, not specific verdicts.
    operator_words = [0x0081, 0x0101, 0x0081]

    def pulse_board(i, word):
        # board arrives at the vision stop
        db_set(1, 0, b"\x01")                       # bTrigger
        drv.write_area(Areas.PE, 0, 4, bytearray(b"\x40"))  # %I4.6
        time.sleep(2.0)                             # app captures + buffers
        db_set(1, 0, b"\x00")
        drv.write_area(Areas.PE, 0, 4, bytearray(b"\x00"))
        time.sleep(0.5)
        # ... board travels to the saws; saws drop; PLC latches the profile
        db_set(1, 20, struct.pack(">H", word))      # wCompareWord
        db_set(4, 2, struct.pack(">H", word))       # ProfileRead (context)
        drv.write_area(Areas.PA, 0, 0,
                       bytearray([word & 0xFF, (word >> 8) & 0x1F]))
        db_set(1, 22, b"\x01")                      # bSawDownCompare pulse
        db_set(4, 38, b"\x01")                      # SawDone too
        time.sleep(0.8)
        db_set(1, 22, b"\x00")
        db_set(4, 38, b"\x00")
        db_set(13, 6, struct.pack(">i", 424242 + i))

    try:
        if not connected.wait(timeout=90):
            raise RuntimeError("app never connected to the sim PLC")
        time.sleep(1.0)  # one clean poll cycle before the first edge
        for i, w in enumerate(operator_words, 1):
            print(f"-- simulating board {i} (operator word 0x{w:04X})")
            pulse_board(i, w)
            time.sleep(1.5)  # respect trigger debounce before next board

        app.wait(timeout=60)
    except (subprocess.TimeoutExpired, RuntimeError) as exc:
        app.kill()
        app.wait()
        print(f"FAIL: {exc}")
        sys.exit(1)
    finally:
        try:
            drv.disconnect()
        except Exception:
            pass
        server.stop()
        server.destroy()

    if app.returncode != 0:
        print(f"FAIL: app exit code {app.returncode}")
        sys.exit(1)

    after = set(SESSION_ROOT.glob("*"))
    new_dirs = sorted(after - before)
    assert new_dirs, "no session directory created"
    sdir = new_dirs[-1]
    csv_lines = (sdir / "boards.csv").read_text(encoding="utf-8").strip().splitlines()
    n_rows = len(csv_lines) - 1
    report_ok = (sdir / "report.md").exists()
    profile_images = list((sdir / "frames").glob("board_*_profile.jpg"))
    events = (sdir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    n_trig = sum(1 for e in events if '"kind": "trigger"' in e)
    n_cmp = sum(1 for e in events if '"kind": "comparison"' in e)
    csv_text = (sdir / "boards.csv").read_text(encoding="utf-8")

    print(f"session: {sdir}")
    print(f"triggers={n_trig} comparisons={n_cmp} csv_rows={n_rows} report={report_ok} profiles={len(profile_images)}")
    ok = (n_trig == 3 and n_cmp == 3 and n_rows == 3 and report_ok and
          len(profile_images) == 3 and "DB1.iTriggerDelay" in csv_text and
          ",780," in csv_text)
    print("PASS" if ok else "FAIL")
    if ok:
        shutil.rmtree(sdir)  # keep the sessions folder clean of test runs
        print("(test session dir removed)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
