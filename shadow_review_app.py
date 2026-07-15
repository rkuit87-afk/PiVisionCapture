"""Local review page for a completed shadow session. Read-only to PLC/cameras."""

import argparse
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml
from flask import Flask, abort, jsonify, render_template_string, request, send_from_directory

from dual_camera_measure import SAW_CALIBRATION
from map_fishtail_color import board_brightness_mask
from vision_host_app import measure_cfg_from

ROOT = Path(__file__).resolve().parent
CALIBRATION_PATH = ROOT / "calibration" / "grading_calibration_2026-07-09.json"
app = Flask(__name__)
SESSION = None
REVIEW_ROLE = "operator"
EDGE_STUDY = False
_MEASURE_CFG = None


def measure_cfg():
    """Lazily load vision_host.yaml's board-band config (used to seed the
    warm/cold overlay's brightness mask with the correct camera band)."""
    global _MEASURE_CFG
    if _MEASURE_CFG is None:
        data = yaml.safe_load((ROOT / "vision_host.yaml").read_text(encoding="utf-8"))
        _MEASURE_CFG = measure_cfg_from(data)
    return _MEASURE_CFG

REVIEW_ROLES = {
    "codex": {"key": "codex", "label": "Codex review", "marker_color": "#ec4899", "match_color": "#ec4899"},
    "claude": {"key": "claude", "label": "Claude review", "marker_color": "#ff5a1f", "match_color": "#ff5a1f"},
    "operator": {"key": "manager", "label": "Production review", "marker_color": "#1685e5", "match_color": "#10a766"},
}

COMPARISON_SOURCES = {
    "operator": {"label": "Operator", "short": "OP", "color": "#d92d20"},
    "codex": {"label": "Codex", "short": "CX", "color": "#ec4899"},
    "claude": {"label": "Claude", "short": "CL", "color": "#ff5a1f"},
    "manager": {"label": "Manager", "short": "ME", "color": "#1685e5"},
}

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


def read_grade_file(path):
    """Return a grade mapping without making a missing review source fatal."""
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def latest_live_data_file(pattern):
    matches = list((ROOT / "Live Data").glob(pattern))
    return max(matches, key=lambda path: path.stat().st_mtime) if matches else None


def comparison_grades():
    """Find each independent review stream; all reads are local and read-only."""
    return {
        "codex": read_grade_file(SESSION / "reviews" / "codex.json"),
        "claude": read_grade_file(latest_live_data_file(
            "claude_blind_review_*/reviews/claude.json")),
        "manager": read_grade_file(latest_live_data_file(
            "operator_grading_*/grading.json")),
    }


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


