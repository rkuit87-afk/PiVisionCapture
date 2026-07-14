"""
plc_sim_tool.py — commissioning tool for the DB10 vision handshake.

Plays the PLC's side of the handshake so the whole loop can be tested
without the machine running (and before the PLC program drives DB10):

  Terminal 1:  python vision_host_app.py            (waits on bTrigger)
  Terminal 2:  python plc_sim_tool.py trigger       (acts as the PLC)
               python plc_sim_tool.py status        (see wSawWord etc.)
               python plc_sim_tool.py clear         (complete the handshake)

NOTE: byte 0 (bTrigger / iBoardWidth) is PLC-owned in production. Writing
it from here is for commissioning ONLY — do not run this against a CPU
whose program is actively driving DB10.

Usage:
  python plc_sim_tool.py status [--watch]
  python plc_sim_tool.py trigger [--width 114]
  python plc_sim_tool.py clear
"""

import argparse
import struct
import sys
import time

import snap7
import yaml

DB_SIZE = 24  # DB1 "DB_Vission" — layout verified via Openness export 2026-07-12


def load_plc_cfg(path="vision_host.yaml"):
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    return cfg["plc"]


def connect(p):
    client = snap7.client.Client()
    client.connect(p["ip"], p.get("rack", 0), p.get("slot", 1))
    if not client.get_connected():
        print("FAILED to connect to PLC at", p["ip"])
        sys.exit(1)
    return client


def decode(data: bytearray) -> dict:
    # Offsets verified against the live DB via Openness export 2026-07-12
    return {
        "bTrigger": bool(data[0] & 0x01),
        "iBoardWidth": struct.unpack_from(">h", data, 2)[0],
        "bAck": bool(data[4] & 0x01),
        "bResultValid": bool(data[4] & 0x02),
        "bError": bool(data[4] & 0x04),
        "wSawWord": struct.unpack_from(">H", data, 6)[0],
        "iLengthMM": struct.unpack_from(">h", data, 8)[0],
        "iWidthMM": struct.unpack_from(">h", data, 10)[0],
        "iBoardCount": struct.unpack_from(">h", data, 12)[0],
        "iErrorCode": struct.unpack_from(">h", data, 14)[0],
        "iHeartbeat": struct.unpack_from(">h", data, 16)[0],
        "iFeedSpeedCmd": struct.unpack_from(">h", data, 18)[0],
        "wCompareWord": struct.unpack_from(">h", data, 20)[0],
        "bSawDownCompare": bool(data[22] & 0x01),
    }


def print_status(d: dict):
    saw_bits = [i for i in range(16) if d["wSawWord"] & (1 << i)]
    print("  bTrigger      :", d["bTrigger"])
    print("  bAck          :", d["bAck"])
    print("  bResultValid  :", d["bResultValid"])
    print("  bError        :", d["bError"])
    print("  wSawWord      : 0x%04X  bits=%s" % (d["wSawWord"], saw_bits))
    print("  iLengthMM     :", d["iLengthMM"])
    print("  iWidthMM      :", d["iWidthMM"])
    print("  iBoardCount   :", d["iBoardCount"])
    print("  iErrorCode    :", d["iErrorCode"])
    print("  iHeartbeat    :", d["iHeartbeat"])
    print("  iFeedSpeedCmd :", d["iFeedSpeedCmd"])
    cmp_bits = [i for i in range(16) if (d["wCompareWord"] & 0xFFFF) & (1 << i)]
    print("  wCompareWord  : 0x%04X  bits=%s" % (d["wCompareWord"] & 0xFFFF, cmp_bits))
    print("  bSawDownCompare:", d["bSawDownCompare"])


def main():
    parser = argparse.ArgumentParser(description="DB10 handshake commissioning tool")
    parser.add_argument("command", choices=["status", "trigger", "clear"])
    parser.add_argument("--watch", action="store_true", help="status: keep polling, print changes")
    parser.add_argument("--width", type=int, default=0,
                        help="trigger: also write iBoardWidth (upstream width hint)")
    parser.add_argument("--config", default="vision_host.yaml")
    args = parser.parse_args()

    p = load_plc_cfg(args.config)
    client = connect(p)
    db = p.get("db_number", 10)

    if args.command == "status":
        last = None
        while True:
            data = client.db_read(db, 0, DB_SIZE)
            d = decode(data)
            if d != last:
                print("\n[%s] DB%d:" % (time.strftime("%H:%M:%S"), db))
                print_status(d)
                last = d
            if not args.watch:
                break
            time.sleep(0.2)

    elif args.command == "trigger":
        # Write PLC-owned bytes 0-3: bTrigger set (+ optional width)
        payload = bytearray(4)
        payload[0] = 0x01
        struct.pack_into(">h", payload, 2, max(0, min(32767, args.width)))
        client.db_write(db, 0, payload)
        print("bTrigger SET (width hint = %d). The vision host should ack and "
              "write results; run 'status' to see them, then 'clear'." % args.width)

    elif args.command == "clear":
        client.db_write(db, 0, bytearray(2))
        print("bTrigger cleared — handshake complete, host should re-arm.")

    client.disconnect()


if __name__ == "__main__":
    main()
