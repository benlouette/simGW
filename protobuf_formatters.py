"""
Protobuf Formatters - Centralized protobuf parsing and formatting
"""

import struct
from typing import Dict, List, Optional, Tuple
from google.protobuf import text_format

from protocol_imports import app_pb2


_HARDWARE_TYPE_MAP = {
    0: "Unknown",
    1: "CMWA6120_std",
    2: "CMWA6120_hf",
}

_OVERALL_TYPE_NAMES = {
    1: "Acceleration",
    2: "Velocity",
    3: "Enveloper3",
    4: "Temperature",
}

_DATA_TYPE_TO_STRUCT = {
    1: ("B", 1),
    2: ("b", 1),
    3: ("H", 2),
    4: ("h", 2),
    5: ("I", 4),
    6: ("i", 4),
    7: ("f", 4),
}

_WAVEFORM_PATHS = (5, 6, 7)


class ProtobufFormatter:
    """Centralized protobuf message parsing and formatting (new protocol)."""

    @staticmethod
    def _parse_app(payload: bytes):
        message = app_pb2.App()
        message.ParseFromString(payload)
        return message

    @staticmethod
    def _has_overall_measurements(send_measurement) -> bool:
        try:
            for meas_data in send_measurement.measurement_data:
                if meas_data.HasField("data") and meas_data.data.HasField("measurement_overall"):
                    return True
        except Exception:
            return False
        return False
    
    @staticmethod
    def get_message_type(payload: bytes) -> str:
        """Extract message type from protobuf payload."""
        try:
            message = ProtobufFormatter._parse_app(payload)
            return message.WhichOneof("payload") or "(none)"
        except Exception:
            return "(parse_error)"
    
    @staticmethod
    def format_payload_readable(payload: bytes) -> str:
        """Format payload as human-readable text with specialized formatting."""
        try:
            message = ProtobufFormatter._parse_app(payload)
            msg_type = message.WhichOneof("payload")

            if msg_type == "accept_session":
                return ProtobufFormatter.format_accept_session_readable(message.accept_session)
            if msg_type == "send_measurement":
                if ProtobufFormatter._has_overall_measurements(message.send_measurement):
                    return ProtobufFormatter.format_overall_measurements_readable(message.send_measurement)

            if message.ListFields():
                return text_format.MessageToString(message, as_one_line=False).rstrip()
        except Exception:
            pass

        try:
            return payload.decode("utf-8", errors="replace")
        except Exception:
            return payload.hex(" ")
    
    @staticmethod
    def format_accept_session_readable(accept_session) -> str:
        """Format accept_session message in a user-friendly way."""
        lines = []
        lines.append("=== SESSION ACCEPTED ===")
        lines.append("")
        
        # Basic info
        if hasattr(accept_session, 'virtual_id'):
            lines.append(f"Virtual ID:        {accept_session.virtual_id}")
        
        # Hardware info
        if hasattr(accept_session, 'hardware_type'):
            hw_type = _HARDWARE_TYPE_MAP.get(accept_session.hardware_type, f"Type_{accept_session.hardware_type}")
            lines.append(f"Hardware Type:     {hw_type}")
        
        if hasattr(accept_session, 'hw_version'):
            lines.append(f"Hardware Version:  {accept_session.hw_version}")
        
        # Firmware version
        if hasattr(accept_session, 'fw_version'):
            fw = accept_session.fw_version
            # Format as hex like 0x10203
            lines.append(f"Firmware Version:  0x{fw:X} ({fw})")
        
        # Serial number
        if hasattr(accept_session, 'serial'):
            serial_bytes = accept_session.serial
            if isinstance(serial_bytes, bytes):
                serial_hex = ':'.join(f'{b:02X}' for b in serial_bytes)
                lines.append(f"Serial Number:     {serial_hex}")
        
        # Battery
        if hasattr(accept_session, 'battery_indicator'):
            battery = accept_session.battery_indicator
            lines.append(f"Battery:           {battery}%")
        
        # Self diagnostic
        if hasattr(accept_session, 'self_diag'):
            lines.append(f"Self Diagnostic:   {accept_session.self_diag}")
        
        # Config hash
        if hasattr(accept_session, 'config_hash'):
            config_hash = accept_session.config_hash
            lines.append(f"Config Hash:       0x{config_hash:08X}")
        
        # Session info (BLE RSSI)
        if hasattr(accept_session, 'session_info'):
            session_info = accept_session.session_info
            if hasattr(session_info, 'session_info_ble'):
                ble_info = session_info.session_info_ble
                if hasattr(ble_info, 'rssi'):
                    rssi = ble_info.rssi
                    # Convert to signed int8
                    if rssi > 127:
                        rssi = rssi - 256
                    lines.append(f"RSSI:              {rssi} dBm")
        
        lines.append("")
        lines.append("=" * 40)
        
        return "\n".join(lines)
    
    @staticmethod
    def format_overall_measurements_readable(send_measurement) -> str:
        """Format overall measurements in a user-friendly way."""
        lines = []
        lines.append("=== OVERALL MEASUREMENTS ===")
        lines.append("")
        
        for meas_data in send_measurement.measurement_data:
            meas_type = None
            duration = None
            if meas_data.HasField("metadata"):
                meta = meas_data.metadata
                if meta.HasField("elo_metadata"):
                    meas_type = meta.elo_metadata.vibration_path
                    duration = meta.elo_metadata.duration

            type_name = _OVERALL_TYPE_NAMES.get(meas_type, f"Type_{meas_type}")

            if meas_data.HasField("data"):
                data = meas_data.data
                
                if data.HasField("measurement_overall"):
                    overall = data.measurement_overall
                    lines.append(f"--- {type_name} ---")
                    if duration:
                        lines.append(f"  Duration:     {duration} ms")
                    lines.append(f"  Peak-to-Peak: {overall.peak2peak}")
                    lines.append(f"  RMS:          {overall.rms}")
                    lines.append(f"  Peak:         {overall.peak}")
                    lines.append(f"  Std Dev:      {overall.std}")
                    if hasattr(overall, 'mean'):
                        lines.append(f"  Mean:         {overall.mean}")
                    lines.append("")
                
                elif data.HasField("int32_data"):
                    # Temperature
                    temp = data.int32_data
                    lines.append(f"--- {type_name} ---")
                    lines.append(f"  Value:        {temp} °C")
                    lines.append("")
        
        lines.append("=" * 40)
        
        return "\n".join(lines)
    
    @staticmethod
    def hex_short(payload: bytes, max_len: int = 48) -> str:
        """Truncated hex representation."""
        if payload is None:
            return ""
        if len(payload) <= max_len:
            return payload.hex(" ")
        return payload[:max_len].hex(" ") + f" ... ({len(payload)} bytes)"
    
    @staticmethod
    def extract_waveform_sample_rows(app_msg) -> list:
        """Extract waveform samples from send_measurement message."""
        rows = []
        try:
            # New protocol: send_measurement.measurement_data[]
            meas_list = getattr(app_msg, "send_measurement", None)
            if meas_list is None:
                return []
            
            for meas_idx, meas_data in enumerate(getattr(meas_list, "measurement_data", [])):
                # Check if it's TWF data
                data_content = getattr(meas_data, "data", None)
                if data_content is None:
                    continue
                
                # Get data bytes
                data_bytes = getattr(data_content, "data_bytes", None)
                if data_bytes is None:
                    # Try int32_data (single value)
                    int32_val = getattr(data_content, "int32_data", None)
                    if int32_val is not None:
                        rows.append((meas_idx, "int32_data", 0, int32_val))
                    continue
                
                metadata = getattr(meas_data, "metadata", None)
                if metadata is None:
                    continue

                elo_metadata = getattr(metadata, "elo_metadata", None)
                if elo_metadata is None:
                    continue

                vibration_path = getattr(elo_metadata, "vibration_path", 0)
                if vibration_path not in _WAVEFORM_PATHS:
                    continue

                data_type = 4
                if data_type not in _DATA_TYPE_TO_STRUCT:
                    continue

                fmt_code, bytes_per_sample = _DATA_TYPE_TO_STRUCT[data_type]
                num_samples = len(data_bytes) // bytes_per_sample
                
                if num_samples > 0:
                    try:
                        # Unpack all samples (little-endian by default for new protocol)
                        values = struct.unpack(f"<{num_samples}{fmt_code}", data_bytes[:num_samples * bytes_per_sample])
                        for sample_idx, sample_value in enumerate(values):
                            rows.append((meas_idx, "twf_sample", sample_idx, sample_value))
                    except Exception:
                        pass
                        
        except Exception:
            return []
        return rows


