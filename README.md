# SimGW v9 - BLE Sensor Gateway

Advanced BLE gateway application for SKF sensors with real-time data capture, protobuf decoding, and session recording. Refactored for maintainability with modular architecture.

## Features

### 🎯 **Demo Tab**
- User-friendly KPI display with timeline visualization
- Session information and overall measurements
- Waveform plotting with matplotlib integration
- Auto-cycle workflow: Scan → Connect → Overall → Waveform → Close

### 🔧 **Expert Tab**
- Multi-tile device monitoring (up to 3 devices simultaneously)
- Manual action control (Session Test, Overall, TWF capture, Full Cycle)
- Real-time protobuf message decoding
- Hex dump display and session logging

### 📱 **Devices Tab**
- BLE device scanner with filtering (MAC prefix: `C4:BD:6A`)
- Real-time RSSI monitoring
- Detailed advertising data display
- One-click connection management

### ⚙️ **Settings Tab**
- TWF type selection (Acceleration/Velocity/Enveloper3)
- Session recording toggle
- MTU configuration
- Session output directory configuration

## Architecture

### Modular Design (Refactored March 2026)

**Core Modules:**
- **simGw_v9.py** - Main application entry point and BLE worker
- **ui_application.py** - Tkinter GUI (4-tab interface with dark theme)

**Configuration Modules:**
- **ble_config.py** - BLE UUIDs, measurement types, protocol constants
- **ui_config.py** - UI colors, manual actions, checklist items
- **protocol_utils.py** - Phase definitions, directories, state machine

**Business Logic:**
- **ble_session_helpers.py** - BLE communication and session management
- **ble_filters.py** - Device filtering and advertising data formatting
- **protobuf_formatters.py** - Protobuf message parsing and display
- **data_exporters.py** - Waveform export to binary format
- **session_recorder.py** - Session logging with protobuf decoding

**UI Utilities:**
- **ui_helpers.py** - Reusable Tkinter widgets and styling helpers
- **display_formatters.py** - Session and measurement text formatting

**Legacy:**
- **config.py** - Deprecated wrapper (use specialized modules instead)

### Protocol
- **protocol/** - Simplified protobuf definitions (SKF protocol)
  - app.proto - Application messages (AcceptSession, CloseSession)
  - session.proto - Session control
  - measurement.proto - Overall and TWF measurements
  - command.proto - Device commands
  - configuration.proto - Configuration messages
  - common.proto - Common data types
  - fota.proto - Firmware update

## Requirements

- **OS**: Windows 10/11 with Bluetooth LE support
- **Python**: 3.10+ (tested on 3.13)
- **Dependencies**: 
  - `bleak` - Cross-platform BLE library
  - `protobuf` - Protocol Buffers runtime
  - `matplotlib` - (Optional) For waveform plotting in Demo tab

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

### Demo Tab - Quick Workflow
1. Click **"Start Auto"** to begin automatic cycle
2. Application automatically: Scans → Connects → Requests Overall → Requests Waveform → Closes
3. View KPIs in the timeline visualization
4. Plot waveform data (if matplotlib available)

### Expert Tab - Manual Control
1. **Scan** for devices, select one
2. Use **Manual Actions** buttons:
   - **Session Test**: Quick session info check
   - **Overall**: Request all 4 overall measurements
   - **Acceleration/Velocity/Enveloper3 TWF**: Request specific waveform
   - **Full Cycle**: Overall + TWF (from Settings)
   - **Connect Test**: Test BLE connection only
3. Monitor real-time RX/TX messages in tile displays

### Session Recording
Sessions are automatically logged to `sessions/<sensor_id>_<timestamp>/` with:
- **events.txt**: Decoded protobuf messages with human-readable format
- **meta.json**: Session metadata (device info, timestamps)
- Hex dumps for debugging

### Waveform Export
Waveforms are saved to `captures/waveform_tile<N>_<timestamp>.bin` as raw protobuf payloads.

## UI Theme

Modern dark theme (Windows 11 optimized):
- **Background**: `#0f1115` (dark blue-gray)
- **Panel**: `#171a21` (darker panels)
- **Accent**: `#0F7FFF` (electric blue)
- **Success**: `#22c55e` (green)
- **Warning**: `#f59e0b` (orange)
- **Error**: `#ef4444` (red)
- **Windows 11**: Rounded corners, dark title bar, custom borders

## Configuration

### BLE Settings (ble_config.py)
- UART service/characteristic UUIDs
- Measurement type constants
- Default TWF type

### UI Settings (ui_config.py)
- Color palette
- Manual actions list
- Checklist items

### Protocol Settings (protocol_utils.py)
- Phase definitions (scanning, connecting, metrics, etc.)
- Directory paths (captures, sessions, protocol)
- Auto-restart delay

## Data Management

### Git Ignore
The `.gitignore` file excludes:
- `captures/` - Binary waveform data (can be large)
- `sessions/` - Session logs (can contain sensitive data)
- `__pycache__/` - Python bytecode
- `*.pyc`, `*.pyo` - Compiled Python files
- `.vscode/`, `.idea/` - IDE settings

### Data Directories
- **captures/**: Waveform binary files (`.bin`)
- **sessions/**: Session logs with events and metadata
- **protocol/**: Protobuf definitions and generated Python files

## Troubleshooting

**Bluetooth not found**
- Ensure Bluetooth adapter is enabled in Windows settings
- Check Device Manager for driver issues

**Device not discovered**
- Verify device is powered on and in range
- Check MAC address filter in `ble_filters.py`

**Connection timeout**
- Increase `AUTO_RESTART_DELAY_MS` in `protocol_utils.py`
- Ensure device is not connected to another application

**Protobuf decode errors**
- Verify `protocol/` directory contains all required `*_pb2.py` files
- Regenerate if needed: `protoc --python_out=. *.proto` (from protocol/ directory)

**UI Theme Issues (Windows)**
- Dark title bar requires Windows 10 1809+
- Rounded corners require Windows 11 22000+
- If customization fails, app continues with default styling

## Development

### Code Organization
- **Separation of Concerns**: BLE logic, UI logic, and configuration are in separate modules
- **Dependency Injection**: `ui_application.py` uses factory pattern for testability
- **Centralized Configuration**: Three focused config modules instead of one monolithic file
- **Reusable Utilities**: `ui_helpers.py` and `display_formatters.py` for common patterns

### Adding New Features
1. **New BLE message**: Add to `protobuf_formatters.py` decoder
2. **New UI component**: Use helpers from `ui_helpers.py`
3. **New configuration**: Add to appropriate config module (`ble_config.py`, `ui_config.py`, `protocol_utils.py`)

### Modifying Protocol
1. Edit `.proto` files in `protocol/`
2. Regenerate Python bindings from `protocol/` directory:
   ```powershell
   protoc --python_out=. *.proto
   ```
3. Update `protobuf_formatters.py` if message structure changed

## Version History

- **v9.1** - March 2026 (Current)
  - 🧹 **Major Refactoring**: Modular architecture for maintainability
  - 📦 Created 6 new modules: `ble_filters`, `display_formatters`, `ble_config`, `ui_config`, `protocol_utils`, `ui_helpers`
  - ♻️ Removed 627 lines of dead code
  - 🎨 Separated UI styling into reusable helpers
  - 📋 Deprecated monolithic `config.py`
  - 🗑️ Removed legacy `froto/` protocol and test files
  
- **v9.0** - February 2026
  - Modern dark UI with Windows 11 integration
  - Demo tab with auto-cycle workflow
  - Enhanced protobuf decoding
  - Session recording with metadata

## License

Internal tool - SKF
