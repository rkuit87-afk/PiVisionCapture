# Shadow Run — Morning Setup (prepared overnight 2026-07-12)

## What got built overnight (TL;DR)

**`shadow_capture_app.py` — a read-only operator-shadow recorder.** It never
writes to the PLC. Per board: on the vision trigger it captures both cameras
and buffers OUR would-be saw word; on the **saw-done pulse** it reads the
operator's ACTUAL applied word (`DB1.wCompareWord`, plus raw `%Q` saw
outputs) and pops our buffer — matched per board like the PLC's own DB4
buffer, never by time. Output per session: `boards.csv`, `events.jsonl`,
every frame, and `report.md` with agreement stats, per-saw confusion and
stop-position deviation. **Tested end-to-end 3× against a local snap7 server
plus a 25 s read-only smoke run against the real CPU — all passing.**

Along the way, from the Openness export of `Trimmer.G2.VissionAdded` (the
latest project, still open in your TIA Portal — I attached read-only, saved
nothing):

1. **Found + fixed a real bug:** DB1 uses S7 standard alignment, so every
   field sits 2 bytes later than `plc_exchange.py` assumed (status bits are
   at byte 4, not 2; wSawWord at 6, not 4; …). The host would have written
   status bits into `iBoardWidth`. Fixed in `plc_exchange.py`,
   `plc_sim_tool.py`, and the new app; layout proven by read-size probing
   the live CPU. See `PLC_DB_LAYOUT.md` (rewritten).
2. Your new compare hooks are mapped: `wCompareWord` @20, `bSawDownCompare`
   @22.0, DB4 buffer (`CountBuffer`, `CutData[0..3]`, `SawDone` @38.0),
   `PE_VissionTrigger` %I4.6, saw outputs %Q0.0–%Q1.4, DB13 `ProxyCount`.
3. **Saw positions inserted into the fresh calibration** (`saw_lines` block
   in `vision_host.yaml`) + overlay images to verify by eye.

## Pre-flight (10 min, in order)

1. **LEFT camera**: confirm it answers (currently DHCP `192.168.2.246` per
   vision_host.yaml). RIGHT `.3.145` was fine.
2. **Verify the saw overlays by eye** — open:
   - `D:\board_captures\calib_recheck_2026-07-12\SAW_OVERLAY_RIGHT.jpg`
     Strong sign it's right: the fit puts the calibration board's far tip at
     **6735 mm and the board's own label says 6734** — 1 mm out.
   - `SAW_OVERLAY_LEFT.jpg` — **NEEDS YOUR EYE.** The plank in the LEFT band
     extends ~1.3 m LEFT of where the fit puts the fence (saw 0.0 @ px 1138).
     Either that plank is machine structure (fine) or the LEFT fit is off
     (recalibrate LEFT with line_calibrator.html before trusting LEFT
     numbers). Width @0.9 line and saws 0.0–3.0 depend on it; the RIGHT-side
     length/saw decision does not.
3. **Fresh empty-deck references** (30 s, NO board in view — the current refs
   are from 2026-07-10, before the cameras moved; presence detection is
   unreliable until this is done):
   ```
   python - << "EOF"
   import cv2
   for name, url in [("L", "rtsp://root:aLTDANJOSH%404878@192.168.2.246/live1s1.sdp"),
                     ("R", "rtsp://root:Altdanjosh%404878@192.168.3.145/live1s1.sdp")]:
       cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG); ok, f = False, None
       for _ in range(5): ok, f = cap.read()
       cap.release()
       if ok: cv2.imwrite("D:/board_captures/empty_ref_%s_0713.jpg" % name, f)
       print(name, "ok" if ok else "FAILED")
   EOF
   ```
   Then point `vision_host.yaml` → `empty_ref_left/right` at the new files.
4. **PLC side** (your download, as always): confirm the program
   - pulses `DB1.bSawDownCompare` and latches `wCompareWord` at saw drop
     (your additions from yesterday — just confirm they're in the downloaded
     program), and
   - feeds the vision sensor to `%I4.6`.
   Nothing else is needed — the app defaults to reading `%I4.6` directly
   (`trigger.source: pe_input`), so the DB handshake can stay idle.
5. **Quick sanity** (mill running, one board through):
   ```
   python plc_sim_tool.py status --watch    # bSawDownCompare should pulse,
                                            # wCompareWord should show the profile
   ```

## Run 1 — observe the operator (100 boards, no changes)

```
cd C:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture
python shadow_capture_app.py --session baseline --notes "operator only, no changes; <add anything relevant>"
```

Watch the console: `[BOARD n IN] our=…` on every stop, `[COMPARE k/100]`
on every saw-done, with running EXACT/CLOSE/MISS. Ctrl+C any time — the
report still gets written. If `[BOARD IN]` lines don't appear when boards
stop, the sensor isn't reaching %I4.6 — try `--trigger-source bTrigger`.

## Run 2 — after your changes

```
python shadow_capture_app.py --session after_<change> --notes "changed: <exactly what you changed>"
python shadow_report.py shadow_sessions\<baseline_dir> --compare shadow_sessions\<after_dir>
```

`comparison_vs_baseline.md` lands in the second session's folder.

## Stop-position optimization

Every board is compared against the calibration board's CURRENT resting
position (references: `LEFT/RIGHT_manual_snapshot2.jpg` from yesterday's
recheck). Per board the console/CSV shows `stop dY` in px (positive = board
stopped later/lower in frame than the calibration board); the report gives
mean ± stdev per side. Trim the stop timing until mean dY → 0; stdev tells
you the mechanical repeatability floor (was ±8-9 px on 07-10).

## Files added/changed overnight

| File | What |
|---|---|
| `shadow_capture_app.py` | the read-only shadow recorder |
| `shadow_capture.yaml` | its config (trigger/saw-done sources, thresholds) |
| `shadow_report.py` | per-session report + session-vs-session compare |
| `tests/shadow_sim_test.py` | full-loop test vs local snap7 server (PASS ×3) |
| `openness/export_db_layout.ps1` | read-only Openness DB+tags exporter |
| `openness/parse_db_xml.py` | XML → verified byte offsets (`db_layouts.json`) |
| `calib_saw_overlay.py` | saw mm → px through current fit + overlays |
| `plc_exchange.py`, `plc_sim_tool.py` | **offsets corrected to the real DB1** |
| `PLC_DB_LAYOUT.md` | rewritten from the verified export |
| `vision_host.yaml` | + `saw_lines` block (auto-generated) |

Ignore/delete the `shadow_sessions\*simtest*` and `*live_smoke*` folders —
overnight test artifacts.

## Open questions for you (not blocking run 1)

1. LEFT fit check above (step 2).
2. `wCompareWord` semantics: I treat it as "the profile word actually applied
   at saw drop". If it's something else (e.g. ProfileRead pre-latch), tell me
   and I'll re-point the comparison to `%QB0-1` (already logged per board as
   `q_saw_word`, so the data is captured either way).
3. Old open items unchanged: saw-word semantics (2 bits vs drop-all-past-end)
   and the <114 mm WIDTH RULE — both affect EXACT-match rates, so expect
   some systematic CLOSE verdicts until decided.
