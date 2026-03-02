"""
Protobuf Formatters - Centralized protobuf parsing and formatting
Extracts ~200 lines from BleCycleWorker
"""

import re
import struct
from typing import Optional, Dict, List
from google.protobuf import text_format
import os
import sys

BASE_DIR = os.path.dirname(__file__)
FROTO_DIR = os.path.join(BASE_DIR, "froto")
if FROTO_DIR not in sys.path:
    sys.path.insert(0, FROTO_DIR)

import DeviceAppBulletSensor_pb2
import SensingDataUpload_pb2
import Common_pb2


class ProtobufFormatter:
    """Centralized protobuf message parsing and formatting."""
    
    @staticmethod
    def get_message_type(payload: bytes) -> str:
        """Extract message type from protobuf payload."""
        try:
            message = DeviceAppBulletSensor_pb2.AppMessage()
            message.ParseFromString(payload)
            return message.WhichOneof("_messages") or "(none)"
        except Exception:
            return "(parse_error)"
    
    @staticmethod
    def format_payload_readable(payload: bytes) -> str:
        """Format payload as human-readable text."""
        try:
            message = DeviceAppBulletSensor_pb2.AppMessage()
            message.ParseFromString(payload)
            if message.ListFields():
                return text_format.MessageToString(message, as_one_line=False).rstrip()
        except Exception:
            pass
        
        # Fallback to UTF-8 or hex
        try:
            return payload.decode("utf-8", errors="replace")
        except Exception:
            return payload.hex(" ")
    
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
        """Extract waveform samples from data_upload message."""
        rows = []
        try:
            for pair_idx, pair in enumerate(getattr(app_msg.data_upload, "data_pair", [])):
                for field_desc, value in pair.ListFields():
                    if field_desc.label != field_desc.LABEL_REPEATED:
                        continue
                    if field_desc.cpp_type not in (
                        field_desc.CPPTYPE_INT32, field_desc.CPPTYPE_INT64,
                        field_desc.CPPTYPE_UINT32, field_desc.CPPTYPE_UINT64,
                        field_desc.CPPTYPE_FLOAT, field_desc.CPPTYPE_DOUBLE,
                    ):
                        continue
                    for sample_idx, sample in enumerate(value):
                        rows.append((pair_idx, field_desc.name, sample_idx, sample))
        except Exception:
            return []
        return rows


