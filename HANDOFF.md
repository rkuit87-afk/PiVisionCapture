# PiVisionCapture Agent Handoff

This project uses multiple AI agents. The authority model is now:

- **Claude and Codex:** implementation-capable engineering agents.
- **Gemini:** advisory / review / handoff agent only, unless the user explicitly grants implementation authority in that session.

Claude and Codex should be treated as peers. Either may inspect the codebase, edit implementation files, update tests, run verification, and prepare deployable changes when the user asks for project work. Neither agent should assume the other has higher or lower authority.

---

## Current Project State

PiVisionCapture has evolved from the original Raspberry Pi capture service into a PC-hosted vision and PLC integration workspace.

The main active track is the **vision host / shadow-run workflow**:

- `shadow_capture_app.py` records read-only comparison runs against the live PLC/operator decisions.
- `vision_host_app.py` is the active host-side measurement loop that can write results back to the PLC.
- `dual_camera_measure.py` contains the current dual-camera measurement and saw-selection logic.
- `plc_exchange.py` contains the corrected DB1 snap7 exchange offsets verified from the live TIA Openness export.
- `vision_host.yaml` and `shadow_capture.yaml` hold current camera, PLC, calibration, and session settings.
- `PLC_DB_LAYOUT.md`, `MORNING_SETUP.md`, and `SHADOW_RUN_MORNING.md` are the main operational references.

The workspace currently contains substantial uncommitted work around PLC DB alignment, shadow capture, calibration, and reporting. Agents must read the current files before making assumptions.

---

## Agent Authority

### Claude

Claude may implement code changes, update tests, edit configuration, and modify documentation when asked by the user. Claude should follow normal engineering discipline: inspect first, keep changes scoped, avoid unrelated cleanup, and verify where possible.

### Codex

Codex has the same implementation authority as Claude. Codex may modify production and non-production project files when the user requests project work. Codex is not restricted to handoff-only tasks.

### Gemini

Gemini is limited to analysis, review, and handoff writing by default. Gemini should not modify implementation files or make production changes unless the user explicitly says Gemini may implement.

---

## Working Rules for Claude and Codex

1. Read the relevant code and docs before editing.
2. Treat uncommitted changes as intentional user or prior-agent work.
3. Do not revert or overwrite another agent's or user's changes unless explicitly instructed.
4. Keep implementation changes focused on the requested task.
5. Update tests or add small verification scripts when the risk justifies it.
6. Run available verification when the local environment supports it.
7. If Python, PLC, camera, or network dependencies are unavailable, report that clearly.
8. For PLC-connected changes, preserve the DB ownership model documented in `PLC_DB_LAYOUT.md`.
9. For shadow-mode work, preserve the guarantee that `shadow_capture_app.py` performs no PLC writes.
10. For active host work, be explicit about any PLC write behavior.

---

## Current High-Value Work Items

### P0 / P1 Operational Items

- Confirm LEFT camera address and update `vision_host.yaml` only when the physical network state is known.
- Refresh empty-deck reference images before trusting presence detection after camera movement or lighting changes.
- Verify `wCompareWord` and `bSawDownCompare` semantics during the first live shadow run.
- Run `shadow_capture_app.py` for an operator-only baseline and review `report.md`.

### Open Product Decisions

- Saw-word semantics: current code selects the datum saw plus one standard-length saw. Confirm whether PLC wants all saws beyond the far end dropped as well.
- Width rule: confirm whether boards under 114 mm should skip the datum/origin trim.
- LEFT calibration: verify by eye before trusting LEFT-derived width and saw positions.

---

## Preferred Handoff Pattern

### Mandatory Session Discipline

- Before starting any live or replay shadow session, read this handoff and
  confirm the current trigger, buffer, storage, and safety assumptions.
- Immediately after a session finalises, append its exact session path,
  trigger/comparison/unmatched counts, verification status, and any observed
  anomalies to this handoff before starting further work.

When an agent leaves work for another agent:

- State what changed.
- State what was verified.
- State what could not be verified.
- Name the next concrete command or file to inspect.
- Avoid assigning implementation work only to Claude; use "Claude/Codex" or "next implementation agent."

Example:

```markdown
## Next Agent

Claude/Codex: start by reading `SHADOW_RUN_MORNING.md`, then run a short
shadow session if PLC/cameras are available. If not available, run the local
snap7 simulation test and report the blocker.
```

---

## Verification Notes

The local Windows shell may not have `python` or `py` on PATH. If so, do not assume the project is broken. Report the missing runtime and continue with static inspection.

## Network Handoff (2026-07-13)

- The USB-to-Ethernet adapter is `Ethernet 3`, a Realtek USB GbE Family Controller,
  MAC `00-E0-4C-68-05-7C`.
- `Ethernet 3` is reserved for the local PLC/camera network and was configured as
  static `192.168.3.148/23`, with no default gateway or DNS.
- The onboard Realtek PCIe adapter is `Ethernet`. It is configured for DHCP and
  is the internet fallback. With the cable connected it received `192.168.2.147`
  and gateway `192.168.3.254`.
- Wi-Fi remains preferred while available; Ethernet has a live fallback route.
  Internet ping and DNS were verified while both links were connected.
- The Siemens PLCSIM virtual adapter (`Ethernet 2`) had an unintended IPv4
  default route with metric 0, which intercepted outbound HTTPS and caused
  Claude Code API connection failures. Its default route was removed; PLCSIM
  itself remains enabled. HTTPS was re-tested successfully (`200 OK`), with
  Wi-Fi now the preferred default route and onboard Ethernet the fallback.
- Host routes for PLC `192.168.3.151`, RIGHT camera `192.168.3.145`, LEFT
  camera DHCP address `192.168.2.246`, and intended LEFT static address
  `192.168.3.146` are pinned to `Ethernet 3` with route metric 1. This avoids
  Windows selecting Wi-Fi or onboard Ethernet for the overlapping `/23` range.
- PLC ping and TCP port 102 were verified through `Ethernet 3`; `plc_sim_tool.py
  status` successfully read DB1 after the host-route correction.

## Current Bring-Up

- Python `3.13.7` is available on the engineering PC.
- Imports for `yaml`, `cv2`, `numpy`, and `snap7` passed.
- The safe live workflow is `shadow_capture_app.py`; it reads PLC/camera state and
  never writes to the PLC. Use this while the plant is being observed.
- `vision_host_app.py` is write-capable and should remain stopped until the LEFT
  camera, fresh empty references, calibration, and PLC handshake are confirmed.

## Next Agent

Claude/Codex: read `SHADOW_RUN_MORNING.md` and `MORNING_SETUP.md`, inspect the
running shadow session, and review its report after boards have passed. Resolve
the LEFT camera address and PLC reachability before enabling the write-capable
vision host.

## Bring-Up Session (2026-07-13)

- Started read-only session `shadow_sessions\\2026-07-13_123717_standing_20260713`.
- Both configured RTSP streams connected: LEFT `192.168.2.246` and RIGHT
  `192.168.3.145`.
- PLC `192.168.3.151:102` initially timed out because its host route was pinned
  to onboard Ethernet. After moving the route to `Ethernet 3`, the recorder
  connected successfully in read-only mode.
- Stop-reference files configured in `shadow_capture.yaml` are absent from this
  PC: `D:/board_captures/calib_recheck_2026-07-12/LEFT_manual_snapshot2.jpg` and
  `D:/board_captures/calib_recheck_2026-07-12/RIGHT_manual_snapshot2.jpg`.
- LEFT camera quirk confirmed: `192.168.2.246` responds to HTTP and its RTSP
  stream connected. Intended static `192.168.3.146` did not respond. Keep the
  current software address until the Vivotek network page can be changed and
  reboot-tested on site.
- Shadow alignment POC: `shadow_capture_app.py` now keeps timestamped RTSP
  histories and selects LEFT/RIGHT frames independently relative to the
  `bTrigger` rising edge. Tune `frame_alignment.left_offset_s` and
  `frame_alignment.right_offset_s` in `shadow_capture.yaml` from the saved
  frame offsets; both start at `0.0`. Restart the shadow process to use this
  logic. It remains read-only.
- Do not start `vision_host_app.py` until PLC reachability and the reference
  image/calibration situation are resolved.

## Current Findings For Claude (2026-07-13)

### Confirmed PLC Observation Access

- DB1, DB2, DB4, and DB13 are readable through Snap7 with PUT/GET enabled.
- DB2 `DB_DebouncedFieldDevices` is a **standard**, externally accessible
  six-byte DB, not an optimized block. A live `db_read(2, 0, 6)` succeeded.
  `L_LArrayDebounced[1..15]` is bytes 0-1; `B_ManDebounced[1..15]` is bytes
  2-3; `B_ControlsDebounced[1..15]` is bytes 4-5. The exact array index of
  the physical origin sensor still needs confirmation in TIA.
- DB4 `DB_DataHandler` is also **standard** and externally accessible. A live
  `db_read(4, 0, 40)` succeeded. It contains `ProfileSelectrion`,
  `ProfileRead`, `CountBuffer[0..3]`, `CutData[0..3]`, and `SawDone`.

### Agreed Physical/PLC Model

```text
operator may change candidate profile
  -> board reaches DB1.bTrigger: capture vision event
  -> board crosses the debounced DB2 origin sensor: PLC commits profile into DB4
  -> board reaches saws: PLC consumes/advances DB4 entry, actuates mask,
     latches DB1.wCompareWord, then pulses DB1.bSawDownCompare
```

