# Operator Grading Dataset - 70 Boards

This folder intentionally contains data only: the 70-row combined
`boards.csv`, a source manifest, and reviewer grades in `grading.json` once
they are saved. No raw images or rendered overlays are copied here.

The local review app resolves each row's `source_key` and `source_board` back
to the corresponding D-drive frame directory defined in `sources.json`.
Grades are saved against the unique combined `board` number (1-70), while the
source fields preserve traceability to the original 20-board or 50-board run.
