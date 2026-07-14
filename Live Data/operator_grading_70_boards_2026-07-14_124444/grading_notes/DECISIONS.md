# Grading Decisions

This folder records the agreed reasoning behind individual board grades.
It supplements `grading.json`; it does not replace the raw applied word,
reviewer grade, source frames, or PLC capture record.

## Board 61

- Source: `aligned50`, source board `41`
- Applied and graded word: `0x03E1`
- Decision: operator decision accepted as correct.
- Visual finding: the board edge is rounded through the RIGHT-camera 4.2 to
  6.6 saw region. The curve is subtle enough that it is difficult to judge
  by eye in the current image.
- Future vision rule: do not classify this from raw brightness alone. Treat it
  as a positive rounded-profile reference for a fixed-background, edge-shape
  method with controlled/diffuse lighting and the 200 mm optimization rule.

## Board 67

- Source: `aligned50`, source board `47`
- Applied word: `0x0000`; reviewer grade: `0x0043`
- Decision: preserve the usable board; do not make a 4.2 cut merely because
  far-side wane and origin-side fishtail are present.
- Visual finding: there is wane on the far side and fishtail at the origin,
  but cutting at the 4.2 boundary would remove usable material for too little
  quality recovery.
- Future vision rule: defects on either end are not automatic cuts. A cut is
  justified only when the agreed recovery / 200 mm optimization threshold is
  exceeded. This is a key material-preservation reference.

## Next Decisions

Add one section per board with source, applied/graded word, agreed outcome,
and the reason for the decision. Keep unresolved cases explicitly marked for
discussion rather than treating them as training truth.
