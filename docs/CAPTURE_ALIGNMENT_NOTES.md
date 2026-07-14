# Capture Alignment Findings — 2026-07-10

## Key discovery: boards STOP DEAD before capture
Doubling capture delay (150ms -> 300ms) did not move the board position at all
(LEFT dY median -168px at both settings). The boards are stationary at their
physical stop when the frame is snapped. Capture timing does NOT control
position — the machine's stop does. This is exactly the desired behaviour.

## Repeatability (20-board raw batch, pairs 29-48, delay 150ms)
- LEFT camera, fence-end travel position (dY): -168px +/- 8px  -> spread 15px.
  Outstanding repeatability. Alignment is a non-issue on the fence end.
- LEFT fence registration (dX): mean +24px, spread 92px (boards sit against
  the fence within ~2-9cm of each other).
- RIGHT camera, far-end position (dY): spread ~174px -> boards are SKEWED
  (rotate slightly on the chains; fence end consistent, far end varies).
  Skew is physical, not timing — handle in software by detecting the actual
  board edge per frame (grading must anchor to detected edges, never to a
  fixed pixel position at the far end).
- RIGHT far-end dX is bimodal (~+25px vs ~+240px groups): raw board LENGTHS
  differ batch to batch. Expected; fence-datum design handles it.

## Decisions
1. capture-delay-ms stays at 150 (300ms produced 2/6 outliers — boards caught
   mid-bounce; 150ms was clean for 20/20).
2. NEW reference = true stop position, saved from captured pair #43:
   D:\board_captures\stop_position_reference_2026-07-10\LEFT_stop_reference.jpg
   D:\board_captures\stop_position_reference_2026-07-10\RIGHT_stop_reference.jpg
   The old naturallight reference photos had the board hand-placed 168px past
   the real stop; the camera pixel<->machine-mm calibration is unchanged
   (cameras never moved), only the board's expected resting Y shifts.
3. Grading anchors to DETECTED board edges (blob), not fixed pixels, so the
   -168px shift and per-board skew are absorbed automatically.

## GPIO trigger noise (same day) — CONFIRMED CAUSING FALSE TRIGGERS
- Raw pin shows up to ~617 edges/sec EMI noise when the mill runs. Noise is
  bursty: mostly 1-11ms pulses, occasional pulses up to 81ms observed.
- CONFIRMED: pairs 55-62 (batch 2) were 8 FALSE TRIGGERS in ~80s — mill
  running with NO boards feeding; frames show empty deck. The 60ms
  stable-high filter was beaten by the occasional long noise pulse.
- FIX APPLIED 2026-07-10: --stable-ms raised 60 -> 500 in
  pivision-gpio-trigger.service (6x worst observed noise pulse; boards rest
  on the switch for 1s+ so no real triggers are lost, and boards are
  stationary so added latency does not shift capture position).
- Hardware fix when parts available: 1k pull-down at GPIO17 to GND +
  twisted ground return wire along the trigger run; optocoupler later.

## CAUTION — analysis detector flaw found 2026-07-10
- board_position_check scripts detected "boards" in EMPTY frames (sunlit
  deck/machinery read as a bright blob; several identical dX values were the
  giveaway — static background). Any position stats that included empty
  frames are suspect, including parts of the batch-1 numbers and possibly
  the "boards stop dead" conclusion (needs re-verification with a detector
  that validates board presence: warm wood colour + plausible blob height
  ~60-260px + position band).
- Stop-position reference pair (#43) DOES contain a real board (visually
  verified), but its measured anchors need re-checking with the fixed
  detector before being trusted for grading.
