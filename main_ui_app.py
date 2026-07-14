"""main_ui_app.py — Layout scaffold for the future vision_host_app.py "main" UI.

LAYOUT ONLY. No live PLC/camera/data wiring yet — every screen renders mock/
skeleton content so the navigation and visual structure can be reviewed before
anything is populated. Read-only, standalone Flask app; does not import or
touch vision_host_app.py or shadow_capture_app.py, so it can't collide with
work in progress on those files.

Run:
  python main_ui_app.py [--port 5070]
"""

import argparse

from flask import Flask, render_template_string

app = Flask(__name__)

NAV = [
    ("overview", "Overview", "/"),
    ("live", "Live / Runtime", "/live"),
    ("calibration", "Calibration", "/calibration"),
    ("review", "Grading & Review", "/review"),
    ("manual", "Manual Controls", "/manual"),
    ("settings", "Settings", "/settings"),
    ("daily", "Daily Stats", "/stats/daily"),
    ("monthly", "Monthly Stats", "/stats/monthly"),
]

SHELL = """<!doctype html>
<html><head><meta charset="utf-8"><title>PiVisionCapture — {{ title }}</title>
<style>
:root{--bg:#f3f5f6;--panel:#fff;--ink:#17212b;--sub:#52616a;--line:#d7dde0;--accent:#0d766e;--accent-ink:#fff;
      --warn:#b8860b;--bad:#bd3d35;--good:#087f5b;--head:#17212b;--head-ink:#b8c5cc}
*{box-sizing:border-box}
body{margin:0;font-family:Segoe UI,Arial,sans-serif;color:var(--ink);background:var(--bg)}
header{background:var(--head);color:#fff;padding:14px 24px;display:flex;align-items:center;justify-content:space-between}
header .brand{font-weight:700;font-size:16px;letter-spacing:.02em}
header .brand span{color:var(--head-ink);font-weight:400;margin-left:10px;font-size:13px}
.status-strip{display:flex;gap:18px;font-size:12px;color:var(--head-ink)}
.status-strip .dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:1px}
.dot.ok{background:#3ecf8e}.dot.warn{background:#e0a63e}.dot.bad{background:#e05f5f}.dot.off{background:#5a6570}
.layout{display:grid;grid-template-columns:220px 1fr;min-height:calc(100vh - 53px)}
nav{background:#1d2733;padding:18px 0;border-right:1px solid #0f151b}
nav a{display:block;padding:11px 22px;color:#c3cdd4;text-decoration:none;font-size:14px;border-left:3px solid transparent}
nav a:hover{background:#25313f;color:#fff}
nav a.active{background:#25313f;color:#fff;border-left-color:var(--accent);font-weight:600}
main{padding:28px 32px;overflow:auto}
h1{font-size:20px;margin:0 0 4px}
.subtitle{color:var(--sub);font-size:13px;margin-bottom:22px}
.mock-banner{background:#fff6e0;border:1px solid #e8d18a;color:#7a5c00;font-size:12.5px;padding:8px 14px;
             border-radius:6px;margin-bottom:22px;display:inline-block}
.grid{display:grid;gap:16px}
.grid.cols-4{grid-template-columns:repeat(4,1fr)}
.grid.cols-3{grid-template-columns:repeat(3,1fr)}
.grid.cols-2{grid-template-columns:repeat(2,1fr)}
@media(max-width:1000px){.grid.cols-4,.grid.cols-3{grid-template-columns:repeat(2,1fr)}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:18px}
.card h3{margin:0 0 4px;font-size:13px;color:var(--sub);font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.stat{font-size:30px;font-weight:700;margin:6px 0 2px}
.stat.small{font-size:22px}
.stat-sub{font-size:12px;color:var(--sub)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:20px;margin-bottom:20px}
.panel h2{font-size:15px;margin:0 0 14px;padding-bottom:10px;border-bottom:1px solid var(--line)}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--sub);background:#f7f9f9;padding:9px 10px;font-weight:600}
td{padding:9px 10px;border-top:1px solid #edf0f1}
.badge{display:inline-block;padding:2px 9px;border-radius:11px;font-size:11.5px;font-weight:600}
.badge.ok{background:#e3f6ee;color:var(--good)}
.badge.warn{background:#fdf1de;color:var(--warn)}
.badge.bad{background:#fbe8e7;color:var(--bad)}
.badge.off{background:#eceff1;color:var(--sub)}
.skeleton{background:linear-gradient(90deg,#eef1f2 25%,#e4e8ea 37%,#eef1f2 63%);background-size:400% 100%;
          animation:sk 1.6s ease-in-out infinite;border-radius:4px}
@keyframes sk{0%{background-position:100% 50%}100%{background-position:0 50%}}
.chart-skel{height:180px}
.thumb-skel{height:110px;border-radius:6px}
.btn{display:inline-block;padding:9px 16px;border-radius:6px;border:1px solid var(--line);background:#fff;
     color:var(--ink);font-size:13px;font-weight:600;cursor:pointer;margin-right:10px}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.btn.danger{background:#fff;border-color:var(--bad);color:var(--bad)}
.btn[disabled]{opacity:.45;cursor:not-allowed}
.form-row{display:grid;grid-template-columns:200px 1fr;gap:14px;align-items:center;padding:10px 0;
          border-bottom:1px solid #f0f2f3}
.form-row label{font-size:13px;color:var(--sub)}
.form-row input,.form-row select{padding:7px 10px;border:1px solid var(--line);border-radius:5px;font-size:13px;
                                  max-width:340px;width:100%}
.hint{font-size:11.5px;color:var(--sub);margin-top:3px}
.camera-tabs{display:flex;gap:8px;margin-bottom:16px}
.camera-tab{padding:7px 16px;border-radius:6px;background:#eef1f2;font-size:13px;font-weight:600;color:var(--sub)}
.camera-tab.active{background:var(--accent);color:#fff}
.two-col{display:grid;grid-template-columns:1.3fr 1fr;gap:20px}
.legend-note{font-size:12px;color:var(--sub);margin-top:8px}
.section-divider{margin:28px 0 18px;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--sub);
                  font-weight:700}
</style></head><body>
<header>
  <div class="brand">PiVisionCapture <span>{{ title }}</span></div>
  <div class="status-strip">
    <span><i class="dot off"></i>PLC — layout only</span>
    <span><i class="dot off"></i>Camera 1 — layout only</span>
    <span><i class="dot off"></i>Camera 2 — layout only</span>
    <span><i class="dot off"></i>Line — layout only</span>
  </div>
</header>
<div class="layout">
  <nav>
    {% for key, label, href in nav %}
    <a href="{{ href }}" class="{{ 'active' if key==active else '' }}">{{ label }}</a>
    {% endfor %}
  </nav>
  <main>
    <h1>{{ title }}</h1>
    <div class="subtitle">{{ subtitle }}</div>
    <div class="mock-banner">Layout preview — no live PLC, camera, or session data wired up yet.</div>
    {{ content|safe }}
  </main>
</div>
</body></html>"""


