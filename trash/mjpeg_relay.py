"""
mjpeg_relay.py — Relay an RTSP camera as a live MJPEG stream viewable in any browser.

Completely independent of api.py / gpio_trigger.py. Reads the RTSP feed
continuously and serves it as multipart MJPEG.

Usage:
  python3 mjpeg_relay.py --rtsp "rtsp://user:pass@192.168.3.146/live1s1.sdp" --port 8090

Then open:  http://<pi-ip>:8090/
"""

import argparse
import threading
import time

import cv2
from flask import Flask, Response

app = Flask(__name__)

_frame_jpg = None
_lock = threading.Lock()


def reader(rtsp_url, fps_limit):
    global _frame_jpg
    min_interval = 1.0 / fps_limit
    while True:
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            time.sleep(3)
            continue
        last = 0.0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            now = time.time()
            if now - last < min_interval:
                continue
            last = now
            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                with _lock:
                    _frame_jpg = jpg.tobytes()
        cap.release()
        time.sleep(3)


@app.route("/")
def stream():
    def gen():
        while True:
            with _lock:
                jpg = _frame_jpg
            if jpg is not None:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")
            time.sleep(0.1)
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--rtsp", required=True)
    p.add_argument("--port", type=int, default=8090)
    p.add_argument("--fps", type=float, default=10.0)
    args = p.parse_args()

    threading.Thread(target=reader, args=(args.rtsp, args.fps), daemon=True).start()
    app.run(host="0.0.0.0", port=args.port, threaded=True)