- Do not correlate a board from `ProfileSelectrion` changes: that is a
  candidate operator choice and can change before the origin sensor commits it.
- `bTrigger` is the vision-capture event; the DB2 origin edge is the proposed
  buffer-enqueue event; `bSawDownCompare` is the actuation/compare event.
- Current FIFO matching is order-based. It is acceptable for a short POC only
  after validating one trigger -> one DB4 enqueue -> one saw-done event.
- For a later robust implementation, use PLC-latched sequence counters rather
  than a transient bit: `OriginSeq`, `BufferLoadSeq`, `SawDoneSeq`, optionally
  with encoder counts. A small separate telemetry DB is preferred over changing
  the current DB1 handshake layout.

### Alignment POC Changes Made By Codex

- Modified `shadow_capture_app.py` and `shadow_capture.yaml` only; no PLC,
  camera, or active-control writes were made.
- The next shadow process uses `DB1.bTrigger` rising edges and keeps timestamped
  JPEG histories for both RTSP streams. It chooses LEFT and RIGHT frames
  independently nearest to configurable trigger-relative offsets.
- Tune `frame_alignment.left_offset_s` and `frame_alignment.right_offset_s` in
  `shadow_capture.yaml`; both currently start at `0.0`. Actual chosen offsets
  are logged to the console, `events.jsonl`, and `boards.csv`.
- The existing running session predates this change. Restart the shadow app for
  the POC with:

```powershell
python shadow_capture_app.py --session alignment_poc --notes "bTrigger frame-alignment POC"
```

- Verification passed: `python -m py_compile shadow_capture_app.py`,
  `python tests/shadow_sim_test.py`, and a local timestamp-selection check.
- `capture_trigger_window.py` and `capture_trigger_edge.py` are separate
  untracked POC helpers already present in the workspace. Preserve them and
  inspect before merging or duplicating their functionality.

### Requested Next Work

Claude: keep the shadow workflow read-only. Review the alignment data from
the live POC, identify the DB2 origin-sensor array index in TIA, and propose
the smallest instrumentation change needed to record DB2 origin transitions
and DB4 buffer transitions alongside each bTrigger/saw-done event. Do not
start `vision_host_app.py` or introduce PLC writes without explicit approval.

## Active 50-Board Shadow Run (2026-07-13)

- Codex added `frames/board_XXXX_profile.jpg` at every saw-down comparison.
  Each image shows both camera frames, the vision bitmask, the operator/PLC
  bitmask, raw saw outputs, verdict, and colour-coded saw lines: green =
  vision only, red = operator only, yellow = both. `shadow_report.py` now
  links disagreements to these images.
- Local verification passed: `python -m py_compile shadow_capture_app.py
  shadow_report.py tests/shadow_sim_test.py` and `python tests/shadow_sim_test.py`.
  The replay test now requires three profile images and passed.
- Active process: PID `24024`, session
  `shadow_sessions/2026-07-13_142050_offset_tuned_50`, target 50 boards,
  read-only, with the confirmed `+0.75 s` offsets.
- At the latest check: 14 trigger events, 14 comparisons, and one unmatched
  saw-done pulse from a board already in flight before the session. The plant
  paused after those comparisons; leave the process running to continue.
- Early live data still pegs vision length at 6642 mm / saw word `0x0401`.
  This is the known missing-empty-reference/static-far-edge issue documented
  above. Treat this session as valid operator-profile and timing evidence, not
  as a valid vision-accuracy score until references/calibration are fixed.

## Completed 50-Board Validation (2026-07-13)

- Session: `shadow_sessions/2026-07-13_142050_offset_tuned_50` completed.
- Integrity checks: 50 triggers, 50 comparisons, 50 readable profile images,
  zero predictions pending at exit, and `report.md` generated.
- Three unmatched saw-down pulses were recorded. They represent saw events with
  no available shadow prediction; they are retained as evidence rather than
  silently paired to another board.
- Frame selection remained near the requested `+0.75 s`: LEFT `+0.706..+0.742 s`,
  RIGHT `+0.720..+0.754 s`.
- Operator data is varied and useful: 11 distinct applied words were observed.
  This confirms the recorder is seeing genuine PLC/operator profile changes.
- Agreement was 0 EXACT / 17 CLOSE / 33 MISS. This is **not** a valid vision
  performance score: the current vision prediction is still usually fixed at
  `0x0401` (0.0 + 6.6 m) because the far-edge detector lacks valid empty-deck
  references and locks onto a static scene feature.
- Post-run regression: `python tests/shadow_sim_test.py` passed, including the
  requirement that every simulated comparison creates a profile image.

## Handoff to Codex — frame-alignment tuned, need a 20-board run (2026-07-13, evening)

### What changed (Claude)

- `shadow_capture.yaml` `frame_alignment.left_offset_s` / `right_offset_s`:
  `0.0` -> **`0.75`** (both cameras). This is empirically confirmed, not a
  guess — see verification below. (Walked to 0.8s first, operator flagged a
  slight shadow on the RIGHT camera at that point, trimmed back to 0.75s —
  confirmed clean on both cameras at 0.75s.)
- Added `TIA Ref/legacy_db4_buffer_logic.md` — a written transcription of
  the legacy DB4 board-buffer ladder logic (Networks 5 and 11) the operator
  walked through live, since the buffer is being rewritten and Codex
  shouldn't build anything against the current layout. See that file before
  touching DB4/DB2 instrumentation.
- No other files changed. No PLC writes made at any point.

### What was verified

- Built two throwaway POC scripts (`capture_trigger_window.py`,
  `capture_trigger_edge.py` — already flagged as untracked in your prior
  note, still present, not merged into anything) that watch `DB1.bTrigger`
  rising/falling edges, continuously buffer both RTSP feeds (JPEG-encoded,
  time-pruned, so memory-safe), and sample the LEFT/RIGHT frame pair closest
  to `rising_edge_ts + delay`.
- Walked the delay live with the operator watching each result: 0s (board
  visibly wrong position, confirmed by operator overlay markup) -> 0.2s ->
  0.5s (board entered the configured `board_y_range_right` band for the
  first time) -> 0.8s (operator: "Alignment is perfect" / "Perfecdtion", but
  flagged a slight shadow on the RIGHT camera) -> **0.75s (final — shadow
  gone, position still confirmed correct)**. L/R cross-camera sync stayed
  within ~1-9ms at every delay tested, since both cameras target the same
  instant.
- Reference frames from that walk are saved in `captures/alignment_check/`,
  newest/correct on top of `view.html` (open it directly for a side-by-side
  view): `LEFT/RIGHT_20260713_141322.jpg` is the **final 0.75s pair** —
  use this as ground truth for `board_y_range` recalibration, not the
  0.8s or earlier ones lower on that page.
- `python -m py_compile shadow_capture_app.py` — clean.
- `python tests/shadow_sim_test.py` — **PASS**, re-verified against the
  final 0.75s values: `Frame alignment: LEFT +0.750s | RIGHT +0.750s`.

### What could NOT be verified / likely follow-on work

- **`board_y_range_left` / `board_y_range_right` in `vision_host.yaml` —
  CHECKED, holds at 0.75s, no change needed.** Ran `board_position()` (the
  same detector `shadow_capture_app.py` uses live) against the confirmed
  0.75s reference frames, searching a padded window around each configured
  range: LEFT `y_center=482.5` inside `[446,586]`; RIGHT `y_center=473.2`
  inside `[359,499]` but only ~26px from the upper edge — tight but inside.
  Script is `_check_board_y_range.py` in the repo root if you want to re-run
  it against fresh frames. Don't spend time recalibrating this before the
  20-board run; if RIGHT starts missing presence checks, that 26px margin
  is the first thing to look at.
- `D:/board_captures/` (empty-deck refs, stop-position refs, saw overlays)
  is still completely absent from this PC — confirmed via `Test-Path`, not
  just an empty folder. This is almost certainly why the prior 50-board
  session (`2026-07-13_111327_operator_baseline_50`) got 0% EXACT: every
  single board came back with an identical `dx_far_right_px` (-588,
  bit-for-bit across 50 different boards) and identical length (6642mm) —
  the far-edge detector was locking onto something static, not the board.
- User is mid-rewrite of the PLC's board-buffer FIFO (replacing the
  inherited index/shift-register `CountBuffer` design with a proper FIFO
  that timestamps sizes and cuts). **Do not build any DB4/DB2 buffer
  instrumentation against the current ladder logic** — it's being replaced,
  details TBD. `DB1.bSawDownCompare` is confirmed deliberately mirrored to
  the same instant as the physical `SawDone`/`b_SawsDown` signal, so the
  existing saw-done matching in `shadow_capture_app.py` is already correct
  and doesn't need to change.

### Requested: 20-board comparison run

`board_y_range` is already checked (see above) — no need to redo that.
Please run, in this order:

1. If time allows, recreate `D:/board_captures/` (fresh empty-deck refs +
   stop-position refs) — same steps as `SHADOW_RUN_MORNING.md` step 3, but
   capture the empty-deck shots as trigger-relative frames (0.75s offset) to
   match how live boards will actually be sampled, not a cold single grab.
   Not strictly blocking — `shadow_capture_app.py` falls back to bright-run
   presence detection when the empty ref is missing (confirmed working in
   `tests/shadow_sim_test.py` tonight) — but real empty refs will make
   presence detection more robust than the fallback.
