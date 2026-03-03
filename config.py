"""
Configuration constants and utility functions for simGW application.

Contains:
- BLE UART UUIDs
- Phase definitions
- Manual actions list
- Checklist items
- Timing constants
- UI color palette
"""
import os

# ==============================================================================
# DIRECTORY PATHS
# ==============================================================================
BASE_DIR = os.path.dirname(__file__)
FROTO_DIR = os.path.join(BASE_DIR, "froto")  # Legacy protocol (deprecated)
PROTOCOL_DIR = os.path.join(BASE_DIR, "protocol")  # New simplified protocol
CAPTURE_DIR = os.path.join(BASE_DIR, "captures")

# ==============================================================================
# UI COLOR PALETTE (Dark theme)
# ==============================================================================
UI_COLORS = {
    "bg": "#0f1115",
    "panel": "#171a21",
    "panel_alt": "#1f2430",
    "text": "#e6e6e6",
    "muted": "#8b93a1",
    "accent": "#0F7FFF",
    "accent_alt": "#4cc9f0",
    "ok": "#22c55e",
    "warn": "#f59e0b",
    "bad": "#ef4444",
    "border": "#2a2f3a",
}

# ==============================================================================
# BLE UART SERVICE UUIDs (as byte arrays)
# ==============================================================================
UART_SERVICE_BYTES = [
    0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0,
    0x93, 0xF3, 0xA3, 0xB5, 0x01, 0x00, 0x40, 0x6E,
]
UART_RX_BYTES = [
    0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0,
    0x93, 0xF3, 0xA3, 0xB5, 0x02, 0x00, 0x40, 0x6E,
]
UART_TX_BYTES = [
    0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0,
    0x93, 0xF3, 0xA3, 0xB5, 0x03, 0x00, 0x40, 0x6E,
]

# ==============================================================================
# TIMING CONSTANTS
# ==============================================================================
AUTO_RESTART_DELAY_MS = 1500
UI_POLL_INTERVAL_MS = 150

# ==============================================================================
# PHASE DEFINITIONS (UI state machine)
# ==============================================================================
PHASE_SCANNING = "scanning"
PHASE_CONNECTING = "connecting"
PHASE_CONNECTED = "connected"
PHASE_METRICS = "metrics"
PHASE_WAVEFORM = "waveform"
PHASE_CLOSE_SESSION = "close_session"
PHASE_DISCONNECTED = "disconnected"
PHASE_ERROR = "error"

_PHASE_ORDER = [
    PHASE_SCANNING,
    PHASE_CONNECTING,
    PHASE_CONNECTED,
    PHASE_METRICS,
    PHASE_WAVEFORM,
    PHASE_CLOSE_SESSION,
    PHASE_DISCONNECTED,
    PHASE_ERROR,
]

def _phase_rank(phase: str) -> int:
    """Return the ordinal position of a phase (for comparison)."""
    try:
        return _PHASE_ORDER.index(phase)
    except ValueError:
        return -1

# ==============================================================================
# MEASUREMENT TYPE CONSTANTS (from protocol/measurement.proto)
# ==============================================================================
# Overall measurement types
MEASUREMENT_TYPE_ACCELERATION_OVERALL = 1
MEASUREMENT_TYPE_VELOCITY_OVERALL = 2
MEASUREMENT_TYPE_ENVELOPER3_OVERALL = 3
MEASUREMENT_TYPE_TEMPERATURE_OVERALL = 4

# Time Waveform (TWF) measurement types
MEASUREMENT_TYPE_ACCELERATION_TWF = 5
MEASUREMENT_TYPE_VELOCITY_TWF = 6
MEASUREMENT_TYPE_ENVELOPER3_TWF = 7

# Default TWF type to request (sensor supports only ONE TWF per request)
DEFAULT_TWF_TYPE = MEASUREMENT_TYPE_ACCELERATION_TWF

# TWF type display names (for UI selector)
TWF_TYPE_NAMES = {
    MEASUREMENT_TYPE_ACCELERATION_TWF: "Acceleration TWF",
    MEASUREMENT_TYPE_VELOCITY_TWF: "Velocity TWF", 
    MEASUREMENT_TYPE_ENVELOPER3_TWF: "Enveloper3 TWF",
}

# ==============================================================================
# MANUAL ACTIONS (for Expert tab)
# ==============================================================================
MANUAL_ACTIONS = [
    ("Sync Time", "sync_time"),
    ("Version", "version"),
    ("Config Hash", "config_hash"),
    ("Metrics", "metrics"),
    ("Waveform", "waveform"),
    ("Close", "close_session"),
    ("Connect Test", "connect_test"),
    ("Discover GATT", "discover_gatt"),
    ("Notify Test", "notify_test"),
]

# ==============================================================================
# CHECKLIST ITEMS (for UI display)
# ==============================================================================
CHECKLIST_ITEMS = [
    ("waiting_connection", "Waiting connection"),
    ("connected", "Connected"),
    ("general_info_exchange", "General info exchange"),
    ("data_collection", "Data collection"),
    ("close_session", "Close session"),
    ("disconnect", "Disconnect"),
]

CHECKLIST_STATE_MAP = {"pending": "☐", "in_progress": "⧗", "done": "☑"}

# ==============================================================================
# UUID UTILITY FUNCTIONS
# ==============================================================================
def _uuid_from_bytes(bytes_list, reverse: bool) -> str:
    """
    Convert a byte array to UUID string format.
    
    Args:
        bytes_list: List of 16 bytes
        reverse: If True, reverse byte order
        
    Returns:
        UUID string in format: 12345678-1234-1234-1234-123456789abc
    """
    ordered = list(reversed(bytes_list)) if reverse else list(bytes_list)
    hex_bytes = [f"{b:02x}" for b in ordered]
    return (
        f"{''.join(hex_bytes[0:4])}-"
        f"{''.join(hex_bytes[4:6])}-"
        f"{''.join(hex_bytes[6:8])}-"
        f"{''.join(hex_bytes[8:10])}-"
        f"{''.join(hex_bytes[10:16])}"
    )


def _get_uart_uuids(reverse: bool) -> tuple:
    """
    Get BLE UART service UUIDs.
    
    Args:
        reverse: If True, use reverse byte order
        
    Returns:
        Tuple of (service_uuid, rx_uuid, tx_uuid)
    """
    service_uuid = _uuid_from_bytes(UART_SERVICE_BYTES, reverse)
    rx_uuid = _uuid_from_bytes(UART_RX_BYTES, reverse)
    tx_uuid = _uuid_from_bytes(UART_TX_BYTES, reverse)
    return service_uuid, rx_uuid, tx_uuid
