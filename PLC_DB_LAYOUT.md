# PLC ↔ Pi Data Exchange — S7-1200 G2 + snap7

Shared DB between the S7-1200 G2 and the Pi (`plc_vision_app.py`).

## CPU / TIA Portal checklist (do these first)

1. **Create a global DB** (suggested: `DB10 "VisionExchange"`).
2. **Disable optimized access:** DB Properties → Attributes → **uncheck
   "Optimized block access"**. snap7 addresses the DB by absolute byte
   offsets — this does not work on optimized DBs.
3. **Permit PUT/GET:** CPU Properties → Protection & Security → Connection
   mechanisms → **check "Permit access with PUT/GET communication from remote
   partner"**. Re-download hardware config.
4. Compile + download, then from the Pi (or any PC on the PLC network):
   `python plc_test_connect.py --ip <plc-ip> --rack 0 --slot 1`

## DB10 layout (16 bytes, standard access)

| Offset | Name         | Type | Written by | Meaning                                        |
|--------|--------------|------|------------|------------------------------------------------|
| 0.0    | bTrigger     | Bool | **PLC**    | Set when board is in position → Pi captures    |
| 2.0    | bAck         | Bool | Pi         | Trigger seen, capture in progress              |
| 2.1    | bResultValid | Bool | Pi         | Results below are valid                        |
| 2.2    | bError       | Bool | Pi         | Measurement failed — see iErrorCode            |
| 4.0    | wSawWord     | Word | Pi         | Bit i = drop saw i (table below)               |
| 6.0    | iLengthMM    | Int  | Pi         | Usable length, mm (fishtail/tear-out excluded) |
| 8.0    | iWidthMM     | Int  | Pi         | Board width, mm                                |
| 10.0   | iBoardCount  | Int  | Pi         | Increments with every result                   |
| 12.0   | iErrorCode   | Int  | Pi         | 0 ok · 1 no board · 2 no frame · 3 measure fail · 4 no product |
| 14.0   | iHeartbeat   | Int  | Pi         | Increments ~1/s while the Pi app runs          |

Bytes 0–1 are written **only by the PLC**, bytes 2–15 **only by the Pi** — no
read-modify-write races on shared bytes.

## Handshake sequence

```
PLC: board in position, bAck = FALSE          → SET bTrigger
Pi : sees bTrigger                            → SET bAck, capture + measure
Pi : writes wSawWord/iLengthMM/iWidthMM       → SET bResultValid (or bError)
PLC: on bResultValid: latch wSawWord to saws  → RESET bTrigger
     on bError: handle reject / default trim  → RESET bTrigger
Pi : sees bTrigger FALSE                      → clears bAck/bResultValid/bError
     (both sides re-armed for the next board)
```

Recommended PLC-side watchdogs:
- If `iHeartbeat` does not change for > 5 s → Pi offline, fall back to manual.
- If `bResultValid`/`bError` not set within ~2 s of `bTrigger` → timeout, reset
  `bTrigger`, treat as error.

## Saw word → saw mapping

`positions_m` in `plc_vision.yaml` — bit i of `wSawWord` = saw at:

| Bit | Position (m) | | Bit | Position (m) |
|-----|--------------|-|-----|--------------|
| 0   | 0.0          | | 5   | 4.2          |
| 1   | 0.6          | | 6   | 4.8          |
| 2   | 0.9          | | 7   | 5.4          |
| 3   | 3.0          | | 8   | 6.0          |
| 4   | 3.6          | | 9   | 6.6          |

The Pi sets exactly **two bits**: the leading trim saw (first saw at/inside
the usable wood) and the trailing trim saw (last saw at/inside it). For the
current discrete-output stage, map the bits in the PLC:

```
wSawWord.%X0 → Q for saw @ 0.0   ...   wSawWord.%X9 → Q for saw @ 6.6
```

(While testing with discrete outputs you can simply move the word to the
output word if the saw outputs are wired contiguously.)

## Notes

- Length fits an Int comfortably (max board ≈ 6700 < 32767).
- All values big-endian (S7 native) — handled by `plc_exchange.py`.
- If the DB number must differ from 10, change `plc.db_number` in
  `plc_vision.yaml` — offsets stay the same.
- Pi install: `pip install python-snap7` (on 32-bit Raspberry Pi OS the
  wheel may be missing — then build libsnap7 from source or use
  `sudo apt install libsnap7-1 libsnap7-dev` + `pip install python-snap7`).