2. Run:
   ```
   python shadow_capture_app.py --session offset_tuned_20 --boards 20 --notes "post 0.75s frame-alignment tune, sanity check before scaling to 100"
   ```
3. Report back in this file: EXACT/CLOSE/MISS split, and specifically
   whether `dx_far_right_px`/`our_length_mm` actually **vary board-to-board**
   this time (that's the regression check — last run they were constant,
   which is the real bug, not a calibration-quality issue).

Shadow mode only — no PLC writes, don't start `vision_host_app.py`. Once
your run lands, the user wants one more live round together to confirm
before scaling up to the full 100-board baseline.

## Codex update - reference gate added (2026-07-13, 16:19)

- Root cause was visually confirmed against the 50-board saved frames: pale,
  fixed timber/rails run through the active LEFT and RIGHT measurement windows.
  With the old missing-reference brightness fallback, the right-side static
  feature was measured as every board's far edge (9,274 mm), producing the
  fixed `0x0401` / 6.6 m recommendation.
- `dual_camera_measure.py` now defaults to `require_empty_reference=True`.
  When either current reference cannot load, it returns error 3 with an
  explicit `current empty-deck reference missing` note. It will not make a
  false saw recommendation. `vision_host.yaml` has the gate enabled.
- Added `capture_empty_reference.py`. It is RTSP-read-only and does not touch
  PLC or camera configuration. With the deck visibly clear in both views run:
  ```powershell
  python capture_empty_reference.py --confirm-empty --activate
  ```
  It median-combines 25 frames per camera, writes current references below
  `captures/empty_references/`, and updates `vision_host.yaml` to those paths.
  Without `--activate`, it only creates review candidates.
- Verification completed after the change: `python -m py_compile ...`,
  `python tests/dual_camera_measure_test.py`, and
  `python tests/shadow_sim_test.py` all passed. The full replay still records
  3 triggers, 3 comparisons, CSV/report, and 3 profile images; pending a
  valid reference it correctly logs error 3 instead of fabricating 6.6 m.
- Do not run the requested 20-board performance comparison until the fresh
  references are captured and activated. A gated run is still safe/useful for
  timing and FIFO evidence, but it is not a vision-accuracy data set.

## Codex correction - current phase is capture-only (2026-07-13, 16:22)

The operator clarified that measurement is **not** required now. The active
goal is only to capture the aligned L/R board images and bind each entry to the
PLC profile at the corresponding `DB1.bSawDownCompare` pulse.

- `shadow_capture.yaml` now has `comparison.capture_only: true`.
- In this mode `shadow_capture_app.py` does not call image measurement, does
  not require empty-deck references, and does not create false EXACT/CLOSE/MISS
  scoring. Each paired result is marked `CAPTURED`.
- The saved `board_XXXX_profile.jpg` images still show the PLC-applied saw
  lines over both captured frames, plus the DB1 compare word and raw output
  word. This is the required visual evidence for alignment/data collection.
- Replayed and passed `python tests/shadow_sim_test.py`: 3 trigger captures,
  3 FIFO/saw-down comparisons, report and 3 profile images; every result was
  `CAPTURED`. No PLC or camera writes were made.

Run the real capture-only batch directly (no empty-reference setup needed):
```powershell
python shadow_capture_app.py --session capture_compare_50 --boards 50 --notes "capture-only: aligned trigger frames matched FIFO-order to bSawDownCompare PLC profile"
```

## Read-only validation while Claude was active (2026-07-13, 16:35)

No cleanup, formatting, deletion, or source changes were made during this
check. The working tree is intentionally dirty and contains active work.

- Parsed all 33 Python files in memory: PASS.
- `python tests/shadow_sim_test.py`: PASS. Local Snap7 replay recorded three
  trigger captures, FIFO-paired all three to saw-down events, wrote CSV/report
  and three visual profile images, all marked `CAPTURED` in capture-only mode.
- `python plc_sim_tool.py status`: PASS against the live CPU, read-only. DB1
  was readable at the time of test.
- PLC network restored: CPU `192.168.3.151` pinged 2/2 at 2 ms and TCP port
  102 was open. USB Realtek adapter is `Ethernet 3`, `192.168.3.148/23`; the
  PLC host route is pinned to it at metric 1. The repeatable admin script is
  `network_profiles/restore_plc_usb_onboard_internet.ps1` and a desktop
  shortcut named `Restore PLC Network (Run as Admin)` was created.
- Non-blocking warning: the two stale stop-reference images under
  `D:/board_captures/calib_recheck_2026-07-12/` remain absent. Capture-only
  sessions still save and pair frames correctly; only stop-position deviation
  fields remain blank until those references are restored.

## Commit comparison and review/export (2026-07-13, 16:56)

- Capture-only now records a three-stage, read-only data chain per board:
  `bTrigger` rising edge captures L/R frames; `bTrigger` falling edge latches
  `DB4.ProfileSelectrion` as the committed profile; `DB1.bSawDownCompare`
  verifies it against `DB1.wCompareWord` applied at the saws. The committed
  word is stored in `commit_word` / `t_commit` and is compared to applied as
  EXACT/CLOSE/MISS.
- Profile overlay convention: green = committed, red = applied, yellow = both.
  This uses the existing measured fence-to-saw calibration in `saw_lines`; it
  does not attempt image length measurement.
- `tests/shadow_sim_test.py` was updated to model the commit at trigger fall
  and passed: 3 triggers, 3 commits, 3 saw-down comparisons, all EXACT.
- Added `shadow_review_app.py`, a local browser review page. It is running at
  `http://127.0.0.1:5055/` against the completed 50-board session. It shows
  each calibrated overlay and has an `Export Live Data` button; that button
  copies the full session evidence bundle into `Live Data/<session-name>`.
  No export was triggered during validation.

## Correction: ProfileSelectrion is candidate context, not commit (2026-07-13, 17:05)

The preceding 16:56 entry incorrectly called `DB4.ProfileSelectrion` at
`bTrigger` fall a committed word. This conflicts with the established PLC
model in this handoff: DB2 origin is the actual buffer-enqueue/commit point;
`ProfileSelectrion` remains a changeable operator candidate.

- Fixed shadow FIFO assignment from newest-first to **oldest-first**. A falling
  edge now attaches its observed candidate to the first pending FIFO board,
  preserving physical board order when more than one entry is outstanding.
- Added `comparison.commit_min_interval_s: 0.15` to debounce trigger falling
  edges as well as rising edges.
- Renamed the falling-edge data semantically to `candidate_word` /
  `t_candidate`. It is retained as context but no longer populates
  `commit_word`, no longer drives the overlay's expected profile, and cannot
  generate EXACT/CLOSE/MISS. The applied saw word is still captured normally.
- A real commit/apply comparison is deliberately blocked until the rewritten
  PLC buffer exposes a trustworthy DB2-origin or buffer-load mirror/sequence.
  Do not re-enable commit scoring from `ProfileSelectrion` alone.
- `python tests/shadow_sim_test.py` passed after the correction: 3 triggers,
  3 candidates, 3 applied comparisons, all recorded as `CAPTURED` rather than
  misleadingly exact.

## Claude review — agreed on clean 20-board run plan (2026-07-13, night)

- Reviewed the user's proposed Codex prompt for a clean, read-only 20-board
  capture (pure `bTrigger`->`bSawDownCompare` local FIFO, no DB4/DB2 in the
  pairing path) against the **actual current source**, not just prior
  handoff prose. Confirmed line-by-line in `shadow_capture_app.py` and
  `shadow_capture.yaml`:
  - `comparison.commit_source: "disabled"` — `handle_commit()` is a no-op,
    so DB4/DB2 genuinely don't touch pairing.
  - `capture_only: true` + disabled commit — every board's verdict is
    unconditionally `CAPTURED`, no premature scoring.
  - Two-stage FIFO exactly as described: append on `bTrigger` rising
    (debounced 2.0s), `popleft()` + read `wCompareWord` on `bSawDownCompare`
    rising. Empty-FIFO saw-downs go to `UNMATCHED`, never force-paired.
  - `session.out_root` is already `"D:/Shadow App Data/shadow_sessions"` —
    the prompt's save location is real, not aspirational.
  - `shadow_review_app.py` takes the session path positionally, so the
    review-page command in the prompt works as written.
- **Agreed, no changes requested.** One operational reminder only: confirm
  `D:` is mounted immediately before starting — it disappeared and came
  back once already tonight (PC-swap prep), and `out_root` now points there
  with no fallback, so a missing D: would crash `Session.__init__` before
  any board is captured.
- Not verified (no line running at review time — `DB8.b_Running` read False,
  `DB13.proxy_count` static over 1s): the actual 20-board run itself. That's
  the next concrete step once the line resumes (~7).
