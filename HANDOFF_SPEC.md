# Handoff Specification for Claude Agent

This document defines how Gemini (or any secondary agent) should structure handoffs to Claude for optimal clarity and actionability.

---

## Core Principle

**Make every item immediately actionable.** Claude should be able to read the handoff once and know exactly what to do without requiring follow-up questions or re-reading analysis.

---

## Document Structure

### 1. Executive Summary (1-2 sentences)
Start with a one-line hook. What's the state of the project? What changed?

**Example:**
```
Found 3 critical bugs and 1 architecture redundancy issue. No code changes made.
All findings are in production code paths and should be fixed before next deployment.
```

---

### 2. Issues (Organized by Priority & Category)

#### Priority Ranking
- **P0 (Critical):** Will cause data loss, crash in production, or security issue. Fix immediately.
- **P1 (High):** Impacts core functionality or makes debugging hard. Fix before next release.
- **P2 (Medium):** Code smell, performance, maintainability. Fix when convenient.
- **P3 (Low):** Nice-to-have improvements or refactoring.

#### For Each Issue, Include:

| Field | What to Include | Example |
|-------|-----------------|---------|
| **Priority** | P0/P1/P2/P3 | P0 |
| **Category** | Bug / Architecture / Perf / CodeQuality | Bug |
| **Title** | Concise, one phrase | File Overwrites on Rapid Triggers |
| **File(s)** | Exact file paths | `storage.py:line 45` |
| **Symptom** | Observable behavior that's wrong | If two frames captured <1s apart, second overwrites first |
| **Root Cause** | Why it happens (be specific, not vague) | Timestamp formatted to seconds only; `2026-07-08T14-30-45.jpg` repeats |
| **Impact** | Business/user consequence | Silent data loss on concurrent triggers |
| **Fix (Concise)** | The actual fix in 2-3 lines max. Pseudo-code OK | Include microseconds: `ts.strftime('%Y-%m-%dT%H-%M-%S.%f').jpg` |
| **Estimated Effort** | XS / S / M / L (time to implement) | S |
| **Blocking** | Is this blocking other work? | No |
| **Testing Note** | How to verify it's fixed | Trigger two captures 0.5s apart; check both files exist |

---

### 3. Verification Notes (Optional but Valuable)

If you tested something, tell Claude what you found:

```
✓ Verified: The bug reproduces consistently when POSTing malformed JSON to /trigger
✓ Tested with: curl -X POST http://localhost:5000/trigger -d '{"invalid": json}'
✗ Could not test: PLC communication (PLC not on network yet)
```

---

### 4. Architecture & Refactoring (Separate Section)

If there are larger refactoring suggestions, **put them in a separate section** and mark them as **non-blocking suggestions**, not bugs.

Format:
- **Issue:** Camera reading logic duplicated across 3 files
- **Current State:** `gpio_trigger.py`, `scan_session.py`, `camera_stream.py` each have their own `CameraReader` implementation
- **Problem:** Hard to maintain, prone to inconsistencies
- **Suggested Fix:** Refactor `camera_stream.py` into a reusable class
- **Why It Matters:** Will make future camera work easier; current state is not broken
- **Effort:** M
- **Blocker:** No — do this after bugs are fixed

---

### 5. Context Links (If Helpful)

If findings reference external resources, link them:

```
- Config schema: see plc_vision.yaml:14-25
- Related code: plc_vision_app.py:86 (how RTSP URL is resolved)
- Deployment target: Raspberry Pi OS (ARM)
```

---

### 6. What NOT to Include

❌ **Verbose explanations or background.** (Claude can read the code if needed.)  
❌ **Multiple possible solutions.** (Pick the best one.)  
❌ **Lengthy copy-pasted code blocks.** (Quote relevant 3-5 lines only.)  
❌ **Questions for Claude.** (Make a decision, or ask upfront before handing off.)  
❌ **Incomplete findings.** (If you can't verify it, say so explicitly.)  
❌ **Blame or judgment.** (Focus on the technical issue, not who wrote it.)

---

## Example: Well-Formatted Issue

```
### P0: Silent JSON Parse Error — `trigger_handler.py:87`

**Symptom:** POST request with malformed JSON body is silently accepted. 
System uses default board_id="unknown". Client gets no error feedback.

**Root Cause:** Line 87 catches all exceptions: `except Exception: pass`

**Impact:** Makes debugging client integration extremely hard. No way for client 
to know their JSON is invalid.

**Fix:**
```python
# Line 87-90: Replace:
#   except Exception: pass
# With:
try:
    data = request.get_json(force=True)
except ValueError as e:
    logger.error("Invalid JSON from client: %s", e)
    return jsonify({"error": "Invalid JSON", "detail": str(e)}), 400
```

**Testing:** 
```bash
curl -X POST http://localhost:5000/trigger -d 'not json'
# Should return 400 with error message, not silently ignore
```

**Effort:** XS (1 line fix + logging)  
**Blocking:** No
```

---

## Template (Use This)

```markdown
# Handoff: [Project Name] — [Date]

## Summary
[1-2 sentences on state of project and what was found]

---

## P0 (Critical) Issues

### Issue Title — `file.py:line`
- **Symptom:** 
- **Root Cause:** 
- **Impact:** 
- **Fix:** 
- **Testing:** 
- **Effort:** 
- **Blocking:** 

---

## P1 (High) Issues

[Same format as P0]

---

## P2 (Medium) Issues

[Same format as P0]

---

## Architecture / Refactoring (Non-blocking)

[Separate issues here with **Why It Matters** and **Blocker: No**]

---

## Verification Notes

[What was tested, what couldn't be tested]

---

## Context

[Links to relevant code/docs]
```

---

## Dos and Don'ts

| Do ✓ | Don't ✗ |
|------|---------|
| Provide exact line numbers | "Somewhere in storage.py" |
| Give a 1-line fix for simple issues | "You should really think about refactoring this" |
| Say "tested and reproduced" or "untested" | Assume Claude will verify everything |
| Organize by priority | Organize by file or agent preference |
| Make a call: "Recommend fixing this" | "This could be a problem if X happens" |
| Link to specific code | Reference entire modules |
| Verify findings against the actual codebase | Speculate based on patterns |

---

## Handoff Workflow

1. **Gemini analyzes** → finds issues
2. **Gemini verifies** → reproduces or tests each finding
3. **Gemini writes handoff** using this spec
4. **Claude reads once** → immediately starts implementing
5. **Claude commits with:** "Fixes [issue title] — handoff from [agent]"

---

## Questions?

If Claude needs clarification on a finding, update this spec and re-handoff. Ideally, the handoff should be self-contained enough that Claude doesn't need to ask.
