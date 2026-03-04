"""
BLE and Protocol Configuration Constants.

Contains:
- BLE UART UUIDs
- Measurement type constants
- Protocol-specific settings
"""

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
# UUID UTILITY FUNCTIONS
# ==============================================================================
def uuid_from_bytes(bytes_list: list, reverse: bool = False) -> str:
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


def get_uart_uuids(reverse: bool = False) -> tuple:
    """
    Get BLE UART service UUIDs.
    
    Args:
        reverse: If True, use reverse byte order
        
    Returns:
        Tuple of (service_uuid, rx_uuid, tx_uuid)
    """
    service_uuid = uuid_from_bytes(UART_SERVICE_BYTES, reverse)
    rx_uuid = uuid_from_bytes(UART_RX_BYTES, reverse)
    tx_uuid = uuid_from_bytes(UART_TX_BYTES, reverse)
    return service_uuid, rx_uuid, tx_uuid
