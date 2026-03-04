"""
Display Formatters - UI-specific text formatting utilities

Separates presentation logic from business logic.
Uses protobuf_formatters for data extraction, adds display-friendly formatting.
"""

import re
from typing import List, Dict, Optional


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


def format_session_and_overall_text(session_info: dict, overall_values: list) -> str:
    """
    Format session info and overall measurements into readable multi-line text for UI display.
    
    Args:
        session_info: Dict containing session data (e.g., accept_msg, device info)
        overall_values: List of dicts with keys: label, value, details
    
    Returns:
        Formatted multi-line string ready for display in UI text widget
    """
    lines = []
    
    # Format session info if available
    if session_info:
        accept_msg = session_info.get("accept_msg")
        if accept_msg:
            lines.append("=== SESSION ACCEPTED ===")
            
            # Virtual ID
            virtual_id = getattr(accept_msg, "virtual_id", 0)
            lines.append(f"Virtual ID:    {virtual_id}")
            
            # Hardware type
            hw_type = getattr(accept_msg, "hardware_type", 0)
            lines.append(f"Hardware Type: {hw_type}")
            
            # HW Version
            hw_version = getattr(accept_msg, "hw_version", 0)
            lines.append(f"HW Version:    0x{hw_version:04X}")
            
            # FW Version
            fw_version = getattr(accept_msg, "fw_version", 0)
            lines.append(f"FW Version:    0x{fw_version:08X}")
            
            # Battery
            battery = getattr(accept_msg, "battery_indicator", 0)
            lines.append(f"Battery:       {battery}%")
            
            # Self diagnostic
            self_diag = getattr(accept_msg, "self_diag", 0)
            lines.append(f"Self Diag:     {self_diag}")
            
            # RSSI (from session_info if available)
            session_info_msg = getattr(accept_msg, "session_info", None)
            if session_info_msg:
                ble_info = getattr(session_info_msg, "session_info_ble", None)
                if ble_info:
                    rssi = getattr(ble_info, "rssi", 0)
                    lines.append(f"RSSI:          {rssi} dBm")
            
            lines.append("")  # Empty line separator
    
    # Format overall measurements if available
    if overall_values and len(overall_values) > 0:
        # Group by measurement type (extract from label)
        grouped = {}
        for item in overall_values:
            label = item.get("label", "")
            value = item.get("value", "")
            details = item.get("details", "")
            
            # Extract measurement type (e.g., "Acceleration (Overall)" -> "Acceleration")
            if " - " in label:
                meas_type, field_name = label.split(" - ", 1)
            else:
                # Single value measurement (like Temperature with int32_data)
                meas_type = label
                field_name = "Value"
            
            if meas_type not in grouped:
                grouped[meas_type] = []
            
            grouped[meas_type].append({
                "field": field_name,
                "value": value,
                "details": details
            })
        
        lines.append("=== OVERALL MEASUREMENTS ===")
        
        # Preferred order
        type_order = ["Acceleration (Overall)", "Velocity (Overall)", "Enveloper3 (Overall)", "Temperature (Overall)"]
        sorted_types = [t for t in type_order if t in grouped] + [t for t in grouped if t not in type_order]
        
        for meas_type in sorted_types:
            fields = grouped[meas_type]
            # Short name for header
            type_name = meas_type.replace(" (Overall)", "")
            lines.append(f"--- {type_name} ---")
            
            # Special handling for Temperature
            if type_name == "Temperature":
                # Temperature can come as int32_data (field="Value") or as measurement_overall (field="Mean")
                temp_value = None
                for item in fields:
                    if item["field"] == "Value":
                        temp_value = item["value"]
                        break
                    elif item["field"] == "Mean" and item["value"] != "0":
                        temp_value = item["value"]
                        break
                
                if temp_value:
                    lines.append(f"  Value:        {temp_value} °C")
                continue
            
            # Extract duration if present
            duration_val = None
            for f in fields:
                if "duration" in f["details"].lower():
                    m = re.search(r"Duration:\s*(\d+)", f["details"])
                    if m:
                        duration_val = m.group(1)
                        break
            
            if duration_val:
                lines.append(f"  Duration:     {duration_val} ms")
            
            # Display fields in preferred order
            field_order = ["Peak to Peak", "RMS", "Peak", "Standard Deviation", "Mean"]
            sorted_fields = [f for f in field_order if any(item["field"] == f for item in fields)]
            
            for field_name in sorted_fields:
                for item in fields:
                    if item["field"] == field_name:
                        # Pad field name to align values
                        lines.append(f"  {field_name:<13} {item['value']}")
                        break
    
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
