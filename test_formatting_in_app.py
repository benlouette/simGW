"""
Test that the formatters are actually being called correctly
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

# Simulate what simGw_v9 does
from protobuf_formatters import ProtobufFormatter

# Test AcceptSession from recent capture
accept_session_hex = "0A 04 08 01 10 01 5A 22 10 01 18 05 22 06 C4 BD 6A 01 02 03 28 83 84 04 30 83 84 04 38 FF FF FF FF 0F 48 5F 52 04 0A 02 08 77"
accept_payload = bytes.fromhex(accept_session_hex.replace(" ", ""))

# Test SendMeasurement with overalls
measurement_hex = "0A 04 08 01 10 02 6A 4D 0A 11 08 A5 CB 96 AD DA B4 E9 D2 A5 01 10 A5 CB 96 AD 0A 12 15 0A 07 0A 05 08 01 18 9F 01 1A 0A 1A 08 08 51 10 0A 18 2B 20 0A 12 15 0A 07 0A 05 08 02 18 9F 01 1A 0A 1A 08 08 53 10 0D 18 2A 20 0D 12 0A 0A 04 0A 02 08 04 1A 02 10 3A"
measurement_payload = bytes.fromhex(measurement_hex.replace(" ", ""))

print("=" * 80)
print("TEST 1: AcceptSession formatting")
print("=" * 80)
result1 = ProtobufFormatter.format_payload_readable(accept_payload)
print(result1)

print("\n" + "=" * 80)
print("TEST 2: Overall Measurements formatting")
print("=" * 80)
result2 = ProtobufFormatter.format_payload_readable(measurement_payload)
print(result2)

print("\n" + "=" * 80)
print("TEST 3: Verify message type detection")
print("=" * 80)
msg_type_1 = ProtobufFormatter.get_message_type(accept_payload)
msg_type_2 = ProtobufFormatter.get_message_type(measurement_payload)
print(f"AcceptSession detected as: {msg_type_1}")
print(f"SendMeasurement detected as: {msg_type_2}")

print("\n" + "=" * 80)
print("All tests complete!")
print("=" * 80)
