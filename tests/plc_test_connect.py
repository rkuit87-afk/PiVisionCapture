"""
plc_test_connect.py — Minimal snap7 connectivity smoke test.

Just proves we can reach the PLC and read its CPU state before we
worry about DB layout, bit offsets, or wiring this into the capture
pipeline. Run this first.

Usage:
  python plc_test_connect.py --ip 192.168.x.x --rack 0 --slot 1
"""

import argparse
import sys

import snap7
from snap7.util import get_bool


def main():
    parser = argparse.ArgumentParser(description="Snap7 PLC connectivity test")
    parser.add_argument("--ip", required=True, help="PLC IP address")
    parser.add_argument("--rack", type=int, default=0, help="Rack number (usually 0)")
    parser.add_argument("--slot", type=int, default=1, help="Slot number (S7-1200/1500 usually 1)")
    args = parser.parse_args()

    client = snap7.client.Client()

    print(f"Connecting to {args.ip} rack={args.rack} slot={args.slot} ...")
    try:
        client.connect(args.ip, args.rack, args.slot)
    except Exception as exc:
        print(f"FAILED to connect: {exc}")
        print("\nCommon causes:")
        print("  - 'Permit access with PUT/GET communication' not enabled in CPU")
        print("    Properties > Protection & Security (TIA Portal), then re-download.")
        print("  - Wrong rack/slot (S7-1200/1500 is usually rack=0, slot=1).")
        print("  - Firewall blocking port 102 (ISO-TSAP) between this PC and the PLC.")
        sys.exit(1)

    print("Connected:", client.get_connected())

    try:
        cpu_state = client.get_cpu_state()
        print("CPU state:", cpu_state)
    except Exception as exc:
        print(f"Connected, but get_cpu_state() failed: {exc}")

    try:
        info = client.get_cpu_info()
        print("CPU info:", info)
    except Exception as exc:
        print(f"get_cpu_info() failed (not fatal): {exc}")

    client.disconnect()
    print("\nConnectivity test passed — snap7 can talk to this PLC.")
    print("Next step: tell me the DB number + byte/bit offset for the trigger bit,")
    print("and whether that DB has 'Optimized block access' disabled (required for")
    print("snap7 to read it by byte/bit offset).")


if __name__ == "__main__":
    main()
