"""
parse_db_xml.py — compute snap7 byte offsets from Openness SimaticML exports.

Reads the DB_*.xml files produced by export_db_layout.ps1 and computes the
absolute byte/bit offset of every member under S7 STANDARD (non-optimized)
layout rules:

  - Bool            bit-packed, 8 per byte, consecutive Bools share a byte
  - Byte/Char/(U)SInt   byte-aligned
  - 2/4/8-byte elementary types   word-aligned (even byte)
  - Array / Struct / UDT          start word-aligned; struct size padded even
  - a non-Bool after Bools closes the bit run (then aligns per its own rule)

Output: db_layouts.json next to the XML files + a readable table on stdout.

Usage:
  python parse_db_xml.py [exports_dir]     (default: newest dir in exports/)
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {"if": "http://www.siemens.com/automation/Openness/SW/Interface/v5"}

ELEM_SIZES = {
    "bool": None,  # special-cased
    "byte": 1, "char": 1, "sint": 1, "usint": 1,
    "word": 2, "int": 2, "uint": 2, "date": 2, "s5time": 2,
    "dword": 4, "dint": 4, "udint": 4, "real": 4, "time": 4,
    "time_of_day": 4, "tod": 4, "dtl": 12,
    "lword": 8, "lint": 8, "ulint": 8, "lreal": 8, "ltime": 8,
}

ARRAY_RE = re.compile(r'^Array\[(-?\d+)\.\.(-?\d+)\]\s+of\s+(.+)$', re.IGNORECASE)


class Cursor:
    def __init__(self):
        self.byte = 0
        self.bit = 0          # next free bit when inside a Bool run
        self.in_bits = False

    def close_bits(self):
        if self.in_bits:
            self.byte += 1
            self.bit = 0
            self.in_bits = False

    def align_even(self):
        self.close_bits()
        if self.byte % 2:
            self.byte += 1

    def take_bool(self):
        if not self.in_bits:
            self.in_bits = True
            self.bit = 0
        pos = (self.byte, self.bit)
        self.bit += 1
        if self.bit == 8:
            self.byte += 1
            self.bit = 0
            self.in_bits = False
        return pos

    def take_bytes(self, size):
        if size == 1:
            self.close_bits()
        else:
            self.align_even()
        pos = (self.byte, None)
        self.byte += size
        return pos


def strip_quotes(dt: str) -> str:
    return dt.strip().strip('"')


def layout_members(members, cur, prefix, out, udts):
    """members: list of (name, datatype, nested_members)."""
    for name, datatype, nested in members:
        dt = strip_quotes(datatype)
        m = ARRAY_RE.match(dt)
        full = f"{prefix}{name}"
        if m:
            lo, hi, elem = int(m.group(1)), int(m.group(2)), strip_quotes(m.group(3))
            cur.align_even()
            if elem.lower() == "bool":
                # Bool arrays are bit-packed from a fresh even byte
                start = cur.byte
                n = hi - lo + 1
                for i in range(n):
                    byte = start + i // 8
                    bit = i % 8
                    out.append({"name": f"{full}[{lo + i}]", "type": "Bool",
                                "byte": byte, "bit": bit})
                nbytes = (n + 7) // 8
                if nbytes % 2:
                    nbytes += 1  # bool arrays pad to word
                cur.byte = start + nbytes
                cur.in_bits = False
            elif elem.lower() in ELEM_SIZES:
                size = ELEM_SIZES[elem.lower()]
                esize = max(size, 1)
                # elements >1 byte sit at even strides; 1-byte packed
                stride = esize if esize % 2 == 0 or esize == 1 else esize + 1
                for i in range(lo, hi + 1):
                    out.append({"name": f"{full}[{i}]", "type": elem,
                                "byte": cur.byte, "bit": None})
                    cur.byte += stride
                if cur.byte % 2:
                    cur.byte += 1
            else:
                # array of UDT/struct: use nested member template per element
                tmpl = nested if nested else udts.get(elem, [])
                for i in range(lo, hi + 1):
                    cur.align_even()
                    sub = Cursor()
                    subout = []
                    layout_members(tmpl, sub, f"{full}[{i}].", subout, udts)
                    base = cur.byte
                    for e in subout:
                        e["byte"] += base
                        out.append(e)
                    size = sub.byte + (1 if sub.in_bits else 0)
                    if size % 2:
                        size += 1
                    cur.byte = base + size
                    cur.in_bits = False
        elif dt.lower() == "bool":
            b, bit = cur.take_bool()
            out.append({"name": full, "type": "Bool", "byte": b, "bit": bit})
        elif dt.lower() in ELEM_SIZES:
            size = ELEM_SIZES[dt.lower()]
            b, _ = cur.take_bytes(size)
            out.append({"name": full, "type": dt, "byte": b, "bit": None})
        elif dt.lower().startswith("string"):
            sm = re.match(r'string\[(\d+)\]', dt.lower())
            n = int(sm.group(1)) if sm else 254
            cur.align_even()
            out.append({"name": full, "type": dt, "byte": cur.byte, "bit": None})
            cur.byte += n + 2
        else:
            # UDT / named struct with nested members from the XML
            tmpl = nested if nested else udts.get(dt, [])
            cur.align_even()
            sub = Cursor()
            subout = []
            layout_members(tmpl, sub, f"{full}.", subout, udts)
            base = cur.byte
            for e in subout:
                e["byte"] += base
                out.append(e)
            size = sub.byte + (1 if sub.in_bits else 0)
            if size % 2:
                size += 1
            cur.byte = base + size
            cur.in_bits = False


def parse_member_el(mel):
    name = mel.get("Name")
    datatype = mel.get("Datatype")
    nested = []
    for sec in mel.findall("if:Sections/if:Section", NS):
        for sub in sec.findall("if:Member", NS):
            nested.append(parse_member_el(sub))
    # Openness also emits nested members without the namespace inside arrays
    if not nested:
        for sec in mel.findall("Sections/Section"):
            for sub in sec.findall("Member"):
                nested.append(parse_member_el(sub))
    return (name, datatype, nested)


def parse_db_xml(path: Path):
    root = ET.parse(path).getroot()
    attr = root.find(".//SW.Blocks.GlobalDB/AttributeList")
    name = attr.findtext("Name")
    number = int(attr.findtext("Number"))
    layout = attr.findtext("MemoryLayout")
    members = []
    iface = attr.find("Interface")
    for sec in iface.iter("{%s}Section" % NS["if"]):
        if sec.get("Name") != "Static":
            continue
        for mel in sec.findall("if:Member", NS):
            members.append(parse_member_el(mel))
    return name, number, layout, members


def main():
    if len(sys.argv) > 1:
        exp = Path(sys.argv[1])
    else:
        root = Path(__file__).parent / "exports"
        exp = sorted([d for d in root.iterdir() if d.is_dir()])[-1]
    print(f"Parsing exports in: {exp}\n")

    result = {}
    for xml in sorted(exp.glob("DB_*.xml")):
        name, number, layout, members = parse_db_xml(xml)
        cur = Cursor()
        out = []
        layout_members(members, cur, "", out, {})
        size = cur.byte + (1 if cur.in_bits else 0)
        if size % 2:
            size += 1
        result[name] = {"db_number": number, "memory_layout": layout,
                        "size_bytes": size, "members": out}
        print(f"=== DB{number} \"{name}\"  ({layout}, {size} bytes) ===")
        for e in out:
            addr = f"{e['byte']}.{e['bit']}" if e["bit"] is not None else f"{e['byte']}"
            print(f"  {addr:>7}  {e['type']:<10} {e['name']}")
        print()

    out_path = exp / "db_layouts.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Written: {out_path}")


if __name__ == "__main__":
    main()
