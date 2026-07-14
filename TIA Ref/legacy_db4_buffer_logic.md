# Legacy DB4 board-buffer ladder logic (reference, being replaced)

Captured from TIA Portal screenshots the user shared with Claude on
2026-07-13. **This is the INHERITED program, copy-pasted from a former CPU —
the user is actively rewriting it to a proper FIFO block that also
timestamps sizes and cuts. Do not build instrumentation or matching logic
against this layout; it's a snapshot for reference only, kept here so
Codex doesn't have to re-derive it.**

Claude could not export the original screenshots to image files (they were
pasted inline in chat, not available as files on disk) — this is a written
transcription of what they show. Ask the user to drop the actual TIA
screenshots into this folder if the visual ladder is needed.

## Network 5 — load side (write into the buffer)

```
#ReqMeas --[N]--> ADD_DInt: OUT = #Stat_ProxyCount + 22  -> #Stat_NewTarget
```
- `N` contact = falling-edge detect. Fires once when `#ReqMeas` drops.
- `#Stat_NewTarget` is an **encoder-count target**, not a time delay:
  current `#Stat_ProxyCount` (DB13 `ProxyCount`, presumably) plus a fixed
  22-count lead. This is the PLC's own equivalent of what Claude/the user
  tuned empirically tonight as a *time* delay (0.75s) for the vision
  cameras — the PLC uses encoder counts instead, which is immune to feed
  speed changes. Worth considering for vision capture timing too if the
  line speed isn't constant.

Four parallel rungs, gated by `#Stat_CutlineIndex`:
```
CutlineIndex == 0  -> MOVE NewTarget -> CountBuffer[0].CutlineDist
                       MOVE CutProfileL -> CountBuffer[0].ProfileInd
CutlineIndex == 1  -> ... CountBuffer[1] ...
CutlineIndex == 2  -> ... CountBuffer[2] ...
CutlineIndex >= 3  -> ... CountBuffer[3] ...   (>= as an overflow-safe catch-all)
```
- **`CountBuffer[i]` is a UDT with `.CutlineDist` (DInt) and `.ProfileInd`
  (Word) fields** — i.e. it IS the structured array. This conflicts with
  `PLC_DB_LAYOUT.md`, which currently documents `CountBuffer[0..3]` as four
  plain Words, separate from a distinct `CutData[0..3]` UDT array. Given
  this ladder logic writes `CountBuffer[i].CutlineDist` /
  `CountBuffer[i].ProfileInd` directly, the doc's split is probably wrong —
  re-run `openness/export_db_layout.ps1` + `parse_db_xml.py` to confirm
  before trusting either name/offset. **Moot if the buffer redesign changes
  these members anyway — check the new layout once the user shares it.**
- Write position is **indexed**, not shift-in: new data lands wherever
  `#Stat_CutlineIndex` currently points. (Where `CutlineIndex` itself gets
  incremented/wrapped wasn't shown in the screenshots.)

## Network 11 — unload side (read + shift the buffer)

```
#Stat_CutlineReached ----------------------------------( #SawDown )
                      |
                      +--[P_TRIG]--> #Send_cutData --> MOVE CountBuffer[0].ProfileInd -> #CutProfileLOut
                      |
                      +--[N_TRIG]--> #Stat_ShiftBuffer --> MOVE CountBuffer[1].CutlineDist -> CountBuffer[0].CutlineDist
                                                            MOVE CountBuffer[2].CutlineDist -> CountBuffer[1].CutlineDist
                                                            MOVE CountBuffer[3].CutlineDist -> CountBuffer[2].CutlineDist
                                                            (mirrored for .ProfileInd — confirmed by user, not separately screenshotted)
```
- **`CountBuffer[0]` is always the head of the queue** — the slot the saw
  actually reads from.
- **Rising edge of `#Stat_CutlineReached`**: read `CountBuffer[0].ProfileInd`
  out to `#CutProfileLOut`. This is the moment the board's profile is
  actually consumed.
- **Falling edge of `#Stat_CutlineReached`**: shift the buffer down
  (`[1]->[0]`, `[2]->[1]`, `[3]->[2]`), for both `.CutlineDist` and
  `.ProfileInd`. Happens strictly after the read, so no race condition.
- `#SawDown` coil is driven directly (no edge logic) by `#Stat_CutlineReached`
  — high for the whole duration, not a pulse.

## Confirmed signal relationships (user, 2026-07-13 — still true after the rewrite)

- `#SawDown` (this legacy FB) **is the same signal as `DB8.b_SawsDown`**
  (per `PLC_DB_LAYOUT.md`), deliberately mirrored by the user.
- `DB1.bSawDownCompare` is **also deliberately mirrored** to fire high/low
  at exactly the same instants as `SawDown`/`b_SawsDown`.
- Practical consequence: `shadow_capture_app.py`'s existing choice to key
  the "saw-done" event off `DB1.bSawDownCompare` is already correct and
  precise — no need to switch to a "more raw" signal. This holds regardless
  of the buffer/FIFO rewrite since it's about the saw-actuation signal, not
  the buffer implementation.

## Status

Legacy design, being replaced. See memory note `project_plc_fifo_rewrite`
(Claude's persistent memory) for the current status of the rewrite. User
will share the new FIFO block "when the time is right."
