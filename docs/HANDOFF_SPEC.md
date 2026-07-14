# Handoff Specification for PiVisionCapture Agents

This document defines how agents should communicate work in this repository.

The authority model is:

- **Claude and Codex are implementation peers.**
- **Gemini is handoff / analysis only by default.**

Do not write handoffs that imply only Claude may implement. Use "Claude/Codex" or "next implementation agent" unless the user names a specific agent.

---

## Core Principle

Make every item immediately actionable. The next implementation agent should be able to read the handoff once, understand the current state, and continue without redoing all prior reasoning.

---

## Required Structure

### 1. Summary

Use 1-3 sentences:

- What changed?
- What is currently working?
- What is the next concrete step?

Example:

```markdown
The shadow recorder now reads DB1/DB4/DB13 and records operator-vs-vision saw words without PLC writes. The local snap7 simulation passes, but the live LEFT camera address still needs confirmation. Next implementation agent should verify camera connectivity and run a short baseline session.
```

---

### 2. Authority / Safety Notes

Call out any boundaries that matter for the next agent:

- Whether a script is read-only or writes to the PLC.
- Whether a file is production Pi code, host-side code, or test/debug code.
- Whether a change has deployment risk.
- Whether hardware, PLC, camera, or network access is required.

Example:

```markdown
`shadow_capture_app.py` must remain read-only. It may read DBs and process images, but it must not call DB write or output write APIs.
```

---

### 3. Changes Made

List concrete changes by file:

```markdown
- `plc_exchange.py`: corrected DB1 offsets for S7 standard alignment.
- `shadow_capture_app.py`: added FIFO matching between board trigger and saw-done pulse.
- `PLC_DB_LAYOUT.md`: documented DB1/DB4/DB13 offsets from Openness export.
```

---

### 4. Verification

State exactly what was tested and what was not.

Use this format:

```markdown
## Verification

Passed:
- `python tests/shadow_sim_test.py`

Not run:
- Live PLC/camera test; PLC was not reachable from this machine.

Observed:
- Local shell did not have `python` on PATH.
```

Never imply verification happened if it did not.

---

### 5. Issues / Next Tasks

Organize by priority.

Priority definitions:

- **P0:** data loss, unsafe machine behavior, production crash, or PLC write risk.
- **P1:** blocks live run, measurement correctness, camera/PLC communication, or debugging.
- **P2:** maintainability, cleanup, operator ergonomics, reporting improvements.
- **P3:** nice-to-have polish.

For each issue, include:

| Field | Meaning |
|---|---|
| **Title** | Concise issue name |
| **File(s)** | Exact file paths |
| **Symptom** | What is wrong or unknown |
| **Root Cause / Context** | Why it happens or why it matters |
| **Recommended Fix** | Specific next action |
| **Verification** | How to prove it is fixed |
| **Risk** | PLC write risk, deployment risk, or hardware dependency |

Template:

```markdown
### P1: LEFT Camera Address Unknown

- **File(s):** `vision_host.yaml`, `SHADOW_RUN_MORNING.md`
- **Symptom:** LEFT camera may be on DHCP `192.168.2.246` rather than static `192.168.3.146`.
- **Context:** Measurement depends on both camera streams for width and stop-position checks.
- **Recommended Fix:** Confirm current IP on-site, then update config if needed.
- **Verification:** Open RTSP stream or capture one frame from LEFT camera.
- **Risk:** Hardware/network dependency; no PLC write risk.
```

---

## Agent-Specific Rules

### Claude / Codex

Claude and Codex may:

- Modify implementation files.
- Modify production code when the user requests implementation work.
- Add or update tests.
- Update configs when requested or when required by the task.
- Run local verification.
- Prepare deployable changes.

Claude and Codex must:

- Read current files before editing.
- Preserve unrelated uncommitted changes.
- Avoid broad cleanup unless requested.
- Be explicit when a change affects PLC writes, camera capture, or production Pi behavior.

### Gemini

Gemini may:

- Analyze code.
- Review changes.
- Write handoff notes.
- Recommend fixes.

Gemini must not:

- Modify implementation files.
- Make production changes.
- Run deployment actions.

Exception: Gemini may implement only if the user explicitly grants that authority in the current task.

---

## What Not To Include

- Do not write "Claude must fix this" unless the user specifically assigned Claude.
- Do not assign Codex to documentation only.
- Do not include long background essays.
- Do not paste large code blocks.
- Do not speculate without marking it as unverified.
- Do not omit hardware or PLC access limitations.

---

## Good Closing Section

Use this shape at the end of every handoff:

```markdown
## Next Implementation Agent

Start here:
1. Read `SHADOW_RUN_MORNING.md`.
2. Confirm `vision_host.yaml` camera addresses.
3. Run `python tests/shadow_sim_test.py` if Python and snap7 are available.
4. If live PLC/cameras are available, run a short shadow session and inspect `report.md`.

Known blockers:
- Python not available on PATH in the current shell.
- LEFT camera IP may still be DHCP.
```