def render(active, title, subtitle, content):
    return render_template_string(SHELL, nav=NAV, active=active, title=title, subtitle=subtitle, content=content)


@app.get("/")
def overview():
    content = """
    <div class="grid cols-4">
      <div class="card"><h3>Line status</h3><div class="stat small">—</div><div class="stat-sub">running / stopped</div></div>
      <div class="card"><h3>Boards today</h3><div class="stat">—</div><div class="stat-sub">captured / compared</div></div>
      <div class="card"><h3>Unmatched rate</h3><div class="stat small">—</div><div class="stat-sub">last session</div></div>
      <div class="card"><h3>Camera health</h3><div class="stat small">—/—</div><div class="stat-sub">connected</div></div>
    </div>

    <div class="section-divider">Active session</div>
    <div class="panel">
      <div class="skeleton" style="height:18px;width:280px;margin-bottom:10px"></div>
      <div class="skeleton" style="height:14px;width:420px;margin-bottom:18px"></div>
      <table>
        <thead><tr><th>Board</th><th>Time</th><th>Applied</th><th>Result</th><th>Thumbnail</th></tr></thead>
        <tbody>
          {% for _ in range(4) %}
          <tr>
            <td><div class="skeleton" style="height:12px;width:40px"></div></td>
            <td><div class="skeleton" style="height:12px;width:70px"></div></td>
            <td><div class="skeleton" style="height:12px;width:90px"></div></td>
            <td><span class="badge off">—</span></td>
            <td><div class="skeleton thumb-skel" style="width:70px;height:40px"></div></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <div class="section-divider">Warnings</div>
    <div class="panel">
      <table>
        <tbody>
          <tr><td style="width:90px"><span class="badge warn">example</span></td><td>Placeholder: e.g. "empty-deck reference is stale" would surface here</td></tr>
          <tr><td><span class="badge bad">example</span></td><td>Placeholder: e.g. "camera LEFT disconnected" would surface here</td></tr>
        </tbody>
      </table>
    </div>
    """
    return render("overview", "Overview", "At-a-glance system and session status.", content)


