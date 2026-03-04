"""
[DEPRECATED] This module has been split into specialized modules.

New structure:
- ble_config.py: BLE UUIDs, measurement types, protocol constants
- ui_config.py: UI colors, actions, checklist, timing
- protocol_utils.py: Phases, directories, phase utilities

This file remains for backwards compatibility but will be removed in the future.
Use the new modules directly instead.
"""
import warnings

warnings.warn(
    "config.py is deprecated. Use ble_config, ui_config, or protocol_utils instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export everything for backwards compatibility
from ble_config import (
    UART_SERVICE_BYTES, UART_RX_BYTES, UART_TX_BYTES,
    MEASUREMENT_TYPE_ACCELERATION_OVERALL, MEASUREMENT_TYPE_VELOCITY_OVERALL,
    MEASUREMENT_TYPE_ENVELOPER3_OVERALL, MEASUREMENT_TYPE_TEMPERATURE_OVERALL,
    MEASUREMENT_TYPE_ACCELERATION_TWF, MEASUREMENT_TYPE_VELOCITY_TWF,
    MEASUREMENT_TYPE_ENVELOPER3_TWF, DEFAULT_TWF_TYPE, TWF_TYPE_NAMES,
    uuid_from_bytes, get_uart_uuids
)

from ui_config import (
    UI_COLORS, UI_POLL_INTERVAL_MS, MANUAL_ACTIONS,
    CHECKLIST_ITEMS, CHECKLIST_STATE_MAP
)

from protocol_utils import (
    BASE_DIR, PROTOCOL_DIR, CAPTURE_DIR,
    AUTO_RESTART_DELAY_MS, PHASE_SCANNING, PHASE_CONNECTING,
    PHASE_CONNECTED, PHASE_METRICS, PHASE_WAVEFORM,
    PHASE_CLOSE_SESSION, PHASE_DISCONNECTED, PHASE_ERROR,
    _PHASE_ORDER, phase_rank
)

# Legacy names (with underscore prefix)
_uuid_from_bytes = uuid_from_bytes
_get_uart_uuids = get_uart_uuids
_phase_rank = phase_rank

