"""
Session recording module for BLE communication logging.

Creates per-session log folders with:
- events.csv: timestamp, direction, kind, msg_type, length, hex_short
- events.txt: human-readable lines
- rx_tx.bin: raw frames (dir byte + uint32_le length + payload)
"""
import csv
import os
import struct
import time


class SessionRecorder:
    """
    Writes a per-session log folder with:
    - events.csv: timestamp, direction, kind, msg_type, length, hex_short
    - events.txt: human-readable lines
    - rx_tx.bin: raw frames (dir byte + uint32_le length + payload)
    """
    def __init__(self, root_dir: str, session_name: str):
        self.root_dir = root_dir
        self.session_name = session_name
        self.session_dir = os.path.join(root_dir, session_name)
        os.makedirs(self.session_dir, exist_ok=True)

        self.csv_path = os.path.join(self.session_dir, "events.csv")
        self.txt_path = os.path.join(self.session_dir, "events.txt")
        self.bin_path = os.path.join(self.session_dir, "rx_tx.bin")

        self._csv_f = open(self.csv_path, "w", newline="", encoding="utf-8")
        self._csv = csv.writer(self._csv_f)
        self._csv.writerow(["ts_ms", "dir", "kind", "msg_type", "len", "hex_short"])

        self._txt_f = open(self.txt_path, "w", encoding="utf-8")
        self._bin_f = open(self.bin_path, "wb")

    def close(self):
        """Close all open file handles."""
        for f in (getattr(self, "_csv_f", None), getattr(self, "_txt_f", None), getattr(self, "_bin_f", None)):
            try:
                if f is not None:
                    f.close()
            except Exception:
                pass

    def log(self, direction: str, kind: str, msg_type: str, payload: bytes):
        """
        Log a BLE message to all output files.
        
        Args:
            direction: "RX", "TX", or "EVT"
            kind: Message kind/category
            msg_type: Protobuf message type
            payload: Raw message bytes
        """
        ts_ms = int(time.time() * 1000)
        hex_short = " ".join(f"{b:02X}" for b in payload[:24])
        if len(payload) > 24:
            hex_short += " …"

        self._csv.writerow([ts_ms, direction, kind, msg_type, len(payload), hex_short])
        self._csv_f.flush()

        self._txt_f.write(f"{ts_ms} {direction} {kind} {msg_type} len={len(payload)} hex={hex_short}\n")
        self._txt_f.flush()

        # dir byte: 0=RX, 1=TX, 2=EVT
        dir_b = 0 if direction == "RX" else (1 if direction == "TX" else 2)
        self._bin_f.write(bytes([dir_b]))
        self._bin_f.write(struct.pack("<I", len(payload)))
        self._bin_f.write(payload)
        self._bin_f.flush()

    def log_text(self, text: str):
        """
        Log a text event (not a BLE message).
        
        Args:
            text: Event description
        """
        ts_ms = int(time.time() * 1000)
        self._txt_f.write(f"{ts_ms} EVT {text}\n")
        self._txt_f.flush()
