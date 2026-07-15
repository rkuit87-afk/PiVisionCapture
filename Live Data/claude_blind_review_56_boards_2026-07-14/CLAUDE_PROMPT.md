# Claude Prompt - Independent Shadow Grading

You are performing an independent visual grading pass on 56 captured boards.
This is a review-only task. Do not run the live capture application, connect to
the PLC, write to the PLC, or change calibration/code.

## Use This Dataset Only

Point the review app at:

`C:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture\Live Data\claude_blind_review_56_boards_2026-07-14`

From the project root, run:

```powershell
python shadow_review_app.py "C:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture\Live Data\claude_blind_review_56_boards_2026-07-14" --role claude --port 5064
```

Then open `http://127.0.0.1:5064/`.

Your decisions will be orange and will save to:

`Live Data\claude_blind_review_56_boards_2026-07-14\reviews\claude.json`

Do not inspect or copy any Codex, manager, historical, or previous operator
grading JSON. In particular, do not open `reviews/codex.json` or the
`historical` folder in the separate review pipeline. The red lines visible in
the image are the PLC/operator-applied word, not the correct answer.

## How To Read The Image

1. Select a board row and start with **Grading Band** at about 3.5x zoom.
2. Use **Full Frame** only to regain orientation. Return to the grading band
   before deciding.
3. The board is the long horizontal bright/wood-coloured strip running through
   the hold-down area. The LEFT and RIGHT camera views join near the middle.
4. Ignore hold-down chains, steel rails, brackets, cables, the lower conveyor,
   shadows cast by machine parts, and the small red light. They are background
   machinery, not board defects.
5. The board is heavily overexposed in places. Do not treat white pixels as
   automatically clean wood, or dark pixels as automatically wane. Follow the
   physical top and bottom board edges and look for sustained changes in the
   silhouette.
6. Judge fishtail/taper, rounded profile, wane, tear-out, and the amount of
   usable timber that would be removed. A small patch of wane is not by itself
   a reason to sacrifice a substantial length of usable board.
7. Check both camera halves around the centre seam. Do not infer a defect from
   a discontinuity caused only by the change of camera perspective.

## Making A Decision

Decide from the board image first. Only after choosing your expected cuts,
compare them with the red PLC lines.

The active saw picker is:

`0.0, 0.3, 0.6, 3.0, 3.6, 4.2, 4.8, 5.4, 6.0, 6.6`

There is no active 0.9 saw. `0x0000` means no cuts. The picker represents the
final physical saw word, not merely the name of an operator button. A normal
profile may therefore contain the trim saw and several cumulative downstream
saws.

- If the PLC decision is correct, use **Confirm Applied**.
- If it is wrong, select the complete expected set of saws and use
  **Save Expected**.
- Enter reviewer name `Claude`.
- Add a short note stating the visible reason and confidence, for example:
  `wane continues past 4.2; choose 4.8 profile; medium confidence`.
- If the frame is too obscured or ambiguous to support a decision, leave it
  ungraded and report its board number. Do not invent a profile.

## What Matters Most

The goal is not to imitate the red operator word. The goal is to identify the
earliest defensible cut that removes unacceptable board shape while preserving
usable timber. Avoid unnecessary saw drops when the saw would not improve the
recoverable board.

Known special cases:

- A two-board/overlap condition should be flagged as `STOP FEED / invalid
  single-board frame`, not forced into a normal cut profile.
- The future 38 x 76 width exception is not part of this grading pass.
- Do not use the experimental warm/cold colour map as a grader. It is only a
  diagnostic aid; shape evidence remains primary.

## Completion Report

When finished, report:

- number graded;
- number agreeing with the PLC;
- number superseding the PLC;
- board numbers left ambiguous;
- recurring visual reasons for disagreement.

Do not export or merge another reviewer's decisions. Leave the completed
Claude pass in `reviews\claude.json` for later comparison.
