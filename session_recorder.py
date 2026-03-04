"""
Session recording module for BLE communication logging.

Creates per-session log folder with:
- events.txt: human-readable decoded protobuf messages with useful fields
"""
import os
import time

try:
    from protocol_imports import app_pb2
    from google.protobuf import text_format
    PROTOBUF_AVAILABLE = True
except Exception:
    PROTOBUF_AVAILABLE = False


class SessionRecorder:
    """
    Writes a per-session log folder with events.txt containing decoded message data.
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

    def _decode_message(self, payload: bytes) -> tuple:
        """
        Decode protobuf message and extract useful information.
        
        Returns:
            (msg_type, decoded_info_dict, full_proto_text)
        """
        if not PROTOBUF_AVAILABLE or not payload:
            return "unknown", {}, ""
        
        try:
            message = app_pb2.App()
            message.ParseFromString(payload)
            msg_type = message.WhichOneof("payload") or "unknown"
            
            # Extract useful fields based on message type
            info = {}
            
            if msg_type == "accept_session":
                acc = message.accept_session
                info["virtual_id"] = getattr(acc, "virtual_id", "?")
                info["hw_type"] = str(getattr(acc, "hardware_type", "?"))
                info["fw_version"] = getattr(acc, "fw_version", 0)
                info["serial"] = getattr(acc, "serial", b"").hex()
                info["battery"] = getattr(acc, "battery_indicator", 0)
                info["config_hash"] = getattr(acc, "config_hash", 0)
            
            elif msg_type == "send_measurement":
                sm = message.send_measurement
                meas_count = len(getattr(sm, "measurement_data", []))
                info["measurement_count"] = meas_count
            
            elif msg_type == "open_session":
                os_msg = message.open_session
                info["sync_time"] = getattr(os_msg, "current_sync_time", 0)
            
            elif msg_type == "measurement_request":
                mr = message.measurement_request
                meas_types = getattr(mr, "measurement", [])
                info["requested_types"] = len(meas_types)
            
            elif msg_type == "command":
                cmd = message.command
                info["command_type"] = str(getattr(cmd, "command", "?"))
            
            elif msg_type == "ack":
                ack = message.ack
                info["ack"] = getattr(ack, "ack", False)
                info["error_code"] = getattr(ack, "error_code", 0)
            
            elif msg_type == "error":
                err = message.error
                info["error_code"] = getattr(err, "error_code", 0)
                info["config_hash"] = getattr(acc, "config_hash", "?")
                
            elif msg_type == "open_session":
                op = message.open_session
                info["sync_time"] = getattr(op, "current_sync_time", "?")
                
            elif msg_type == "close_session":
                info["closing"] = "session"
                
            elif msg_type == "get_version":
                ver = message.get_version
                if hasattr(ver, "fw_version"):
                    info["fw_version"] = hex(ver.fw_version)
                if hasattr(ver, "hw_version"):
                    info["hw_version"] = ver.hw_version
                    
            elif msg_type == "data_selection":
                sel = message.data_selection
                types = []
                for t in getattr(sel, "measurement_type", []):
                    types.append(str(t))
                info["measurement_types"] = types
                info["duration_sec"] = getattr(sel, "duration_sec", "?")
                info["frequency_hz"] = getattr(sel, "frequency_hz", "?")
                
            elif msg_type == "data_upload":
                # Don't dump waveform data - just summarize
                upload = message.data_upload
                pair_count = len(getattr(upload, "data_pair", []))
                info["data_pairs"] = pair_count
                info["note"] = "Waveform data (not dumped - too large)"
                return msg_type, info, ""  # Skip full proto
                
            elif msg_type == "config_hash":
                cfg = message.config_hash
                info["hash"] = getattr(cfg, "hash", "?")
                
            elif msg_type == "sync_time":
                sync = message.sync_time
                info["sync_time"] = getattr(sync, "current_sync_time", "?")
                
            # Get full protobuf text representation (except for data_upload)
            if msg_type != "data_upload":
                proto_text = text_format.MessageToString(message, as_one_line=False).rstrip()
            else:
                proto_text = ""
                
            return msg_type, info, proto_text
            
        except Exception as e:
            return "parse_error", {"error": str(e)}, ""

    def log(self, direction: str, kind: str, msg_type: str, payload: bytes):
        """
        Log a BLE message to text file with decoded protobuf information.
        
        Args:
            direction: "RX", "TX", or "EVT"
            kind: Message kind/category
            msg_type: Protobuf message type (hint from caller)
            payload: Raw message bytes
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Decode the message
        decoded_type, info, proto_text = self._decode_message(payload)
        
        # Use decoded type if available, fallback to hint
        final_type = decoded_type if decoded_type != "unknown" else msg_type
        
        # Write header
        self._txt_f.write(f"[{timestamp}] {direction} | {kind} | {final_type}\n")
        self._txt_f.write(f"  Length: {len(payload)} bytes\n")
        
        # Write extracted key information
        if info:
            self._txt_f.write(f"  Key fields:\n")
            for key, value in info.items():
                if isinstance(value, list):
                    self._txt_f.write(f"    {key}: {', '.join(str(v) for v in value)}\n")
                else:
                    self._txt_f.write(f"    {key}: {value}\n")
        
        # Write hex for small messages only (< 100 bytes)
        if len(payload) <= 100 and final_type != "data_upload":
            hex_lines = []
            for i in range(0, len(payload), 32):
                chunk = payload[i:i+32]
                hex_str = " ".join(f"{b:02X}" for b in chunk)
                hex_lines.append(f"    {hex_str}")
            if hex_lines:
                self._txt_f.write(f"  Hex:\n" + "\n".join(hex_lines) + "\n")
        
        # Write full protobuf structure for non-waveform messages
        if proto_text and final_type != "data_upload":
            self._txt_f.write(f"  Protobuf structure:\n")
            for line in proto_text.split('\n'):
                self._txt_f.write(f"    {line}\n")
        
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

        self._txt_f.flush()
