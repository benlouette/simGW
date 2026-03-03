"""
Test the new formatting functions for accept_session and overall measurements
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from protobuf_formatters import ProtobufFormatter

# Test with sample data from recent session
session_file = r"c:\Users\GJ2640\Desktop\simGW\sessions\sensor1_20260303_140146_auto\events.txt"

print("Testing formatter with data from events.txt")
print("=" * 80)

# We'll parse the hex dumps from events.txt to test the formatters
import re

def extract_hex_from_events(filepath, message_types=None):
    """Extract hex payloads from events.txt"""
    payloads = []
    
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    current_msg_type = None
    current_hex = []
    in_hex_section = False
    
    for line in lines:
        # Detect message type
        if "| notify | accept_session" in line or "| write | accept_session" in line:
            current_msg_type = "accept_session"
        elif "| notify | send_measurement" in line or "| write | send_measurement" in line:
            current_msg_type = "send_measurement"
        
        # Detect hex section
        if "Hex:" in line:
            in_hex_section = True
            current_hex = []
            continue
        
        # Detect end of hex section
        if in_hex_section and ("Protobuf structure:" in line or "---" in line):
            in_hex_section = False
            if current_hex and (message_types is None or current_msg_type in message_types):
                # Convert hex string to bytes
                hex_str = ' '.join(current_hex).replace('\n', '').replace('\r', '')
                try:
                    payload = bytes.fromhex(hex_str)
                    payloads.append((current_msg_type, payload))
                except Exception as e:
                    pass
            current_hex = []
            current_msg_type = None
        
        # Collect hex data
        if in_hex_section:
            # Extract hex bytes from line
            hex_parts = line.strip().split()
            for part in hex_parts:
                if re.match(r'^[0-9A-Fa-f]{2}$', part):
                    current_hex.append(part)
    
    return payloads

# Extract payloads
print("\nExtracting payloads from events.txt...")
payloads = extract_hex_from_events(session_file, ["accept_session", "send_measurement"])

print(f"Found {len(payloads)} relevant messages\n")

# Test formatting
for idx, (msg_type, payload) in enumerate(payloads[:5]):  # Only first 5 to avoid spam
    print(f"\n{'=' * 80}")
    print(f"Message {idx+1}: {msg_type} ({len(payload)} bytes)")
    print('=' * 80)
    
    try:
        formatted = ProtobufFormatter.format_payload_readable(payload)
        print(formatted)
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 80)
print("Test complete!")
