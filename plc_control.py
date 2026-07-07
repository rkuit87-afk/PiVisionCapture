"""
plc_control.py

This module handles communication back to the PLC, such as triggering
actuators like saws.
"""

import logging
import snap7
from snap7.util import set_bool

logger = logging.getLogger(__name__)

# --- PLC Configuration ---
# IMPORTANT: These values must be provided by the user/system configuration.
PLC_IP = "169.254.9.152"  # Assuming same IP as camera, might need to be changed.
PLC_RACK = 0             # Default for S7-1200/1500
PLC_SLOT = 1             # Default for S7-1200/1500

# These need to be confirmed by the user.
SAW_TRIGGER_DB_NUMBER = 1        # Placeholder
SAW_TRIGGER_BYTE_OFFSET = 0      # Placeholder
SAW_TRIGGER_BIT_OFFSET = 0       # Placeholder


def trigger_saws():
    """
    Connects to the PLC and sets the specified bit to trigger the saws.
    """
    logger.info(
        "Attempting to trigger saws via PLC: DB=%d, Byte=%d, Bit=%d",
        SAW_TRIGGER_DB_NUMBER,
        SAW_TRIGGER_BYTE_OFFSET,
        SAW_TRIGGER_BIT_OFFSET
    )

    # --- Placeholder Implementation ---
    # The following code is a placeholder and will not execute until the
    # PLC details are confirmed. For now, it will just log the action.

    use_real_plc = False # Set to True when PLC details are confirmed and ready for testing

    if not use_real_plc:
        logger.warning("PLC communication is disabled. 'trigger_saws' was called but no signal was sent.")
        return

    try:
        plc = snap7.client.Client()
        plc.connect(PLC_IP, PLC_RACK, PLC_SLOT)

        if plc.get_connected():
            logger.info("Successfully connected to PLC at %s", PLC_IP)

            # Read the current DB content
            db_data = plc.db_read(SAW_TRIGGER_DB_NUMBER, SAW_TRIGGER_BYTE_OFFSET, 1)

            # Set the specific bit to True (1)
            set_bool(db_data, 0, SAW_TRIGGER_BIT_OFFSET, True)

            # Write the modified data back to the DB
            plc.db_write(SAW_TRIGGER_DB_NUMBER, SAW_TRIGGER_BYTE_OFFSET, db_data)

            logger.info("Successfully wrote trigger signal to PLC.")

            # It's good practice to reset the trigger bit after a short delay
            # if the PLC doesn't do it automatically. This might require
            # a separate thread or mechanism. For now, we set it and disconnect.
            # time.sleep(0.5)
            # set_bool(db_data, 0, SAW_TRIGGER_BIT_OFFSET, False)
            # plc.db_write(SAW_TRIGGER_DB_NUMBER, SAW_TRIGGER_BYTE_OFFSET, db_data)

            plc.disconnect()
            logger.info("Disconnected from PLC.")
        else:
            logger.error("Could not connect to PLC at %s.", PLC_IP)

    except Exception as e:
        logger.error("An error occurred during PLC communication: %s", e, exc_info=True)

