# PiVisionCapture — Deployment Ready

**Status:** ✓ System tested and ready for trimmer saw deployment

## Active Capture Method: GPIO Trigger

### Wiring (24VDC Relay Dry Contacts)
```
Relay Dry Contact 1 → Raspberry Pi GPIO 17 (Pin 11)
Relay Dry Contact 2 → Raspberry Pi 3.3V (Pin 1)
```

**When relay coil energizes:** Dry contacts close → GPIO 17 goes HIGH → captures board

### Run GPIO Trigger
```bash
ssh Kuit87@192.168.2.11
cd ~/PiVisionCapture
python gpio_trigger.py --cam-capture "rtsp://root:<CAMERA_PASSWORD>@169.254.9.152/live1s1.sdp"
```

### Captured Files Location
- Path: `~/PiVisionCapture/captures/gpio_scan_YYYY-MM-DD/board_XXXX/`
- Format: `board_XXXX.jpg` + `board_XXXX.json` (metadata)
- Quality: 95% JPG, 1920×1080 resolution

### Transfer Captures to Engineering PC
```powershell
.\transfer_session.ps1
```
Copies all captures to: `C:\Users\PSM-LPT-PLC\Desktop\SoftwareProjects\PiVisionCapture\captures_review\`

## Camera Configuration
- **Left (monitor)**: 169.254.9.172 (credentials in CAM_LEFT_RTSP_URL env var, not committed)
- **Right (capture)**: 169.254.9.152 (credentials in CAM_RIGHT_RTSP_URL env var, not committed)
- **Network**: Link-local 169.254.x.x via USB-to-Ethernet adapter (eth1)

## Network Access from Engineering PC
- Pi IP: 192.168.2.11 (shop network)
- Dashboard: http://192.168.2.11:8000/ (view status, test endpoints)
- API command endpoint: http://192.168.2.11:8000/command (REST API)

## To Deploy
1. Wire relay dry contacts to GPIO 17 (Pin 11) and 3.3V (Pin 1)
2. Start gpio_trigger.py on Pi
3. PLC trigger → 24VDC relay coil → dry contacts close → GPIO 17 goes HIGH → captures board
4. Each capture saved automatically with timestamp and metadata
5. Transfer and review on engineering PC when done

---

**All files:** Saved in `/Desktop/SoftwareProjects/PiVisionCapture/`
- `gpio_trigger.py` — Main trigger script (ready to deploy)
- `storage.py` — File saving logic (unchanged, verified)
- `test_capture.py` — Verification script (tested ✓)
- `transfer_session.ps1` — Batch transfer script (ready)
- `scan_session.py` — Manual C key capture (backup option)
- `api.py` — REST API + dashboard (running on port 8000)

**Created:** 2026-07-07
**Tested:** GPIO trigger ready, cameras connected, storage verified
