"""
api.py — REST API for PiVisionCapture management and control.

Provides endpoints for:
- Terminal command execution
- App lifecycle control (start/stop/status)
- Log streaming
- Configuration management
- Health checks

Run: python api.py [--port 5000]
"""

import argparse
import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

import cv2

import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)-15s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("api")

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max

# Global app process handle
_app_process = None
_app_lock = threading.Lock()


@app.route("/", methods=["GET"])
def dashboard():
    """Serve the dashboard HTML."""
    try:
        dashboard_file = Path.home() / "PiVisionCapture" / "dashboard.html"
        if dashboard_file.exists():
            return send_file(str(dashboard_file), mimetype="text/html")
        return jsonify({"error": "dashboard.html not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/capture-button", methods=["GET"])
def capture_button():
    """Serve the capture control button page."""
    try:
        button_file = Path.home() / "PiVisionCapture" / "capture_control.html"
        if button_file.exists():
            return send_file(str(button_file), mimetype="text/html")
        return jsonify({"error": "capture_control.html not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/left-camera", methods=["GET"])
def left_camera():
    """Serve the left camera live view page."""
    try:
        camera_file = Path.home() / "PiVisionCapture" / "left_camera.html"
        if camera_file.exists():
            return send_file(str(camera_file), mimetype="text/html")
        return jsonify({"error": "left_camera.html not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/capture", methods=["POST"])
def capture_board():
    """Capture a frame from specified camera and save it."""
    try:
        data = request.get_json() or {}
        board_id = data.get("board_id", f"board_{int(time.time())}")
        base_path = data.get("base_path", str(Path.home() / "PiVisionCapture" / "captures"))
        camera = data.get("camera", "right")  # "right" or "left"

        if camera == "left":
            rtsp_url = os.environ.get("CAM_LEFT_RTSP_URL")
        else:
            rtsp_url = os.environ.get("CAM_RIGHT_RTSP_URL")

        if not rtsp_url:
            return jsonify({"error": f"RTSP URL not configured for camera '{camera}' (set CAM_LEFT_RTSP_URL / CAM_RIGHT_RTSP_URL)"}), 500

        logger.info("[CAPTURE] Attempting capture for %s", board_id)

        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            return jsonify({"error": "Failed to connect to camera"}), 500

        ok, frame = cap.read()
        cap.release()

        if not ok:
            return jsonify({"error": "Failed to read frame from camera"}), 500

        ts = datetime.now()
        img_path = storage.save_frame(frame, ts, board_id, base_path, 95, rtsp_url)

        logger.info("[CAPTURE] ✓ Saved %s", img_path)

        # Convert absolute path to relative path for /image endpoint
        captures_base = Path.home() / "PiVisionCapture" / "captures"
        rel_path = Path(img_path).relative_to(captures_base)
        image_url = f"/image/{rel_path}"

        return jsonify({
            "status": "captured",
            "board_id": board_id,
            "file": str(img_path),
            "image_url": image_url,
            "timestamp": ts.isoformat(),
        }), 201

    except Exception as e:
        logger.error("[CAPTURE] Failed: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


def _run_command(cmd: str, timeout: int = 10) -> dict:
    """Execute a shell command and return output."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(Path.home() / "PiVisionCapture"),
        )
        return {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
        }
    except Exception as e:
        return {
            "success": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e),
        }


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "app_running": _app_process is not None and _app_process.poll() is None,
    })


@app.route("/command", methods=["POST"])
def run_command():
    """Execute an arbitrary shell command."""
    data = request.get_json() or {}
    cmd = data.get("command", "").strip()

    if not cmd:
        return jsonify({"error": "No command provided"}), 400

    logger.info(f"[CMD] Executing: {cmd}")
    result = _run_command(cmd, timeout=data.get("timeout", 30))
    logger.info(f"[CMD] Exit code: {result['exit_code']}")

    return jsonify(result)


@app.route("/app/start", methods=["POST"])
def start_app():
    """Start the main.py application."""
    global _app_process

    with _app_lock:
        if _app_process is not None and _app_process.poll() is None:
            return jsonify({"error": "App is already running"}), 409

        try:
            repo_path = Path.home() / "PiVisionCapture"
            cmd = f"cd {repo_path} && python main.py --config config.yaml"

            _app_process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            logger.info(f"[APP] Started with PID {_app_process.pid}")
            return jsonify({
                "status": "started",
                "pid": _app_process.pid,
                "timestamp": datetime.now().isoformat(),
            })
        except Exception as e:
            logger.error(f"[APP] Failed to start: {e}")
            return jsonify({"error": str(e)}), 500


@app.route("/app/stop", methods=["POST"])
def stop_app():
    """Stop the main.py application."""
    global _app_process

    with _app_lock:
        if _app_process is None or _app_process.poll() is not None:
            return jsonify({"error": "App is not running"}), 409

        try:
            _app_process.terminate()
            _app_process.wait(timeout=5)
            logger.info("[APP] Stopped gracefully")
            _app_process = None
            return jsonify({
                "status": "stopped",
                "timestamp": datetime.now().isoformat(),
            })
        except subprocess.TimeoutExpired:
            _app_process.kill()
            logger.warning("[APP] Killed forcefully")
            _app_process = None
            return jsonify({
                "status": "killed",
                "timestamp": datetime.now().isoformat(),
            })
        except Exception as e:
            logger.error(f"[APP] Failed to stop: {e}")
            return jsonify({"error": str(e)}), 500


@app.route("/app/status", methods=["GET"])
def app_status():
    """Get application status."""
    if _app_process is None:
        return jsonify({
            "running": False,
            "pid": None,
        })

    poll_result = _app_process.poll()
    return jsonify({
        "running": poll_result is None,
        "pid": _app_process.pid if _app_process else None,
        "exit_code": poll_result,
    })


@app.route("/logs", methods=["GET"])
def get_logs():
    """Get recent logs from storage directory."""
    try:
        repo_path = Path.home() / "PiVisionCapture"
        log_file = repo_path / "app.log"

        if not log_file.exists():
            return jsonify({"logs": [], "note": "No log file yet"})

        lines = log_file.read_text().splitlines()
        limit = request.args.get("limit", 100, type=int)

        return jsonify({
            "logs": lines[-limit:],
            "total_lines": len(lines),
            "displayed": min(limit, len(lines)),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/config", methods=["GET"])
def get_config():
    """Get current configuration."""
    try:
        repo_path = Path.home() / "PiVisionCapture"
        config_file = repo_path / "config.yaml"

        if not config_file.exists():
            return jsonify({"error": "config.yaml not found"}), 404

        return jsonify({
            "config": config_file.read_text(),
            "path": str(config_file),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/config", methods=["POST"])
def update_config():
    """Update configuration (careful!)."""
    try:
        data = request.get_json() or {}
        config_content = data.get("config", "").strip()

        if not config_content:
            return jsonify({"error": "No config provided"}), 400

        repo_path = Path.home() / "PiVisionCapture"
        config_file = repo_path / "config.yaml"

        # Backup old config
        backup_file = config_file.with_suffix(".yaml.backup")
        if config_file.exists():
            backup_file.write_text(config_file.read_text())
            logger.info(f"[CONFIG] Backed up to {backup_file}")

        config_file.write_text(config_content)
        logger.info("[CONFIG] Updated")

        return jsonify({
            "status": "updated",
            "backup": str(backup_file),
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error(f"[CONFIG] Failed to update: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/image/<path:filepath>", methods=["GET"])
def serve_image(filepath):
    """Serve captured image files."""
    try:
        captures_path = Path.home() / "PiVisionCapture" / "captures"
        full_path = captures_path / filepath

        # Security: prevent directory traversal
        if not full_path.resolve().is_relative_to(captures_path.resolve()):
            return jsonify({"error": "Access denied"}), 403

        if not full_path.exists():
            return jsonify({"error": "File not found"}), 404

        return send_file(str(full_path), mimetype="image/jpeg")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/files", methods=["GET"])
def list_files():
    """List captures and files in the project."""
    try:
        repo_path = Path.home() / "PiVisionCapture"
        captures_path = Path("/data/captures")

        files = {
            "project": list(repo_path.glob("*.py")) if repo_path.exists() else [],
            "captures": list(captures_path.rglob("*")) if captures_path.exists() else [],
        }

        return jsonify({
            "project_files": [str(f.name) for f in files["project"]],
            "capture_count": len([f for f in files["captures"] if f.is_file()]),
            "captures_path": str(captures_path),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PiVisionCapture API Server")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    args = parser.parse_args()

    logger.info(f"Starting API on {args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
