"""
UI Configuration Constants.

Contains:
- Color palette
- Manual actions list
- Checklist items
- UI timing constants
"""

from typing import Dict, List, Tuple


ColorPalette = Dict[str, str]
ManualAction = Tuple[str, str]
ChecklistItem = Tuple[str, str]

# ==============================================================================
# UI COLOR PALETTE (Slate theme - modern dark but softer)
# ==============================================================================
UI_COLORS = {
    "bg": "#1e2127",          # Charcoal gray (less aggressive than pure black)
    "panel": "#282c34",       # Slightly lighter panel
    "panel_alt": "#2c313a",   # Alt panels
    "text": "#e8eaed",        # High contrast white (excellent readability)
    "muted": "#9da5b4",       # Much better contrast for secondary text
    "accent": "#61afef",      # Soft blue (less electric)
    "accent_alt": "#56b6c2",  # Cyan accent
    "ok": "#98c379",          # Softer green
    "warn": "#e5c07b",        # Warm yellow
    "bad": "#e06c75",         # Soft red
    "border": "#181a1f",      # Subtle border
}


# ==============================================================================
# TIMING CONSTANTS
# ==============================================================================
UI_POLL_INTERVAL_MS = 150


# ==============================================================================
# CHECKLIST STATE SYMBOLS
# ==============================================================================
CHECKLIST_STATE_PENDING = "☐"
CHECKLIST_STATE_IN_PROGRESS = "⧗"
CHECKLIST_STATE_DONE = "☑"


# ==============================================================================
# MANUAL ACTIONS (for Expert tab)
# ==============================================================================
MANUAL_ACTIONS: List[ManualAction] = [
    ("Session Test", "session_test"),       # Open session, display info, close
    ("Overall", "overall"),                 # Request all 4 overalls
    ("Acceleration TWF", "acceleration_twf"),  # Request AccelerationTwf
    ("Velocity TWF", "velocity_twf"),       # Request VelocityTwf
    ("Enveloper3 TWF", "enveloper3_twf"),  # Request Enveloper3Twf
    ("Full Cycle", "full_cycle"),          # Overall + 3 waveform requests
    ("Connect Test", "connect_test"),       # Just connect and disconnect
]


# ==============================================================================
# CHECKLIST ITEMS (for UI display)
# ==============================================================================
CHECKLIST_ITEMS: List[ChecklistItem] = [
    ("waiting_connection", "Scanning..."),
    ("connected", "Connected"),
    ("general_info_exchange", "Session Accepted"),
    ("data_collection", "Data Collection"),
    ("close_session", "Session Closed"),
    ("disconnect", "Disconnected"),
]

CHECKLIST_STATE_MAP = {
    "pending": CHECKLIST_STATE_PENDING,
    "in_progress": CHECKLIST_STATE_IN_PROGRESS,
    "done": CHECKLIST_STATE_DONE,
}


__all__ = [
    "UI_COLORS",
    "UI_POLL_INTERVAL_MS",
    "MANUAL_ACTIONS",
    "CHECKLIST_ITEMS",
    "CHECKLIST_STATE_MAP",
    "CHECKLIST_STATE_PENDING",
    "CHECKLIST_STATE_IN_PROGRESS",
    "CHECKLIST_STATE_DONE",
]
