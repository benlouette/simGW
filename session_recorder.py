"""
Session recording module for BLE communication logging.

Creates per-session log folder with:
- events.txt: human-readable lines with FULL hex data (no truncation)
"""
import os
import time


class SessionRecorder:
    """
    Writes a per-session log folder with events.txt containing full message data.
    """
    def __init__(self, root_dir: str, session_name: str):
        self.root_dir = root_dir
        self.session_name = session_name
        self.session_dir = os.path.join(root_dir, session_name)
        os.makedirs(self.session_dir, exist_ok=True)

        self.txt_path = os.path.join(self.session_dir, "events.txt")
        self._txt_f = open(self.txt_path, "w", encoding="utf-8")
        
        # Write header
        self._txt_f.write("=" * 80 + "\n")
        self._txt_f.write(f"SESSION: {session_name}\n")
        self._txt_f.write(f"STARTED: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        self._txt_f.write("=" * 80 + "\n\n")
        self._txt_f.flush()

    def close(self):
        """Close text file handle."""
        try:
            if hasattr(self, "_txt_f") and self._txt_f is not None:
                self._txt_f.write("\n" + "=" * 80 + "\n")
                self._txt_f.write(f"SESSION ENDED: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                self._txt_f.write("=" * 80 + "\n")
                self._txt_f.close()
        except Exception:
            pass

    def log(self, direction: str, kind: str, msg_type: str, payload: bytes):
        """
        Log a BLE message to text file with FULL hex data.
        
        Args:
            direction: "RX", "TX", or "EVT"
            kind: Message kind/category
            msg_type: Protobuf message type
            payload: Raw message bytes (ALL bytes, no truncation)
        """
        ts_ms = int(time.time() * 1000)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Format hex data in readable lines (32 bytes per line for readability)
        hex_lines = []
        for i in range(0, len(payload), 32):
            chunk = payload[i:i+32]
            hex_str = " ".join(f"{b:02X}" for b in chunk)
            hex_lines.append(f"  {hex_str}")
        
        hex_full = "\n".join(hex_lines) if hex_lines else "  (empty)"
        
        # Write formatted entry
        self._txt_f.write(f"[{timestamp}] {direction} | {kind} | {msg_type}\n")
        self._txt_f.write(f"  Length: {len(payload)} bytes\n")
        self._txt_f.write(f"  Hex data:\n{hex_full}\n")
        self._txt_f.write("-" * 80 + "\n")
        self._txt_f.flush()

    def log_text(self, text: str):
        """
        Log a text event (not a BLE message).
        
        Args:
            text: Event description
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        self._txt_f.write(f"[{timestamp}] EVENT | {text}\n")
        self._txt_f.write("-" * 80 + "\n")
        self._txt_f.flush()
