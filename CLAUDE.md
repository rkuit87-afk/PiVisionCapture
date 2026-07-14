# PiVisionCapture — Claude Project Instructions

## Critical Rules

**DO NOT modify production code files without explicit request:**
- `main.py`
- `camera_stream.py`
- `trigger_handler.py`
- `storage.py`
- `config.yaml`

These files are deployed to the Raspberry Pi and any changes will break production.

## Safe to Modify
- Documentation files (*.md)
- Configuration files (only on explicit request)
- New test/debug scripts

## Before Making Changes
Always ask the user first. If unsure, ask.

## Contact
If you have questions about the codebase, ask the user directly before taking action.
# CURRENT AUTHORITY OVERRIDE

Claude and Codex have the same implementation authority in this project. Either agent may inspect code, edit implementation files, update tests, and modify documentation when the user asks for project work.

Gemini is handoff / analysis only by default. Gemini should not make implementation changes unless the user explicitly grants that authority.

This section supersedes the older restriction above that limited Claude to documentation or required extra permission for every production-code edit. Claude and Codex should still inspect first, keep changes scoped, preserve unrelated user/prior-agent work, and clearly explain any PLC write, camera, or deployment impact.

---
