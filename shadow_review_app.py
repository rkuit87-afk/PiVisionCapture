"""Local review page for a completed shadow session. Read-only to PLC/cameras."""

import argparse
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, abort, jsonify, render_template_string, request, send_from_directory

from dual_camera_measure import SAW_CALIBRATION

ROOT = Path(__file__).resolve().parent
CALIBRATION_PATH = ROOT / "calibration" / "grading_calibration_2026-07-09.json"
app = Flask(__name__)
SESSION = None

SAW_BITS = {saw["label"]: bit for bit, saw in SAW_CALIBRATION.items()}


def load_review_saw_lines():
    data = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
    lines = {"left": {}, "right": {}}
    for source, side in (("L", "left"), ("R", "right")):
        for label, point in data[source]["saws"].items():
            lines[side][SAW_BITS[label]] = round(float(point["px"]))
    return lines


def word_value(value):
    text = str(value or "0").strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def render_calibrated_profile(board, actual_word, frames=None):
    """Create a review-only overlay from raw frames and the supplied calibration."""
    frames = frames or SESSION / "frames"
    out_path = frames / f"board_{board:04d}_calibrated_mask_v2.jpg"
    raw_paths = [frames / f"board_{board:04d}_{side}.jpg" for side in ("L", "R")]
    if out_path.exists() or not any(path.exists() for path in raw_paths):
        return out_path if out_path.exists() else None

    saw_lines = load_review_saw_lines()
    applied = word_value(actual_word)

    def mark(path, side):
        frame = cv2.imread(str(path))
        if frame is None:
            return None
        out = frame.copy()
        height, _ = out.shape[:2]
        for bit, x in saw_lines[side].items():
            if not applied & (1 << bit):
                continue
            cv2.line(out, (x, 0), (x, height - 1), (0, 0, 255), 3)
            cv2.putText(out, SAW_CALIBRATION[bit]["label"], (max(2, x - 18), 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 255), 2, cv2.LINE_AA)
        return out

    left, right = mark(raw_paths[0], "left"), mark(raw_paths[1], "right")
    if left is None and right is None:
        return None
    if left is None:
        left = np.zeros_like(right)
    if right is None:
        right = np.zeros_like(left)
    if left.shape[0] != right.shape[0]:
        right = cv2.resize(right, (int(right.shape[1] * left.shape[0] / right.shape[0]), left.shape[0]))
    canvas = cv2.hconcat([left, right])
    header = np.zeros((105, canvas.shape[1], 3), dtype=np.uint8)
    cv2.putText(header, "REVIEW CALIBRATION 2026-07-09", (30, 42),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 220, 255), 2, cv2.LINE_AA)
    cv2.putText(header, f"PLC APPLIED: 0x{applied:04X}   red = applied saws", (30, 82),
                cv2.FONT_HERSHEY_SIMPLEX, 0.78, (0, 0, 255), 2, cv2.LINE_AA)
    cv2.imwrite(str(out_path), cv2.vconcat([header, canvas]), [cv2.IMWRITE_JPEG_QUALITY, 92])
    return out_path

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Shadow Data Review</title>
<style>
*{box-sizing:border-box} body{margin:0;font-family:Segoe UI,Arial,sans-serif;color:#17212b;background:#f3f5f6}
header{background:#17212b;color:white;padding:18px 28px;display:flex;align-items:center;justify-content:space-between;gap:20px}
h1{font-size:20px;margin:0;font-weight:600} header p{margin:4px 0 0;color:#b8c5cc;font-size:13px}
button{border:0;background:#0d766e;color:white;padding:10px 14px;font-weight:600;cursor:pointer;border-radius:4px}
button:hover{background:#095b55}.layout{display:grid;grid-template-columns:minmax(400px,1fr) minmax(460px,1.3fr);height:calc(100vh - 76px)}
.list{overflow:auto;background:#fff;border-right:1px solid #d7dde0}.summary{padding:14px 18px;border-bottom:1px solid #d7dde0;color:#52616a;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;color:#52616a;background:#f7f9f9;padding:10px;position:sticky;top:0}td{padding:10px;border-top:1px solid #e5e9eb}tr{cursor:pointer}tr:hover,tr.active{background:#e6f3f1}.word{font-family:Consolas,monospace}.exact{color:#087f5b;font-weight:700}.miss{color:#bd3d35;font-weight:700}
.viewer{padding:18px;overflow:auto}.viewer h2{font-size:16px;margin:0 0 10px}.meta{font-size:13px;color:#52616a;margin-bottom:12px}.tools{display:flex;align-items:center;gap:10px;margin-bottom:12px}.tools button{padding:7px 10px;background:#52616a}.tools button.active{background:#0d766e}.tools label{font-size:13px;color:#52616a}.tools input{width:150px}.image-wrap{overflow:auto;max-height:calc(100vh - 220px);background:#182127}.viewer img{width:350%;max-width:none;height:auto;background:#182127;display:block}.empty{color:#61717a;padding:28px;text-align:center}
#grade{display:none;align-items:end;gap:10px;flex-wrap:wrap;margin:12px 0;padding:12px;background:white;border:1px solid #d7dde0}#grade label{display:grid;gap:4px;font-size:12px;color:#52616a}#grade input{height:32px;padding:5px 7px;border:1px solid #b8c5cc;font-family:Consolas,monospace}#grade button{padding:8px 10px}.saw-picker{display:flex;flex-wrap:wrap;gap:6px;align-items:center;flex-basis:100%;padding-top:4px}.saw-picker strong{font-size:12px;color:#52616a;margin-right:2px}.saw-picker .saw-toggle{background:#e8edef;color:#26353c;border:1px solid #b8c5cc;padding:7px 9px;font-family:Consolas,monospace}.saw-picker .saw-toggle.selected{background:#bd3d35;border-color:#972e28;color:white}.saw-picker .divider{width:1px;height:28px;background:#d7dde0;margin:0 3px}
#notice{font-size:12px;color:#c8f0eb;min-width:180px;text-align:right}.image-stage{position:relative;display:inline-block;line-height:0}.image-stage img{position:relative}.marker-layer{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.marker-layer .selected{stroke:#1685e5}.marker-layer .matched{stroke:#10a766}.marker-layer line{stroke-width:5}.marker-layer text{font:700 30px Segoe UI,Arial,sans-serif;paint-order:stroke;stroke:#111;stroke-width:5px;stroke-linejoin:round}@media(max-width:900px){.layout{grid-template-columns:1fr;height:auto}.list{border-right:0}.viewer{min-height:480px}}
</style></head><body>
<header><div><h1>Shadow Data Review</h1><p>{{ session_name }} | trigger capture -> falling-edge commit -> saw-down applied profile</p></div><div><span id="notice"></span><button onclick="exportData()">Export Live Data</button></div></header>
<main class="layout"><section class="list"><div class="summary">{{ count }} completed boards. Select a row to inspect its calibrated saw-line overlay.</div>
<table><thead><tr><th>Board</th><th>Committed</th><th>Applied</th><th>Result</th></tr></thead><tbody>
{% for r in rows %}<tr onclick="showBoard({{ loop.index0 }},this)"><td>{{ r.board }}</td><td class="word">{{ r.commit_word or '-' }}</td><td class="word">{{ r.actual_word }}</td><td class="{{ r.match|lower }}">{{ r.match }}</td></tr>{% endfor %}
</tbody></table></section><section class="viewer"><h2 id="title">Select a board</h2><div class="meta" id="meta">The overlay uses the measured fence-to-saw calibration.</div><div class="tools"><button class="active" id="gradingBtn" onclick="setView('grading')">Grading Band</button><button id="fullBtn" onclick="setView('full')">Full Frame</button><label>Zoom <input id="zoom" type="range" min="1" max="6" step="0.25" value="3.5" oninput="setZoom(this.value)"> <span id="zoomValue">3.5x</span></label></div><div id="grade"><label>Reviewer<input id="reviewer" placeholder="name"></label><label>Expected word<input id="gradedWord" placeholder="0x0000" oninput="syncSawButtons(this.value)"></label><button onclick="saveGrade('confirm')">Confirm Applied</button><button onclick="saveGrade('supersede')">Save Expected</button><div class="saw-picker"><strong>Expected saws</strong><button class="saw-toggle" data-bit="0" onclick="toggleSaw(0)">0.0</button><button class="saw-toggle" data-bit="1" onclick="toggleSaw(1)">0.3</button><button class="saw-toggle" data-bit="2" onclick="toggleSaw(2)">0.6</button><button class="saw-toggle" data-bit="3" onclick="toggleSaw(3)">0.9</button><span class="divider"></span><button class="saw-toggle" data-bit="6" onclick="toggleSaw(6)">3.0</button><button class="saw-toggle" data-bit="7" onclick="toggleSaw(7)">3.6</button><button class="saw-toggle" data-bit="8" onclick="toggleSaw(8)">4.2</button><button class="saw-toggle" data-bit="9" onclick="toggleSaw(9)">4.8</button><button class="saw-toggle" data-bit="10" onclick="toggleSaw(10)">5.4</button><button class="saw-toggle" data-bit="11" onclick="toggleSaw(11)">6.0</button><button class="saw-toggle" data-bit="12" onclick="toggleSaw(12)">6.6</button></div></div><div class="image-wrap"><div class="image-stage"><img id="profile" hidden alt="Board profile comparison"><svg id="markerLayer" class="marker-layer" hidden aria-hidden="true"></svg></div></div><div id="empty" class="empty">Choose a completed board to inspect its capture and saw profile.</div></section></main>
<script>const boards={{ rows_json|safe }};let selected=null,view='grading';function render(){if(selected===null)return;const b=boards[selected],img=document.getElementById('profile'),file=view==='grading'&&b.grading_image?b.grading_image:b.profile_image;img.src='/frames/'+file+'?v='+Date.now();document.getElementById('gradingBtn').classList.toggle('active',view==='grading');document.getElementById('fullBtn').classList.toggle('active',view==='full')}function showBoard(i,row){document.querySelectorAll('tr.active').forEach(x=>x.classList.remove('active'));row.classList.add('active');selected=i;const b=boards[i],img=document.getElementById('profile');document.getElementById('title').textContent='Board '+String(b.board).padStart(4,'0');document.getElementById('meta').textContent=(b.notes||'')+' | captured '+b.t_trigger;img.hidden=false;document.getElementById('empty').hidden=true;render()}function setView(v){view=v;render()}function setZoom(v){document.getElementById('profile').style.width=(v*100)+'%';document.getElementById('zoomValue').textContent=Number(v).toFixed(1)+'x'}async function exportData(){const n=document.getElementById('notice');n.textContent='Exporting…';const r=await fetch('/export',{method:'POST'});const d=await r.json();n.textContent=d.ok?'Saved to '+d.path:'Export failed: '+d.error}</script>
<script>
const reviewLines={{ review_lines|safe }};
const SAW_BUTTONS=[['0.0',0],['0.3',1],['0.6',2],['3.0',3],['3.6',4],['4.2',5],['4.8',6],['5.4',7],['6.0',8],['6.6',9]];
function configureSawButtons(){document.querySelectorAll('.saw-toggle').forEach((button,index)=>{const saw=SAW_BUTTONS[index];if(!saw){button.remove();return}button.textContent=saw[0];button.dataset.bit=saw[1];button.onclick=()=>toggleSaw(saw[1])})}configureSawButtons();
function wordValue(text){const value=String(text||'').trim();if(!value)return 0;const base=value.toLowerCase().startsWith('0x')?16:10;const parsed=parseInt(value,base);return Number.isFinite(parsed)?parsed:0}
function renderMarkers(){const img=document.getElementById('profile'),layer=document.getElementById('markerLayer');if(selected===null||!img.naturalWidth){layer.hidden=true;return}const expected=wordValue(document.getElementById('gradedWord').value),actual=wordValue(boards[selected].actual_word),rawWidth=img.naturalWidth/2,header=105,lines=[];for(const [side,offset] of [['left',0],['right',rawWidth]])for(const [bit,rawX] of Object.entries(reviewLines[side])){const mask=1<<Number(bit);if(!(expected&mask))continue;const x=offset+Number(rawX),matched=Boolean(actual&mask),color=matched?'#10a766':'#1685e5',label=SAW_BUTTONS.find(s=>s[1]===Number(bit))[0];lines.push(`<line class="${matched?'matched':'selected'}" x1="${x}" y1="${header}" x2="${x}" y2="${img.naturalHeight}"/><text x="${x+8}" y="${header+38}" fill="${color}">${label}</text>`)}layer.setAttribute('viewBox',`0 0 ${img.naturalWidth} ${img.naturalHeight}`);layer.innerHTML=lines.join('');layer.hidden=lines.length===0}
function syncSawButtons(word){const value=wordValue(word);document.querySelectorAll('.saw-toggle').forEach(button=>button.classList.toggle('selected',Boolean(value&(1<<Number(button.dataset.bit)))));renderMarkers()}
function setZoom(v){const img=document.getElementById('profile'),stage=document.querySelector('.image-stage'),layer=document.getElementById('markerLayer'),factor=Number(v);if(!img.naturalWidth)return;stage.style.width=Math.round(img.naturalWidth*factor)+'px';img.style.width='100%';layer.style.zIndex='1';layer.style.display='block';document.getElementById('zoomValue').textContent=factor.toFixed(1)+'x';renderMarkers()}
document.getElementById('profile').addEventListener('load',()=>setZoom(document.getElementById('zoom').value));
function toggleSaw(bit){const input=document.getElementById('gradedWord');const value=wordValue(input.value)^(1<<bit);input.value='0x'+value.toString(16).toUpperCase().padStart(4,'0');syncSawButtons(input.value)}
function showBoard(i,row){document.querySelectorAll('tr.active').forEach(x=>x.classList.remove('active'));row.classList.add('active');selected=i;const b=boards[i],img=document.getElementById('profile'),g=b.grade||{};document.getElementById('title').textContent='Board '+String(b.board).padStart(4,'0');document.getElementById('meta').textContent=(b.notes||'')+' | applied '+(b.actual_word||'-')+' | captured '+b.t_trigger;document.getElementById('reviewer').value=g.reviewer||'';document.getElementById('gradedWord').value=g.graded_word||'';syncSawButtons(g.graded_word||'');document.getElementById('grade').style.display='flex';img.hidden=false;document.getElementById('empty').hidden=true;render()}
async function saveGrade(mode){if(selected===null)return;const b=boards[selected],word=mode==='confirm'?b.actual_word:document.getElementById('gradedWord').value;const r=await fetch('/grade/'+b.board,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:mode,graded_word:word,reviewer:document.getElementById('reviewer').value})});const d=await r.json();document.getElementById('notice').textContent=d.ok?'Grade saved':'Grade failed: '+d.error;if(d.ok){b.grade=d.grade;document.getElementById('gradedWord').value=d.grade.graded_word;syncSawButtons(d.grade.graded_word)}}
function ensureGradeNotes(){if(document.getElementById('gradeNotes'))return;const group=document.getElementById('grade'),label=document.createElement('label'),input=document.createElement('textarea');label.textContent='Review notes';input.id='gradeNotes';input.rows=2;input.placeholder='Optional observation';input.style.minWidth='280px';input.style.resize='vertical';label.appendChild(input);group.insertBefore(label,group.querySelector('.saw-picker'))}ensureGradeNotes();
function showBoard(i,row){document.querySelectorAll('tr.active').forEach(x=>x.classList.remove('active'));row.classList.add('active');selected=i;const b=boards[i],img=document.getElementById('profile'),g=b.grade||{};document.getElementById('title').textContent='Board '+String(b.board).padStart(4,'0');document.getElementById('meta').textContent=(b.notes||'')+' | applied '+(b.actual_word||'-')+' | captured '+b.t_trigger;document.getElementById('reviewer').value=g.reviewer||'';document.getElementById('gradedWord').value=g.graded_word||'';document.getElementById('gradeNotes').value=g.notes||'';syncSawButtons(g.graded_word||'');document.getElementById('grade').style.display='flex';img.hidden=false;document.getElementById('empty').hidden=true;render()}
async function saveGrade(mode){if(selected===null)return;const b=boards[selected],word=mode==='confirm'?b.actual_word:document.getElementById('gradedWord').value;const r=await fetch('/grade/'+b.board,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:mode,graded_word:word,reviewer:document.getElementById('reviewer').value,notes:document.getElementById('gradeNotes').value})});const d=await r.json();document.getElementById('notice').textContent=d.ok?'Grade saved':'Grade failed: '+d.error;if(d.ok){b.grade=d.grade;document.getElementById('gradedWord').value=d.grade.graded_word;syncSawButtons(d.grade.graded_word)}}
</script>
</body></html>"""


def source_frame_roots():
    """Return frame directories for a data-only combined review manifest."""
    manifest = SESSION / "sources.json"
    if not manifest.exists():
        return {}
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return {key: Path(value["frames"]).resolve()
            for key, value in data.get("sources", {}).items()}


def frame_url(row, filename):
    key = row.get("source_key", "")
    return f"source/{key}/{filename}" if key else filename


def rows():
    with (SESSION / "boards.csv").open(encoding="utf-8-sig", newline="") as fh:
        data = list(csv.DictReader(fh))
    grades = load_grades()
    for row in data:
        board = int(row["board"])
        source_board = int(row.get("source_board") or board)
        roots = source_frame_roots()
        frames = roots.get(row.get("source_key", ""), SESSION / "frames")
        calibrated = render_calibrated_profile(source_board, row.get("actual_word"), frames)
        profile_name = calibrated.name if calibrated else Path(
            row.get("profile_image") or f"board_{source_board:04d}_profile.jpg").name
        row["profile_image"] = frame_url(row, profile_name)
        grading_name = Path(row.get("grading_image") or
                            f"board_{source_board:04d}_grading.jpg").name
        # Live capture writes a full profile overlay; imported calibration
        # sessions may additionally have a focused grading crop.
        row["grading_image"] = frame_url(row, grading_name) if (frames / grading_name).exists() else ""
        row["grade"] = grades.get(str(row["board"]))
    return data


def grades_path():
    return SESSION / "grading.json"


def load_grades():
    path = grades_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_grades(grades):
    path = grades_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(grades, indent=2), encoding="utf-8")
    tmp.replace(path)


@app.get("/")
def index():
    data = rows()
    return render_template_string(PAGE, session_name=SESSION.name, count=len(data), rows=data,
                                  rows_json=json.dumps(data),
                                  review_lines=json.dumps(load_review_saw_lines()))


@app.get("/frames/<path:name>")
def frames(name):
    parts = Path(name).parts
    if len(parts) == 3 and parts[0] == "source":
        root = source_frame_roots().get(parts[1])
        filename = parts[2]
        if root is None or Path(filename).name != filename:
            abort(404)
        return send_from_directory(root, filename)
    return send_from_directory(SESSION / "frames", name)


@app.post("/grade/<int:board>")
def grade(board):
    try:
        row = next((r for r in rows() if int(r["board"]) == board), None)
        if row is None:
            return jsonify(ok=False, error="board not found"), 404
        payload = request.get_json(force=True)
        mode = payload.get("mode")
        word = str(payload.get("graded_word") or "").strip().upper()
        if mode == "confirm":
            word = row.get("actual_word", "")
        try:
            value = int(word, 16) if word.lower().startswith("0x") else int(word)
        except ValueError:
            return jsonify(ok=False, error="expected word must be hexadecimal, e.g. 0x0101"), 400
        if not 0 <= value <= 0xFFFF:
            return jsonify(ok=False, error="expected word is outside 0x0000..0xFFFF"), 400
        record = {"graded_word": f"0x{value:04X}", "mode": mode,
                  "reviewer": str(payload.get("reviewer") or "").strip(),
                  "notes": str(payload.get("notes") or "").strip(),
                  "graded_at": datetime.now().isoformat(timespec="seconds"),
                  "applied_word": row.get("actual_word", "")}
        grades = load_grades()
        grades[str(board)] = record
        save_grades(grades)
        return jsonify(ok=True, grade=record)
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 500


@app.post("/export")
def export():
    try:
        out_root = ROOT / "Live Data"
        out_root.mkdir(exist_ok=True)
        dest = out_root / SESSION.name
        if dest.exists():
            dest = out_root / f"{SESSION.name}_{datetime.now():%H%M%S}"
        shutil.copytree(SESSION, dest)
        return jsonify(ok=True, path=str(dest.relative_to(ROOT)))
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 500


def main():
    global SESSION
    ap = argparse.ArgumentParser(description="Review/export a completed shadow session")
    ap.add_argument("session", nargs="?", help="session directory; default is latest")
    ap.add_argument("--port", type=int, default=5055)
    args = ap.parse_args()
    if args.session:
        SESSION = Path(args.session).resolve()
    else:
        sessions = sorted((ROOT / "shadow_sessions").glob("*"), key=lambda p: p.stat().st_mtime)
        SESSION = sessions[-1] if sessions else None
    if not SESSION or not (SESSION / "boards.csv").exists():
        raise SystemExit("No completed shadow session with boards.csv found.")
    print(f"Shadow review: http://127.0.0.1:{args.port}  session={SESSION}")
    app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