class OverallValuesExtractor:
    """Extracts overall/metrics values from protobuf send_measurement messages (new protocol)."""

    _ENUM_MAP = {
        0: "Unknown",
        1: "AccelerationOverall",
        2: "VelocityOverall",
        3: "Enveloper3Overall",
        4: "TemperatureOverall",
        5: "AccelerationTwf",
        6: "VelocityTwf",
        7: "Enveloper3Twf",
    }

    _FIELD_REPLACEMENTS = {
        "peak2peak": "Peak to Peak",
        "rms": "RMS",
        "peak": "Peak",
        "std": "STD",
        "mean": "Mean",
    }

    _OVERALL_FIELDS = ("peak2peak", "rms", "peak", "std", "mean")
    
    @staticmethod
    def pretty_label_from_enum_token(token: str) -> str:
        """Convert enum tokens like 'MeasurementTypeAccelerationOverall' into human-friendly labels."""
        if not token:
            return "Value"
        
        t = token.strip()
        
        # Remove MeasurementType prefix
        if t.startswith("MeasurementType"):
            t = t[len("MeasurementType"):]
        
        # Extract suffix
        suffix = ""
        if t.endswith("Overall"):
            suffix = " (Overall)"
            t = t[:-len("Overall")]
        elif t.endswith("Twf"):
            suffix = " (TWF)"
            t = t[:-len("Twf")]
        
        # Split camelCase to words
        words = []
        current_word = []
        for char in t:
            if char.isupper() and current_word:
                words.append(''.join(current_word))
                current_word = [char]
            else:
                current_word.append(char)
        if current_word:
            words.append(''.join(current_word))
        
        s = " ".join(word.capitalize() for word in words if word)
        return (s.strip() or "Value") + suffix
    
    @staticmethod
    def pretty_field_name(name: str) -> str:
        """Humanize proto field names like 'peak2peak' -> 'Peak to Peak'."""
        if not name:
            return ""

        if name in OverallValuesExtractor._FIELD_REPLACEMENTS:
            return OverallValuesExtractor._FIELD_REPLACEMENTS[name]
        
        return name.replace("_", " ").strip().capitalize()
    
    @staticmethod
    def _data_format_to_struct_code(data_type: int):
        """Convert DataType enum to (struct_code, bytes_per_sample)."""
        return _DATA_TYPE_TO_STRUCT.get(data_type, (None, None))
    
    @staticmethod
    def _get_measurement_type_token(meas_data) -> str:
        """Extract MeasurementType enum token from metadata."""
        try:
            metadata = getattr(meas_data, "metadata", None)
            if metadata is None:
                return ""
            
            # Get ELO metadata
            elo_metadata = getattr(metadata, "elo_metadata", None)
            if elo_metadata is None:
                return ""
            
            vibration_path = getattr(elo_metadata, "vibration_path", 0)

            return OverallValuesExtractor._ENUM_MAP.get(vibration_path, f"Type{vibration_path}")
        except Exception:
            return ""

    @staticmethod
    def _build_duration_details(meas_data) -> str:
        det_parts = []
        try:
            metadata = getattr(meas_data, "metadata", None)
            if metadata:
                elo_meta = getattr(metadata, "elo_metadata", None)
                if elo_meta:
                    duration = getattr(elo_meta, "duration", 0)
                    if duration > 0:
                        det_parts.append(f"Duration: {duration}ms")
        except Exception:
            pass
        return "  •  " + "   ".join(det_parts) if det_parts else ""

    @staticmethod
    def _has_overall_values(overalls) -> bool:
        return any(
            getattr(overalls, field_name, 0) != 0
            for field_name in OverallValuesExtractor._OVERALL_FIELDS
        )

    @staticmethod
    def _extract_int32_value(data_content) -> Optional[int]:
        try:
            if data_content.HasField("int32_data"):
                return data_content.int32_data
            return None
        except (AttributeError, ValueError):
            int32_val = getattr(data_content, "int32_data", 0)
            return int32_val if int32_val != 0 else None

    @classmethod
    def _append_overall_fields(cls, out: List[Dict[str, str]], base_label: str, overalls, details: str) -> None:
        for field_name in cls._OVERALL_FIELDS:
            field_value = getattr(overalls, field_name, 0)
            label = f"{base_label} - {cls.pretty_field_name(field_name)}"
            out.append({"label": label, "value": str(field_value), "details": details})

    @classmethod
    def _summarize_data_bytes(cls, meas_data, data_bytes: bytes) -> Tuple[str, str]:
        num_samples = 0
        try:
            metadata_twf = getattr(meas_data, "metadata_twf", None)
            if metadata_twf:
                elo_twf = getattr(metadata_twf, "elo_metadata_twf", None)
                if elo_twf:
                    data_type = getattr(elo_twf, "data_type", 0)
                    _, bytes_per_sample = cls._data_format_to_struct_code(data_type)
                    if bytes_per_sample:
                        num_samples = len(data_bytes) // bytes_per_sample
        except Exception:
            pass

        value_str = f"{len(data_bytes)} bytes" + (f" ({num_samples} samples)" if num_samples > 0 else "")

        det_parts = []
        try:
            metadata_twf = getattr(meas_data, "metadata_twf", None)
            if metadata_twf:
                elo_twf = getattr(metadata_twf, "elo_metadata_twf", None)
                if elo_twf:
                    sampling_rate = getattr(elo_twf, "sampling_rate", 0)
                    if sampling_rate > 0:
                        det_parts.append(f"Sampling rate: {sampling_rate} Hz")
                    twf_hash = getattr(elo_twf, "twf_hash", 0)
                    if twf_hash > 0:
                        det_parts.append(f"TWF hash: 0x{twf_hash:08X}")
        except Exception:
            pass

        details = "  •  " + "   ".join(det_parts) if det_parts else ""
        return value_str, details
    
    @classmethod
    def extract_overall_values(cls, send_measurement_msg) -> List[Dict[str, str]]:
        """
        Extract overall/metrics values from a send_measurement message.
        Returns list of dicts with keys: label, value, details
        """
        out: List[Dict[str, str]] = []
        
        try:
            meas_data_list = list(getattr(send_measurement_msg, "measurement_data", []))
        except Exception:
            meas_data_list = []
        
        for meas_data in meas_data_list:
            mt_token = cls._get_measurement_type_token(meas_data)
            base_label = cls.pretty_label_from_enum_token(mt_token) if mt_token else "Measurement"

            data_content = getattr(meas_data, "data", None)
            if data_content is None:
                continue

            overalls = getattr(data_content, "measurement_overall", None)
            if overalls is not None:
                if cls._has_overall_values(overalls):
                    details = cls._build_duration_details(meas_data)
                    cls._append_overall_fields(out, base_label, overalls, details)
                    continue

            int32_val = cls._extract_int32_value(data_content)
            if int32_val is not None:
                out.append({"label": base_label, "value": str(int32_val), "details": ""})
                continue

            data_bytes = getattr(data_content, "data_bytes", None)
            if data_bytes is not None and len(data_bytes) > 0:
                value_str, details = cls._summarize_data_bytes(meas_data, data_bytes)
                out.append({"label": base_label, "value": value_str, "details": details})
        
        return out