@app.get("/live")
def live():
    content = """
    <div class="two-col">
      <div class="panel">
        <h2>Most recent capture</h2>
        <div class="skeleton" style="height:340px"></div>
        <div class="legend-note">Latest board_XXXX_profile.jpg / calibrated overlay would render here.</div>
      </div>
      <div class="panel">
        <h2>Session counters</h2>
        <div class="grid cols-2">
          <div class="card"><h3>Triggers</h3><div class="stat small">—</div></div>
          <div class="card"><h3>Compared</h3><div class="stat small">—</div></div>
          <div class="card"><h3>FIFO depth</h3><div class="stat small">—</div></div>
          <div class="card"><h3>Unmatched</h3><div class="stat small">—</div></div>
        </div>
        <div class="section-divider">Connection health</div>
        <table>
          <tr><td>PLC round-trip</td><td><div class="skeleton" style="height:12px;width:60px"></div></td></tr>
          <tr><td>Camera 1 last frame</td><td><div class="skeleton" style="height:12px;width:60px"></div></td></tr>
          <tr><td>Camera 2 last frame</td><td><div class="skeleton" style="height:12px;width:60px"></div></td></tr>
        </table>
      </div>
    </div>

    <div class="section-divider">Live board log (this session)</div>
    <div class="panel">
      <table>
        <thead><tr><th>Board</th><th>Triggered</th><th>Applied word</th><th>Frame offsets</th><th>Status</th></tr></thead>
        <tbody>
          {% for _ in range(6) %}
          <tr>
            <td><div class="skeleton" style="height:12px;width:36px"></div></td>
            <td><div class="skeleton" style="height:12px;width:70px"></div></td>
            <td><div class="skeleton" style="height:12px;width:90px"></div></td>
            <td><div class="skeleton" style="height:12px;width:110px"></div></td>
            <td><span class="badge off">—</span></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    """
    return render("live", "Live / Runtime", "Current session, updating in real time once wired up.", content)


@app.get("/calibration")
def calibration():
    content = """
    <div class="camera-tabs">
      <div class="camera-tab active">Camera 1</div>
      <div class="camera-tab">Camera 2</div>
      <div class="camera-tab" style="opacity:.5">+ Add camera</div>
    </div>

    <div class="two-col">
      <div class="panel">
        <h2>Live / reference frame — click known saw positions</h2>
        <div class="skeleton" style="height:380px"></div>
        <div class="legend-note">Clicked points would tag with saw mm value, build the px/mm + roll fit.</div>
      </div>
      <div class="panel">
        <h2>Camera info</h2>
        <div class="form-row"><label>Detected resolution</label><div class="skeleton" style="height:14px;width:120px"></div></div>
        <div class="form-row"><label>RTSP URL</label><input placeholder="rtsp://..." disabled></div>
        <div class="section-divider">Fit result</div>
        <table>
          <tr><td>px per mm</td><td><div class="skeleton" style="height:12px;width:70px"></div></td></tr>
          <tr><td>Origin (mm)</td><td><div class="skeleton" style="height:12px;width:70px"></div></td></tr>
          <tr><td>Roll correction</td><td><div class="skeleton" style="height:12px;width:70px"></div></td></tr>
          <tr><td>Max residual</td><td><span class="badge off">— px</span> <span class="legend-note">(target &lt;3px)</span></td></tr>
        </table>
        <div style="margin-top:18px">
          <button class="btn" disabled>Add calibration point</button>
          <button class="btn" disabled>Fit roll</button>
          <button class="btn primary" disabled>Save calibration</button>
        </div>
      </div>
    </div>

    <div class="section-divider">Reference points logged</div>
    <div class="panel">
      <table>
        <thead><tr><th>Saw</th><th>mm from fence</th><th>Pixel x</th><th>Residual</th></tr></thead>
        <tbody>
          {% for _ in range(3) %}
          <tr>
            <td><div class="skeleton" style="height:12px;width:50px"></div></td>
            <td><div class="skeleton" style="height:12px;width:50px"></div></td>
            <td><div class="skeleton" style="height:12px;width:50px"></div></td>
            <td><div class="skeleton" style="height:12px;width:40px"></div></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <div class="section-divider">Phase 2 (not in this pass)</div>
    <div class="panel">
      <p style="color:var(--sub);font-size:13px;margin:0">Lens/fisheye undistortion — checkerboard-pattern camera
      calibration, done once per camera, separate flow from saw-click calibration above.</p>
    </div>
    """
    return render("calibration", "Calibration", "Per-camera saw-position and roll calibration.", content)


@app.get("/review")
def review():
    content = """
    <div class="panel">
      <h2>Sessions</h2>
      <table>
        <thead><tr><th>Session</th><th>Boards</th><th>Unmatched</th><th>Started</th><th></th></tr></thead>
        <tbody>
          {% for _ in range(3) %}
          <tr>
            <td><div class="skeleton" style="height:12px;width:220px"></div></td>
            <td><div class="skeleton" style="height:12px;width:40px"></div></td>
            <td><div class="skeleton" style="height:12px;width:40px"></div></td>
            <td><div class="skeleton" style="height:12px;width:90px"></div></td>
            <td><button class="btn" disabled>Open</button></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    <div class="legend-note">This screen would link out to (or embed) the existing per-board grading workflow
    already running in <code>shadow_review_app.py</code> — not rebuilt here, just linked.</div>
    """
    return render("review", "Grading & Review", "Existing per-board grading workflow.", content)


