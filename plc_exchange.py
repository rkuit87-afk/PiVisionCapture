"""
plc_exchange.py — snap7 data exchange with the S7-1200 (G2) over a shared DB.

DB layout verified 2026-07-12 against the LIVE project "Trimmer.G2.VissionAdded"
via TIA Openness export (openness/exports/2026-07-12_153302/db_layouts.json)
and proven by read-size probing of the running CPU. DB1 "DB_Vission",
Standard (non-optimized) layout, 24 bytes. S7 word-alignment puts every
field 2 bytes later than the old hand-packed layout assumed — do NOT revert.

Ownership split (no read-modify-write races):
  PLC-owned:  bytes 0-3 and 20-23
    0.0  bTrigger         Bool  board in position -> host captures
    2    iBoardWidth      Int   optional upstream width hint
    20   wCompareWord     Int   actual profile applied, latched at saw-down
    22.0 bSawDownCompare  Bool  saw-done pulse: compare wCompareWord now
  Host-owned: bytes 4-19
    4.0  bAck             Bool  trigger seen, capture in progress
    4.1  bResultValid     Bool  results below are valid
    4.2  bError           Bool  measurement failed, see iErrorCode
    6    wSawWord         Word  bit i = drop saw i (see saw position table)
    8    iLengthMM        Int   usable length in mm
    10   iWidthMM         Int   board width in mm
    12   iBoardCount      Int   increments with every result
    14   iErrorCode       Int   0=ok 1=no board 2=no frame 3=measure fail 4=no product
    16   iHeartbeat       Int   increments ~1/s while the host app is alive
    18   iFeedSpeedCmd    Int   commanded feed speed (0-100%)
"""

import logging
import struct
import threading
import time

import snap7

logger = logging.getLogger(__name__)

DB_SIZE = 24

# Offsets — verified against Openness export 2026-07-12, do not hand-edit
OFF_PLC_CTRL = 0      # byte: PLC-owned control bits
OFF_PLC_WIDTH = 2     # Int: PLC-owned upstream width
BIT_TRIGGER = 0x01    # 0.0

OFF_PI_STATUS = 4     # byte: host-owned status bits
BIT_ACK = 0x01        # 4.0
BIT_RESULT_VALID = 0x02  # 4.1
BIT_ERROR = 0x04      # 4.2

OFF_SAW_WORD = 6
OFF_LENGTH = 8
OFF_WIDTH = 10
OFF_COUNT = 12
OFF_ERRCODE = 14
OFF_HEARTBEAT = 16
OFF_FEED_SPEED = 18
OFF_COMPARE_WORD = 20   # PLC-owned: actual applied profile (latched at saw-down)
OFF_SAWDOWN_CMP = 22    # PLC-owned: saw-done compare pulse
BIT_SAWDOWN_CMP = 0x01  # 22.0
HOST_AREA_END = 20      # host owns bytes [OFF_PI_STATUS, HOST_AREA_END)


