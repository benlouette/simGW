"""
Test the updated extract_true_waveform_samples function
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from data_exporters import WaveformParser

# Test with latest capture
test_file = r"c:\Users\GJ2640\Desktop\simGW\captures\waveform_tile1_20260303_140150.bin"

print(f"Testing: {test_file}")
print("=" * 80)

try:
    y, meta = WaveformParser.extract_true_waveform_samples(test_file)
    
    print(f"✅ Success!")
    print(f"  Samples: {len(y)}")
    print(f"  Blocks: {meta.get('blocks')}")
    print(f"  TWF Type: {meta.get('twf_type')}")
    print(f"  Sampling Rate: {meta.get('fs_hz')} Hz")
    print(f"  Sample range: [{min(y)}, {max(y)}]")
    print("=" * 80)
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
