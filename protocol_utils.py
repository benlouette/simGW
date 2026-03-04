"""
Protocol State Machine and Directory Utilities.

Contains:
- Phase definitions
- Directory paths
- Timing constants for protocol operations
"""
import os

# ==============================================================================
# DIRECTORY PATHS
# ==============================================================================
BASE_DIR = os.path.dirname(__file__)
PROTOCOL_DIR = os.path.join(BASE_DIR, "protocol")  # Simplified protocol
CAPTURE_DIR = os.path.join(BASE_DIR, "captures")


# ==============================================================================
# TIMING CONSTANTS
# ==============================================================================
AUTO_RESTART_DELAY_MS = 1500


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

PHASE_ORDER = (
    PHASE_SCANNING,
    PHASE_CONNECTING,
    PHASE_CONNECTED,
    PHASE_METRICS,
    PHASE_WAVEFORM,
    PHASE_CLOSE_SESSION,
    PHASE_DISCONNECTED,
    PHASE_ERROR,
)

# Backward compatibility alias (prefer PHASE_ORDER in new code)
_PHASE_ORDER = PHASE_ORDER


def phase_rank(phase: str) -> int:
    """
    Return the ordinal position of a phase (for comparison).
    
    Args:
        phase: Phase name string
        
    Returns:
        Integer rank (0-based index), or -1 if phase is unknown
    """
    try:
        return PHASE_ORDER.index(phase)
    except ValueError:
        return -1
