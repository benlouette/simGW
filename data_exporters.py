"""
Data Exporters - Centralized export logic for waveforms and sessions
Extracts ~150 lines from BleCycleWorker
"""

import os
import struct
import time
from typing import List, Dict, Optional

BASE_DIR = os.path.dirname(__file__)
CAPTURE_DIR = os.path.join(BASE_DIR, "captures")


class WaveformExporter:
    """Handles waveform capture exports to binary format (protobuf payloads)."""
    
    def __init__(self, capture_dir: str = CAPTURE_DIR):
        """
        Args:
            capture_dir: Directory where captures are saved
        """
        self.capture_dir = capture_dir
        os.makedirs(self.capture_dir, exist_ok=True)
    
    def export_waveform_capture(self, tile_id: int, payloads: list, parsed_msgs: list, 
                               formatter_func=None) -> Dict[str, str]:
        """
        Export waveform capture to binary file only.
        
        Args:
            tile_id: Tile identifier
            payloads: List of raw protobuf payloads
            parsed_msgs: List of parsed AppMessage objects (unused now, kept for compatibility)
            formatter_func: Optional function (unused now, kept for compatibility)
        
        Returns:
            dict: Export info with raw path and count
        """
        ts = time.strftime("%Y%m%d_%H%M%S")
        base = os.path.join(self.capture_dir, f"waveform_tile{tile_id}_{ts}")
        
        raw_path = base + ".bin"
        
        # Write raw binary (4-byte length prefix + payload for each message)
        with open(raw_path, "wb") as f:
            for payload in payloads:
                f.write(len(payload).to_bytes(4, "little"))
                f.write(payload)
        
        return {
            "raw": raw_path,
            "count": len(payloads)
        }


class WaveformParser:
    """Parses waveform exports for plotting and analysis."""
    
    DEFAULT_FS_HZ = 25600.0
    
    @staticmethod
    def pb_read_varint(buf: bytes, i: int):
        """Read protobuf varint from buffer."""
        shift = 0
        val = 0
        n = len(buf)
        while True:
            if i >= n:
                raise ValueError("Truncated varint")
            b = buf[i]
            i += 1
            val |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                return val, i
            shift += 7
            if shift > 70:
                raise ValueError("Varint too long")
    
    @classmethod
    def pb_parse_fields(cls, buf: bytes):
        """Parse protobuf fields from buffer."""
        i = 0
        n = len(buf)
        out = []
        while i < n:
            tag, i = cls.pb_read_varint(buf, i)
            field_no = tag >> 3
            wt = tag & 0x07
            
            if wt == 0:  # Varint
                v, i = cls.pb_read_varint(buf, i)
                out.append((field_no, wt, v))
            elif wt == 2:  # Length-delimited
                ln, i = cls.pb_read_varint(buf, i)
                v = buf[i:i+ln]
                if len(v) != ln:
                    raise ValueError("Truncated length-delimited field")
                i += ln
                out.append((field_no, wt, v))
            elif wt == 5:  # 32-bit
                v = buf[i:i+4]
                if len(v) != 4:
                    raise ValueError("Truncated 32-bit field")
                i += 4
                out.append((field_no, wt, v))
            elif wt == 1:  # 64-bit
                v = buf[i:i+8]
                if len(v) != 8:
                    raise ValueError("Truncated 64-bit field")
                i += 8
                out.append((field_no, wt, v))
            else:
                raise ValueError(f"Unsupported wire type {wt}")
        return out
    
    @classmethod
    def extract_true_waveform_samples(cls, raw_path: str):
        """
        Extract true waveform samples from raw export file.
        
        Args:
            raw_path: Path to .bin export file
        
        Returns:
            tuple: (samples: List[int], metadata: dict)
        """
        import sys
        protocol_dir = os.path.join(os.path.dirname(__file__), "protocol")
        if protocol_dir not in sys.path:
            sys.path.insert(0, protocol_dir)
        
        try:
            import app_pb2
            import measurement_pb2
        except ImportError as e:
            raise RuntimeError(f"Cannot import protocol modules: {e}")
        
        with open(raw_path, "rb") as f:
            raw = f.read()
        
        # Parse export format: repeated [uint32_le payload_len][payload]
        off = 0
        payloads = []
        while off + 4 <= len(raw):
            ln = int.from_bytes(raw[off:off+4], "little", signed=False)
            off += 4
            p = raw[off:off+ln]
            if len(p) != ln:
                break
            off += ln
            payloads.append(p)
        
        # Extract measurement_data.data blocks using protobuf parser
        blocks = []  # (fragment_num, data_bytes)
        fs_hz = cls.DEFAULT_FS_HZ
        twf_type = None
        
        for idx, payload in enumerate(payloads):
            try:
                app_msg = app_pb2.App()
                app_msg.ParseFromString(payload)
                
                # Check if it's a send_measurement message
                if not app_msg.HasField("send_measurement"):
                    continue
                
                meas = app_msg.send_measurement
                fragment_num = app_msg.header.current_fragment if app_msg.HasField("header") else idx
                
                # Iterate through measurement_data
                for meas_data in meas.measurement_data:
                    # Check metadata to confirm it's TWF
                    if meas_data.HasField("metadata"):
                        meta = meas_data.metadata
                        if meta.HasField("elo_metadata"):
                            vib_path = meta.elo_metadata.vibration_path
                            # Check if TWF type (5, 6, or 7)
                            if vib_path in (5, 6, 7):
                                twf_type = vib_path
                    
                    # Get data bytes
                    if meas_data.HasField("data"):
                        data = meas_data.data
                        if data.HasField("data_bytes"):
                            data_bytes = bytes(data.data_bytes)
                            if data_bytes:
                                blocks.append((fragment_num, data_bytes))
                
            except Exception as e:
                # Skip malformed fragments
                continue
        
        if not blocks:
            raise RuntimeError("No TWF data_bytes found in export (new protocol format)")
        
        # Sort by fragment number
        blocks.sort(key=lambda x: x[0])
        
        # Concatenate all data blocks
        blob = b"".join(b for _fn, b in blocks)
        if len(blob) < 2:
            raise RuntimeError("Waveform blob too small")
        if (len(blob) % 2) != 0:
            blob = blob[:-1]
        
        # Unpack as int16 array (little-endian)
        count = len(blob) // 2
        if count <= 0:
            raise RuntimeError("No int16 samples reconstructed")
        
        y = list(struct.unpack("<" + "h" * count, blob))
        
        twf_type_names = {5: "AccelerationTwf", 6: "VelocityTwf", 7: "Enveloper3Twf"}
        
        meta = {
            "blocks": len(blocks),
            "samples": len(y),
            "fs_hz": fs_hz,
            "raw_unit": "int16",
            "twf_type": twf_type_names.get(twf_type, "Unknown") if twf_type else "Unknown",
        }
        
        return y, meta
