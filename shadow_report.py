"""
shadow_report.py — summarize a shadow session (and compare two sessions).

Reads events.jsonl written by shadow_capture_app.py and produces report.md
in the session directory: agreement totals, per-saw confusion counts,
stop-position statistics, and the full disagreement list with image paths.

Usage:
  python shadow_report.py <session_dir>
  python shadow_report.py <baseline_dir> --compare <changed_dir>
"""

import argparse
import json
import statistics
from pathlib import Path

from dual_camera_measure import SAW_CALIBRATION


def load_events(session_dir: Path):
    events = []
    path = session_dir / "events.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    return events


def word_int(v):
    if isinstance(v, int):
        return v
    return int(str(v), 16) if str(v).startswith("0x") else int(v)


def summarize(session_dir: Path):
    events = load_events(session_dir)
    comps = [e for e in events if e["kind"] == "comparison"]
    trigs = [e for e in events if e["kind"] == "trigger"]
    unmatched = [e for e in events if e["kind"] == "saw_done_unmatched"]

    tally = {"EXACT": 0, "CLOSE": 0, "MISS": 0, "CAPTURED": 0}
    per_saw = {b: {"ours_only": 0, "operator_only": 0, "both": 0}
               for b in SAW_CALIBRATION}
    disagreements = []
    for c in comps:
        tally[c["match"]] = tally.get(c["match"], 0) + 1
        ours = word_int(c["our_word"]) if c.get("our_word") else 0
        actual = word_int(c["actual_word"])
        for b in SAW_CALIBRATION:
            o, a = bool(ours & (1 << b)), bool(actual & (1 << b))
            if o and a:
                per_saw[b]["both"] += 1
            elif o:
                per_saw[b]["ours_only"] += 1
            elif a:
                per_saw[b]["operator_only"] += 1
        if c["match"] not in ("EXACT", "CAPTURED"):
            disagreements.append(c)

    def stats(key):
        vals = []
        for t in trigs:
            v = (t.get(key) or {}).get("dy_px") if isinstance(t.get(key), dict) else None
            if v is not None:
                vals.append(float(v))
        if not vals:
            return None
        return {"n": len(vals), "mean": statistics.mean(vals),
                "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0,
                "min": min(vals), "max": max(vals)}

    return {
        "dir": str(session_dir),
        "triggers": len(trigs),
        "compared": len(comps),
        "unmatched_sawdone": len(unmatched),
        "tally": tally,
        "per_saw": per_saw,
        "stop_dy_left": stats("dev_left"),
        "stop_dy_right": stats("dev_right"),
        "disagreements": disagreements,
    }


def fmt_stats(s):
    if not s:
        return "n/a (no boards with a detected position)"
    return (f"n={s['n']}  mean={s['mean']:+.1f}px  stdev={s['stdev']:.1f}px  "
            f"range {s['min']:+.1f}..{s['max']:+.1f}px")