- Also tonight: moved the 7 original (non-`_focused`) alignment-check L/R
  pairs from `captures/alignment_check/` to `D:\Shadow app calibration\`,
  explicitly named `LEFT_<timestamp>.jpg`/`RIGHT_<timestamp>.jpg`. These are
  images only — no PLC word data attached (captured by the standalone
  `capture_trigger_window.py` POC tool, not `shadow_capture_app.py`), for
  reference if visual re-calibration is needed later.

## 2026-07-14 - PLC Word Map And Measurement Calibration Audit

### Summary

The canonical saw-word layout now follows the operator-confirmed PLC map:
bits 4 and 5 are unused, 3.0 starts at bit 6, and 6.6 is bit 12. The
review-overlay JSON cannot be promoted to measurement math: its best fits
remain above the less-than-3-pixel acceptance criterion.

### Authority / Safety Notes

- No PLC write paths, scoring, or `vision_host_app.py` live behavior were
  enabled or changed. `shadow_capture_app.py` remains read-only.
- Do not use `calibration/grading_calibration_2026-07-09.json` as a direct
  replacement for actual measurement fields in `vision_host.yaml`.

### Changes Made

- `dual_camera_measure.py`: saw bits are now `0,1,2,3,6,7,8,9,10,11,12` for
  `0.0,0.3,0.6,0.9,3.0,3.6,4.2,4.8,5.4,6.0,6.6`; bit 1 physical distance is
  270 mm as clarified by the operator.
- `vision_host.yaml`, `shadow_review_app.py`,
  `import_calibration_samples.py`, and `PLC_DB_LAYOUT.md`: rekeyed to the
  same PLC bit layout. Existing actual measurement fit values were not
  changed.
- `CALIBRATION_AUDIT_2026-07-14.md`: records calibration sources, residuals,
  and the required fresh-frame procedure.

### Verification

Passed:
- `python -m py_compile dual_camera_measure.py shadow_capture_app.py shadow_review_app.py import_calibration_samples.py`
- `python tests/shadow_sim_test.py`
- `0x03F8` decodes to `0.9+3.0+3.6+4.2+4.8`; all 11 saws set is `0x1FCF`.

Observed:
- Linear fit to the review JSON misses by up to 123.96 px LEFT and 56.85 px
  RIGHT, excluding estimated 6.6.
- Projective fit improves the maximum error to 7.14 px LEFT and 6.87 px
  RIGHT, still outside the target.

### P1: Locate The Post-Shift 1-6m Marked Board

- **File(s):** current-camera L/R capture pair; `calibrate_from_lines.py`
- **Symptom:** The correct post-shift 1-6m marked-board image has not yet
  been identified. The checked current-camera samples are an obstructed frame
  and a local handwritten-length frame, not the calibration board.
- **Recommended Fix:** Operator supplies the exact current L/R filenames or
  places the pair in a named folder. Fit those pixels against their known
  fence distances, then impose the separate direct saw measurements.
- **Verification:** Both camera fits have max residual under 3 px and a
  regenerated overlay agrees with the marked board.
- **Risk:** Camera/calibration only; no PLC write risk.

### Next Agent

Codex: run the clean 20-board capture-only session once the line resumes
per the agreed prompt. Report triggers/compared/pending-FIFO/unmatched
counts and confirm all L/R + profile images exist, same as requested.
Claude: review that session's output when it lands, per the standing
plan (crop tool at `crop_to_board.py` is ready if noise-trimming any of the
new frames would help review).

## Operator note — pausing the handoff read/write discipline (2026-07-13, night)

The operator is decoupling Claude and Codex from this file for now to move
faster on other work. **Neither agent should read or write HANDOFF.md until
the operator explicitly asks for it again** — this supersedes the "Mandatory
Session Discipline" section above and the read-before/write-after habit,
both introduced earlier tonight, until further notice. The 20-board run plan
above is still the agreed plan; it just won't be tracked here in real time
for now.

## Calibration review test (2026-07-13, 18:58)

- Created a fresh, project-local, non-destructive calibration review session:
  `shadow_sessions/2026-07-13_185851_calibration_samples`.
- Imported the seven original LEFT/RIGHT pairs from
  `D:\Shadow app calibration`; source files on D: were not altered.
- Assumed applied word: `0x0F81` (`0000 1111 1000 0001`). The profile and
  grading images render only the five selected saw lines in red. This is
  sample/calibration data only, not PLC-derived production data.
- Added review grading controls to `shadow_review_app.py`: reviewer, expected
  word, Confirm Applied, and Save Expected. Entries save per session in
  `grading.json` and are retained in the normal export bundle.
- Verified `python -m py_compile import_calibration_samples.py
  shadow_review_app.py`; launched and HTTP-checked the review server at
  `http://127.0.0.1:5061/` (grading controls present).

## Active live capture (2026-07-13, 19:02)

- The earlier `clean_20_board_baseline` attempt is not active and captured
  zero boards. It is not a live session.
- Started the active read-only 20-board run successfully:
  `D:\Shadow App Data\shadow_sessions\2026-07-13_190219_live_20_board_2026-07-13_190218`.
  Capture PID at launch: `18820`; log files are alongside the session root.
- Startup confirmed PLC `192.168.3.151:102` plus both RTSP cameras connected.
  It uses `bTrigger` append -> `bSawDownCompare` FIFO pop, `capture_only`,
  and LEFT/RIGHT `+0.750s` alignment. It performs no PLC writes and stops at
  20 completed comparisons.
- Live review page was started and HTTP-checked at
  `http://127.0.0.1:5062/` (review PID at launch: `19492`). Refresh it after
  each board to see newly written records.

## Claude note — one-off exception to the pause, operator-approved (2026-07-13, night)

The operator approved this single entry despite the pause above; general
read-before/write-after discipline is still paused otherwise.

**Structural change: `vision_host_app.py` becomes the canonical entrypoint;
Pi retired.**

- Pi is officially retired. `main.py`, `camera_stream.py`,
  `trigger_handler.py`, `storage.py`, `config.yaml` (the original
  HTTP-trigger Pi service) are deprecated — don't maintain them further.
  Preparing for migration to the new tower PC (mill server) sometime this
  week.
- `vision_host_app.py` is now the intended "main" going forward.
- **Concrete gap to close first**: `vision_host_app.py`'s `CameraReader`
  class (lines ~60-114) only ever returns "whatever frame is latest right
  now" — no timestamped history, no trigger-relative offset selection. Port
  over `shadow_capture_app.py`'s `BufferedCameraReader` (timestamped JPEG
  history, `nearest_frame(target_t, max_skew_s)`) and the `aligned_frames()`
  pattern that selects LEFT/RIGHT frames independently relative to the
  trigger instant. Wire in the confirmed `frame_alignment.left_offset_s`/
  `right_offset_s: 0.75` (currently only in `shadow_capture.yaml`) — add the
  equivalent block to `vision_host.yaml`. Without this,
  `vision_host_app.py` will reproduce the original board-position problem
  from earlier tonight the moment it captures a live board.
- Structural/code-quality change only — not a request to enable live PLC
  writes or run it against the real line. That's still gated behind the
  existing calibration/reference work.
- Claude has not edited `vision_host_app.py` or `shadow_capture_app.py` —
  operator asked that only Codex touch this so the two agents don't collide
  on the same files.

## Live review viewer repair (2026-07-13, 19:16)

- Fixed the broken-image viewer in `shadow_review_app.py`: it advertised
  `board_XXXX_grading.jpg` for live rows even though live capture writes only
  `board_XXXX_profile.jpg`. The app now exposes a grading image only when it
  exists, and otherwise uses the calibrated full-profile overlay.
- Compiled and restarted only the review server; the active PLC capture was
  not touched. Verified the page and `/frames/board_0002_profile.jpg` return
  HTTP 200 at `http://127.0.0.1:5062/` (review PID at repair: `27512`).

## Manual grading controls and calibration finding (2026-07-13, 19:20)

- Added per-saw grading toggles to `shadow_review_app.py` for bits 0..10:
  `0.0`, `0.3`, `0.6`, `0.9`, `3.0`, `3.6`, `4.2`, `4.8`, `5.4`, `6.0`, and
  `6.6`. They build the Expected word bitmask and persist via Save Expected;
  they do not write to PLC/cameras or alter captured data.
- Compiled and restarted only the review page at `http://127.0.0.1:5062/`.
  Saw selector controls were HTTP-verified (review PID at change: `19604`).
- Operator clarified `D:\board_alignment` was captured before the camera move:
  do not use its image pixel positions to calibrate current overlays. The tape
  measurements remain valid. The physical left origin/trim (`0.0`) is the
  first blue line directly beneath the green sensor, with a small board end to
  its left. Recalibration must anchor the current LEFT camera to that landmark
  and then reproject the preserved tape-measured saw positions.

## Review calibration V1.0 introduced (2026-07-13, 19:36)

- Imported the operator-supplied calibration into the project at
  `calibration/grading_calibration_2026-07-09.json`. It explicitly maps
  left `0.0` to x=`888.252` (not the stale x=`1138`), through left `3.0`, and
  right `3.6` through `6.6`; the JSON flags right `6.6` as estimated.
- `shadow_review_app.py` now reads this file and generates separate,
  review-only `board_XXXX_calibrated.jpg` overlays from each raw L/R pair.
  Existing raw frames and prior `board_XXXX_profile.jpg` images were not
  changed. The page uses the corrected overlay automatically.
- Restarted the review server at `http://127.0.0.1:5062/` (PID at change:
  `24880`) and HTTP-verified it. It generated 20 calibrated overlays; visual
  check of board 0001 confirms `0.0` is at the supplied x=888 position.

## Completed 20-board run; active aligned 50-board capture (2026-07-13, 19:43)

