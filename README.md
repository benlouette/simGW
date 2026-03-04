# SimGW v9 - BLE Sensor Gateway

Simulated BLE gateway application for SKF sensors ELO-IMX1 with real-time data capture, protobuf decoding, and session recording.

## Features

### 🎯 **Demo Tab**
- User-friendly KPI display with timeline visualization
- Session information and overall measurements
- Waveform plotting with matplotlib integration
- Auto-cycle workflow: Scan → Connect → Overall → Waveform → Close

### 🔧 **Expert Tab**
- Multi-tile device monitoring 
- Manual action control (Session Test, Overall, TWF capture, Full Cycle)
- Real-time protobuf message decoding
- Hex dump display and session logging

### 📱 **Devices Tab**
- BLE device scanner with configurable address + name filtering
- Real-time RSSI monitoring
- Detailed advertising data display
- Auto-scan while the tab is active

### ⚙️ **Settings Tab**
- TWF type selection (Acceleration/Velocity/Enveloper3)
- Session recording toggle
- MTU configuration
- Session output directory configuration

## Architecture

### Modular Design 

**Core Modules:**
- **simGw_v9.py** - Main entry point + `BleCycleWorker` orchestration
- **ui_application.py** - Tkinter GUI shell and queue consumer

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

**Worker Services (extracted):**
- **ble_worker_services.py** - Filter normalization, recorder creation, scan helpers
- **ble_waveform_service.py** - Shared waveform collection/export flow

**UI Tab Modules:**
- **TabDemo.py** - Demo tab widgets and helpers
- **TabExpert.py** - Expert tab widgets and tile helpers
- **TabDevices.py** - Devices scan table and details view
- **TabSettings.py** - Settings tab controls

**UI Utilities:**
- **ui_helpers.py** - Reusable Tkinter widgets and styling helpers
- **display_formatters.py** - Session and measurement text formatting

**Protocol / Event Integration:**
- **protocol_imports.py** - Single import entry-point for protobuf modules (`app_pb2`, etc.)
- **ui_events.py** - Typed queue contract (`tile_update`, `cycle_done`) between worker and UI

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
  - `matplotlib` - For waveform plotting in Demo tab

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
4. Plot waveform data 

### Expert Tab - Manual Control
1. **filter** for devices, select one
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
- Hex dumps for debugging

### Waveform Export
Waveforms are exported to `captures/` from collected protobuf payloads:
- **`.bin`** always (raw payload blocks)
- **`.txt`** optional (human-readable blocks, when available)
- Optional side outputs (index/samples) depending on payload content

## UI Theme

Modern dark theme (Windows 11 optimized):
- **Background**: `#1e2127` (charcoal gray)
- **Panel**: `#282c34` (slightly lighter panel)
- **Accent**: `#61afef` (soft blue)
- **Success**: `#98c379` (soft green)
- **Warning**: `#e5c07b` (warm yellow)
- **Error**: `#e06c75` (soft red)
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
- Public phase order constant (`PHASE_ORDER`) used for monotonic UI phase updates
- Directory paths (captures, sessions, protocol)
- Auto-restart delay

### Runtime Debug
- Set `SIMGW_DEBUG=1` (or `true` / `yes` / `on`) to enable debug logs in console.
- Keep unset (default) for quiet runtime output.

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
- Regenerate if needed: `protoc --python_out=. *.proto` (from `protocol/` directory)
- Keep module names unchanged (`app_pb2.py`, `session_pb2.py`, etc.) because imports are centralized in `protocol_imports.py`

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
- **Worker Decomposition**: scan/session/waveform responsibilities split into dedicated services
- **Typed UI Contract**: queue events are standardized in `ui_events.py` to reduce payload drift

### UI Event Contract (Worker ↔ UI)
- `tile_update`: `(kind, tile_id, payload)` where payload is a typed dict (`status`, `phase`, `checklist`, `rx_text`, `export_info`, etc.)
- `cycle_done`: `(kind, tile_id)` end-of-cycle signal for auto-run orchestration
- Producers use helper constructors from `ui_events.py` (`make_tile_update`, `make_cycle_done`) to keep event shape consistent

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

## License

Internal tool - SKF
