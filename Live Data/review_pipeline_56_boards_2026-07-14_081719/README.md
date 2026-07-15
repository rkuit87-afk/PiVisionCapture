# Independent Review Pipeline - 56 Boards

This workspace contains only the 56 boards that already have a saved human
decision in the original 70-board grading run. It preserves the original board
numbers and links to the D-drive source-frame sessions through `sources.json`.

The original decisions are preserved in
`historical/operator_initial_70_grades.json` and are intentionally not loaded
by the review application.

Each independent review pass saves to its own file:

- `reviews/codex.json` - pink proposal lines
- `reviews/claude.json` - orange proposal lines
- `reviews/operator.json` - blue proposal lines, green where matching the PLC

Run one role at a time. Do not inspect another role's JSON before completing a
blind pass. The PLC-applied operator decision remains the red baseline in all
three views.
