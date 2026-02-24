# SimGW v2 BLE Loop

This tool scans for a BLE device whose address starts with `C4:BD:6A`, connects, requests MTU 247, sends `t` to TX characteristic, waits for RX data, then disconnects. Each run creates a tile with status and received data.

## Requirements

- Windows with Bluetooth
- Python 3.8+
- BLEK (Bleak) library

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Run

```powershell
python .\simGw_v2.py
```

## Notes

- Click **Start** to run one loop (scan → connect → send → receive → disconnect).
- Adjust timeouts and MTU in the UI if needed.
