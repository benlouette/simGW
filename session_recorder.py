"""
Session recording module for BLE communication logging.

Creates per-session log folder with:
- events.txt: human-readable decoded protobuf messages with useful fields
"""
import os
import time
from typing import Any, Dict, Tuple

try:
    from protocol_imports import app_pb2
    from google.protobuf import text_format
    PROTOBUF_AVAILABLE = True
except Exception:
    app_pb2 = None
    text_format = None
    PROTOBUF_AVAILABLE = False


_SECTION_LINE = "=" * 80
_ENTRY_SEPARATOR = "-" * 80
_MAX_HEX_DUMP_BYTES = 100
_HEX_CHUNK_SIZE = 32
_MAX_DATA_BYTES_HEX_PREVIEW = 256


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
        self._write_session_header()
        self._txt_f.flush()

    @staticmethod
    def _now_str() -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

    def _write_session_header(self) -> None:
        self._txt_f.write(_SECTION_LINE + "\n")
        self._txt_f.write(f"SESSION: {self.session_name}\n")
        self._txt_f.write(f"STARTED: {self._now_str()}\n")
        self._txt_f.write(_SECTION_LINE + "\n\n")

    def _write_session_footer(self) -> None:
        self._txt_f.write("\n" + _SECTION_LINE + "\n")
        self._txt_f.write(f"SESSION ENDED: {self._now_str()}\n")
        self._txt_f.write(_SECTION_LINE + "\n")

    def close(self):
        """Close text file handle."""
        try:
            if hasattr(self, "_txt_f") and self._txt_f is not None and not self._txt_f.closed:
                self._write_session_footer()
                self._txt_f.close()
        except Exception:
            pass

    @staticmethod
    def _bytes_to_hex_preview(data: bytes, max_bytes: int = _MAX_DATA_BYTES_HEX_PREVIEW) -> str:
        """Format bytes as uppercase hex, truncated for very large payloads."""
        if not data:
            return ""
        if len(data) <= max_bytes:
            return data.hex(" ").upper()
        shown = data[:max_bytes].hex(" ").upper()
        return f"{shown} ... (+{len(data) - max_bytes} bytes)"

    @staticmethod
    def _strip_send_measurement_data_bytes_for_text(message: Any) -> Any:
        """Clone App message and remove send_measurement.data.data_bytes for readable text output."""
        cloned = app_pb2.App()
        cloned.CopyFrom(message)
        try:
            for meas_data in getattr(cloned.send_measurement, "measurement_data", []):
                data_content = getattr(meas_data, "data", None)
                if data_content is None:
                    continue
                try:
                    if data_content.HasField("data_bytes"):
                        data_content.ClearField("data_bytes")
                except Exception:
                    pass
        except Exception:
            pass
        return cloned

    def _extract_key_fields(self, message: Any, msg_type: str) -> Dict[str, Any]:
        """Extract compact key fields from a parsed App message."""
        info: Dict[str, Any] = {}

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
            measurement_data = list(getattr(sm, "measurement_data", []))
            info["measurement_count"] = len(measurement_data)
            for index, meas_data in enumerate(measurement_data):
                data_content = getattr(meas_data, "data", None)
                if data_content is None:
                    continue
                raw_bytes = getattr(data_content, "data_bytes", None)
                if not raw_bytes:
                    continue
                raw = bytes(raw_bytes)
                info[f"measurement_{index}_bytes_len"] = len(raw)
                info[f"measurement_{index}_bytes_hex"] = self._bytes_to_hex_preview(raw)

        elif msg_type == "open_session":
            os_msg = message.open_session
            info["sync_time"] = getattr(os_msg, "current_sync_time", 0)

        elif msg_type == "measurement_request":
            mr = message.measurement_request
            info["requested_types"] = len(getattr(mr, "measurement", []))

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
            types = [str(t) for t in getattr(sel, "measurement_type", [])]
            info["measurement_types"] = types
            info["duration_sec"] = getattr(sel, "duration_sec", "?")
            info["frequency_hz"] = getattr(sel, "frequency_hz", "?")

        elif msg_type == "data_upload":
            upload = message.data_upload
            info["data_pairs"] = len(getattr(upload, "data_pair", []))
            info["note"] = "Waveform data (not dumped - too large)"

        elif msg_type == "config_hash":
            cfg = message.config_hash
            info["hash"] = getattr(cfg, "hash", "?")

        elif msg_type == "sync_time":
            sync = message.sync_time
            info["sync_time"] = getattr(sync, "current_sync_time", "?")

        return info

    def _decode_message(self, payload: bytes) -> Tuple[str, Dict[str, Any], str]:
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

            info = self._extract_key_fields(message, msg_type)

            if msg_type != "data_upload":
                message_for_text = message
                if msg_type == "send_measurement":
                    message_for_text = self._strip_send_measurement_data_bytes_for_text(message)
                proto_text = text_format.MessageToString(message_for_text, as_one_line=False).rstrip()
            else:
                proto_text = ""

            return msg_type, info, proto_text

        except Exception as e:
            return "parse_error", {"error": str(e)}, ""

    def _write_key_fields(self, info: Dict[str, Any]) -> None:
        if not info:
            return

        self._txt_f.write("  Key fields:\n")
        for key, value in info.items():
            if isinstance(value, list):
                formatted = ", ".join(str(v) for v in value)
                self._txt_f.write(f"    {key}: {formatted}\n")
            else:
                self._txt_f.write(f"    {key}: {value}\n")

    def _write_hex_dump(self, payload: bytes) -> None:
        if not payload:
            return

        hex_lines = []
        for offset in range(0, len(payload), _HEX_CHUNK_SIZE):
            chunk = payload[offset:offset + _HEX_CHUNK_SIZE]
            hex_str = " ".join(f"{byte:02X}" for byte in chunk)
            hex_lines.append(f"    {hex_str}")

        if hex_lines:
            self._txt_f.write("  Hex:\n" + "\n".join(hex_lines) + "\n")

    def _write_proto_text(self, proto_text: str) -> None:
        if not proto_text:
            return

        self._txt_f.write("  Protobuf structure:\n")
        for line in proto_text.split("\n"):
            self._txt_f.write(f"    {line}\n")

    def log(self, direction: str, kind: str, msg_type: str, payload: bytes):
        """
        Log a BLE message to text file with decoded protobuf information.

        Args:
            direction: "RX", "TX", or "EVT"
            kind: Message kind/category
            msg_type: Protobuf message type (hint from caller)
            payload: Raw message bytes
        """
        payload = payload or b""
        timestamp = self._now_str()

        decoded_type, info, proto_text = self._decode_message(payload)

        final_type = decoded_type if decoded_type != "unknown" else msg_type

        self._txt_f.write(f"[{timestamp}] {direction} | {kind} | {final_type}\n")
        self._txt_f.write(f"  Length: {len(payload)} bytes\n")

        self._write_key_fields(info)

        if len(payload) <= _MAX_HEX_DUMP_BYTES and final_type != "data_upload":
            self._write_hex_dump(payload)

        if final_type != "data_upload":
            self._write_proto_text(proto_text)

        self._txt_f.write(_ENTRY_SEPARATOR + "\n")
        self._txt_f.flush()

    def log_text(self, text: str):
        """
        Log a text event (not a BLE message).
        
        Args:
            text: Event description
        """
        timestamp = self._now_str()
        self._txt_f.write(f"[{timestamp}] EVENT | {text}\n")
        self._txt_f.write(_ENTRY_SEPARATOR + "\n")
        self._txt_f.flush()
