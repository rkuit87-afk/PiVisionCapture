# Gemini Code Assist - Debug Handoff (2026-07-14)

This document contains the results of a static analysis and debug pass over the active project files. It is intended to provide a clear, prioritized list of actionable items for the next implementation agent.

---

## 1. Summary

The project has rapidly evolved, leading to several inconsistencies between the now-canonical PLC logic and the Python codebase. The primary issues are a hardcoded and incorrect saw bit mapping in `dual_camera_measure.py` and a JavaScript bug in `shadow_review_app.py` that prevents the saw picker from working correctly. Addressing these P1 issues is critical for both accurate measurement and effective data grading.

## 2. Authority / Safety Notes

- This review was conducted via static analysis only. No code was executed.
- All findings are based on the provided file context.
- The proposed changes affect measurement logic (`dual_camera_measure.py`) and the data review UI (`shadow_review_app.py`). They do not introduce any new PLC write paths.

## 3. Changes Made

None. This is a review-only document.

## 4. Verification

- **Performed:** Static code analysis of all non-stale Python files and review of all markdown documentation.
- **Observed:** Inconsistencies between the final PLC saw bit mapping documented in `HANDOFF.md` and the hardcoded values in the measurement and review modules. Identified several JavaScript bugs and areas of code duplication in the review application.

---

## 5. Issues / Next Tasks

### P1: Canonical Saw Bit Map Not Implemented

- **File(s):** `c:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture\dual_camera_measure.py`, `c:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture\shadow_review_app.py`
- **Symptom:** The `SAW_CALIBRATION` dictionary in `dual_camera_measure.py` and the `SAW_BUTTONS` list in `shadow_review_app.py` contain an outdated, incorrect mapping of saw labels to bit numbers (e.g., `3.0` is bit 3, `6.6` is bit 9).
- **Root Cause / Context:** The `HANDOFF.md` (entry "Codex — final live profile map and review UI") confirms the PLC uses a simple, contiguous bit map: `0x0001=0.0` (bit 0), `0x0002=0.3` (bit 1), ..., `0x0200=6.6` (bit 9). The Python code was never updated to reflect this final ground truth. Any measurement performed by `dual_camera_measure.py` will generate an incorrect `saw_word`.
- **Recommended Fix:**
    1.  Update `SAW_CALIBRATION` in `dual_camera_measure.py` to use the correct bit numbers (0-9) and remove the non-existent "0.9" saw.
    2.  Update `SAW_BUTTONS` in `shadow_review_app.py` to match the canonical 10 saws and their bit numbers (0-9).
- **Verification:** `dual_camera_measure.measure_dual_camera` produces a `saw_word` of `0x0201` for a `0.0+6.6` cut. The review UI's saw picker correctly toggles bit 9 for the "6.6" button.
- **Risk:** Low. This is a critical correctness fix for a read-only component.

### P1: Review UI Saw Picker Is Broken

- **File(s):** `c:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture\shadow_review_app.py`
- **Symptom:** The saw picker buttons in the review UI do not work. Clicking a saw button does not update the "Expected word" input field or the visual markers.
- **Root Cause / Context:** The JavaScript in the HTML template has two conflicting definitions for the `configureSawButtons` function. The first, incorrect version is executed, which assigns the wrong bit numbers to the buttons. The second, correct version is defined but never called.
- **Recommended Fix:**
    1.  Delete the first, incorrect `configureSawButtons` function and its call.
    2.  Rename the second, correct `SAW_BUTTONS` constant to avoid conflict and ensure it's used to build the buttons.
- **Verification:** Clicking saw buttons in the review UI toggles the correct bits in the "Expected word" field and updates the blue/green SVG overlay.
- **Risk:** Low. This is a UI-only fix for the review tool.

### P2: Redundant Code in Review App

- **File(s):** `c:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture\shadow_review_app.py`
- **Symptom:** The JavaScript block contains multiple, conflicting definitions for `showBoard`, `saveGrade`, and `ensureGradeNotes`. This makes the code hard to read and maintain.
- **Root Cause / Context:** Functionality was likely added incrementally, leading to duplicated and partially overwritten function definitions. The browser uses the last definition it encounters, but this is fragile.
- **Recommended Fix:** Consolidate the duplicated function definitions into a single, correct implementation for each. The final versions that include the `notes` field are the correct ones.
- **Verification:** The review UI continues to load boards, display grades, and save grades (including notes) correctly.
- **Risk:** Low. Code quality and maintainability improvement.

### P2: Inconsistent Empty Reference Handling

- **File(s):** `c:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture\dual_camera_measure.py`, `c:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture\capture_empty_reference.py`
- **Symptom:** `dual_camera_measure.py` uses a module-level `_EMPTY_REF_CACHE` to avoid reloading reference images from disk. However, `capture_empty_reference.py` updates the `vision_host.yaml` file but has no mechanism to invalidate this in-memory cache in a long-running process.
- **Root Cause / Context:** If `vision_host_app.py` is running and an operator uses `capture_empty_reference.py` to update the references, the `vision_host_app.py` process will continue to use the old, stale images from its cache until it is restarted.
- **Recommended Fix:**
    1.  Modify `_load_empty_ref` to take the cache dictionary as an argument instead of using a global.
    2.  In `measure_dual_camera`, create the cache dictionary instance.
    3.  In the main application loop (`vision_host_app.py`), add a mechanism to watch for changes to `vision_host.yaml` (e.g., using `watchdog` or simple timestamp checking) and clear/re-create the cache dictionary when a change is detected.
- **Verification:** After running `capture_empty_reference.py --activate`, a running `vision_host_app.py` process starts using the new reference images on its next measurement cycle without needing a restart.
- **Risk:** Medium. Involves changes to the main application loop.

---

## 6. Next Implementation Agent

Start here:
1.  **Address the P1 issues first.** The saw bit mapping is a critical correctness bug that invalidates all current measurements and makes grading difficult.
2.  Apply the recommended fix for the `SAW_CALIBRATION` constant in `dual_camera_measure.py`.
3.  Apply the recommended fixes for the JavaScript in `shadow_review_app.py` to repair the saw picker and remove duplicated code.
4.  After fixing the UI, proceed with the manual grading task to build the "golden rulebook".

Known blockers:
- The vision system's measurement logic is currently producing incorrect `saw_word` values due to the bit-map bug. Do not trust its output until P1 is resolved.