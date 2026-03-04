"""
BLE Filtering and Advertising Data Utilities

Centralized module for BLE device filtering and advertising data formatting.
Prevents code duplication across ui_application.py and simGw_v9.py.
"""

from typing import Optional


def adv_matches(
    device, 
    adv, 
    addr_prefix: str = "", 
    name_contains: str = "", 
    svc_contains: str = "", 
    mfg_id_hex: str = "", 
    mfg_data_hex: str = ""
) -> bool:
    """
    Check if a BLE device matches the given filters.
    
    Args:
        device: BLEDevice or device address string
        adv: AdvertisementData object (can be None)
        addr_prefix: Match device address starting with this (case-insensitive)
        name_contains: Match name containing this substring (case-insensitive)
        svc_contains: Match service UUID containing this substring (case-insensitive)
        mfg_id_hex: Match manufacturer ID (e.g., "004C" or "0x004C")
        mfg_data_hex: Match manufacturer data containing this hex string
    
    Returns:
        True if device matches all non-empty filters, False otherwise
    """
    # Address prefix filter
    addr_prefix = (addr_prefix or "").strip().upper()
    if addr_prefix:
        addr = (getattr(device, "address", "") if not isinstance(device, str) else str(device)).upper()
        if not addr.startswith(addr_prefix):
            return False

    if not adv:
        # If no adv data, only address prefix can match
        return True if addr_prefix else False

    # Name filter (device.name or adv.local_name)
    if name_contains:
        n = (getattr(adv, "local_name", "") or "") + " " + (getattr(device, "name", "") or "")
        if name_contains.lower() not in n.lower():
            return False

    # Service UUID filter
    if svc_contains:
        su = getattr(adv, "service_uuids", None) or []
        if not any(svc_contains.lower() in (u or "").lower() for u in su):
            return False

    # Manufacturer ID and data filters
    mfg_id_hex = (mfg_id_hex or "").strip().lower().replace("0x", "")
    mfg_data_hex = (mfg_data_hex or "").strip().lower().replace("0x", "")

    if mfg_id_hex:
        try:
            want_id = int(mfg_id_hex, 16)
        except ValueError:
            want_id = None
        if want_id is not None:
            md = getattr(adv, "manufacturer_data", None) or {}
            if want_id not in md:
                return False
            if mfg_data_hex:
                sub = "".join(ch for ch in mfg_data_hex if ch in "0123456789abcdef")
                try:
                    sub_b = bytes.fromhex(sub)
                except ValueError:
                    sub_b = b""
                if sub_b:
                    vv = bytes(md[want_id]) if not isinstance(md[want_id], (bytes, bytearray)) else md[want_id]
                    if sub_b not in vv:
                        return False
    else:
        if mfg_data_hex:
            # If data specified but no ID, match any manufacturer value containing it
            sub = "".join(ch for ch in mfg_data_hex if ch in "0123456789abcdef")
            try:
                sub_b = bytes.fromhex(sub)
            except ValueError:
                sub_b = b""
            if sub_b:
                md = getattr(adv, "manufacturer_data", None) or {}
                found = False
                for _k, v in md.items():
                    vv = bytes(v) if not isinstance(v, (bytes, bytearray)) else v
                    if sub_b in vv:
                        found = True
                        break
                if not found:
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
    lines.append("=" * 60)
    lines.append(f"📱 DEVICE INFORMATION")
    lines.append("=" * 60)
    lines.append(f"Address:     {getattr(device, 'address', device)}")
    lines.append(f"Name:        {getattr(device, 'name', '') or '(unnamed)'}")
    
    if adv is None:
        lines.append("No AdvertisingData available.")
        return "\n".join(lines)

    lines.append("")
    lines.append("=" * 60)
    lines.append(f"📡 ADVERTISING DATA")
    lines.append("=" * 60)
    lines.append(f"Local name:  {getattr(adv, 'local_name', None) or '(not set)'}")
    lines.append(f"RSSI:        {getattr(adv, 'rssi', None)} dBm")
    
    tx = getattr(adv, 'tx_power', None)
    lines.append(f"TX power:    {tx if tx is not None else '(not advertised)'}")
    
    # Platform data (if any)
    platform = getattr(adv, 'platform_data', None)
    if platform:
        lines.append(f"Platform:    {platform}")
    
    lines.append("")
    
    # Service UUIDs
    su = getattr(adv, "service_uuids", None) or []
    if su:
        lines.append(f"🔧 SERVICE UUIDs ({len(su)}):")
        for u in su:
            # Try to show short UUID for standard services
            if len(u) > 8:
                lines.append(f"  • {u}")
            else:
                lines.append(f"  • {u} (short)")
    else:
        lines.append("🔧 SERVICE UUIDs: (none)")
    
    lines.append("")
    
    # Manufacturer data with known IDs
    md = getattr(adv, "manufacturer_data", None) or {}
    if md:
        lines.append(f"🏭 MANUFACTURER DATA ({len(md)} entries):")
        
        # Known manufacturer IDs (Bluetooth SIG assigned numbers)
        known_mfg = {
            0x004C: "Apple Inc.",
            0x0059: "Nordic Semiconductor ASA",
            0x006A: "Abbott Diabetes Care",
            0x0075: "Samsung Electronics Co. Ltd.",
            0x00E0: "Google LLC",
            0x0087: "Garmin International, Inc.",
            0x0157: "Huawei Technologies Co., Ltd.",
        }
        
        for k, v in md.items():
            vv = bytes(v) if not isinstance(v, (bytes, bytearray)) else v
            mfg_name = known_mfg.get(k, "Unknown")
            lines.append(f"  • ID: 0x{k:04X} ({mfg_name})")
            lines.append(f"    Data: {vv.hex().upper()}")
            lines.append(f"    Len:  {len(vv)} bytes")
    else:
        lines.append("🏭 MANUFACTURER DATA: (none)")
    
    lines.append("")
    
    # Service data
    sd = getattr(adv, "service_data", None) or {}
    if sd:
        lines.append(f"🔐 SERVICE DATA ({len(sd)} entries):")
        for k, v in sd.items():
            vv = bytes(v) if not isinstance(v, (bytes, bytearray)) else v
            lines.append(f"  • UUID: {k}")
            lines.append(f"    Data: {vv.hex().upper()}")
            lines.append(f"    Len:  {len(vv)} bytes")
    else:
        lines.append("🔐 SERVICE DATA: (none)")
    
    lines.append("")
    lines.append("=" * 60)
    
    return "\n".join(lines)