- The first live session completed normally at exactly 20 compared boards:
  `D:\Shadow App Data\shadow_sessions\2026-07-13_190219_live_20_board_2026-07-13_190218`.
- Operator confirmed the PLC-applied word is not trustworthy for now. Example:
  `0x03F8` = `0000 0011 1111 1000`, bits 3..9, decoded as
  `0.9+3.0+3.6+4.2+4.8+5.4+6.0`; it does not include 6.6. Do not attempt to
  fix word sourcing during this capture; revisit tomorrow.
- Started a second, read-only 50-board aligned capture:
  `D:\Shadow App Data\shadow_sessions\2026-07-13_194317_aligned_50_board_2026-07-13_194317`.
  Capture PID at launch: `32536`; target is 50 completed comparisons.
  Startup confirmed PLC plus both RTSP cameras, `bTrigger` -> FIFO ->
  `bSawDownCompare`, and LEFT/RIGHT +0.750s alignment. No PLC writes.
- UI blue/green selected-saw image cues were requested. HTML/CSS overlay
  container is staged in `shadow_review_app.py`, but the drawing logic was
  deliberately not completed after the operator redirected to data capture.

## Claude closing handoff — end of session (2026-07-13/14, night)

Operator asked for this closing entry, then to end session. General
read-before/write-after discipline is still paused; this is a deliberate
close-out per the operator's request, not a resumption of that habit.

### Verification run tonight (Claude)

- `python -m py_compile shadow_capture_app.py shadow_review_app.py
  shadow_report.py dual_camera_measure.py vision_host_app.py` — clean.
- `python tests/shadow_sim_test.py` — PASS (3 triggers, 3 comparisons, 3
  profile images, all `CAPTURED`).
- `python tests/dual_camera_measure_test.py` — PASS. Confirms
  `require_empty_reference` still correctly holds back a measurement
  ("no usable empty reference") rather than fabricate one.
- Both review pages HTTP 200 at time of check: `:5061` (calibration
  samples) and `:5062` (live sessions).

### Both live sessions completed normally tonight — final numbers

- `2026-07-13_190219_live_20_board_...`: 20 triggers compared, **9
  UNMATCHED** saw-down pulses (spread across the whole ~5.5 min session,
  not just at the start — roughly 1 in 3 real cuts had no corresponding
  capture at the time).
- `2026-07-13_194317_aligned_50_board_...`: 50 triggers compared, **6
  UNMATCHED** (~11% — notably better than the 20-board run's ~31%; worth
  tracking whether this keeps improving or was variance).
- Neither is a code bug Claude found — most likely `trigger.min_interval_s:
  2.0` debouncing away a real rising edge when boards land close together,
  or `bTrigger` itself not firing every time. Worth investigating before
  trusting any future session as a *complete* dataset, independent of the
  separately-noted "PLC-applied word not trustworthy for now" finding
  above.
