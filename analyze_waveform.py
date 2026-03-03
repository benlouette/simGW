"""
Quick script to analyze the latest waveform capture
"""
import struct
import sys
import os

# Add protocol directory to path
base_dir = os.path.dirname(__file__)
protocol_dir = os.path.join(base_dir, "protocol")
if protocol_dir not in sys.path:
    sys.path.insert(0, protocol_dir)

try:
    import app_pb2
    import measurement_pb2
    import common_pb2
except ImportError as e:
    print(f"ERROR: Cannot import protocol modules: {e}")
    print(f"Protocol dir: {protocol_dir}")
    print(f"Exists: {os.path.exists(protocol_dir)}")
    sys.exit(1)

def analyze_waveform_file(filepath):
    """Analyze a waveform .bin file"""
    print(f"Analyzing: {filepath}")
    print(f"File size: {os.path.getsize(filepath)} bytes")
    print("=" * 80)
    
    with open(filepath, "rb") as f:
        fragment_num = 0
        total_data_bytes = 0
        
        while True:
            # Read 4-byte length prefix
            length_bytes = f.read(4)
            if not length_bytes:
                break
            
            payload_len = int.from_bytes(length_bytes, "little")
            payload = f.read(payload_len)
            
            if len(payload) != payload_len:
                print(f"ERROR: Expected {payload_len} bytes, got {len(payload)}")
                break
            
            fragment_num += 1
            
            # Parse protobuf
            try:
                app_msg = app_pb2.App()
                app_msg.ParseFromString(payload)
                
                # Get header info
                header = app_msg.header
                print(f"\nFragment {fragment_num}:")
                print(f"  Header: msg_id={header.message_id}, frag={header.current_fragment}/{header.total_fragments}")
                
                # Get measurement data
                if app_msg.HasField("send_measurement"):
                    meas = app_msg.send_measurement
                    print(f"  Measurements: {len(meas.measurement_data)}")
                    
                    for idx, meas_data in enumerate(meas.measurement_data):
                        # Check metadata
                        if meas_data.HasField("metadata"):
                            meta = meas_data.metadata
                            if meta.HasField("elo_metadata"):
                                vib_path = meta.elo_metadata.vibration_path
                                duration = meta.elo_metadata.duration
                                print(f"    Measurement {idx}: type={vib_path}, duration={duration}")
                        
                        # Check data
                        if meas_data.HasField("data"):
                            data = meas_data.data
                            if data.HasField("data_bytes"):
                                data_bytes = data.data_bytes
                                print(f"      Data bytes: {len(data_bytes)} bytes")
                                total_data_bytes += len(data_bytes)
                                
                                # Try to parse as int16
                                num_samples = len(data_bytes) // 2
                                if num_samples > 0:
                                    samples = struct.unpack(f"<{num_samples}h", data_bytes[:num_samples*2])
                                    print(f"      Parsed samples: {num_samples} int16 values")
                                    print(f"      Sample range: min={min(samples)}, max={max(samples)}")
                            elif data.HasField("int32_data"):
                                print(f"      Int32: {data.int32_data}")
                            elif data.HasField("measurement_overall"):
                                overall = data.measurement_overall
                                print(f"      Overall: p2p={overall.peak2peak}, rms={overall.rms}")
                
            except Exception as e:
                print(f"  ERROR parsing fragment: {e}")
                import traceback
                traceback.print_exc()
    
    print("\n" + "=" * 80)
    print(f"Summary:")
    print(f"  Total fragments: {fragment_num}")
    print(f"  Total data bytes: {total_data_bytes}")
    print(f"  Expected samples (int16): {total_data_bytes // 2}")
    print("=" * 80)

if __name__ == "__main__":
    latest = r"c:\Users\GJ2640\Desktop\simGW\captures\waveform_tile1_20260303_140150.bin"
    analyze_waveform_file(latest)
