"""
main.py — Pi Vision Capture

Usage:
  python main.py [--config config.yaml]

This runs the headless application. It starts three background threads:
  1. camera_stream: Connects to the RTSP feed and holds the latest frame.
  2. trigger_handler: Listens for HTTP triggers from the PLC.
  3. storage: Waits for items in a queue and saves frames to disk.

The application waits for a SIGTERM or KeyboardInterrupt to shut down.
"""

import argparse
import logging
import signal
import threading
import time
from http.server import HTTPServer

import yaml

import camera_stream
import storage
import trigger_handler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(threadName)-12.12s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config(path: str) -> dict:
    """Load configuration from a YAML file."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    """Main application entrypoint."""
    parser = argparse.ArgumentParser(description="Pi Vision Capture")
    parser.add_argument(
        "--config", default="config.yaml", help="Path to the config.yaml file."
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    cam_cfg = cfg["camera"]
    trg_cfg = cfg["trigger"]
    sto_cfg = cfg["storage"]

    rtsp_url = cam_cfg["rtsp_url"]
    reconnect_t = cam_cfg.get("reconnect_timeout", 5)
    http_port = trg_cfg["http_port"]
    base_path = sto_cfg["base_path"]
    jpg_quality = sto_cfg.get("jpg_quality", 95)

    # Use a single event to signal shutdown to all threads
    stop_event = threading.Event()
    threads = []
    trigger_server: HTTPServer | None = None

    def shutdown_handler(signum, frame):
        """Signal handler to initiate graceful shutdown."""
        logger.info("Shutdown signal received (signal %d). Exiting gracefully...", signum)
        stop_event.set()

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    try:
        # ── Start modules ─────────────────────────────────────────────────────
        cam_thread = camera_stream.start(rtsp_url, reconnect_t)
        threads.append(cam_thread)
        logger.info("Camera thread started, connecting to %s", rtsp_url)

        trg_thread, trigger_server = trigger_handler.start(http_port)
        threads.append(trg_thread)
        logger.info("Trigger server listening on port %d", trg_cfg["http_port"])

        q = trigger_handler.get_queue()
        sto_thread = storage.start(q, base_path, jpg_quality, rtsp_url, stop_event)
        threads.append(sto_thread)
        # log is already in storage.start()

        logger.info("Ready. Waiting for PLC trigger...")

        # ── Block until shutdown signal ───────────────────────────────────────
        stop_event.wait()

    except Exception as e:
        logger.error("An unexpected error occurred in main thread: %s", e, exc_info=True)
        stop_event.set() # Signal shutdown on error

    finally:
        logger.info("Shutting down all threads...")

        # Stop camera and trigger threads
        camera_stream.stop()
        if trigger_server:
            # Shutdown needs to be called from a different thread
            threading.Thread(target=trigger_server.shutdown).start()

        # Wait for all threads to complete
        for t in threads:
            if t and t.is_alive():
                t.join(timeout=5)
        
        if trigger_server:
            trigger_server.server_close()

        logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()