class PlcExchange:
    """Manages the snap7 connection and the handshake DB, with auto-reconnect."""

    def __init__(self, ip: str, rack: int = 0, slot: int = 1,
                 db_number: int = 10, reconnect_delay_s: float = 3.0):
        self.ip = ip
        self.rack = rack
        self.slot = slot
        self.db_number = db_number
        self.reconnect_delay_s = reconnect_delay_s
        self._client = snap7.client.Client()
        self._lock = threading.Lock()  # snap7 client is not thread-safe
        self._connected = False

    # ---- connection management ----

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        with self._lock:
            try:
                try:
                    self._client.disconnect()
                except Exception:
                    pass
                self._client.connect(self.ip, self.rack, self.slot)
                self._connected = bool(self._client.get_connected())
            except Exception as exc:
                self._connected = False
                logger.warning("PLC connect to %s failed: %s", self.ip, exc)
            if self._connected:
                logger.info("PLC connected: %s rack=%d slot=%d DB%d",
                            self.ip, self.rack, self.slot, self.db_number)
            return self._connected

    def ensure_connected(self) -> bool:
        if self._connected:
            return True
        ok = self.connect()
        if not ok:
            time.sleep(self.reconnect_delay_s)
        return ok

    def _read(self, start: int, size: int) -> bytearray:
        with self._lock:
            try:
                return self._client.db_read(self.db_number, start, size)
            except Exception:
                self._connected = False
                raise

    def _write(self, start: int, data: bytearray) -> None:
        with self._lock:
            try:
                self._client.db_write(self.db_number, start, data)
            except Exception:
                self._connected = False
                raise

    # ---- handshake operations ----

    def read_trigger(self) -> bool:
        data = self._read(OFF_PLC_CTRL, 1)
        return bool(data[0] & BIT_TRIGGER)

    def read_board_width(self) -> int:
        """Reads the optional board width provided by the PLC (Int at byte 2)."""
        data = self._read(OFF_PLC_WIDTH, 2)
        return struct.unpack_from(">h", data, 0)[0]

    def read_compare_word(self) -> int:
        """Actual applied saw profile, latched by the PLC at saw-down."""
        data = self._read(OFF_COMPARE_WORD, 2)
        return struct.unpack_from(">h", data, 0)[0]

    def read_saw_done_compare(self) -> bool:
        """PLC saw-done pulse: when True, read_compare_word() is fresh."""
        data = self._read(OFF_SAWDOWN_CMP, 1)
        return bool(data[0] & BIT_SAWDOWN_CMP)

    def write_status(self, ack: bool = False, result_valid: bool = False,
                     error: bool = False) -> None:
        bits = (BIT_ACK if ack else 0) | \
               (BIT_RESULT_VALID if result_valid else 0) | \
               (BIT_ERROR if error else 0)
        self._write(OFF_PI_STATUS, bytearray([bits, 0]))

    def write_results(self, saw_word: int, length_mm: int, width_mm: int,
                      board_count: int, error_code: int) -> None:
        """Write the result block (data first — caller sets bResultValid after)."""
        base = OFF_SAW_WORD
        payload = bytearray(10)
        struct.pack_into(">H", payload, OFF_SAW_WORD - base, saw_word & 0xFFFF)
        struct.pack_into(">h", payload, OFF_LENGTH - base, _clamp_int(length_mm))
        struct.pack_into(">h", payload, OFF_WIDTH - base, _clamp_int(width_mm))
        struct.pack_into(">h", payload, OFF_COUNT - base, _clamp_int(board_count))
        struct.pack_into(">h", payload, OFF_ERRCODE - base, _clamp_int(error_code))
        self._write(base, payload)

    def write_heartbeat(self, value: int) -> None:
        self._write(OFF_HEARTBEAT, bytearray(struct.pack(">h", value % 32000)))

    def write_feed_speed(self, speed_percent: int) -> None:
        """Write the commanded feed speed percentage."""
        clamped_speed = max(0, min(100, int(speed_percent)))
        self._write(OFF_FEED_SPEED, bytearray(struct.pack(">h", clamped_speed)))

    def clear_pi_area(self) -> None:
        """Zero everything the host owns (bytes 4-19) — call once at startup.
        MUST NOT touch bytes 20+ (wCompareWord / bSawDownCompare are PLC-owned)."""
        self._write(OFF_PI_STATUS, bytearray(HOST_AREA_END - OFF_PI_STATUS))

    def disconnect(self) -> None:
        with self._lock:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._connected = False


def _clamp_int(v: int) -> int:
    return max(-32768, min(32767, int(v)))


class SimulatedPlc:
    """Drop-in stand-in for PlcExchange while the real PLC is not connected.

    Trigger it by calling .fire() (the app wires this to the Enter key).
    Everything written is just logged.
    """

    def __init__(self):
        self._trigger = threading.Event()
        self.connected = True

    def fire(self):
        self._trigger.set()

    def ensure_connected(self) -> bool:
        return True

    def read_trigger(self) -> bool:
        return self._trigger.is_set()

    def write_status(self, ack=False, result_valid=False, error=False) -> None:
        logger.info("[SIM-PLC] status ack=%s valid=%s error=%s", ack, result_valid, error)
        if result_valid or error:
            # Real PLC would consume the result then drop the trigger
            self._trigger.clear()

    def write_results(self, saw_word, length_mm, width_mm, board_count, error_code) -> None:
        logger.info("[SIM-PLC] results saw_word=0x%04X length=%d mm width=%d mm "
                    "count=%d err=%d", saw_word, length_mm, width_mm,
                    board_count, error_code)

    def read_board_width(self) -> int:
        return 150 # Simulate a 150mm wide board

    def write_feed_speed(self, speed_percent: int) -> None:
        logger.info("[SIM-PLC] feed_speed=%d%%", speed_percent)

    def write_heartbeat(self, value: int) -> None:
        pass

    def clear_pi_area(self) -> None:
        pass

    def disconnect(self) -> None:
        pass
