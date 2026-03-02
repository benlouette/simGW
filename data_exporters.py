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
        
        # Extract measurement_data.data blocks
        blocks = []  # (start_point, bytes)
        for payload in payloads:
            try:
                top = cls.pb_parse_fields(payload)
            except Exception:
                continue
            
            # Find data_upload (field 2)
            du_list = [v for fn, wt, v in top if fn == 2 and wt == 2]
            if not du_list:
                continue
            du = du_list[0]
            
            try:
                du_fields = cls.pb_parse_fields(du)
            except Exception:
                continue
            
            # Find data_pair (field 4)
            for fn, wt, dp_bytes in du_fields:
                if fn != 4 or wt != 2:
                    continue
                try:
                    dp_fields = cls.pb_parse_fields(dp_bytes)
                except Exception:
                    continue
                
                # Find measurement_data (field 2)
                md_list = [v for f, w, v in dp_fields if f == 2 and w == 2]
                for md in md_list:
                    try:
                        md_fields = cls.pb_parse_fields(md)
                    except Exception:
                        continue
                    
                    start_point = None
                    data_bytes = None
                    for f, w, v in md_fields:
                        if f == 1 and w == 0:  # start_point
                            start_point = int(v)
                        elif f == 2 and w == 2:  # data
                            data_bytes = bytes(v)
                    
                    if data_bytes:
                        blocks.append((start_point, data_bytes))
        
        if not blocks:
            raise RuntimeError("No measurement_data.data blocks found in raw export")
        
        # Sort by start_point if available
        if all(sp is not None for sp, _ in blocks):
            blocks.sort(key=lambda x: x[0])
        
        # Concatenate all data blocks
        blob = b"".join(b for _sp, b in blocks)
        if len(blob) < 2:
            raise RuntimeError("Waveform blob too small")
        if (len(blob) % 2) != 0:
            blob = blob[:-1]
        
        # Unpack as int16 array
        count = len(blob) // 2
        if count <= 0:
            raise RuntimeError("No int16 samples reconstructed")
        
        y = list(struct.unpack("<" + "h" * count, blob))
        
        meta = {
            "blocks": len(blocks),
            "samples": len(y),
            "fs_hz": cls.DEFAULT_FS_HZ,
            "raw_unit": "int16",
        }
        
        return y, meta
