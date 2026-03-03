"""
Test script for new protocol migration
Tests message construction and parsing
"""
import sys
import os
import time

BASE_DIR = os.path.dirname(__file__)
PROTOCOL_DIR = os.path.join(BASE_DIR, "protocol")
sys.path.insert(0, PROTOCOL_DIR)

import app_pb2
import session_pb2
import measurement_pb2
import command_pb2
import common_pb2

def test_open_session():
    """Test OpenSession message construction."""
    print("\n=== Test 1: OpenSession ===")
    header = common_pb2.Header(version=1, message_id=1, current_fragment=1, total_fragments=1)
    open_session = session_pb2.OpenSession(current_sync_time=int(time.time()))
    app_msg = app_pb2.App(header=header, open_session=open_session)
    
    payload = app_msg.SerializeToString()
    print(f"✓ OpenSession serialized: {len(payload)} bytes")
    
    # Parse back
    parsed = app_pb2.App()
    parsed.ParseFromString(payload)
    msg_type = parsed.WhichOneof("payload")
    print(f"✓ Parsed message type: {msg_type}")
    print(f"✓ Sync time: {parsed.open_session.current_sync_time}")
    return True

def test_accept_session():
    """Test AcceptSession message construction."""
    print("\n=== Test 2: AcceptSession ===")
    header = common_pb2.Header(version=1, message_id=2, current_fragment=1, total_fragments=1)
    accept_session = session_pb2.AcceptSession(
        virtual_id=1234,
        hardware_type=session_pb2.HardwareTypeCmwa6120_std,
        hw_version=1,
        serial=b"SN123456",
        fw_version=0x01020304,
        fw_cache_version=0,
        config_hash=0xABCDEF01,
        self_diag=0,
        battery_indicator=85
    )
    app_msg = app_pb2.App(header=header, accept_session=accept_session)
    
    payload = app_msg.SerializeToString()
    print(f"✓ AcceptSession serialized: {len(payload)} bytes")
    
    # Parse back
    parsed = app_pb2.App()
    parsed.ParseFromString(payload)
    msg_type = parsed.WhichOneof("payload")
    print(f"✓ Parsed message type: {msg_type}")
    print(f"✓ Virtual ID: {parsed.accept_session.virtual_id}")
    print(f"✓ FW Version: 0x{parsed.accept_session.fw_version:08X}")
    print(f"✓ Battery: {parsed.accept_session.battery_indicator}%")
    return True

def test_measurement_request():
    """Test measurementRequest message construction."""
    print("\n=== Test 3: measurementRequest ===")
    header = common_pb2.Header(version=1, message_id=3, current_fragment=1, total_fragments=1)
    meas_types = [
        measurement_pb2.measurementType(measurement_type=measurement_pb2.MeasurementTypeAccelerationOverall),
        measurement_pb2.measurementType(measurement_type=measurement_pb2.MeasurementTypeVelocityOverall),
        measurement_pb2.measurementType(measurement_type=measurement_pb2.MeasurementTypeTemperatureOverall),
    ]
    meas_request = measurement_pb2.measurementRequest(measurement=meas_types)
    app_msg = app_pb2.App(header=header, measurement_request=meas_request)
    
    payload = app_msg.SerializeToString()
    print(f"✓ measurementRequest serialized: {len(payload)} bytes")
    
    # Parse back
    parsed = app_pb2.App()
    parsed.ParseFromString(payload)
    msg_type = parsed.WhichOneof("payload")
    print(f"✓ Parsed message type: {msg_type}")
    print(f"✓ Requested {len(parsed.measurement_request.measurement)} measurement types")
    return True

def test_send_measurement():
    """Test SendMeasurement message construction."""
    print("\n=== Test 4: SendMeasurement (Overall) ===")
    header = common_pb2.Header(version=1, message_id=4, current_fragment=1, total_fragments=1)
    
    # Create overall measurement
    metadata = measurement_pb2.Metadata(
        elo_metadata=measurement_pb2.MetadataElo(
            vibration_path=measurement_pb2.MeasurementTypeAccelerationOverall,
            duration=1000
        )
    )
    overalls = measurement_pb2.MeasurementOveralls(
        peak2peak=1234,
        rms=567,
        peak=890,
        std=123,
        mean=456
    )
    data_content = measurement_pb2.MeasurementDataContent(measurement_overall=overalls)
    meas_data = measurement_pb2.MeasurementData(metadata=metadata, data=data_content)
    
    send_meas = measurement_pb2.SendMeasurement(measurement_data=[meas_data])
    app_msg = app_pb2.App(header=header, send_measurement=send_meas)
    
    payload = app_msg.SerializeToString()
    print(f"✓ SendMeasurement serialized: {len(payload)} bytes")
    
    # Parse back
    parsed = app_pb2.App()
    parsed.ParseFromString(payload)
    msg_type = parsed.WhichOneof("payload")
    print(f"✓ Parsed message type: {msg_type}")
    print(f"✓ Measurement count: {len(parsed.send_measurement.measurement_data)}")
    meas = parsed.send_measurement.measurement_data[0]
    print(f"✓ RMS value: {meas.data.measurement_overall.rms}")
    print(f"✓ Peak value: {meas.data.measurement_overall.peak}")
    return True

def test_close_session():
    """Test Command (CloseSession) message construction."""
    print("\n=== Test 5: Command (CloseSession) ===")
    header = common_pb2.Header(version=1, message_id=5, current_fragment=1, total_fragments=1)
    cmd = command_pb2.Command(command=command_pb2.CommandTypeCloseSession)
    app_msg = app_pb2.App(header=header, command=cmd)
    
    payload = app_msg.SerializeToString()
    print(f"✓ Command (CloseSession) serialized: {len(payload)} bytes")
    
    # Parse back
    parsed = app_pb2.App()
    parsed.ParseFromString(payload)
    msg_type = parsed.WhichOneof("payload")
    print(f"✓ Parsed message type: {msg_type}")
    print(f"✓ Command type: {parsed.command.command}")
    return True

def test_ack():
    """Test Ack message construction."""
    print("\n=== Test 6: Ack ===")
    header = common_pb2.Header(version=1, message_id=6, current_fragment=1, total_fragments=1)
    ack = common_pb2.Ack(ack=True, error_code=0)
    app_msg = app_pb2.App(header=header, ack=ack)
    
    payload = app_msg.SerializeToString()
    print(f"✓ Ack serialized: {len(payload)} bytes")
    
    # Parse back
    parsed = app_pb2.App()
    parsed.ParseFromString(payload)
    msg_type = parsed.WhichOneof("payload")
    print(f"✓ Parsed message type: {msg_type}")
    print(f"✓ Ack value: {parsed.ack.ack}")
    return True

def main():
    print("=" * 60)
    print("TEST DE MIGRATION DU PROTOCOLE")
    print("=" * 60)
    
    tests = [
        test_open_session,
        test_accept_session,
        test_measurement_request,
        test_send_measurement,
        test_close_session,
        test_ack,
    ]
    
    passed = 0
    failed = 0
    
    for test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"✗ Test échoué: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"RÉSULTATS: {passed} réussis, {failed} échoués")
    print("=" * 60)
    
    if failed == 0:
        print("\n✓ Tous les tests sont passés avec succès !")
        print("✓ La migration du protocole est fonctionnelle.")
        return 0
    else:
        print(f"\n✗ {failed} test(s) ont échoué.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
