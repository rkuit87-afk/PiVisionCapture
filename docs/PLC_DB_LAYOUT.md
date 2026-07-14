# PLC ↔ Vision Host Data Exchange — S7-1200 G2 + snap7

**Source of truth (2026-07-12):** TIA Openness read-only export of the LIVE
project `Trimmer.G2.VissionAdded` → `openness/exports/2026-07-12_153302/`
(`db_layouts.json` has every member's computed offset). Every DB size was
verified against the running CPU by read-size probing (read at size succeeds,
read past the end fails). Re-export any time with:

```
powershell -ExecutionPolicy Bypass -File openness\export_db_layout.ps1
python openness\parse_db_xml.py
```

> **History note:** this file previously showed an 18-byte hand-packed layout
> (status bits at byte 2, saw word at 4, …). The real DB uses S7 STANDARD
> alignment — an Int after a Bool starts at the next EVEN byte — so every
> field actually sits 2 bytes later. `plc_exchange.py`, `plc_sim_tool.py`
> and `shadow_capture_app.py` all carry the corrected offsets now.

## DB1 "DB_Vission" (Standard access, 24 bytes)

| Offset | Name            | Type | Written by | Meaning                                    |
|--------|-----------------|------|------------|--------------------------------------------|
| 0.0    | bTrigger        | Bool | **PLC**    | Board in position → host captures          |
| 2      | iBoardWidth     | Int  | **PLC**    | Optional upstream width hint               |
| 4.0    | bAck            | Bool | Host       | Trigger seen, capture in progress          |
| 4.1    | bResultValid    | Bool | Host       | Results below are valid                    |
| 4.2    | bError          | Bool | Host       | Measurement failed — see iErrorCode        |
| 6      | wSawWord        | Word | Host       | Bit i = drop saw i (table below)           |
| 8      | iLengthMM       | Int  | Host       | Usable length, mm                          |
| 10     | iWidthMM        | Int  | Host       | Board width, mm                            |
| 12     | iBoardCount     | Int  | Host       | Increments with every result               |
| 14     | iErrorCode      | Int  | Host       | 0 ok · 1 no board · 2 no frame · 3 measure fail · 4 no product |
| 16     | iHeartbeat      | Int  | Host       | Increments ~1/s while the host app runs    |
| 18     | iFeedSpeedCmd   | Int  | Host       | Commanded feed speed (0-100%)              |
| 20     | wCompareWord    | Int  | **PLC**    | ACTUAL applied profile, latched at saw-down |
| 22.0   | bSawDownCompare | Bool | **PLC**    | Saw-done pulse → compare wCompareWord now  |

Ownership: PLC owns bytes 0-3 and 20-23; host owns 4-19. The host's
startup clear (`clear_pi_area`) zeroes ONLY bytes 4-19.

## Shadow-mode observation points (all READ-ONLY)

| What                       | Where                              |
|----------------------------|-------------------------------------|
| Board-arrival trigger      | DB1 0.0 `bTrigger`, or `%I4.6` (`PE_VissionTrigger`) directly |
| Saw-done / board unloaded  | DB1 22.0 `bSawDownCompare` (or DB4 38.0 `SawDone`) |
| Operator's actual decision | DB1 `wCompareWord` @20; raw outputs `%QB0-%QB1` (Saw0.0=%Q0.0 … Saw6.6=%Q1.3, spare %Q1.4) |
| PLC board buffer           | DB4 `DB_DataHandler` (below)        |
| Piece counter              | DB13 `ProxyCount` @6 (DInt)         |

## DB4 "DB_DataHandler" (Standard, 40 bytes) — the PLC's board buffer

| Offset | Name              | Type            |
|--------|-------------------|-----------------|
| 0      | ProfileSelectrion | Word            |
| 2      | ProfileRead       | Word            |
| 4.0    | Exception         | Bool            |
| 4.1    | ProfileEn         | Bool            |
| 6      | CountBuffer[0..3] | Word ×4 (@6,8,10,12) |
| 14     | CutData[0..3]     | UDT_CutData ×4: CutlineDist DInt + ProfileInd Word, 6 B stride (@14,20,26,32) |
| 38.0   | SawDone           | Bool            |

## DB13 "DB_Mesurements" (Standard, 10 bytes)

`i_ThicknessRaw` Int @0 · `r_ThicknessScaled` Real @2 · `ProxyCount` DInt @6

## DB8 "DP_OP" (Standard, 2 bytes)

`b_TargetReached` 0.0 · `b_SawsDown` 0.1 · `b_Running` 0.2

## Handshake sequence (unchanged)

```
PLC: board in position, bAck = FALSE          → SET bTrigger
Host: sees bTrigger                           → SET bAck, capture + measure
Host: writes wSawWord/iLengthMM/iWidthMM      → SET bResultValid (or bError)
PLC: on bResultValid: latch wSawWord to saws  → RESET bTrigger
Host: sees bTrigger FALSE                     → clears bAck/bResultValid/bError
PLC: at saw drop: wCompareWord = applied word → PULSE bSawDownCompare
```

## Saw word → saw mapping (tape-measured from the fence, 2026-07-09)

| Bit | Mask | Saw | mm from fence |
|-----|------|-----|---------------|
| 0 | `0x0001` | 0.0 | 18 |
| 1 | `0x0002` | 0.3 | 270 |
| 2 | `0x0004` | 0.6 | 560 |
| 3 | `0x0008` | 3.0 | 3057 |
| 4 | `0x0010` | 3.6 | 3670 |
| 5 | `0x0020` | 4.2 | 4249 |
| 6 | `0x0040` | 4.8 | 4813 |
| 7 | `0x0080` | 5.4 | 5490 |
| 8 | `0x0100` | 6.0 | 6023 |
| 9 | `0x0200` | 6.6 | 6660 |

`0x0000` means no cuts. `0x0201` means 0.0 plus 6.6. The operator compared
this contiguous ten-saw map against the live ladder on 2026-07-14; there is
no 0.9 saw in the live profile word.

## Notes

- All values big-endian (S7 native) — handled by `plc_exchange.py`.
- PUT/GET enabled + non-optimized DB confirmed working 2026-07-12.
- `plc_sim_tool.py status` decodes all DB1 fields incl. wCompareWord.