def severity_bands(img, mask, dark_v=90, warm_r_minus_b=25):
    """Classify each board-mask pixel into a 3-band traffic-light severity
    map instead of a continuous heatmap: dark (likely gouge/tear-out/shadow)
    -> red, ambiguous/overexposed-but-not-dark -> yellow, bright real wood
    tone -> green (usable). Thresholds are a starting heuristic, not a
    calibrated defect model -- expect to retune dark_v/warm_r_minus_b
    against real boards."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    v = hsv[:, :, 2].astype(np.int16)
    b = img[:, :, 0].astype(np.int16)
    r = img[:, :, 2].astype(np.int16)
    warmth = r - b

    red = v < dark_v
    green = (~red) & (warmth >= warm_r_minus_b)
    yellow = (~red) & (~green)

    band = np.zeros_like(img)
    band[red] = (0, 0, 220)      # BGR red
    band[yellow] = (0, 210, 230)  # BGR yellow
    band[green] = (60, 180, 60)   # BGR green

    out = img.copy()
    board_only = mask > 0
    out[board_only] = cv2.addWeighted(img, 0.30, band, 0.70, 0)[board_only]
    out[mask == 0] = (img[mask == 0] * 0.4).astype(np.uint8)
    return out


def render_severity_overlay(board, frames):
    """Cache the red/yellow/green severity overlay as a selectable review
    layer: red = dark (likely gouge/tear-out/shadow), yellow = ambiguous or
    overexposed, green = confidently usable wood tone."""
    out_path = frames / f"board_{board:04d}_severity_overlay.jpg"
    raw_paths = {"left": frames / f"board_{board:04d}_L.jpg", "right": frames / f"board_{board:04d}_R.jpg"}
    if out_path.exists() or not any(path.exists() for path in raw_paths.values()):
        return out_path if out_path.exists() else None

    cfg = measure_cfg()
    y_ranges = {"left": cfg.board_y_range_left, "right": cfg.board_y_range_right}

    def render_side(path, side):
        frame = cv2.imread(str(path))
        if frame is None:
            return None
        mask, _ = board_brightness_mask(frame, y_range=y_ranges[side])
        if mask is None:
            return frame
        return severity_bands(frame, mask)

    left, right = render_side(raw_paths["left"], "left"), render_side(raw_paths["right"], "right")
    if left is None and right is None:
        return None
    if left is None:
        left = np.zeros_like(right)
    if right is None:
        right = np.zeros_like(left)
    if left.shape[0] != right.shape[0]:
        right = cv2.resize(right, (int(right.shape[1] * left.shape[0] / right.shape[0]), left.shape[0]))
    canvas = cv2.hconcat([left, right])
    header = np.zeros((70, canvas.shape[1], 3), dtype=np.uint8)
    cv2.putText(header, "SEVERITY OVERLAY - red=dark/likely defect  yellow=ambiguous/overexposed  green=usable wood",
                (24, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 220, 255), 2, cv2.LINE_AA)
    cv2.imwrite(str(out_path), cv2.vconcat([header, canvas]), [cv2.IMWRITE_JPEG_QUALITY, 92])
    return out_path


def edge_study_config_path():
    return SESSION / "annotations" / "edge_study_10_boards.json"


def load_edge_study_config():
    path = edge_study_config_path()
    if not path.exists():
        return {"boards": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"boards": []}


def edge_annotations_path():
    return SESSION / "annotations" / "edge_study_annotations.json"


def load_edge_annotations():
    return read_grade_file(edge_annotations_path())


def save_edge_annotations(data):
    path = edge_annotations_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def render_edge_study_image(study_board, source_board, frames):
    """Create a neutral, calibrated raw pair for visual evidence marking."""
    out_dir = SESSION / "annotations" / "edge_study_images"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"study_{study_board:04d}_source_{source_board:04d}_edge_study_v1.jpg"
    if out_path.exists():
        return out_path

    left = cv2.imread(str(frames / f"board_{source_board:04d}_L.jpg"))
    right = cv2.imread(str(frames / f"board_{source_board:04d}_R.jpg"))
    if left is None or right is None:
        return None
    right_scale = left.shape[0] / right.shape[0]
    if right_scale != 1:
        right = cv2.resize(right, (round(right.shape[1] * right_scale), left.shape[0]))
    canvas = cv2.hconcat([left, right])
    header_height = 70
    header = np.zeros((header_height, canvas.shape[1], 3), dtype=np.uint8)
    cv2.putText(header, "EDGE STUDY - neutral saw positions; mark the usable edge and defect evidence",
                (24, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (225, 225, 225), 2, cv2.LINE_AA)
    saw_lines = load_review_saw_lines()
    left_width = left.shape[1]
    for side, offset, scale in (("left", 0, 1.0), ("right", left_width, right_scale)):
        for bit, raw_x in saw_lines[side].items():
            x = offset + round(raw_x * scale)
            cv2.line(canvas, (x, 0), (x, canvas.shape[0] - 1), (135, 135, 135), 1)
            cv2.putText(canvas, SAW_CALIBRATION[bit]["label"], (max(2, x - 15), 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (205, 205, 205), 1, cv2.LINE_AA)
    cv2.imwrite(str(out_path), cv2.vconcat([header, canvas]), [cv2.IMWRITE_JPEG_QUALITY, 94])
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
#notice{font-size:12px;color:#c8f0eb;min-width:180px;text-align:right}.image-stage{position:relative;display:inline-block;line-height:0}.image-stage img{position:relative}.marker-layer{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.marker-layer .selected{stroke:#1685e5}.marker-layer .matched{stroke:#10a766}.marker-layer line{stroke-width:5}.marker-layer text{font:700 30px Segoe UI,Arial,sans-serif;paint-order:stroke;stroke:#111;stroke-width:5px;stroke-linejoin:round}.compare-panel{display:grid;gap:9px;margin:12px 0;padding:12px;background:#fff;border:1px solid #d7dde0}.compare-toolbar{display:flex;flex-wrap:wrap;gap:7px;align-items:center}.compare-toolbar span{font-size:12px;color:#52616a;font-weight:600;margin-right:2px}.compare-toggle{background:#fff;color:#34424c;border:1px solid #aebbc1;padding:6px 9px}.compare-toggle.active{color:#fff;border-color:transparent}.compare-toggle[data-source="operator"].active{background:#d92d20}.compare-toggle[data-source="codex"].active{background:#ec4899}.compare-toggle[data-source="claude"].active{background:#ff5a1f}.compare-toggle[data-source="manager"].active{background:#1685e5}.compare-toggle.all.active{background:#26353c}.comparison-summary{font:12px Consolas,monospace;color:#52616a}.decision-matrix{overflow:auto}.decision-matrix table{font-size:12px;min-width:470px}.decision-matrix th,.decision-matrix td{padding:5px 8px;text-align:center;border:1px solid #e1e7e9}.decision-matrix th:first-child,.decision-matrix td:first-child{text-align:left}.decision-matrix .yes{font-weight:800}.decision-matrix .missing{color:#9aa6ad}.edge-study{display:grid;gap:9px;margin:12px 0;padding:12px;background:#fff;border:1px solid #d7dde0}.edge-study-header{font-size:13px;color:#26353c;font-weight:700}.edge-study p{margin:0;font-size:12px;color:#52616a;line-height:1.4}.edge-study-controls{display:flex;gap:8px;align-items:end;flex-wrap:wrap}.edge-study label{display:grid;gap:4px;font-size:12px;color:#52616a}.edge-study select,.edge-study input,.edge-study textarea{border:1px solid #b8c5cc;padding:6px;font:13px Segoe UI,Arial,sans-serif}.edge-study textarea{min-width:300px;resize:vertical}.edge-study .secondary{background:#52616a}.edge-study .danger{background:#a9433d}.edge-legend{display:flex;gap:10px;flex-wrap:wrap;font-size:12px;color:#52616a}.edge-legend i{display:inline-block;width:11px;height:11px;margin-right:4px;border-radius:50%;vertical-align:-1px}.edge-instruction{font:12px Consolas,monospace;color:#0d766e}.edge-study-mode .image-stage{cursor:crosshair}.edge-study-mode #grade,.edge-study-mode #comparePanel{display:none!important}@media(max-width:900px){.layout{grid-template-columns:1fr;height:auto}.list{border-right:0}.viewer{min-height:480px}}
</style></head><body>
<header><div><h1>Shadow Data Review - {{ review.label }}</h1><p>{{ session_name }} | operator/PLC decision is red; this review's proposed cuts use its assigned colour.</p></div><div><span id="notice"></span><button onclick="exportData()">Export Live Data</button></div></header>
<main class="layout"><section class="list"><div class="summary">{{ count }} completed boards. Select a row to inspect its calibrated saw-line overlay.</div>
<table><thead><tr><th>Board</th>{% if edge_study %}<th>Review status</th>{% else %}<th>Committed</th><th>Applied</th><th>Result</th>{% endif %}</tr></thead><tbody>
{% for r in rows %}<tr onclick="showBoard({{ loop.index0 }},this)"><td>{{ r.board }}</td>{% if edge_study %}<td>ungraded evidence</td>{% else %}<td class="word">{{ r.commit_word or '-' }}</td><td class="word">{{ r.actual_word }}</td><td class="{{ r.match|lower }}">{{ r.match }}</td>{% endif %}</tr>{% endfor %}
</tbody></table></section><section class="viewer"><h2 id="title">Select a board</h2><div class="meta" id="meta">The overlay uses the measured fence-to-saw calibration.</div><div class="tools"><button class="active" id="gradingBtn" onclick="setView('grading')">Grading Band</button><button id="fullBtn" onclick="setView('full')">Full Frame</button><button id="severityBtn" onclick="setView('severity')">Severity (R/Y/G)</button><label>Zoom <input id="zoom" type="range" min="1" max="6" step="0.25" value="3.5" oninput="setZoom(this.value)"> <span id="zoomValue">3.5x</span></label></div><div id="grade"><label>Reviewer<input id="reviewer" placeholder="name"></label><label>Expected word<input id="gradedWord" placeholder="0x0000" oninput="syncSawButtons(this.value)"></label><button onclick="saveGrade('confirm')">Confirm Applied</button><button onclick="saveGrade('supersede')">Save Expected</button><div class="saw-picker"><strong>Expected saws</strong><button class="saw-toggle" data-bit="0" onclick="toggleSaw(0)">0.0</button><button class="saw-toggle" data-bit="1" onclick="toggleSaw(1)">0.3</button><button class="saw-toggle" data-bit="2" onclick="toggleSaw(2)">0.6</button><button class="saw-toggle" data-bit="3" onclick="toggleSaw(3)">0.9</button><span class="divider"></span><button class="saw-toggle" data-bit="6" onclick="toggleSaw(6)">3.0</button><button class="saw-toggle" data-bit="7" onclick="toggleSaw(7)">3.6</button><button class="saw-toggle" data-bit="8" onclick="toggleSaw(8)">4.2</button><button class="saw-toggle" data-bit="9" onclick="toggleSaw(9)">4.8</button><button class="saw-toggle" data-bit="10" onclick="toggleSaw(10)">5.4</button><button class="saw-toggle" data-bit="11" onclick="toggleSaw(11)">6.0</button><button class="saw-toggle" data-bit="12" onclick="toggleSaw(12)">6.6</button></div></div><div id="comparePanel" class="compare-panel" hidden><div class="compare-toolbar"><span>Show decisions</span><button class="compare-toggle active" data-source="operator" onclick="toggleComparison('operator')">Operator</button><button class="compare-toggle active" data-source="codex" onclick="toggleComparison('codex')">Codex</button><button class="compare-toggle active" data-source="claude" onclick="toggleComparison('claude')">Claude</button><button class="compare-toggle active" data-source="manager" onclick="toggleComparison('manager')">Manager</button><button class="compare-toggle all active" id="allComparisons" onclick="toggleAllComparisons()">All</button></div><div id="comparisonSummary" class="comparison-summary"></div><div id="decisionMatrix" class="decision-matrix"></div></div><div class="image-wrap"><div class="image-stage"><img id="profile" hidden alt="Board profile comparison"><svg id="markerLayer" class="marker-layer" hidden aria-hidden="true"></svg></div></div><div id="empty" class="empty">Choose a completed board to inspect its capture and saw profile.</div></section></main>
<script>const boards={{ rows_json|safe }};let selected=null,view='grading';function render(){if(selected===null)return;const b=boards[selected],img=document.getElementById('profile'),file=view==='severity'&&b.severity_image?b.severity_image:(view==='grading'&&b.grading_image?b.grading_image:b.profile_image);img.src='/frames/'+file+'?v='+Date.now();document.getElementById('gradingBtn').classList.toggle('active',view==='grading');document.getElementById('fullBtn').classList.toggle('active',view==='full');document.getElementById('severityBtn').classList.toggle('active',view==='severity')}function showBoard(i,row){document.querySelectorAll('tr.active').forEach(x=>x.classList.remove('active'));row.classList.add('active');selected=i;const b=boards[i],img=document.getElementById('profile');document.getElementById('title').textContent='Board '+String(b.board).padStart(4,'0');document.getElementById('meta').textContent=(b.notes||'')+' | captured '+b.t_trigger;img.hidden=false;document.getElementById('empty').hidden=true;render()}function setView(v){view=v;render()}function setZoom(v){document.getElementById('profile').style.width=(v*100)+'%';document.getElementById('zoomValue').textContent=Number(v).toFixed(1)+'x'}async function exportData(){const n=document.getElementById('notice');n.textContent='Exporting…';const r=await fetch('/export',{method:'POST'});const d=await r.json();n.textContent=d.ok?'Saved to '+d.path:'Export failed: '+d.error}</script>
<script>
const reviewLines={{ review_lines|safe }};
const REVIEW={{ review_json|safe }};
const SAW_BUTTONS=[['0.0',0],['0.3',1],['0.6',2],['3.0',3],['3.6',4],['4.2',5],['4.8',6],['5.4',7],['6.0',8],['6.6',9]];
function configureSawButtons(){document.querySelectorAll('.saw-toggle').forEach((button,index)=>{const saw=SAW_BUTTONS[index];if(!saw){button.remove();return}button.textContent=saw[0];button.dataset.bit=saw[1];button.onclick=()=>toggleSaw(saw[1])})}configureSawButtons();
function wordValue(text){const value=String(text||'').trim();if(!value)return 0;const base=value.toLowerCase().startsWith('0x')?16:10;const parsed=parseInt(value,base);return Number.isFinite(parsed)?parsed:0}
function renderMarkers(){const img=document.getElementById('profile'),layer=document.getElementById('markerLayer');if(selected===null||!img.naturalWidth){layer.hidden=true;return}const expected=wordValue(document.getElementById('gradedWord').value),actual=wordValue(boards[selected].actual_word),rawWidth=img.naturalWidth/2,header=105,lines=[];for(const [side,offset] of [['left',0],['right',rawWidth]])for(const [bit,rawX] of Object.entries(reviewLines[side])){const mask=1<<Number(bit);if(!(expected&mask))continue;const x=offset+Number(rawX),matched=Boolean(actual&mask),color=matched?REVIEW.match_color:REVIEW.marker_color,label=SAW_BUTTONS.find(s=>s[1]===Number(bit))[0];lines.push(`<line class="${matched?'matched':'selected'}" x1="${x}" y1="${header}" x2="${x}" y2="${img.naturalHeight}" style="stroke:${color}"/><text x="${x+8}" y="${header+38}" fill="${color}">${label}</text>`)}layer.setAttribute('viewBox',`0 0 ${img.naturalWidth} ${img.naturalHeight}`);layer.innerHTML=lines.join('');layer.hidden=lines.length===0}
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
<script>
const COMPARISON_SOURCES={{ comparison_json|safe }};
let visibleComparisons=new Set(Object.keys(COMPARISON_SOURCES));
function comparisonEntries(board){return Object.entries(board.comparison||{}).filter(([key,value])=>visibleComparisons.has(key)&&value&&value.word)}
function toggleComparison(key){if(visibleComparisons.has(key))visibleComparisons.delete(key);else visibleComparisons.add(key);syncComparisonButtons();renderComparison()}
function toggleAllComparisons(){const keys=Object.keys(COMPARISON_SOURCES);visibleComparisons=visibleComparisons.size===keys.length?new Set():new Set(keys);syncComparisonButtons();renderComparison()}
function syncComparisonButtons(){document.querySelectorAll('.compare-toggle[data-source]').forEach(button=>button.classList.toggle('active',visibleComparisons.has(button.dataset.source)));const all=document.getElementById('allComparisons');all.classList.toggle('active',visibleComparisons.size===Object.keys(COMPARISON_SOURCES).length)}
function sourceWord(board,key){const source=(board.comparison||{})[key];let word=source&&source.word;if(key===REVIEW.key&&document.getElementById('gradedWord').value)word=document.getElementById('gradedWord').value;return wordValue(word)}
function renderComparison(){renderMarkers();renderDecisionMatrix()}
function renderMarkers(){const img=document.getElementById('profile'),layer=document.getElementById('markerLayer');if(selected===null||!img.naturalWidth){layer.hidden=true;return}const board=boards[selected],rawWidth=img.naturalWidth/2,header=105,marks=[];for(const [side,offset] of [['left',0],['right',rawWidth]])for(const [bit,rawX] of Object.entries(reviewLines[side])){const mask=1<<Number(bit),x=offset+Number(rawX),active=Object.keys(COMPARISON_SOURCES).filter(key=>visibleComparisons.has(key)&&(sourceWord(board,key)&mask));if(!active.length)continue;if(active.length===1){const source=COMPARISON_SOURCES[active[0]],label=SAW_BUTTONS.find(s=>s[1]===Number(bit))[0];marks.push(`<line x1="${x}" y1="${header}" x2="${x}" y2="${img.naturalHeight}" style="stroke:${source.color}"/><text x="${x+8}" y="${header+38}" fill="${source.color}">${label}</text>`);continue}marks.push(`<line x1="${x}" y1="${header}" x2="${x}" y2="${img.naturalHeight}" style="stroke:#a9b3b8;stroke-width:3;stroke-dasharray:14 10;opacity:.72"/>`);active.forEach(key=>{const source=COMPARISON_SOURCES[key],lane=Object.keys(COMPARISON_SOURCES).indexOf(key),y=header+10+lane*25;marks.push(`<line x1="${x}" y1="${y}" x2="${x}" y2="${y+16}" style="stroke:${source.color};stroke-width:11"/><text x="${x+10}" y="${y+15}" fill="${source.color}" style="font-size:17px">${source.short}</text>`)});}
layer.setAttribute('viewBox',`0 0 ${img.naturalWidth} ${img.naturalHeight}`);layer.innerHTML=marks.join('');layer.hidden=marks.length===0}
function renderDecisionMatrix(){const panel=document.getElementById('comparePanel'),summary=document.getElementById('comparisonSummary'),target=document.getElementById('decisionMatrix');if(selected===null){panel.hidden=true;return}panel.hidden=false;const board=boards[selected],keys=Object.keys(COMPARISON_SOURCES).filter(key=>visibleComparisons.has(key)),words=keys.map(key=>`${COMPARISON_SOURCES[key].label} ${((board.comparison||{})[key]||{}).word||'-'}`);summary.textContent=words.join('   |   ');let html='<table><thead><tr><th>Saw</th>'+keys.map(key=>`<th style="color:${COMPARISON_SOURCES[key].color}">${COMPARISON_SOURCES[key].label}</th>`).join('')+'</tr></thead><tbody>';SAW_BUTTONS.forEach(([label,bit])=>{html+=`<tr><td>${label}</td>`+keys.map(key=>{const has=Boolean(sourceWord(board,key)&(1<<bit));return `<td class="${has?'yes':'missing'}" style="color:${has?COMPARISON_SOURCES[key].color:''}">${has?'&#10003;':'-'}</td>`}).join('')+'</tr>'});target.innerHTML=html+'</tbody></table>'}
function showBoard(i,row){document.querySelectorAll('tr.active').forEach(x=>x.classList.remove('active'));row.classList.add('active');selected=i;const b=boards[i],img=document.getElementById('profile'),g=b.grade||{};document.getElementById('title').textContent='Board '+String(b.board).padStart(4,'0');document.getElementById('meta').textContent=(b.notes||'')+' | applied '+(b.actual_word||'-')+' | captured '+b.t_trigger;document.getElementById('reviewer').value=g.reviewer||'';document.getElementById('gradedWord').value=g.graded_word||'';document.getElementById('gradeNotes').value=g.notes||'';syncSawButtons(g.graded_word||'');document.getElementById('grade').style.display='flex';img.hidden=false;document.getElementById('empty').hidden=true;render();renderDecisionMatrix()}
</script>
<script>
const EDGE_STUDY={{ 'true' if edge_study else 'false' }};
const EDGE_STUDY_INSTRUCTIONS={{ edge_study_instructions|tojson }};
const EDGE_TYPES={
  board_outline:{label:'Board outline (trace)',short:'OUTL',color:'#00e5ff'},
  usable_edge:{label:'Usable edge',short:'EDGE',color:'#00a884'},
  fishtail:{label:'Fish tail (trace shape)',short:'FISH',color:'#d91b92'},
  tear_out:{label:'Tear-out',short:'TEAR',color:'#ff6b00'},
  wane:{label:'Wane',short:'WANE',color:'#d5a500'},
  lighting_limit:{label:'Lighting limit',short:'LIGHT',color:'#1685e5'},
  machine_occlusion:{label:'Machine occlusion',short:'OCC',color:'#7b8790'},
  max_usable_line:{label:'Max usable line (2 clicks)',short:'MAX',color:'#c6ff00'}
};
const SHAPE_KINDS=['board_outline','fishtail','tear_out','wane'];
let edgeMarks=[];
function edgePanel(){return `<div id="edgeStudyPanel" class="edge-study"><div class="edge-study-header">Visual Evidence Trace</div><p id="edgeFocus"></p><p>${EDGE_STUDY_INSTRUCTIONS}</p><div class="edge-study-controls"><label>Reviewer<input id="edgeReviewer" placeholder="name"></label><label>Marker<select id="edgeKind">${Object.entries(EDGE_TYPES).map(([key,value])=>`<option value="${key}">${value.label}</option>`).join('')}</select></label><label>Severity<select id="edgeSeverity"><option value="1">1 - faint / doubtful</option><option value="2" selected>2 - visible</option><option value="3">3 - clear</option><option value="4">4 - severe / certain</option></select></label><button class="secondary" onclick="undoEdgeMark()">Undo Last</button><button class="danger" onclick="clearEdgeMarks()">Clear Board</button><button onclick="saveEdgeMarks()">Save Evidence</button></div><label>Observation<textarea id="edgeNotes" rows="2" placeholder="What you see, and what prevents or supports a confident call."></textarea></label><div id="edgeMarkCount" class="edge-instruction"></div><div class="edge-legend"><span><i style="background:#00e5ff"></i>board outline (click 3+ points around the boundary, closes into a shape)</span><span><i style="background:#00a884"></i>usable edge</span><span><i style="background:#d91b92"></i>fish tail (click 3+ points to trace the shape)</span><span><i style="background:#ff6b00"></i>tear-out</span><span><i style="background:#d5a500"></i>wane</span><span><i style="background:#1685e5"></i>lighting limit</span><span><i style="background:#7b8790"></i>machine occlusion</span><span><i style="background:#c6ff00"></i>max usable line (click 2 points for a straight cut boundary)</span></div></div>`}
function updateEdgePanel(){if(!EDGE_STUDY||selected===null)return;const b=boards[selected];document.getElementById('edgeFocus').textContent=b.study_context||'Mark visual evidence on the raw paired image.';document.getElementById('edgeMarkCount').textContent=`${edgeMarks.length} marker(s). Click successive points with the same marker type to trace that boundary or defect (outline/fish tail/tear-out/wane close into a filled shape at 3+ points; max usable line stays a straight line).`}
function edgeColor(kind,severity){const palette={board_outline:['#e8feff','#9df3f7','#00e5ff','#007a85'],usable_edge:['#b7ead9','#58c9a9','#00a884','#066a58'],fishtail:['#f8c8e5','#ec75b8','#d91b92','#8e145d'],tear_out:['#ffd7ad','#ffad52','#ff6b00','#b93800'],wane:['#fbf0ad','#eac94c','#d5a500','#826200'],lighting_limit:['#bedfff','#69aff4','#1685e5','#0759a5'],machine_occlusion:['#d2d7da','#aab4ba','#7b8790','#47535c'],max_usable_line:['#f2ffb0','#dcff4d','#c6ff00','#7a9900']};const colors=palette[kind]||palette.lighting_limit;return colors[Math.max(1,Math.min(4,Number(severity)||2))-1]}
function renderEdgeMarks(){const img=document.getElementById('profile'),layer=document.getElementById('markerLayer');if(selected===null||!img.naturalWidth){layer.hidden=true;return}const half=img.naturalWidth/2,items=[];for(const side of ['left','right'])for(const kind of Object.keys(EDGE_TYPES)){const group=edgeMarks.filter(mark=>mark.side===side&&mark.kind===kind);if(group.length<2)continue;const points=group.map(mark=>`${(side==='right'?half:0)+Number(mark.x)},${Number(mark.y)}`),severity=Math.max(...group.map(mark=>Number(mark.severity)||2)),color=edgeColor(kind,severity);if(kind==='max_usable_line'){items.push(`<polyline points="${points.join(' ')}" fill="none" stroke="${color}" stroke-width="6" opacity=".95"/>`)}else if(SHAPE_KINDS.includes(kind)&&group.length>=3){items.push(`<polygon points="${points.join(' ')}" fill="${color}" fill-opacity="0.22" stroke="${color}" stroke-width="4" stroke-dasharray="10 7" opacity=".9"/>`)}else{items.push(`<polyline points="${points.join(' ')}" fill="none" stroke="${color}" stroke-width="4" stroke-dasharray="10 7" opacity=".85"/>`)}}edgeMarks.forEach(mark=>{const x=(mark.side==='right'?half:0)+Number(mark.x),y=Number(mark.y),style=EDGE_TYPES[mark.kind]||EDGE_TYPES.lighting_limit,severity=Number(mark.severity)||2,color=edgeColor(mark.kind,severity),radius=mark.kind==='max_usable_line'?4:5+severity*2;items.push(`<circle cx="${x}" cy="${y}" r="${radius}" fill="${color}" stroke="#111" stroke-width="3"/><text x="${x+radius+5}" y="${y-radius-4}" fill="${color}" style="font-size:18px">${style.short} ${severity}</text>`)});layer.setAttribute('viewBox',`0 0 ${img.naturalWidth} ${img.naturalHeight}`);layer.innerHTML=items.join('');layer.hidden=items.length===0}
function undoEdgeMark(){if(!EDGE_STUDY)return;edgeMarks.pop();updateEdgePanel();renderEdgeMarks()}
function clearEdgeMarks(){if(!EDGE_STUDY)return;edgeMarks=[];updateEdgePanel();renderEdgeMarks()}
async function saveEdgeMarks(){if(!EDGE_STUDY||selected===null)return;const b=boards[selected],payload={reviewer:document.getElementById('edgeReviewer').value,notes:document.getElementById('edgeNotes').value,marks:edgeMarks};const r=await fetch('/edge-annotation/'+b.board,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),d=await r.json();document.getElementById('notice').textContent=d.ok?'Evidence saved':'Save failed: '+d.error;if(d.ok)b.edge_annotation=d.annotation}
if(EDGE_STUDY){
  document.body.classList.add('edge-study-mode');
  document.querySelector('header h1').textContent='Edge Evidence Study';
  document.querySelector('header p').textContent='Ten documented fish-tail and tear-out examples. Neutral saw positions only; mark what the image actually supports.';
  document.querySelector('.summary').textContent='10 documented edge cases. Save each board before selecting the next one.';
  document.querySelector('.image-wrap').insertAdjacentHTML('beforebegin',edgePanel());
  visibleComparisons=new Set();
  render=function(){if(selected===null)return;const b=boards[selected],img=document.getElementById('profile'),useSeverity=view==='severity'&&b.severity_image;img.src=(useSeverity?('/frames/'+b.severity_image):(b.profile_url||''))+'?v='+Date.now();document.getElementById('gradingBtn').classList.remove('active');document.getElementById('fullBtn').classList.toggle('active',!useSeverity);document.getElementById('severityBtn').classList.toggle('active',useSeverity)};
  renderMarkers=renderEdgeMarks;
  showBoard=function(i,row){document.querySelectorAll('tr.active').forEach(x=>x.classList.remove('active'));row.classList.add('active');selected=i;const b=boards[i],annotation=b.edge_annotation||{};edgeMarks=Array.isArray(annotation.marks)?annotation.marks.map(mark=>({...mark})):[];document.getElementById('title').textContent='Board '+String(b.board).padStart(4,'0')+' - evidence trace';document.getElementById('meta').textContent='Neutral raw pair with calibrated saw positions. Mark the visible boundary, defect onset, and any imaging limitation.';document.getElementById('edgeReviewer').value=annotation.reviewer||'';document.getElementById('edgeNotes').value=annotation.notes||'';document.getElementById('grade').style.display='none';document.getElementById('comparePanel').hidden=true;document.getElementById('profile').hidden=false;document.getElementById('empty').hidden=true;updateEdgePanel();render()};
  document.querySelector('.image-stage').addEventListener('click',event=>{if(selected===null)return;const img=document.getElementById('profile');if(!img.naturalWidth)return;const rect=img.getBoundingClientRect(),x=(event.clientX-rect.left)*img.naturalWidth/rect.width,y=(event.clientY-rect.top)*img.naturalHeight/rect.height,half=img.naturalWidth/2;edgeMarks.push({kind:document.getElementById('edgeKind').value,severity:Number(document.getElementById('edgeSeverity').value),side:x<half?'left':'right',x:Math.round((x<half?x:x-half)*10)/10,y:Math.round(y*10)/10});updateEdgePanel();renderEdgeMarks()});
  function cycleEdgeKind(dir){const sel=document.getElementById('edgeKind');if(!sel)return;sel.selectedIndex=(sel.selectedIndex+dir+sel.options.length)%sel.options.length}
  function cycleEdgeSeverity(){const sel=document.getElementById('edgeSeverity');if(!sel)return;sel.selectedIndex=(sel.selectedIndex+1)%sel.options.length}
  // Ctrl+T is reserved by every major browser for "new tab" and never reaches page JS,
  // so Alt+T is wired to the same action as a shortcut that actually fires.
  document.addEventListener('keydown',event=>{
    if(!EDGE_STUDY||selected===null)return;
    const tag=(event.target.tagName||'').toLowerCase();
    if(tag==='input'||tag==='textarea'||tag==='select')return;
    if(!(event.ctrlKey||event.metaKey||event.altKey))return;
    const key=event.key.toLowerCase();
    if(key==='t'){event.preventDefault();cycleEdgeKind(event.shiftKey?-1:1)}
    else if(key==='g'){event.preventDefault();cycleEdgeSeverity()}
    else if(key==='z'){event.preventDefault();undoEdgeMark()}
  });
}
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
    comparison = comparison_grades()
    edge_config = load_edge_study_config()
    edge_context = {int(item["board"]): item for item in edge_config.get("boards", [])}
    if EDGE_STUDY:
        data = [row for row in data if int(row["board"]) in edge_context]
        data.sort(key=lambda row: list(edge_context).index(int(row["board"])))
    edge_annotations = load_edge_annotations()
    for row in data:
        board = int(row["board"])
        source_board = int(row.get("source_board") or board)
        roots = source_frame_roots()
        frames = roots.get(row.get("source_key", ""), SESSION / "frames")
        severity = render_severity_overlay(source_board, frames)
        row["severity_image"] = frame_url(row, severity.name) if severity else ""
        if EDGE_STUDY:
            study_image = render_edge_study_image(board, source_board, frames)
            row["profile_url"] = f"/study/{study_image.name}" if study_image else ""
            row["grading_image"] = ""
            row["study_context"] = edge_context.get(board, {}).get("focus", "")
        else:
            calibrated = render_calibrated_profile(source_board, row.get("actual_word"), frames)
            profile_name = calibrated.name if calibrated else Path(
                row.get("profile_image") or f"board_{source_board:04d}_profile.jpg").name
            row["profile_image"] = frame_url(row, profile_name)
            row["profile_url"] = f"/frames/{row['profile_image']}"
        if not EDGE_STUDY:
            grading_name = Path(row.get("grading_image") or
                                f"board_{source_board:04d}_grading.jpg").name
            # Live capture writes a full profile overlay; imported calibration
            # sessions may additionally have a focused grading crop.
            row["grading_image"] = frame_url(row, grading_name) if (frames / grading_name).exists() else ""
        row["grade"] = grades.get(str(row["board"]))
        board_key = str(row["board"])
        row["comparison"] = {
            "operator": {"word": row.get("actual_word", "")},
            **{
                key: {"word": record.get("graded_word", ""),
                      "notes": record.get("notes", "")}
                for key, records in comparison.items()
                for record in [records.get(board_key, {})]
            },
        }
        if EDGE_STUDY:
            # Keep fresh evidence marking blind: the page must not carry the
            # operator/PLC word or prior comparison streams in its payload.
            row["commit_word"] = ""
            row["actual_word"] = ""
            row["match"] = ""
            row["comparison"] = {}
        row["edge_annotation"] = edge_annotations.get(str(board), {})
    return data


def grades_path():
    return SESSION / "reviews" / f"{REVIEW_ROLE}.json"


def load_grades():
    path = grades_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_grades(grades):
    path = grades_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(grades, indent=2), encoding="utf-8")
    tmp.replace(path)


@app.get("/")
def index():
    data = rows()
    return render_template_string(PAGE, session_name=SESSION.name, review=REVIEW_ROLES[REVIEW_ROLE], count=len(data), rows=data,
                                  rows_json=json.dumps(data),
                                  review_lines=json.dumps(load_review_saw_lines()),
                                  review_json=json.dumps(REVIEW_ROLES[REVIEW_ROLE]),
                                  comparison_json=json.dumps(COMPARISON_SOURCES),
                                  edge_study=EDGE_STUDY,
                                  edge_study_instructions=load_edge_study_config().get("instructions", ""))


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


@app.get("/study/<path:name>")
def study_image(name):
    if Path(name).name != name:
        abort(404)
    return send_from_directory(SESSION / "annotations" / "edge_study_images", name)


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


@app.post("/edge-annotation/<int:board>")
def edge_annotation(board):
    if not EDGE_STUDY:
        return jsonify(ok=False, error="edge study mode is not enabled"), 400
    if board not in {int(item["board"]) for item in load_edge_study_config().get("boards", [])}:
        return jsonify(ok=False, error="board is not in the edge study"), 404
    try:
        payload = request.get_json(force=True)
        raw_marks = payload.get("marks", [])
        if not isinstance(raw_marks, list) or len(raw_marks) > 40:
            return jsonify(ok=False, error="marks must contain 0 to 40 entries"), 400
        allowed = {"usable_edge", "fishtail", "tear_out", "wane",
                   "lighting_limit", "machine_occlusion",
                   "board_outline", "max_usable_line"}
        marks = []
        for mark in raw_marks:
            kind = str(mark.get("kind") or "")
            if kind not in allowed:
                return jsonify(ok=False, error="invalid marker type"), 400
            side = str(mark.get("side") or "")
            if side not in {"left", "right"}:
                return jsonify(ok=False, error="invalid camera side"), 400
            x, y = float(mark.get("x")), float(mark.get("y"))
            if not 0 <= x <= 5000 or not 0 <= y <= 3000:
                return jsonify(ok=False, error="marker is outside the image"), 400
            severity = int(mark.get("severity", 2))
            if not 1 <= severity <= 4:
                return jsonify(ok=False, error="severity must be 1 to 4"), 400
            marks.append({"kind": kind, "side": side, "x": round(x, 1), "y": round(y, 1),
                          "severity": severity})
        record = {"reviewer": str(payload.get("reviewer") or "").strip(),
                  "notes": str(payload.get("notes") or "").strip(),
                  "marks": marks,
                  "updated_at": datetime.now().isoformat(timespec="seconds")}
        all_annotations = load_edge_annotations()
        all_annotations[str(board)] = record
        save_edge_annotations(all_annotations)
        return jsonify(ok=True, annotation=record)
    except (TypeError, ValueError) as exc:
        return jsonify(ok=False, error=f"invalid marker: {exc}"), 400
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
    global SESSION, REVIEW_ROLE, EDGE_STUDY
    ap = argparse.ArgumentParser(description="Review/export a completed shadow session")
    ap.add_argument("session", nargs="?", help="session directory; default is latest")
    ap.add_argument("--port", type=int, default=5055)
    ap.add_argument("--role", choices=sorted(REVIEW_ROLES), default="operator",
                    help="independent review stream; each role saves to its own file")
    ap.add_argument("--edge-study", action="store_true",
                    help="show the focused ten-board visual-evidence annotation study")
    args = ap.parse_args()
    REVIEW_ROLE = args.role
    EDGE_STUDY = args.edge_study
    if args.session:
        SESSION = Path(args.session).resolve()
    else:
        sessions = sorted((ROOT / "shadow_sessions").glob("*"), key=lambda p: p.stat().st_mtime)
        SESSION = sessions[-1] if sessions else None
    if not SESSION or not (SESSION / "boards.csv").exists():
        raise SystemExit("No completed shadow session with boards.csv found.")
    mode = "edge study" if EDGE_STUDY else "review"
    print(f"Shadow {mode}: http://127.0.0.1:{args.port}  session={SESSION}")
    app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
