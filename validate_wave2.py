#!/usr/bin/env python3
"""
Validation script for simGw_v9_Temp.py refactoring (Wave 2)
Tests that all extracted modules work correctly
"""
import sys
import os

def validate_wave2():
    """Validate the second wave of refactoring"""
    print("🔍 Validating Wave 2 Refactoring...")
    print("=" * 60)
    
    errors = []
    
    # Check that new modules exist
    modules_to_check = [
        'ble_session_helpers.py',
        'protobuf_formatters.py',
        'data_exporters.py'
    ]
    
    print("\n1️⃣  Checking module files exist...")
    for module in modules_to_check:
        if os.path.exists(module):
            size = os.path.getsize(module)
            print(f"   ✅ {module} ({size:,} bytes)")
        else:
            errors.append(f"Module {module} not found")
            print(f"   ❌ {module} MISSING")
    
    # Try importing the new modules
    print("\n2️⃣  Testing module imports...")
    try:
        from ble_session_helpers import BleSessionHelpers
        print("   ✅ BleSessionHelpers imported")
    except ImportError as e:
        errors.append(f"Cannot import BleSessionHelpers: {e}")
        print(f"   ❌ BleSessionHelpers import failed: {e}")
    
    try:
        from protobuf_formatters import ProtobufFormatter, OverallValuesExtractor
        print("   ✅ ProtobufFormatter imported")
        print("   ✅ OverallValuesExtractor imported")
    except ImportError as e:
        errors.append(f"Cannot import protobuf_formatters: {e}")
        print(f"   ❌ protobuf_formatters import failed: {e}")
    
    try:
        from data_exporters import WaveformExporter, WaveformParser
        print("   ✅ WaveformExporter imported")
        print("   ✅ WaveformParser imported")
    except ImportError as e:
        errors.append(f"Cannot import data_exporters: {e}")
        print(f"   ❌ data_exporters import failed: {e}")
    
    # Check main file
    print("\n3️⃣  Checking main file structure...")
    try:
        with open('simGw_v9_Temp.py', 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Check imports
        required_imports = [
            'from ble_session_helpers import BleSessionHelpers',
            'from protobuf_formatters import ProtobufFormatter, OverallValuesExtractor',
            'from data_exporters import WaveformExporter, WaveformParser'
        ]
        
        for imp in required_imports:
            if imp in content:
                print(f"   ✅ Found import: {imp}")
            else:
                errors.append(f"Missing import: {imp}")
                print(f"   ❌ Missing import: {imp}")
        
        # Check alias
        if 'WaveformExportTools = WaveformParser' in content:
            print("   ✅ WaveformExportTools alias found")
        else:
            errors.append("WaveformExportTools alias not found")
            print("   ❌ WaveformExportTools alias not found")
        
        # Count lines
        lines = content.count('\n') + 1
        print(f"\n   📊 File size: {lines:,} lines")
        
    except Exception as e:
        errors.append(f"Cannot read simGw_v9_Temp.py: {e}")
        print(f"   ❌ Error reading file: {e}")
    
    # Check that key wrapper methods exist
    print("\n4️⃣  Checking wrapper methods...")
    wrapper_methods = [
        '_format_rx_payload',
        '_pb_message_type',
        '_hex_short',
        '_extract_waveform_sample_rows',
        '_extract_overall_values',
        '_export_waveform_capture'
    ]
    
    for method in wrapper_methods:
        pattern = f'def {method}('
        if pattern in content:
            print(f"   ✅ {method} wrapper found")
        else:
            errors.append(f"Method {method} not found")
            print(f"   ❌ {method} wrapper not found")
    
    # Summary
    print("\n" + "=" * 60)
    if errors:
        print(f"❌ Validation FAILED with {len(errors)} error(s):")
        for err in errors:
            print(f"   • {err}")
        return False
    else:
        print("✅ Validation PASSED - All checks successful!")
        return True

if __name__ == '__main__':
    success = validate_wave2()
    sys.exit(0 if success else 1)