def render(s) -> str:
    total = max(1, s["compared"])
    lines = [
        f"# Shadow session report — {Path(s['dir']).name}",
        "",
        f"- Triggers seen (boards captured): **{s['triggers']}**",
        f"- Boards compared at saw-done: **{s['compared']}**",
        f"- Saw-done pulses with empty FIFO (fed before start): {s['unmatched_sawdone']}",
        "",
        "## Commit / applied comparison",
        "",
        f"| verdict | boards | share |",
        f"|---|---|---|",
        f"| EXACT (same saw word) | {s['tally'].get('EXACT', 0)} | {s['tally'].get('EXACT', 0)/total:.0%} |",
        f"| CLOSE (≤1 saw each way) | {s['tally'].get('CLOSE', 0)} | {s['tally'].get('CLOSE', 0)/total:.0%} |",
        f"| MISS | {s['tally'].get('MISS', 0)} | {s['tally'].get('MISS', 0)/total:.0%} |",
        f"| CAPTURED (no vision measurement) | {s['tally'].get('CAPTURED', 0)} | {s['tally'].get('CAPTURED', 0)/total:.0%} |",
        "",
        "## Per-saw usage (boards where the saw dropped)",
        "",
        "| saw | mm | both | ours only | operator only |",
        "|---|---|---|---|---|",
    ]
    for b, saw in SAW_CALIBRATION.items():
        p = s["per_saw"][b]
        if p["both"] or p["ours_only"] or p["operator_only"]:
            lines.append(f"| {saw['label']} | {saw['mm']} | {p['both']} | "
                         f"{p['ours_only']} | {p['operator_only']} |")
    lines += [
        "",
        "## Stop position vs calibration-board reference",
        "",
        f"- LEFT  dY: {fmt_stats(s['stop_dy_left'])}",
        f"- RIGHT dY: {fmt_stats(s['stop_dy_right'])}",
        "",
        "Positive dY = board rests LOWER in the image than the calibration",
        "board (stop later); negative = earlier. Use the mean to trim the",
        "stop timing; the stdev shows mechanical repeatability.",
        "",
        f"## Disagreements ({len(s['disagreements'])})",
        "",
    ]
    for d in s["disagreements"]:
        profile_image = d.get("profile_image") or f"frames/board_{int(d['board']):04d}_profile.jpg"
        lines.append(
            f"- board {d['board']}: committed **{d['our_saws']}** ({d['our_word']}) vs "
            f"applied **{d['actual_saws']}** ({d['actual_word']}) [{d['match']}] "
            f"len={d['our_length_mm']}mm err={d['our_error']} "
            f"-> `{profile_image}`")
    lines.append("")
    return "\n".join(lines)


def generate(session_dir):
    session_dir = Path(session_dir)
    s = summarize(session_dir)
    out = session_dir / "report.md"
    out.write_text(render(s), encoding="utf-8")
    print(f"report -> {out}")
    return s


def compare(base_dir, changed_dir):
    a, b = summarize(Path(base_dir)), summarize(Path(changed_dir))
    ta, tb = max(1, a["compared"]), max(1, b["compared"])
    lines = [
        f"# Session comparison",
        "",
        f"| metric | {Path(a['dir']).name} | {Path(b['dir']).name} |",
        "|---|---|---|",
        f"| boards compared | {a['compared']} | {b['compared']} |",
        f"| EXACT | {a['tally'].get('EXACT',0)} ({a['tally'].get('EXACT',0)/ta:.0%}) | "
        f"{b['tally'].get('EXACT',0)} ({b['tally'].get('EXACT',0)/tb:.0%}) |",
        f"| CLOSE | {a['tally'].get('CLOSE',0)} ({a['tally'].get('CLOSE',0)/ta:.0%}) | "
        f"{b['tally'].get('CLOSE',0)} ({b['tally'].get('CLOSE',0)/tb:.0%}) |",
        f"| MISS | {a['tally'].get('MISS',0)} ({a['tally'].get('MISS',0)/ta:.0%}) | "
        f"{b['tally'].get('MISS',0)} ({b['tally'].get('MISS',0)/tb:.0%}) |",
        f"| stop dY LEFT | {fmt_stats(a['stop_dy_left'])} | {fmt_stats(b['stop_dy_left'])} |",
        f"| stop dY RIGHT | {fmt_stats(a['stop_dy_right'])} | {fmt_stats(b['stop_dy_right'])} |",
        "",
    ]
    out = Path(changed_dir) / "comparison_vs_baseline.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"comparison -> {out}")


def main():
    ap = argparse.ArgumentParser(description="Shadow session report")
    ap.add_argument("session_dir")
    ap.add_argument("--compare", help="second session dir (changed run) to compare against")
    args = ap.parse_args()
    generate(args.session_dir)
    if args.compare:
        generate(args.compare)
        compare(args.session_dir, args.compare)


if __name__ == "__main__":
    main()
