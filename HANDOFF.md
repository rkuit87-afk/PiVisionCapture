# Handoff: Pi Vision Capture Scaffold

This document summarizes the initial scaffolding for the Pi Vision Capture project, completed by Gemini. The system is now ready for PLC integration and on-site deployment.

## Summary of Work Completed

The following files have been created and/or updated to form a complete, headless Python application that captures and stores images based on an HTTP trigger.

-   **`main.py`**: The main application entrypoint. It loads the configuration, starts all background services, and handles graceful shutdown on `SIGTERM` or `KeyboardInterrupt`.
-   **`config.yaml`**: Application configuration, including RTSP URL, HTTP port, and storage path. The `storage.base_path` has been set to `/data/captures` for the Pi deployment.
-   **`camera_stream.py`**: Manages the RTSP camera connection in a dedicated thread. It provides the most recent frame on demand and automatically handles reconnects.
-   **`trigger_handler.py`**: Runs a lightweight, multi-threaded HTTP server. It exposes endpoints for the PLC to trigger a capture and for health checks.
-   **`storage.py`**: Runs in a background thread, pulling capture requests from a queue and writing the image (`.jpg`) and metadata (`.json`) to the filesystem.
-   **`requirements.txt`**: Defines the necessary Python packages (`opencv-python`, `pyyaml`).

## How to Run the Application

1.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Run the application:**
    ```bash
    python main.py --config config.yaml
    ```
    The application will start and log its status to the console. It is now waiting for triggers.

## API Endpoints

The trigger server listens on port `8888` (configurable in `config.yaml`).

### Trigger a Capture

-   **Endpoint:** `POST /trigger`
-   **Description:** Signals the application to capture the current frame from the camera stream.
-   **Optional JSON Body:** You can provide a `board_id` for tracking.
    ```json
    {
      "board_id": "B123-ABC"
    }
    ```
-   **Success Response (200 OK):**
    ```json
    {
      "status": "queued",
      "board_id": "B123-ABC",
      "timestamp": "2026-07-03T18:00:00.123456"
    }
    ```

### Check System Health

-   **Endpoint:** `GET /health`
-   **Description:** A simple endpoint for a PLC watchdog or other monitoring tool to verify the application is running.
-   **Success Response (200 OK):**
    ```json
    {
      "status": "ok"
    }
    ```

## Next Steps for PLC Integration

The scaffold is complete. The project is now ready for the next phase, which involves connecting it to the specific PLC hardware and workflow. As outlined in the original plan:

1.  **Wire PLC Communication:** The PLC needs to be programmed to send an HTTP POST request to the Pi's IP address (`http://<pi-ip>:8888/trigger`) when a board is in position. The exact method (e.g., TIA Portal HTTP client block) is to be determined.
2.  **Manual Grading UI:** Develop a minimal web-based user interface to display the last N captured images and allow for manual grading or defect tagging.
3.  **Integrate with JustAutomate:** If required, connect the capture metadata with the main JustAutomate project records.
4.  **On-Site Testing:** Test the complete system with the live Vivotek IB9369 camera and the trimmer PLC trigger on-site to validate performance and reliability.