class OverallValuesExtractor:
    """Extracts overall/metrics values from protobuf data_upload messages."""
    
    @staticmethod
    def pretty_label_from_enum_token(token: str) -> str:
        """Convert enum tokens like 'ENVIROMENTAL_TEMPERATURE_CURRENT' into human-friendly labels."""
        if not token:
            return "Value"
        
        t = token.strip()
        t = t.replace("ENVIROMENTAL", "ENVIRONMENTAL")
        
        # Extract suffix
        suffix = ""
        m = re.search(r"_(CURRENT|AVG|MEAN|RMS|MIN|MAX)$", t)
        if m:
            suf = m.group(1)
            suf = suf.upper() if suf in ("RMS", "AVG") else suf.capitalize()
            suffix = f" ({suf})"
            t = t[:-len(m.group(0))]
        
        # Keep last 2-3 relevant parts
        parts = [p for p in t.split("_") if p]
        if len(parts) >= 2 and parts[-1] in ("TEMPERATURE", "HUMIDITY", "VOLTAGE", "PRESSURE"):
            parts = parts[-2:]
        elif len(parts) >= 1:
            parts = parts[-3:] if len(parts) > 3 else parts
        
        s = " ".join(p.capitalize() if p.lower() not in ("rms", "avg") else p.upper() for p in parts)
        s = s.replace("Environmental ", "")
        
        return (s.strip() or "Value") + suffix
    
    @staticmethod
    def pretty_field_name(name: str) -> str:
        """Humanize proto field names like 'acc_rms_mg' -> 'Acc rms mg'."""
        if not name:
            return ""
        return name.replace("_", " ").strip().capitalize()
    
    @staticmethod
    def _data_format_to_struct_code(fmt_name: str):
        """Return (struct_code, bytes_per_sample) or (None, None)."""
        mapping = {
            "FORMAT_INT8": ("b", 1),
            "FORMAT_UINT8": ("B", 1),
            "FORMAT_INT16": ("h", 2),
            "FORMAT_UINT16": ("H", 2),
            "FORMAT_INT32": ("i", 4),
            "FORMAT_UINT32": ("I", 4),
            "FORMAT_FLOAT32": ("f", 4),
            "FORMAT_FLOAT": ("f", 4),
            "FORMAT_DOUBLE64": ("d", 8),
            "FORMAT_DOUBLE": ("d", 8),
        }
        return mapping.get(fmt_name, (None, None))
    
    @staticmethod
    def _get_pair_measure_type_token(pair) -> str:
        """Return enum token name for measurement.measure_type."""
        try:
            meas = getattr(pair, "measurement", None)
            if meas is not None:
                mt = getattr(meas, "measure_type", None)
                if mt is not None:
                    try:
                        fd = meas.DESCRIPTOR.fields_by_name.get("measure_type")
                        if fd and fd.enum_type:
                            return fd.enum_type.values_by_number[int(mt)].name
                    except Exception:
                        pass
                    return str(int(mt)) if isinstance(mt, int) else str(mt)
        except Exception:
            pass
        
        # Fallback to text_format parsing
        try:
            ptxt = text_format.MessageToString(pair, as_one_line=False)
            m = re.search(r"\bmeasure_type\s*:\s*([A-Z0-9_]+)", ptxt)
            if m:
                return m.group(1)
        except Exception:
            pass
        
        return ""
    
    @staticmethod
    def _get_pair_format_token(pair) -> str:
        """Return enum token name for measurement.data_format."""
        try:
            meas = getattr(pair, "measurement", None)
            if meas is not None:
                df = getattr(meas, "data_format", None)
                if df is not None:
                    try:
                        fd = meas.DESCRIPTOR.fields_by_name.get("data_format")
                        if fd and fd.enum_type:
                            return fd.enum_type.values_by_number[int(df)].name
                    except Exception:
                        pass
                    return str(int(df)) if isinstance(df, int) else str(df)
        except Exception:
            pass
        
        try:
            ptxt = text_format.MessageToString(pair, as_one_line=False)
            m = re.search(r"\bdata_format\s*:\s*([A-Z0-9_]+)", ptxt)
            if m:
                return m.group(1)
        except Exception:
            pass
        
        return ""
    
    @staticmethod
    def _get_pair_data_bytes(pair) -> bytes:
        """Extract data bytes from measurement_data.data."""
        try:
            md = getattr(pair, "measurement_data", None)
            if md is not None:
                raw = getattr(md, "data", None)
                if raw is None:
                    return b""
                try:
                    return bytes(raw)
                except Exception:
                    try:
                        return bytes(bytearray(raw))
                    except Exception:
                        return b""
        except Exception:
            return b""
    
    @classmethod
    def extract_overall_values(cls, data_upload_msg) -> List[Dict[str, str]]:
        """
        Extract overall/metrics values from a data_upload message.
        Returns list of dicts with keys: label, value, details
        """
        out = []
        
        try:
            pairs = list(getattr(data_upload_msg, "data_pair", []))
        except Exception:
            pairs = []
        
        # Check endianness
        is_big = False
        try:
            is_big = bool(getattr(data_upload_msg, "is_big_endian", False))
        except Exception:
            pass
        endian = ">" if is_big else "<"
        
        for pair in pairs:
            mt_token = cls._get_pair_measure_type_token(pair)
            label = cls.pretty_label_from_enum_token(mt_token) if mt_token else "Value"
            
            # Primary path: decode bytes payload
            raw = cls._get_pair_data_bytes(pair)
            fmt_token = cls._get_pair_format_token(pair)
            code, bps = cls._data_format_to_struct_code(fmt_token)
            
            values = []
            
            if raw and code and bps:
                n = len(raw) // bps
                if n > 0:
                    raw2 = raw[:n * bps]
                    try:
                        values = list(struct.unpack(endian + (code * n), raw2))
                    except Exception:
                        values = []
            
            # Secondary path: collect scalar fields (legacy / other proto layouts)
            if not values:
                try:
                    for fd, v in pair.ListFields():
                        if fd.name in ("measure_type", "measurement_type", "type", "measurement", "measurement_data"):
                            continue
                        if fd.label == fd.LABEL_REPEATED:
                            try:
                                n = len(v)
                            except Exception:
                                n = 0
                            if n == 1:
                                values.append(v[0])
                            elif n > 1:
                                values.append(f"{n} values")
                            continue
                        if fd.cpp_type in (fd.CPPTYPE_INT32, fd.CPPTYPE_INT64, fd.CPPTYPE_UINT32, 
                                          fd.CPPTYPE_UINT64, fd.CPPTYPE_FLOAT, fd.CPPTYPE_DOUBLE, fd.CPPTYPE_BOOL):
                            values.append(v)
                        elif fd.cpp_type == fd.CPPTYPE_STRING:
                            values.append(v)
                        elif fd.cpp_type == fd.CPPTYPE_ENUM:
                            try:
                                values.append(fd.enum_type.values_by_number[int(v)].name)
                            except Exception:
                                values.append(v)
                except Exception:
                    values = []
            
            # Format value string (raw)
            if isinstance(values, list) and values and all(isinstance(x, (int, float, bool)) for x in values):
                if len(values) == 1:
                    value_str = str(values[0])
                else:
                    head = ", ".join(str(x) for x in values[:6])
                    tail = "" if len(values) <= 6 else f", … ({len(values)} samples)"
                    value_str = head + tail
            elif values:
                value_str = ", ".join(str(x) for x in values)
            else:
                value_str = "—"
            
            # Details (raw debug)
            det_parts = []
            if fmt_token:
                det_parts.append(f"Data format: {fmt_token}")
            
            # sample_time
            try:
                meas = getattr(pair, "measurement", None)
                if meas and hasattr(meas, "sample_time"):
                    det_parts.append(f"Sample time: {int(getattr(meas, 'sample_time'))}")
            except Exception:
                pass
            
            # raw bytes preview
            if raw:
                try:
                    rb = raw[:16]
                    det_parts.append(f"Data: {repr(rb)}" + ("…" if len(raw) > 16 else ""))
                except Exception:
                    pass
            
            # CRC (not verified yet)
            try:
                md = getattr(pair, "measurement_data", None)
                if md and hasattr(md, "crc32_value"):
                    det_parts.append(f"CRC: 0x{int(getattr(md, 'crc32_value')):08X} (TODO)")
            except Exception:
                pass
            
            details = "  •  " + "   ".join(det_parts) if det_parts else ""
            out.append({"label": label, "value": value_str, "details": details})
        
        return out