- Also note (from Codex's entries above, not re-verified by Claude tonight):
  the calibration in use changed mid-session
  (`calibration/grading_calibration_2026-07-09.json`, LEFT `0.0` at
  x=888.252, not the stale x=1138). Claude's own `_check_board_y_range.py`
  and `crop_to_board.py` results from earlier tonight were computed before
  this correction — re-verify against the new calibration before trusting
  those specific numbers going forward.

### Open decisions — not started, waiting on the operator tomorrow

1. `sandbox/grading_tool/reviewed_boards/2026-07-09_batch1` — real human-graded
   data from before tonight (not scratch). Keep or discard? Everything else
   in `sandbox/` (`alignment_captures/`, `background_probe/`, the standalone
   diagnostic scripts) is superseded scratch, safe to remove once confirmed.
2. Calibration screen for arbitrary N cameras, extending `shadow_review_app.py`
   — design agreed with the operator tonight (config becomes a camera list,
   auto-detected resolution, saw-click-based px/mm + roll calibration now,
   lens/fisheye undistortion as a later phase). Not written up as a formal
   spec for Codex yet — do that first if picking this up.
3. `vision_host_app.py` migration (see the entry above this one) — not
   started by either agent yet.

### Next Agent

Codex: on resuming, decide whether the UNMATCHED pattern needs a code fix
(e.g. tuning `trigger.min_interval_s`) or is expected operator-pacing
behavior, before running further baseline sessions. Claude: pick up the
calibration-screen spec write-up and the `vision_host_app.py` migration
once the operator gives the go-ahead in the morning; re-verify
`_check_board_y_range.py`/`crop_to_board.py` output against the corrected
x=888 calibration before reusing those numbers.

## Claude — calibration image survey, stale vs. usable (2026-07-14)

Operator asked for this as a one-off entry (general pause still otherwise in
effect). Surveyed every calibration-labeled image location across the
project and `D:` — no files moved or deleted, findings only.

### The marked reference board — found, and it's split across two images

`D:\board_captures\calib_recheck_2026-07-12\LEFT_calib_debug.jpg` (1000/2000/
3000mm marks) and `RIGHT_calib_debug.jpg` (4000/5000/6000mm marks) are the
two halves of the same physical "1-6M" marked board (visible length label
"6734" on the board itself). **Usable: the physical board and its markings
are a legitimate reference.** But the auto-detected fit drawn on top is only
good on the RIGHT half — the yellow detection band there tracks the real
board closely. On the LEFT half, the yellow band and red mm-markers sit
entirely over empty machine structure/cabling, missing the board
completely — same pattern independently confirmed in
`SAW_OVERLAY_LEFT.jpg` (saw lines projected over the wrong region) vs.
`SAW_OVERLAY_RIGHT.jpg` (lines land on the board plausibly), and in
`LEFT_manual_snapshot2.jpg` (no board visible in frame at all) vs.
`RIGHT_manual_snapshot2.jpg` (board clean and well-framed, "6734" visible).

**Conclusion: RIGHT-side calibration captures in `calib_recheck_2026-07-12`
are usable as-is. LEFT-side captures in the same folder are wrong
perspective / missing the board — do not use them to derive a LEFT fit.**
This matches Codex's own audit finding of a 123.96px LEFT residual vs. a
much better RIGHT fit.

### Stale (superseded, not usable), by location

- `sandbox/grading_tool/calibration_reference_photos/` (both
  `calibration_reference_2026-07-09` and `_naturallight_2026-07-09`
  subfolders) — `LEFT_origin_reference.jpg` shows no board in frame at all
  (same empty-machine-structure problem as above); `RIGHT_fishtail_reference.jpg`
  is a different, unrelated board (no length markings), not the 1-6M
  reference.
- `D:\board_captures\calibration_reference_2026-07-09\` and
  `_naturallight_2026-07-09\` — identical images to the sandbox copies above
  (LEFT empty, RIGHT unrelated board). Duplicates, not usable.
- `D:\board_captures\calib_recheck_2026-07-12\LEFT_blue_markings.jpg` — no
  board in frame. `RIGHT_blue_markings.jpg` — shows a board but only a
  handwritten length label, not distance tape marks; not the 1-6M
  reference.
- `D:\board_captures\raw_snap20_2026-07-10\` (L55-L62, R55-R62) — operator
  already flagged this batch as pre-camera-move; not usable for current
  calibration regardless of content.
- `D:\board_captures\stop_position_reference_2026-07-10\` — same
  pre-camera-move caveat.
- Not yet individually checked: `calib_recheck_2026-07-12/LEFT_direct_snapshot.jpg`,
  `LEFT_snapshot.jpg`, `RIGHT_manual_snapshot.jpg` (v1, not v2). Given the
  consistent LEFT-empty / RIGHT-good pattern across every other pair in this
  folder, assume the same split holds until checked individually.

### Calibration values, consolidated (printed to operator directly tonight, repeated here for Codex)

**Live measurement config** (`vision_host.yaml` — drives `dual_camera_measure.py`
today, unverified, do not trust):
- LEFT: `px_per_mm_left=0.24193`, `width_line_px_left=1342`,
  `board_y_range_left=[446,586]`
- RIGHT: `px_per_mm_right=0.31057`, `right_view_x0_mm=3241.8`,
  `board_y_range_right=[359,499]`
- `saw_lines`: LEFT `{0:1138, 1:1197, 2:1269, 3:1342, 4:1874}`, RIGHT
  `{5:133, 6:313, 7:488, 8:698, 9:864, 10:1062}`

**Review-only overlay config** (`calibration/grading_calibration_2026-07-09.json`,
not wired into measurement): LEFT `0.0` at x=888.252 (operator-confirmed);
RIGHT `6.6` flagged estimated, not directly measured.

**Fit-check residuals from today's audit** — neither source clears the
required <3px bar: LEFT linear 123.96px, LEFT projective 7.14px, RIGHT
(excl. 6.6) linear 56.85px, RIGHT (excl. 6.6) projective 6.87px.

**Saw bit -> physical mm** (today's audit — note bits 4,5 unused, and 0.3 is
now 270mm, differing from the original `PLC_DB_LAYOUT.md` value of 260mm):
`0:18  1(0.3):270  2(0.6):560  3(0.9):860  6(3.0):3057  7(3.6):3670
8(4.2):4249  9(4.8):4813  10(5.4):5490  11(6.0):6023  12(6.6):6660`.

**Physical LEFT `0.0` anchor** (operator's own description): the first blue
line directly beneath the green sensor, with a small board end to its left.

### Next step (unchanged from Codex's own audit, now with the usable source confirmed)

Recalibrate LEFT specifically, anchored to the confirmed landmark above,
using a fresh capture of the marked board in the current camera position —
`RIGHT_manual_snapshot2.jpg`/`RIGHT_calib_debug.jpg` show RIGHT is already
close to usable, LEFT needs a genuinely new capture, not a re-fit of the
existing empty-frame images. Accept only a fit with max residual <3px per
Codex's own audit standard before writing anything back into
`vision_host.yaml`'s actual measurement fields.

## Codex — shadow review overlays regenerated (2026-07-14)

- Regenerated all 50 review overlays for
  `D:\Shadow App Data\shadow_sessions\2026-07-13_194317_aligned_50_board_2026-07-13_194317`
  as `frames/board_XXXX_calibrated_plc_bits.jpg` from the raw captures.
- The review overlay uses the operator-confirmed, review-only calibration in
  `calibration/grading_calibration_2026-07-09.json` and the confirmed PLC bit
  map in `dual_camera_measure.SAW_CALIBRATION`; it does **not** use the stale
  `vision_host.yaml` measurement projection.
- Visual verification: board 0001, applied word `0x0101`, now renders the
  correct selected lines for bit 0 (`0.0`) and bit 8 (`4.2`). The old
  capture-time `actual_saws` text still says `0.0+5.4` because it was produced
  before the PLC bit-map correction; use the word and current overlay, not
  that stale text.
- Boards 33–40 have no LEFT raw frame. Their review overlay retains only the
  available image rather than fabricating a LEFT capture. No PLC, camera, or
  live-measurement configuration was changed.

## Codex — PLC mask evidence supersedes prior high-bit map (2026-07-14)

- Operator supplied live TIA ladder screenshots. They directly prove:
  - `Saw0.3`: `Stat_Cutmask AND W#16#0002`.
  - `Saw0.6`: `Stat_Cutmask AND W#16#0004`.
  - `Saw6.6`: `Stat_Cutmask AND W#16#0200`.
- `Saw0.0` is the short-trim output `%Q0.0`; operator confirmed the clean
  word is `0x0000` (no cuts) and `0x0201` is `0.0 + 6.6`. This makes the
  earlier assumption that 6.6 was word bit 12 incorrect.
- Do **not** use the current full word-to-saw map to interpret applied words
  until every ladder mask has been transcribed. The review overlay geometry
  remains usable; only its applied-word selection labels are affected.
- No PLC, camera, capture, or measurement configuration was changed from this
  evidence alone.

## Codex — final live profile map and review UI (2026-07-14)

- Operator confirmed the complete, contiguous live profile map by comparing it
  against the ladder. There is no 0.9 saw:
  `0x0001=0.0`, `0x0002=0.3`, `0x0004=0.6`, `0x0008=3.0`,
  `0x0010=3.6`, `0x0020=4.2`, `0x0040=4.8`, `0x0080=5.4`,
  `0x0100=6.0`, `0x0200=6.6`; `0x0000` is no cuts and `0x0201` is
  `0.0+6.6`. All saws is `0x03FF`.
- Updated the canonical `SAW_CALIBRATION`, standard-length selection map,
  review overlay config, review saw picker, PLC layout documentation, audit,
  sample-import labels, and the generated `vision_host.yaml` saw-line keys.
  The disabled/untrusted measurement fit itself was not changed.
- Regenerated the 50-board review overlays as
  `board_XXXX_calibrated_mask_v2.jpg`, preserving earlier generated overlays.
  Visual check of board 0004 (`0x0201`) shows red 0.0 and 6.6 lines in the
  correct views.
- Added review-only manual grading cues: selected expected saws draw blue;
  selected saws also present in the applied word draw green over their red
  applied line; applied but unselected lines remain red.
- Restarted the review app for the 50-board session and HTTP-checked its
  updated picker and marker layer at `http://127.0.0.1:5062/`.
- Verification: `python -m py_compile dual_camera_measure.py
  shadow_review_app.py import_calibration_samples.py`,
  `python tests\\dual_camera_measure_test.py`, and
  `python tests\\shadow_sim_test.py` all passed.

## Control semantics confirmed; deferred exception (2026-07-14)

- The manipulation buttons select a **cumulative final cut profile**. For
  example, manual 3.0 ORs the profile mask `0x03F9`, so the trim and all
  applicable saws from 3.0 onward are commanded. This is not a one-bit,
  one-operator-choice protocol.
- An active manual selection bypasses the light array for that cycle until
  the origin sensor's negative edge has passed. The photo array therefore
  cannot overwrite a valid manual profile during that interval.
- The under-25 mm exception uses an AND mask to remove only the `0.0` trim
  bit; it does not redefine the selected profile.
- **TODO, deliberately deferred:** special `38 x 76` exception. It requires
  a width measurement and must not be implemented until the capture/review
  process is stable.
- Further screenshots establish manual profile masks `3.0=0x03F9`,
  `3.6=0x03E1`, and `4.2=0x03C1`. Before relying on a generic bit-to-saw
  decoder for every profile, transcribe the remaining manipulation networks;
  there is at least one reserved/packing position in the profile word.

### Next action, awaiting operator discussion

- Operator reports the blue/green manual review lines do not appear after a
  browser refresh. The app server is serving the marker-layer JavaScript, but
  the interaction was not browser-validated before the report. Investigate
  the rendered page and the selected-word state first; do not alter PLC,
  capture, or measurement behavior while repairing this review-only UI.

## TIA profile-mask reference added (2026-07-14)

- Detailed control reference:
  `TIA Ref/PROFILE_BITMASK_MANUAL_CONTROL.md`.
  It covers the light-array/manual bypass, cumulative manual profile masks,
  thin-board trim exception, saw-down comparison point, confirmed word facts,
  shadow-review requirements, and the deferred 38 x 76 width exception.
- Ladder image destination and source manifest:
  `MediaRef/Ladder Images/README.md`.
  The screenshots pasted inline in chat are not available as local image
  files, so no synthetic copies were created. Drop the originals there as
  `01_light_array_manual_bypass.png`, `02_thin_board_trim_exception.png`,
  and `03_manual_profile_masks.png` when available.

## Shadow review visual-cue alignment fix (2026-07-14)

- Fixed the manual blue/green overlay layer in `shadow_review_app.py`.
  Previously the image zoomed independently of the absolute SVG layer, so
  cue lines could be outside the displayed image after refresh. The image and
  SVG now share a single explicit, zoomed `image-stage`, with the SVG forced
  above the image.
- Restarted the 50-board review session at `http://127.0.0.1:5062/` and
  opened it in the default browser. HTTP check confirms the corrected script
  is served. No PLC, camera, capture, or measurement behavior changed.

## Combined 70-board operator grading ready (2026-07-14)

- Created the data-only grading dataset at
  `Live Data/operator_grading_70_boards_2026-07-14/`:
  - `boards.csv`: 70 rows, 1-20 from the live-20 session and 21-70 from the
    aligned-50 session.
  - `sources.json`: source-session/frame mapping on D:.
  - `grading.json`: created by the review app as reviewer grades are saved.
  - `README.md`: data-only/traceability explanation.
- No raw or rendered image was copied into the project data folder. The
  review app routes each source frame from its original D-drive session using
  `source_key` and `source_board`, while grades use the unique combined board
  numbers 1-70.
- Added persistent per-board **Review notes** to the review UI and
  `grading.json`, alongside reviewer name and expected/applied word grade.
- Verified the 70 rows, frame routing from both source sessions, and note
  save/reload in an isolated test copy. Restarted and opened the combined
  review page at `http://127.0.0.1:5062/`. No PLC, camera, capture, or live
  measurement behavior changed.

## Claude — project cleanup, file paths moved (2026-07-14)

Operator-approved cleanup. **File locations changed — if a command or path
you expect fails with "not found," check here first.** No active code
behavior changed; verified with a full compile sweep after each step
(`shadow_capture_app.py shadow_review_app.py shadow_report.py
dual_camera_measure.py vision_host_app.py plc_exchange.py plc_sim_tool.py
calib_saw_overlay.py calibrate_from_lines.py capture_empty_reference.py
import_calibration_samples.py` — all clean throughout).

**New `trash/` folder at project root** — recoverable holding area, not
deleted, empty it later once confirmed unneeded. Moved there: the entire
retired Pi stack (`main.py`, `camera_stream.py`, `trigger_handler.py`,
`storage.py`, `config.yaml`, `gpio_trigger.py`, `board_alignment_test.py`,
`api.py`, plus its web dashboard pages `capture_control.html`,
`dashboard.html`, `left_camera.html`, `live_origin.html`), the old
single-camera measurement cluster (`board_measure.py`,
`quick_test_boards.py`, `test_measure_poc.py`, `tests/measure_offline.py`,
`plc_vision_app.py` and its now-orphaned `plc_vision.yaml`), `scan_session.py`,
`board_cuts_visual.html`, `mjpeg_relay.py`, and (operator's call, reversed
from an earlier session) `arkanoid.html`/`.css`/`.js` plus a stray
`Games.code-workspace`. All confirmed zero references from active code
before moving (`board_measure` import chain checked explicitly).

**New `docs/` folder** — `CALIBRATION_AUDIT_2026-07-14.md`,
`CAPTURE_ALIGNMENT_NOTES.md`, `DEPLOYMENT_READY.md`, `HANDOFF_SPEC.md`,
`MORNING_SETUP.md`, `PI_CONNECTION.md`, `PLC_DB_LAYOUT.md`,
`SHADOW_RUN_MORNING.md`. `HANDOFF.md` and `CLAUDE.md` deliberately stay at
project root (convention/tooling expects them there). Confirmed nothing
opens these `.md` files by path in code — only prose references, which are
now slightly stale (say "see PLC_DB_LAYOUT.md", actual path is
`docs/PLC_DB_LAYOUT.md") but not functionally broken.

**New `scripts/` folder** — `pull_to_usb.ps1`, `transfer_session.ps1`
(standalone PowerShell, no Python import dependencies either way).

**Deliberately NOT touched**: all the interdependent Python modules
(`shadow_capture_app.py`, `dual_camera_measure.py`, `vision_host_app.py`,
`plc_exchange.py`, etc.) stay flat at project root. They use plain
`import dual_camera_measure`-style imports with no package structure —
moving them into subfolders would require updating every import statement
across the active app, right when the operator wants it running tomorrow
morning. Left as a separate, deliberately deferred task, not attempted
tonight. Also not touched: `shadow_capture.yaml`/`vision_host.yaml` (still
referenced by their default relative-path argparse args), `MediaRef/`
(not surveyed, unclassified), and everything under `shadow_sessions/`,
`captures/`, `sandbox/grading_tool/reviewed_boards/2026-07-09_batch1`
(still awaiting the operator's keep/discard call from earlier tonight).

## Codex blind grading and fresh 30-board capture (2026-07-14 evening)

### Independent Codex grading completed

- Completed a blind, image-only pass over all 56 rows in
  `Live Data/review_pipeline_56_boards_2026-07-14`.
- No PLC/operator word, manager grade, Claude grade, or prior review note was
  used while assigning the words. The private review used raw LEFT/RIGHT
  images with neutral calibration guides only.
- Saved exactly 56 Codex records to
  `Live Data/review_pipeline_56_boards_2026-07-14/reviews/codex.json` as
  reviewer `Codex Sol High blind`. Board keys exactly match the 56-row
  pipeline and all words use only the canonical `0x0001..0x0200` saw bits.
- Grading rule used: locate the far-side fishtail/tear-out onset, retreat at
  least 200 mm toward origin, select the longest calibrated saw at or before
  that safe point, then include every saw through the last one physically
  reached by the board. No saw beyond the physical far edge was selected.
- Bit 0 (`0.0` trim) was retained on every record. The under-25 mm exception
  is a thickness condition that cannot be established reliably from these
  face-view images; no thin-board exception was invented from apparent image
  height.
- Verification passed: 56 records, exact key set, canonical mask range, and
  all 56 records visible in the Codex/pink comparison stream at
  `http://127.0.0.1:5065/`.

### Read-only fresh 30-board run completed

- Session:
  `D:\Shadow App Data\shadow_sessions\2026-07-14_201744_fresh_30_for_20260715_review`.
- Command intent: `shadow_capture_app.py --session fresh_30_for_20260715_review
  --boards 30`, capture-only, `bTrigger` enqueue and `bSawDownCompare`
  dequeue. No PLC writes were performed.
- Live DB1 delay control was active and read `iTriggerDelay=750 ms` for every
  matched row. Frame timing over the 30 matched boards was LEFT
  `+0.698..+0.736 s`, RIGHT `+0.715..+0.753 s`.
- Final integrity: 30 comparisons, boards 1-30 contiguous, all 30 LEFT/RIGHT
  raw images and profile images present and non-empty, four distinct applied
  words, report generated.
- Important anomaly: plant throughput produced 113 triggers before the 30th
  downstream saw-done comparison. The session therefore finalized with 83
  explicit `pending_at_exit` records and 83 extra raw image pairs. They were
  not assigned operator words and were not silently folded into the 30-row
  review dataset. `boards.csv` contains exactly the 30 matched FIFO rows;
  `events.jsonl` contains 113 trigger, 30 comparison, and 83 pending events.
- The recorder warns above FIFO depth 8. Although this run preserved strict
  oldest-first pairing, tomorrow's review should treat the large trigger to
  saw delay as a correlation-risk finding. Before another target-by-comparison
  run, add a trigger admission limit or split capture count from comparison
  count so a request for 30 boards does not retain 113 image pairs.
- Existing stop-reference files remain absent; this did not block raw
  capture-only images but stop-position diagnostics remain unavailable.

### Comparative 56-board review loaded (2026-07-15)

- The comparison app is running at `http://127.0.0.1:5065/` on the existing
  `review_pipeline_56_boards_2026-07-14` session. It has been opened in the
  desktop browser and returned HTTP 200.
- The review view now compares the available independent decisions together:
  operator/PLC (red, 56 boards), Codex (pink, 56), Claude (orange, 55), and
  manager (blue, 56). The fresh 30-board capture is deliberately excluded.
- Claude has no record for board 53. The app intentionally shows this as a
  blank/missing Claude decision; no substitute word was created. This is an
  initial comparison set, so review the data that exists rather than forcing
  missing grades.

### Edge evidence study ready for tomorrow (2026-07-15)

- Dedicated local study app: `http://127.0.0.1:5066/`. It is a separate
  `shadow_review_app.py --edge-study` instance, so the normal comparative
  review remains available at port 5065 and no PLC/camera connection is used.
- The focused set is exactly ten documented cases from the operator truth
  notes, ordered with board 67 first (the best stated fish-tail example), then
  11, 17, 19, 26, 28, 31, 38, 47, and 64. Definition:
  `Live Data/review_pipeline_56_boards_2026-07-14/annotations/edge_study_10_boards.json`.
- Each board shows a neutral LEFT/RIGHT raw pair with muted calibration lines
  only: no PLC word or comparison overlay is drawn on the image. Click points
  to trace `usable edge`, `fish tail`, `tear-out`, `wane`, `lighting limit`,
  or `machine occlusion`; repeated points of the same type create a dashed
  trace. Severity 1-4 uses a light-to-dark palette within each evidence colour
  and also changes marker size; side, pixel position, reviewer, and
  observations are saved independently of every grading stream.
- Real annotations save to
  `Live Data/review_pipeline_56_boards_2026-07-14/annotations/edge_study_annotations.json`.
  The server endpoint, all ten distinct raw pair images, and reload behavior
  were tested. The temporary endpoint-test annotation was removed, leaving
  board 67 clean for the first operator trace.
- Important validation fix: boards 11 and 31 have matching source-board
  numbers from different capture sessions. Edge-study images are now named
  with both study board and source board, so they cannot collide or receive
  each other's annotations.

### Review of Claude grading changes (2026-07-15)

- Reviewed the expanded `shadow_review_app.py`. The edge-study page loads with
  10 boards and the new `board_outline`/`max_usable_line` controls are present;
  the normal app remains read-only with respect to PLC/cameras. Python compile
  and Flask smoke tests passed.
- The red/yellow/green severity layer is useful as an exploratory visual, not
  yet as a grading algorithm. It classifies dark pixels as red and warm pixels
  as green inside a brightness mask (`severity_bands`); shadows, occlusion,
  overexposure, wood species, and LED changes can produce the same signals.
  It must not generate saw words or be treated as ground truth until compared
  against the hand-marked regions.
- Current shape rendering groups every same-kind point on one camera into one
  closed polygon. Multiple disconnected fish-tail/tear-out regions can
  therefore be joined into a false shape. Add a trace/group identifier or a
  `New Trace` control before using these masks for training.
- The annotation endpoint currently rejects more than 40 points per board;
  the smoke test confirmed HTTP 400 at 41. This is likely too restrictive for
  meticulous outlines and should be raised or made per-trace before the full
  ten-board annotation pass.
- Severity overlays are cached by filename and generated for every row while
  loading. If thresholds, calibration, or lighting settings change, old cached
  overlays can remain visually stale. Add a version/config hash or generate
  them on demand before relying on comparative results.
- No implementation changes were made during this review. Recommended next
  step: preserve the hand annotations, add trace grouping and a larger point
  budget, then evaluate the heuristic overlay against those annotations.

### Fresh aligned 30-board capture ready for blind grading (2026-07-15)

- New read-only capture session:
  `D:\Shadow App Data\shadow_sessions\2026-07-15_113126_fresh_aligned_30_20260715_113125`.
- Capture used `bTrigger` rising enqueue, `bSawDownCompare` dequeue, live
  `DB1.iTriggerDelay=750 ms`, and the confirmed `0.780 s` camera offsets. No
  PLC writes were performed.
- Final integrity: 30 matched rows, 31 triggers, 31 LEFT/RIGHT raw pairs, and
  30 profile images. Three later FIFO/unmatched events are excluded from the
  grading set. Frame timing was LEFT `+0.711..+0.739 s` and RIGHT
  `+0.720..+0.751 s`.
- Fresh blind grading view: `http://127.0.0.1:5067/`. It is a separate
  `shadow_review_app.py --edge-study` instance with 30 neutral raw pairs. The
  operator/applied word, old comparison streams, and result columns are
  removed from both the visible table and the browser payload.
- Fresh edge-study configuration is stored in the session's
  `annotations/edge_study_10_boards.json` for compatibility with the existing
  app option; it intentionally contains all 30 fresh board ids. Grade these
  images independently before importing any words for comparison.

### Camera reconnect recheck and harsh-light sample (2026-07-15)

- After the camera network reconnect, a monitored read-only 30-board recheck
  completed successfully at:
  `D:\Shadow App Data\shadow_sessions\2026-07-15_145154_fresh_recheck_30_20260715_1453`.
- Final result: 30 matched capture rows, 32 triggers, and no PLC writes. The
  selected frame offsets were LEFT `+0.709..0.741 s` and RIGHT
  `+0.721..0.755 s`, with DB1 `iTriggerDelay=750 ms`.
- A separate one-board sample was captured after the lighting condition was
  changed, at:
  `D:\Shadow App Data\shadow_sessions\2026-07-15_145613_harsh_lights_down_1_20260715`.
  It captured one matched pair with LEFT `+0.718 s` and RIGHT `+0.728 s`.
- Both sessions used `bTrigger` rising enqueue and `bSawDownCompare` dequeue
  in `capture_only` shadow mode. The earlier failed detached attempt saved 19
  partial pairs at `...144843_fresh_recheck_30_20260715_1450`; treat that as
  incomplete and do not combine it with the completed run.

### Dimmed harsh-light batch (2026-07-15)

- After the harsh lighting was dimmed, the recorder waited for live triggers
  and captured 20 matched read-only board pairs at:
  `D:\Shadow App Data\shadow_sessions\2026-07-15_145723_harsh_lights_dim_20_20260715`.
- Final result: 20 compared capture rows, 21 triggers, and no PLC writes. The
  selected frame offsets ranged approximately LEFT `+0.716..0.741 s` and
  RIGHT `+0.720..0.755 s`.
- This batch is separate from the normal-light recheck and the one-board harsh-
  light sample. Review it as the dimmed-light condition only.
- Blind review is available at `http://127.0.0.1:5068/`. The session now has a
  20-board edge-study index under `annotations/edge_study_10_boards.json`;
  operator/applied words are intentionally not used for the grading view.

### Active review switched back to normal-light 30-board run (2026-07-15)

- The dimmed/harsh-light 20-board session was removed from active review and
  moved reversibly to:
  `D:\Shadow App Data\junk\2026-07-15_145723_harsh_lights_dim_20_20260715`.
- The blind review server on `http://127.0.0.1:5068/` now loads the preceding
  30-board recheck:
  `D:\Shadow App Data\shadow_sessions\2026-07-15_145154_fresh_recheck_30_20260715_1453`.
- All 30 board records were verified in the active review payload. The images
  remain capture evidence only; lighting/colour mismatch is documented and no
  grading or PLC behavior was changed.

### Shadow timing reference adjusted for common board position (2026-07-15)

- For the next shadow capture, `shadow_capture.yaml` now uses the common
  application timing `left_offset_s=0.78` and `right_offset_s=0.78`.
- `frame_alignment.delay_from_db1.enabled` is temporarily `false`, so the
  live `DB1.iTriggerDelay=750 ms` no longer overrides this shadow-only test.
- No PLC value was written or changed. This is a single global timing offset;
  no independent per-board leading-edge alignment was added.

### 780 ms alignment test and new 20-board batch (2026-07-15)

- A five-board read-only alignment test at the global `780 ms` timing showed
  the common board presentation staying consistent across the saved pairs:
  `D:\Shadow App Data\shadow_sessions\2026-07-15_152005_alignment_test_5_780ms_20260715`.
- The following 20-board read-only batch completed with 20 matched rows and
  no PLC writes:
  `D:\Shadow App Data\shadow_sessions\2026-07-15_152102_aligned_780ms_20_20260715`.
- All captured frames used `delay=780 ms` from `shadow_capture.yaml`; the live
  DB1 delay was deliberately ignored for this shadow-only test.
- Blind review is now loaded at `http://127.0.0.1:5068/` with all 20 boards
  from this 780 ms session and no operator/applied-word grading context.

### Supplier camera/lens/lighting sample pack (2026-07-15)

- Created `Supplier Sample Pack 2026-07-15/` in the project folder. It contains
  ten raw LEFT/RIGHT pairs from the 780 ms run, one comparison pair from the
  preceding run, a technical README, and `Supplier email draft.txt`.
- The draft asks for recommendations on industrial cameras, lenses, working
  distance, field of view, lighting, polarisation/diffusion, and calibration.
  It contains no camera credentials, PLC addresses, or control details.

### Vision Upgrade To-Do: third camera, controlled lighting and algorithms

Goal: produce a stable, visible usable-board boundary first, then detect
wane/fish-tail/tear-out, then derive a traceable saw-word recommendation. Do
not train a model to output the PLC word directly as the first step.

#### Field setup: before fitting the third camera

- [ ] Measure and record each existing camera's distance to the board, height,
  angle, field width, and physical distance from `bTrigger`.
- [ ] Decide whether the third camera can be a **geometry-reference view**:
  near perpendicular to the board plane, seeing the full grading band and the
  far-side edge, with meaningful overlap with both existing views.
- [ ] Keep hold-down chains, guide rails and machine structure outside its
  primary region of interest wherever physically possible.
- [ ] Use a stable mounting bracket; document the final camera positions with
  photos and measured dimensions so calibration can be repeated after service.

#### Lighting enclosure: validate before collecting training data

- [ ] Build a shrouded inspection zone with a matte black, non-reflective
  background wherever a silhouette/background separation is needed.
- [ ] Provide one diffuse, even visible-light mode for stable colour and
  usable-wood segmentation.
- [ ] Provide a separate low-angle/raking-light mode for tear-out, texture and
  fish-tail contours. Preserve each mode as a separately labelled channel or
  capture, not as an uncontrolled mixture.
- [ ] If physically possible, trial a backlight behind the board path for a
  high-contrast outer-board silhouette.
- [ ] Test for LED flicker/banding at the actual exposure time. Use DC-driven
  LEDs or a synchronised strobe controller if banding appears.
- [ ] Trial cross-polarisation only if glare remains after diffuser/angle work.

#### Camera and timing setup

- [ ] Prefer global-shutter machine-vision cameras for the eventual upgrade.
  GigE Vision is the cleanest network integration; USB3 global-shutter cameras
  require an edge PC or USB-over-Cat6 extender rather than a normal USB-to-
  Ethernet adapter.
- [ ] Lock focus, aperture, exposure, gain, white balance and gamma once the
  inspection enclosure is commissioned. Do not leave automatic controls on.
- [ ] Trigger all camera views from the same event and retain per-frame
  timestamps. Record exact trigger-to-frame offsets for every capture.
- [ ] Keep one common global presentation offset. Do not introduce per-board
  leading-edge alignment unless a future tracking design explicitly requires it.
- [ ] Keep `shadow_capture_app.py` read-only and do not start write-capable
  `vision_host_app.py` during this data-collection phase.

#### Calibration and data capture

- [ ] Run a marked calibration board through the final inspection position:
  origin, 1 m, 3 m, 6.6 m and other known saw marks.
- [ ] Capture a colour chart plus matte white/grey reference in each final
  camera under the final light modes; make a per-camera colour correction or
  normalisation profile rather than comparing raw camera colours directly.
- [ ] Re-fit lens distortion and image-to-machine coordinates after every
  camera movement. Keep the physical tape measurements as the saw datum.
- [ ] Capture 30-50 boards with the final settings locked; save raw L/R/third
  frames, timestamps, camera settings and lighting mode. Do not save only
  rendered overlays.
- [ ] Attach the operator/PLC word only after blind visual annotation so it
  cannot bias grading.

#### Annotation and model sequence

- [ ] Use the edge-study app to label: `board_outline`, `usable_edge`, `wane`,
  `fishtail`, `tear_out`, `machine_occlusion`, and `lighting_limit`.
- [ ] Add trace grouping and raise the current 40-point annotation cap before
  detailed outline work; disconnected defects must not be merged into one
  polygon.
- [ ] Phase 1 algorithm: deterministic board geometry. Use controlled-light
  background separation, gradient/edge detection, connected components and a
  robust line/spline fit to produce the outer-board mask.
- [ ] Phase 2 algorithm: train pixel segmentation for `usable` versus
  `non-usable`, with confidence per pixel. A U-Net/DeepLab-style model is more
  appropriate than boxes because cut positions depend on the exact boundary.
- [ ] Phase 3 algorithm: extend the segmentation classes to wane, fish-tail
  and tear-out; retain uncertain/occluded regions as an explicit outcome.
- [ ] Evaluate anomaly detection only as a supplement for unexpected defects,
  not as the source of the board boundary.
- [ ] Future higher-confidence wane upgrade: trial line laser/structured-light
  profiling. It adds surface shape information where colour/texture is
  ambiguous.

#### Cut decision and acceptance tests

- [ ] Build the cut optimiser separately from image segmentation: sample the
  usable-mask confidence at each calibrated saw line, apply the 200 mm safety
  rule, then map the selected lines to the established PLC bitmask.
- [ ] Log the selected lines, rejected lines, usable confidence and reason for
  every proposed word. The overlay must make the decision inspectable.
- [ ] Score edge-position error, defect-mask precision/recall, false cuts,
  missed cuts and operator-agreement separately. Never treat word agreement
  alone as proof that the vision layer is correct.
- [ ] Keep recommendations shadow-only until the geometry and defect metrics
  are stable across lighting modes, board types and multiple production runs.
