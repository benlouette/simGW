"""
BLE Filtering and Advertising Data Utilities

Centralized module for BLE device filtering and advertising data formatting.
Prevents code duplication across ui_application.py and simGw_v9.py.
"""

_SECTION_DIVIDER = "=" * 60

# Known manufacturer IDs (Bluetooth SIG assigned numbers)
_KNOWN_MANUFACTURERS = {
    0x004C: "Apple Inc.",
    0x0059: "Nordic Semiconductor ASA",
    0x006A: "Abbott Diabetes Care",
    0x0075: "Samsung Electronics Co. Ltd.",
    0x00E0: "Google LLC",
    0x0087: "Garmin International, Inc.",
    0x0157: "Huawei Technologies Co., Ltd.",
    0x040E: "SKF (U.K.) Limited",
    0x0D63: "SKF France",
}


def _as_bytes(value) -> bytes:
    return bytes(value) if not isinstance(value, (bytes, bytearray)) else value


def _device_address(device) -> str:
    if isinstance(device, str):
        return str(device)
    return getattr(device, "address", "") or ""


def _device_name(device) -> str:
    if isinstance(device, str):
        return ""
    return getattr(device, "name", "") or ""


def _append_section_header(lines: list[str], title: str) -> None:
    lines.append(_SECTION_DIVIDER)
    lines.append(title)
    lines.append(_SECTION_DIVIDER)


def _append_service_uuids(lines: list[str], adv) -> None:
    service_uuids = getattr(adv, "service_uuids", None) or []
    if not service_uuids:
        lines.append("🔧 SERVICE UUIDs: (none)")
        return

    lines.append(f"🔧 SERVICE UUIDs ({len(service_uuids)}):")
    for service_uuid in service_uuids:
        label = f"{service_uuid} (short)" if len(service_uuid) <= 8 else service_uuid
        lines.append(f"  • {label}")


def _append_manufacturer_data(lines: list[str], adv) -> None:
    manufacturer_data = getattr(adv, "manufacturer_data", None) or {}
    if not manufacturer_data:
        lines.append("🏭 MANUFACTURER DATA: (none - no manufacturer AD field in this advertisement)")
        return

    lines.append(f"🏭 MANUFACTURER DATA ({len(manufacturer_data)} entries):")
    for manufacturer_id, raw_value in sorted(manufacturer_data.items(), key=lambda item: int(item[0])):
        value_bytes = _as_bytes(raw_value)
        manufacturer_name = _KNOWN_MANUFACTURERS.get(manufacturer_id, "Unknown")
        lines.append(f"  • ID: 0x{manufacturer_id:04X} ({manufacturer_name})")
        lines.append(f"    Data: {value_bytes.hex().upper()}")
        lines.append(f"    Len:  {len(value_bytes)} bytes")


def _append_service_data(lines: list[str], adv) -> None:
    service_data = getattr(adv, "service_data", None) or {}
    if not service_data:
        lines.append("🔐 SERVICE DATA: (none)")
        return

    lines.append(f"🔐 SERVICE DATA ({len(service_data)} entries):")
    for service_uuid, raw_value in sorted(service_data.items(), key=lambda item: str(item[0])):
        value_bytes = _as_bytes(raw_value)
        lines.append(f"  • UUID: {service_uuid}")
        lines.append(f"    Data: {value_bytes.hex().upper()}")
        lines.append(f"    Len:  {len(value_bytes)} bytes")


def adv_matches(
    device, 
    adv, 
    addr_prefix: str = "", 
    name_contains: str = "",
) -> bool:
    """
    Check if a BLE device matches the given filters.
    
    Args:
        device: BLEDevice or device address string
        adv: AdvertisementData object (can be None)
        addr_prefix: Match device address starting with this (case-insensitive)
        name_contains: Match name containing this substring (case-insensitive)
    
    Returns:
        True if device matches all non-empty filters, False otherwise
    """
    address = _device_address(device).upper()

    # Address prefix filter
    addr_prefix = (addr_prefix or "").strip().upper()
    if addr_prefix and not address.startswith(addr_prefix):
        return False

    name_query = (name_contains or "").strip().lower()
    if not name_query:
        return True

    device_name = _device_name(device)

    if not adv:
        return name_query in device_name.lower()

    # Name filter (device.name or adv.local_name)
    local_name = (getattr(adv, "local_name", "") or "")
    search_blob = f"{local_name} {device_name}".lower()
    if name_query not in search_blob:
        return False

    return True


def format_adv_details(device, adv) -> str:
    """
    Format device and advertising data into human-readable text.
    
    Args:
        device: BLEDevice or device address string
        adv: AdvertisementData object (can be None)
    
    Returns:
        Formatted multi-line string with device and advertising details
    """
    lines = []
    _append_section_header(lines, "📱 DEVICE INFORMATION")
    lines.append(f"Address:     {_device_address(device)}")
    lines.append(f"Name:        {_device_name(device) or '(unnamed)'}")
    
    if adv is None:
        lines.append("No AdvertisingData available.")
        return "\n".join(lines)

    lines.append("")
    _append_section_header(lines, "📡 ADVERTISING DATA")
    lines.append(f"Local name:  {getattr(adv, 'local_name', None) or '(not set)'}")
    lines.append(f"RSSI:        {getattr(adv, 'rssi', None)} dBm")
    
    tx = getattr(adv, 'tx_power', None)
    lines.append(f"TX power:    {tx if tx is not None else '(not advertised)'}")
    
    # Platform data (if any)
    platform = getattr(adv, 'platform_data', None)
    if platform:
        lines.append(f"Platform:    {platform}")
    
    lines.append("")
    
    _append_service_uuids(lines, adv)
    
    lines.append("")
    
    _append_manufacturer_data(lines, adv)
    
    lines.append("")
    
    _append_service_data(lines, adv)
    
    lines.append("")
    lines.append(_SECTION_DIVIDER)
    
    return "\n".join(lines)