@app.get("/manual")
def manual():
    content = """
    <div class="mock-banner" style="background:#fbe8e7;border-color:#e3a6a2;color:var(--bad)">
      Scope: controls over the vision system only — capture/session/mode. No saw or PLC write commands live here.
    </div>
    <div class="grid cols-3">
      <div class="card">
        <h3>Session</h3>
        <button class="btn primary" disabled>Start session</button>
        <button class="btn" disabled>Pause</button>
        <button class="btn danger" disabled>Stop</button>
      </div>
      <div class="card">
        <h3>Test capture</h3>
        <button class="btn" disabled>Trigger test capture</button>
        <div class="hint">Grabs one L/R pair without waiting for a real board — for calibration checks.</div>
      </div>
      <div class="card">
        <h3>Mode</h3>
        <div class="form-row" style="grid-template-columns:1fr auto">
          <label>Capture-only mode</label>
          <input type="checkbox" checked disabled>
        </div>
        <div class="hint">Off = attempt real measurement/scoring (gated, not yet trusted).</div>
      </div>
      <div class="card">
        <h3>Reconnect</h3>
        <button class="btn" disabled>Reconnect PLC</button>
        <button class="btn" disabled>Reconnect cameras</button>
      </div>
    </div>
    """
    return render("manual", "Manual Controls", "Vision-system controls only — not PLC/saw commands.", content)


@app.get("/settings")
def settings():
    content = """
    <div class="panel">
      <h2>Cameras</h2>
      <div class="form-row"><label>Camera 1 name</label><input value="LEFT" disabled></div>
      <div class="form-row"><label>Camera 1 RTSP URL</label><input value="rtsp://..." disabled></div>
      <div class="form-row"><label>Camera 2 name</label><input value="RIGHT" disabled></div>
      <div class="form-row"><label>Camera 2 RTSP URL</label><input value="rtsp://..." disabled></div>
      <button class="btn" disabled style="margin-top:10px">+ Add camera</button>
    </div>
    <div class="panel">
      <h2>PLC connection</h2>
      <div class="form-row"><label>IP address</label><input value="192.168.3.151" disabled></div>
      <div class="form-row"><label>Rack / Slot</label><input value="0 / 1" disabled></div>
      <div class="form-row"><label>DB number</label><input value="1" disabled></div>
    </div>
    <div class="panel">
      <h2>Trigger / timing</h2>
      <div class="form-row"><label>Trigger min interval (s)</label><input value="2.0" disabled>
        <div class="hint" style="grid-column:2">Tuning this is the leading suspect for the UNMATCHED rate seen in recent sessions.</div></div>
      <div class="form-row"><label>Frame offset — Camera 1 (s)</label><input value="0.75" disabled></div>
      <div class="form-row"><label>Frame offset — Camera 2 (s)</label><input value="0.75" disabled></div>
    </div>
    <div class="panel">
      <h2>Mode</h2>
      <div class="form-row"><label>Capture-only</label><input type="checkbox" checked disabled></div>
    </div>
    """
    return render("settings", "Settings", "Configuration — a UI over the underlying YAML.", content)


def _stats_content(period_label):
    return f"""
    <div class="grid cols-4">
      <div class="card"><h3>Boards</h3><div class="stat">—</div></div>
      <div class="card"><h3>Unmatched rate</h3><div class="stat small">—</div></div>
      <div class="card"><h3>Agreement rate</h3><div class="stat small">—</div><div class="stat-sub">once measurement is trusted</div></div>
      <div class="card"><h3>Avg. board interval</h3><div class="stat small">—</div></div>
    </div>
    <div class="section-divider">Saw usage</div>
    <div class="panel"><div class="skeleton chart-skel"></div></div>
    <div class="section-divider">Trend over {period_label}</div>
    <div class="panel"><div class="skeleton chart-skel"></div></div>
    """


@app.get("/stats/daily")
def stats_daily():
    return render("daily", "Daily Stats", "Today's session rollups.", _stats_content("today"))


@app.get("/stats/monthly")
def stats_monthly():
    return render("monthly", "Monthly Stats", "Rollups and trend across the month.", _stats_content("the month"))


def main():
    ap = argparse.ArgumentParser(description="Layout-only scaffold for the main app UI")
    ap.add_argument("--port", type=int, default=5070)
    args = ap.parse_args()
    print(f"Main UI layout preview: http://127.0.0.1:{args.port}/")
    app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
