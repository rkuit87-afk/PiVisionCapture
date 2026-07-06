"""
trigger_handler.py — HTTP trigger server.

PLC (or browser/curl for PC testing) POSTs to /trigger to capture a frame.
Optional JSON body: {"board_id": "B123"} — defaults to "unknown".
GET /health for watchdog / connectivity check.
"""

import json
import logging
import queue
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

from camera_stream import get_latest_frame

logger = logging.getLogger(__name__)

_trigger_queue: queue.Queue = queue.Queue(maxsize=50)


def get_queue() -> queue.Queue:
    return _trigger_queue


class _Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # Route http.server access logs through our logger instead of stderr
        logger.debug("HTTP %s", format % args)

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"status": "ok"})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/trigger":
            self._respond(404, {"error": "not found"})
            return

        # Parse optional JSON body
        board_id = "unknown"
        length = int(self.headers.get("Content-Length", 0))
        if length:
            try:
                body = json.loads(self.rfile.read(length))
                board_id = body.get("board_id", "unknown") or "unknown"
            except Exception:
                pass

        frame = get_latest_frame()
        ts = datetime.now()

        if frame is None:
            logger.warning("[TRIGGER] No frame available yet — camera still connecting?")
            self._respond(503, {"error": "no frame available"})
            return

        try:
            _trigger_queue.put_nowait((frame, board_id, ts))
            ts_iso = ts.isoformat()
            logger.info("[TRIGGER] POST /trigger — board_id=%s at %s", board_id, ts_iso)
            self._respond(200, {"status": "queued", "board_id": board_id, "timestamp": ts_iso})
        except queue.Full:
            logger.warning("[TRIGGER] Queue full — storage may be lagging")
            self._respond(503, {"error": "queue full"})

    def _respond(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def start(http_port: int) -> tuple[threading.Thread, HTTPServer]:
    """Start the trigger server in a background thread."""
    server = _ThreadedHTTPServer(("", http_port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True, name="trigger-server")
    t.start()
    return t, server
