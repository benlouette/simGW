# SimGW v9 - BLE Sensor Gateway

Advanced BLE gateway application for connecting to and managing multiple sensor devices with real-time data capture, protobuf decoding, and session recording.

## Features

### 🔍 **Scan Tab**
- Automatic BLE device discovery (filter by MAC prefix: `C4:BD:6A`)
- Real-time signal strength (RSSI) monitoring
- One-click connection management

### 🎯 **Expert Tab**
- Session management with automatic recording
- Protobuf message encoding/decoding
- Data selection and waveform capture
- Session details viewer with human-readable logs
- Export waveforms to binary files

### 📱 **Devices Tab**
- Multi-device tile display (up to 3 devices)
- Real-time connection status
- Device-specific configuration and metrics
- Individual device control

### 📊 **Export Tab**
- Waveform data export functionality
- CSV index generation
- Binary data parsing and visualization

## Architecture

### Core Modules
- **simGw_v9.py** - Main application entry point
- **ui_application.py** - Modern Tkinter UI (4-tab interface)
- **session_recorder.py** - Session logging with protobuf decoding
- **ble_session_helpers.py** - BLE connection management
- **protobuf_formatters.py** - Message formatting utilities
- **data_exporters.py** - Waveform export handlers
- **config.py** - Centralized configuration (colors, timeouts, UUIDs)

### Protocol
- **froto/** - Protobuf definitions (SKFChina.App)
  - DeviceAppBulletSensor
  - SensingDataUpload
  - ConfigurationAndCommand
  - FirmwareUpdateOverTheAir
  - Common, Debug, Froto

## Requirements

- **OS**: Windows 10/11 with Bluetooth LE support
- **Python**: 3.13+ (tested on 3.13)
- **Dependencies**: 
  - `bleak` - Cross-platform BLE library
  - `protobuf` - Protocol Buffers runtime

Install dependencies:

```powershell
pip install -r requirements.txt
```

## Installation

1. Clone or extract the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Ensure Bluetooth is enabled on your system
4. Run the application: `python simGw_v9.py`

## Usage

### Basic Workflow
1. **Scan**: Click "Start Scan" to discover nearby sensors
2. **Connect**: Select a device and click "Connect Device"
3. **Session**: Use Expert tab to start sessions and capture data
4. **Export**: View and export captured waveforms from Export tab

### Session Recording
All BLE communication is automatically logged to `sessions/<sensor_id>_<timestamp>_auto/events.txt` with:
- Decoded protobuf messages
- Key field extraction (virtual_id, firmware version, config hash, etc.)
- Human-readable format for debugging
- Hex dumps for small messages (<100 bytes)

### View Session Details
Click "View Details" button next to any session in the Expert tab to open a popup showing:
- Full decoded message logs
- TX/RX communication timeline
- Copy to clipboard functionality
- Direct notepad integration

## UI Theme

Modern dark theme with:
- Background: `#0f1115` (dark blue-gray)
- Accent: `#4361ee` (electric blue)
- Success: `#22c55e` (green)
- Warning: `#f59e0b` (orange)
- Error: `#ef4444` (red)

## Configuration

Edit `config.py` to customize:
- BLE service/characteristic UUIDs
- Timeouts and retry intervals
- Auto-restart delays
- UI colors and theme
- Device address filters

## Archive

This version uses the **froto protocol**. An archive is maintained at:
```
simGW_froto_archive_<timestamp>.zip
```

## Troubleshooting

**Bluetooth not found**
- Ensure Bluetooth adapter is enabled in Windows settings
- Check Device Manager for driver issues

**Device not discovered**
- Verify device is powered on and in range
- Check MAC address filter in config.py

**Connection timeout**
- Increase timeout values in config.py
- Ensure device is not connected to another application

**Protobuf decode errors**
- Verify froto/ directory contains all required _pb2.py files
- Check message format matches protocol version

## Development

### Adding New Protobuf Messages
1. Add/modify .proto files in froto/
2. Regenerate Python bindings: `protoc --python_out=. <file>.proto`
3. Update session_recorder.py decoder if needed

### Modifying UI
- Theme colors: Edit `UI_COLORS` in config.py
- Layout changes: Modify ui_application.py
- Tab styling: See `_apply_theme()` method

## License

Internal tool - SKF

## Version History

- **v9** - Current (March 2026)
  - Modern dark UI with uniform tab width
  - Session details viewer
  - Enhanced protobuf decoding in logs
  - Centralized configuration
- **v2-v8** - Archived iterations
