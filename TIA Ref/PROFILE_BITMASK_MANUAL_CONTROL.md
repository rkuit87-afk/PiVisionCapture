# PLC Profile Bitmask and Manual Control Reference

## Purpose

This document describes the production PLC's profile-word behavior as shown
in the TIA ladder screenshots supplied on 2026-07-14. It is a reference for
the read-only shadow capture/review tooling. It does not authorize PLC writes
or changes to the production program.

The screenshot sources belong in
[`MediaRef/Ladder Images`](../MediaRef/Ladder%20Images/README.md).

## The Important Distinction

The profile word is a **final cut pattern**, not simply a one-hot record of
which manual button the operator pressed.

When the operator selects a profile, the PLC ORs a predefined, cumulative
mask into `#Stat_ButtonMask`. A 3.0 selection, for example, requests the
trim cut and the applicable saws from 3.0 onward. The word contains every
cut that must occur for that board, not merely the starting length.

The shadow system must therefore:

1. Capture and retain the raw final word for the board.
2. Compare the raw word associated with the same FIFO board at saw-down.
3. Render all saw lines represented by that final profile.
4. Avoid treating an operator's button press as a single saw bit.

## Final Word Lifecycle

### 1. Light-array fallback

The light array chooses a profile only when manual mode is not active. The
ladder's `#Stat_ManualActive` normally-closed condition prevents the light
array from overwriting a manual decision.

The latches remain active while the board is in the relevant sensing region.
After the board passes the origin sensor's negative edge, the selected light
profile is moved to the output path for that cycle.

### 2. Manual profile selection

Each manipulation button uses a rising-edge trigger (`P_TRIG`). On that
edge, its fixed mask is ORed into `#Stat_ButtonMask`. This makes the decision
stable for the board and prevents a later photo-eye state from replacing it.

Verified screenshot examples:

| Manual selection | OR mask | Meaning |
|---|---:|---|
| 3.0 | `0x03F9` | trim plus the 3.0-and-longer cumulative profile |
| 3.6 | `0x03E1` | trim plus the 3.6-and-longer cumulative profile |
| 4.2 | `0x03C1` | trim plus the 4.2-and-longer cumulative profile |

The difference between these masks is intentional. It shows that the
profile word contains packing/reserved positions and must be read from the
ladder presets, not inferred from physical output byte addresses alone.

### 3. Thin-board exception

For boards below 25 mm thick, the PLC applies an AND operation to remove only
the `0.0` trim cut from the otherwise selected light/profile word. The rest
of the selected profile remains intact.

Conceptually:

```
final_profile = selected_profile AND NOT(trim_bit)
```

The exact literal in the screenshot is not used here as a new software
constant. The production behavior is the authority: this exception strips
only the trim bit; it does not choose a different length profile.

### 4. Saw-down comparison

At saw-down the PLC exposes the applied profile through `DB1.wCompareWord`
and pulses `DB1.bSawDownCompare`. The shadow capture FIFO appends a board on
`DB1.bTrigger` and removes the oldest pending board on this saw-down event.

This is the correct comparison moment because it is the final profile for
the same physical board. Candidate changes earlier in the cycle are not a
reliable record of the applied profile.

## Confirmed Word Facts

The following direct facts are confirmed by ladder and operator review:

| Fact | Evidence |
|---|---|
| `0x0000` means no cuts | operator confirmation |
| `0x0002` is the 0.3 saw test | ladder AND network |
| `0x0004` is the 0.6 saw test | ladder AND network |
| `0x0200` is the 6.6 saw test | ladder AND network |
| `0x0201` is 0.0 plus 6.6 | operator confirmation and ladder-derived mask |
| There is no live 0.9 saw | operator review of the active program |

Do not infer the complete profile table from these isolated facts. The manual
profile masks above are authoritative for the shown selections. Transcribe
the remaining manual networks before adding any further direct word-to-saw
decoding rules to the shadow app.

## Shadow App Requirements

The review app is read-only and must remain so. Its responsibilities are:

- Show the image pair and the red lines for the applied final profile.
- Allow a reviewer to choose an expected profile.
- Draw blue lines for reviewer-selected saws.
- Draw green over a red line where a reviewer selection matches the applied
  profile.
- Leave applied lines red when the reviewer did not select them.
- Persist the reviewer decision separately in `grading.json`; do not alter
  the PLC word or raw capture record.

## Deferred Work

### 38 x 76 exception

The `38 x 76` case is a separate future exception. It requires an actual
width measurement and must not be implemented from the current profile word
alone. Capture/review stability comes first.

### Complete profile-mask transcription

Before production analysis depends on every individual rendered saw, capture
the remaining manual-selection networks (4.8, 5.4, 6.0, 6.6 and any reset or
clear logic) and add the exact preset masks here.

## Safety Boundary

This reference supports observation, review, and data labelling only. Do not
enable measurement writes, modify `wSawWord`, or alter PLC logic based on
this document without an explicit production change request and an on-machine
validation plan.
