"""
Display Formatters - UI-specific text formatting utilities

Separates presentation logic from business logic.
Uses protobuf_formatters for data extraction, adds display-friendly formatting.
"""

import re
from typing import Any, Dict, List, Optional


_MEASUREMENT_TYPE_ORDER = [
    "Acceleration (Overall)",
    "Velocity (Overall)",
    "Enveloper3 (Overall)",
    "Temperature (Overall)",
]
_FIELD_ORDER = ["Peak to Peak", "RMS", "Peak", "STD", "Mean"]
_DURATION_RE = re.compile(r"Duration:\s*(\d+)")


def pretty_field_name(name: str) -> str:
    """
    Humanize proto field names for display.
    
    Examples:
        'acc_rms_mg' -> 'Acc rms mg'
        'peak_to_peak' -> 'Peak to peak'
    
    Args:
        name: Raw field name from protobuf
    
    Returns:
        Human-friendly field name
    """
    if not name:
        return ""
    return name.replace("_", " ").strip().capitalize()


def _append_session_info_lines(lines: List[str], session_info: Dict[str, Any]) -> None:
    """Append formatted session section (if present) to output lines."""
    if not session_info:
        return

    accept_msg = session_info.get("accept_msg")
    if not accept_msg:
        return

    lines.append("=== SESSION ACCEPTED ===")

    virtual_id = getattr(accept_msg, "virtual_id", 0)
    lines.append(f"Virtual ID:    {virtual_id}")

    hw_type = getattr(accept_msg, "hardware_type", 0)
    lines.append(f"Hardware Type: {hw_type}")

    hw_version = getattr(accept_msg, "hw_version", 0)
    lines.append(f"HW Version:    0x{hw_version:04X}")

    fw_version = getattr(accept_msg, "fw_version", 0)
    lines.append(f"FW Version:    0x{fw_version:08X}")

    battery = getattr(accept_msg, "battery_indicator", 0)
    lines.append(f"Battery:       {battery}%")

    self_diag = getattr(accept_msg, "self_diag", 0)
    lines.append(f"Self Diag:     {self_diag}")

    session_info_msg = getattr(accept_msg, "session_info", None)
    if session_info_msg:
        ble_info = getattr(session_info_msg, "session_info_ble", None)
        if ble_info:
            rssi = getattr(ble_info, "rssi", 0)
            lines.append(f"RSSI:          {rssi} dBm")

    lines.append("")


def _group_overall_values(overall_values: List[dict]) -> Dict[str, List[Dict[str, str]]]:
    """Group overall values by measurement type parsed from their label."""
    grouped: Dict[str, List[Dict[str, str]]] = {}

    for item in overall_values:
        label = item.get("label", "")
        value = item.get("value", "")
        details = item.get("details", "")

        if " - " in label:
            meas_type, field_name = label.split(" - ", 1)
        else:
            meas_type = label
            field_name = "Value"

        if meas_type not in grouped:
            grouped[meas_type] = []

        grouped[meas_type].append({"field": field_name, "value": value, "details": details})

    return grouped


def _sorted_measurement_types(grouped: Dict[str, List[Dict[str, str]]]) -> List[str]:
    preferred = [name for name in _MEASUREMENT_TYPE_ORDER if name in grouped]
    remaining = [name for name in grouped if name not in _MEASUREMENT_TYPE_ORDER]
    return preferred + remaining


def _extract_temperature_value(fields: List[Dict[str, str]]) -> Optional[str]:
    for item in fields:
        if item["field"] == "Value":
            return item["value"]
        if item["field"] == "Mean" and item["value"] != "0":
            return item["value"]
    return None


def _extract_duration_value(fields: List[Dict[str, str]]) -> Optional[str]:
    for item in fields:
        details = item.get("details", "")
        if "duration" not in details.lower():
            continue
        match = _DURATION_RE.search(details)
        if match:
            return match.group(1)
    return None


def _append_overall_measurements_lines(lines: List[str], overall_values: List[dict]) -> None:
    """Append formatted overall-measurements section (if present)."""
    if not overall_values:
        return

    grouped = _group_overall_values(overall_values)
    if not grouped:
        return

    lines.append("=== OVERALL MEASUREMENTS ===")

    for meas_type in _sorted_measurement_types(grouped):
        fields = grouped[meas_type]
        type_name = meas_type.replace(" (Overall)", "")
        lines.append(f"--- {type_name} ---")

        if type_name == "Temperature":
            temp_value = _extract_temperature_value(fields)
            if temp_value:
                lines.append(f"  Value:        {temp_value} °C")
            continue

        duration_val = _extract_duration_value(fields)
        if duration_val:
            lines.append(f"  Duration:     {duration_val} ms")

        sorted_fields = [name for name in _FIELD_ORDER if any(item["field"] == name for item in fields)]
        for field_name in sorted_fields:
            for item in fields:
                if item["field"] == field_name:
                    lines.append(f"  {field_name:<13} {item['value']}")
                    break


def format_session_and_overall_text(session_info: dict, overall_values: list) -> str:
    """
    Format session info and overall measurements into readable multi-line text for UI display.
    
    Args:
        session_info: Dict containing session data (e.g., accept_msg, device info)
        overall_values: List of dicts with keys: label, value, details
    
    Returns:
        Formatted multi-line string ready for display in UI text widget
    """
    lines: List[str] = []
    _append_session_info_lines(lines, session_info or {})
    _append_overall_measurements_lines(lines, overall_values or [])

    return "\n".join(lines)


def format_rx_summary(msg_type: str, payload: bytes, formatted_text: str, max_hex_len: int = 48) -> str:
    """
    Format a received message summary for UI display.
    
    Combines message type, hex preview, and formatted content.
    
    Args:
        msg_type: Message type string (e.g., "accept_session")
        payload: Raw protobuf payload bytes
        formatted_text: Already formatted message content
        max_hex_len: Maximum length for hex preview
    
    Returns:
        Complete formatted string with TYPE, HEX, and content
    """
    from protobuf_formatters import ProtobufFormatter
    
    hex_preview = ProtobufFormatter.hex_short(payload, max_hex_len)
    return f"TYPE: {msg_type}\nHEX: {hex_preview}\n\n{formatted_text}"
