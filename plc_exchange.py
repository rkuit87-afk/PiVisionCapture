"""
plc_exchange.py — snap7 data exchange with the S7-1200 (G2) over a shared DB.

DB layout (see PLC_DB_LAYOUT.md for the TIA Portal side). The DB must have
"Optimized block access" DISABLED and the CPU must permit PUT/GET.

To avoid read-modify-write races, ownership is split by byte:
  Bytes 0-1  : written ONLY by the PLC
    0.0  bTrigger      Bool  PLC sets when board is in position, resets after
                             it has consumed the result
  Bytes 2-15 : written ONLY by the Pi
    2.0  bAck          Bool  Pi saw the trigger, capture in progress
    2.1  bResultValid  Bool  measurement finished, results below are valid
    2.2  bError        Bool  measurement failed, see iErrorCode
    4.0  wSawWord      Word  bit i = drop saw i (see saw position table)
    6.0  iLengthMM     Int   usable length in mm (fishtail/tear-out excluded)
    8.0  iWidthMM      Int   board width in mm
   10.0  iBoardCount   Int   increments with every result
   12.0  iErrorCode    Int   0=ok 1=no board 2=no frame 3=measure fail 4=no product
   14.0  iHeartbeat    Int   increments ~1/s while the Pi app is alive
"""

import logging
import struct
import threading
import time

import snap7

logger = logging.getLogger(__name__)

DB_SIZE = 16

# Offsets
OFF_PLC_CTRL = 0      # byte: PLC-owned control bits
BIT_TRIGGER = 0x01    # 0.0

OFF_PI_STATUS = 2     # byte: Pi-owned status bits
BIT_ACK = 0x01        # 2.0
BIT_RESULT_VALID = 0x02  # 2.1
BIT_ERROR = 0x04      # 2.2

OFF_SAW_WORD = 4
OFF_LENGTH = 6
OFF_WIDTH = 8
OFF_COUNT = 10
OFF_ERRCODE = 12
OFF_HEARTBEAT = 14


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

    def write_status(self, ack: bool = False, result_valid: bool = False,
                     error: bool = False) -> None:
        bits = (BIT_ACK if ack else 0) | \
               (BIT_RESULT_VALID if result_valid else 0) | \
               (BIT_ERROR if error else 0)
        self._write(OFF_PI_STATUS, bytearray([bits, 0]))

    def write_results(self, saw_word: int, length_mm: int, width_mm: int,
                      board_count: int, error_code: int) -> None:
        """Write the result block (data first — caller sets bResultValid after)."""
        payload = bytearray(10)
        struct.pack_into(">H", payload, OFF_SAW_WORD - 4, saw_word & 0xFFFF)
        struct.pack_into(">h", payload, OFF_LENGTH - 4, _clamp_int(length_mm))
        struct.pack_into(">h", payload, OFF_WIDTH - 4, _clamp_int(width_mm))
        struct.pack_into(">h", payload, OFF_COUNT - 4, _clamp_int(board_count))
        struct.pack_into(">h", payload, OFF_ERRCODE - 4, _clamp_int(error_code))
        self._write(4, payload)

    def write_heartbeat(self, value: int) -> None:
        self._write(OFF_HEARTBEAT, bytearray(struct.pack(">h", value % 32000)))

    def clear_pi_area(self) -> None:
        """Zero everything the Pi owns — call once at startup."""
        self._write(OFF_PI_STATUS, bytearray(DB_SIZE - OFF_PI_STATUS))

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

    def write_heartbeat(self, value: int) -> None:
        pass

    def clear_pi_area(self) -> None:
        pass

    def disconnect(self) -> None:
        pass
