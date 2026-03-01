import asyncio
import csv
import os
import sys
import re
import struct
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from queue import Queue, Empty
from tkinter import ttk, messagebox
from typing import Dict, Optional

from google.protobuf import text_format
from bleak import BleakClient, BleakScanner


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
        for f in (getattr(self, "_csv_f", None), getattr(self, "_txt_f", None), getattr(self, "_bin_f", None)):
            try:
                if f is not None:
                    f.close()
            except Exception:
                pass

    def log(self, direction: str, kind: str, msg_type: str, payload: bytes):
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
        ts_ms = int(time.time() * 1000)
        self._txt_f.write(f"{ts_ms} EVT {text}\n")
        self._txt_f.flush()

try:
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    try:
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    except Exception:
        FigureCanvasTkAgg = None
except Exception:
    plt = None
    Figure = None
    FigureCanvasTkAgg = None

BASE_DIR = os.path.dirname(__file__)
FROTO_DIR = os.path.join(BASE_DIR, "froto")
CAPTURE_DIR = os.path.join(BASE_DIR, "captures")
if FROTO_DIR not in sys.path:
    sys.path.insert(0, FROTO_DIR)

import DeviceAppBulletSensor_pb2
import ConfigurationAndCommand_pb2
import Common_pb2
import FirmwareUpdateOverTheAir_pb2
import Froto_pb2
import SensingDataUpload_pb2


UART_SERVICE_BYTES = [
    0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0,
    0x93, 0xF3, 0xA3, 0xB5, 0x01, 0x00, 0x40, 0x6E,
]
UART_RX_BYTES = [
    0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0,
    0x93, 0xF3, 0xA3, 0xB5, 0x02, 0x00, 0x40, 0x6E,
]
UART_TX_BYTES = [
    0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0,
    0x93, 0xF3, 0xA3, 0xB5, 0x03, 0x00, 0x40, 0x6E,
]

AUTO_RESTART_DELAY_MS = 1500
UI_POLL_INTERVAL_MS = 150

# Phase machine (UI state). Prefer structured 'phase' over parsing status text.
PHASE_SCANNING = "scanning"
PHASE_CONNECTING = "connecting"
PHASE_CONNECTED = "connected"
PHASE_METRICS = "metrics"
PHASE_WAVEFORM = "waveform"
PHASE_CLOSE_SESSION = "close_session"
PHASE_DISCONNECTED = "disconnected"
PHASE_ERROR = "error"

_PHASE_ORDER = [
    PHASE_SCANNING,
    PHASE_CONNECTING,
    PHASE_CONNECTED,
    PHASE_METRICS,
    PHASE_WAVEFORM,
    PHASE_CLOSE_SESSION,
    PHASE_DISCONNECTED,
    PHASE_ERROR,
]

def _phase_rank(phase: str) -> int:
    try:
        return _PHASE_ORDER.index(phase)
    except ValueError:
        return -1

MANUAL_ACTIONS = [
    ("Sync Time", "sync_time"),
    ("Version", "version"),
    ("Config Hash", "config_hash"),
    ("Metrics", "metrics"),
    ("Waveform", "waveform"),
    ("Close", "close_session"),
    ("Connect Test", "connect_test"),
    ("Discover GATT", "discover_gatt"),
    ("Notify Test", "notify_test"),
]

CHECKLIST_ITEMS = [
    ("waiting_connection", "Waiting connection"),
    ("connected", "Connected"),
    ("general_info_exchange", "General info exchange"),
    ("data_collection", "Data collection"),
    ("close_session", "Close session"),
    ("disconnect", "Disconnect"),
]

CHECKLIST_STATE_MAP = {"pending": "☐", "in_progress": "⧗", "done": "☑"}


def _uuid_from_bytes(bytes_list, reverse: bool) -> str:
    ordered = list(reversed(bytes_list)) if reverse else list(bytes_list)
    hex_bytes = [f"{b:02x}" for b in ordered]
    return (
        f"{''.join(hex_bytes[0:4])}-"
        f"{''.join(hex_bytes[4:6])}-"
        f"{''.join(hex_bytes[6:8])}-"
        f"{''.join(hex_bytes[8:10])}-"
        f"{''.join(hex_bytes[10:16])}"
    )


def _get_uart_uuids(reverse: bool) -> tuple:
    service_uuid = _uuid_from_bytes(UART_SERVICE_BYTES, reverse)
    rx_uuid = _uuid_from_bytes(UART_RX_BYTES, reverse)
    tx_uuid = _uuid_from_bytes(UART_TX_BYTES, reverse)
    return service_uuid, rx_uuid, tx_uuid


class WaveformExportTools:
    """Helpers for parsing/exporting/plotting waveform captures."""

    DEFAULT_FS_HZ = 25600.0

    @staticmethod
    def pb_read_varint(buf: bytes, i: int):
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
        i = 0
        n = len(buf)
        out = []
        while i < n:
            tag, i = cls.pb_read_varint(buf, i)
            field_no = tag >> 3
            wt = tag & 0x07
            if wt == 0:
                v, i = cls.pb_read_varint(buf, i)
                out.append((field_no, wt, v))
            elif wt == 2:
                ln, i = cls.pb_read_varint(buf, i)
                v = buf[i:i+ln]
                if len(v) != ln:
                    raise ValueError("Truncated length-delimited field")
                i += ln
                out.append((field_no, wt, v))
            elif wt == 5:
                v = buf[i:i+4]
                if len(v) != 4:
                    raise ValueError("Truncated 32-bit field")
                i += 4
                out.append((field_no, wt, v))
            elif wt == 1:
                v = buf[i:i+8]
                if len(v) != 8:
                    raise ValueError("Truncated 64-bit field")
                i += 8
                out.append((field_no, wt, v))
            else:
                raise ValueError(f"Unsupported wire type {wt}")
        return out

    @classmethod
    def extract_true_twf_samples_from_raw_export(cls, raw_path: str):
        # patch6 export format: repeated [uint32_le payload_len][payload]
        with open(raw_path, "rb") as f:
            raw = f.read()
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

        blocks = []  # (start_point, bytes)
        for payload in payloads:
            try:
                top = cls.pb_parse_fields(payload)
            except Exception:
                continue
            du_list = [v for fn, wt, v in top if fn == 2 and wt == 2]
            if not du_list:
                continue
            du = du_list[0]
            try:
                du_fields = cls.pb_parse_fields(du)
            except Exception:
                continue
            for fn, wt, dp_bytes in du_fields:
                if fn != 4 or wt != 2:
                    continue
                try:
                    dp_fields = cls.pb_parse_fields(dp_bytes)
                except Exception:
                    continue
                md_list = [v for f, w, v in dp_fields if f == 2 and w == 2]
                for md in md_list:
                    try:
                        md_fields = cls.pb_parse_fields(md)
                    except Exception:
                        continue
                    start_point = None
                    data_bytes = None
                    for f, w, v in md_fields:
                        if f == 1 and w == 0:
                            start_point = int(v)
                        elif f == 2 and w == 2:
                            data_bytes = bytes(v)
                    if data_bytes:
                        blocks.append((start_point, data_bytes))

        if not blocks:
            raise RuntimeError("No measurement_data.data blocks found in raw export")

        if all(sp is not None for sp, _ in blocks):
            blocks.sort(key=lambda x: x[0])

        blob = b"".join(b for _sp, b in blocks)
        if len(blob) < 2:
            raise RuntimeError("Waveform blob too small")
        if (len(blob) % 2) != 0:
            blob = blob[:-1]

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


@dataclass
class TileStatus:
    address: str = "—"
    status: str = "Queued"
    rx_text: str = ""



@dataclass
class TileState:
    """Structured state for a tile, used for UI updates (never parse rx_text for logic)."""
    status: str = "Queued"
    address: str = "—"
    session_dir: str = ""
    rx_text: str = ""
    checklist: Dict[str, str] = None  # key -> state
    overall_values: Optional[list] = None
    export_info: Optional[dict] = None
    phase: str = "idle"
    last_export_raw: str = ""


class BleCycleWorker:
    def __init__(self, ui_queue: Queue):
        self.ui_queue = ui_queue
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.uart_service_uuid, self.uart_rx_uuid, self.uart_tx_uuid = _get_uart_uuids(True)
        self._tile_phase_rank = {}  # tile_id -> last phase rank

    
    def start(self) -> None:
        """Start the background asyncio loop thread."""
        try:
            self.thread.start()
        except RuntimeError:
            # Thread already started
            pass

    def _run_loop(self) -> None:
        """Thread target: run an asyncio loop forever."""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _call_soon(self, coro: asyncio.Future) -> None:
        """Schedule a coroutine on the worker loop."""
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _emit(self, tile_id: int, payload: dict) -> None:
            """Centralized UI emitter for tile updates.
            Adds ts_ms automatically. Never raises.
            Also enforces a monotonic 'phase' progression per tile (best-effort).
            """
            try:
                out = dict(payload) if payload is not None else {}
                out.setdefault("ts_ms", int(time.time() * 1000))

                # Keep phase monotonic per tile to avoid confusing UI regressions.
                if "phase" in out and out["phase"]:
                    pr = _phase_rank(str(out["phase"]))
                    prev = self._tile_phase_rank.get(tile_id, -1)
                    if pr >= 0:
                        if prev >= 0 and pr < prev:
                            # Don't regress; keep the last known phase.
                            out["phase"] = _PHASE_ORDER[prev]
                        else:
                            self._tile_phase_rank[tile_id] = pr

                self.ui_queue.put(("tile_update", tile_id, out))
            except Exception:
                # Never crash worker on UI update failure
                pass


    async def _run_cycle(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float, record_sessions: bool, session_root: str,
                        name_contains: str = "", service_uuid_contains: str = "", mfg_id_hex: str = "", mfg_data_hex_contains: str = "") -> None:
        """Backward-compatible wrapper (some versions referenced _run_cycle)."""
        await self._run_cycle_impl(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, record_sessions, session_root,
                                  name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains)

    def run_cycle(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float, record_sessions: bool, session_root: str,
                name_contains: str = "", service_uuid_contains: str = "", mfg_id_hex: str = "", mfg_data_hex_contains: str = "") -> None:
        self._call_soon(self._run_cycle_impl(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, record_sessions, session_root,
                        name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains))

    def run_manual_action(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float, action: str, record_sessions: bool, session_root: str,
                name_contains: str = "", service_uuid_contains: str = "", mfg_id_hex: str = "", mfg_data_hex_contains: str = "") -> None:
        self._call_soon(self._run_manual_action(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, action, record_sessions, session_root,
                        name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains))

    def _adv_matches(self, device, adv, address_prefix: str, name_contains: str, service_uuid_contains: str,
                    mfg_id_hex: str, mfg_data_hex_contains: str) -> bool:
        """
        Match a device against address prefix + optional advertising-content filters.
        All non-empty filters must match.
        """
        try:
            addr = (getattr(device, "address", "") or "").upper()
        except Exception:
            addr = ""
        if address_prefix:
            if not addr.startswith(address_prefix.upper()):
                return False

        # Name filter (device.name or adv.local_name)
        if name_contains:
            nc = name_contains.lower()
            dn = (getattr(device, "name", None) or "").lower()
            aln = (getattr(adv, "local_name", None) if adv is not None else None) or ""
            if (nc not in dn) and (nc not in aln.lower()):
                return False

        # Service UUID contains (substring match on any advertised UUID)
        if service_uuid_contains:
            svc_sub = service_uuid_contains.lower()
            uuids = []
            if adv is not None:
                uuids = list(getattr(adv, "service_uuids", None) or [])
            if not any(svc_sub in (u or "").lower() for u in uuids):
                return False

        # Manufacturer ID + data filters
        if mfg_id_hex or mfg_data_hex_contains:
            mfg = {}
            if adv is not None:
                mfg = getattr(adv, "manufacturer_data", None) or {}

            # normalize mfg id
            mfg_id = None
            if mfg_id_hex:
                s = mfg_id_hex.strip().lower().replace("0x", "")
                try:
                    mfg_id = int(s, 16)
                except ValueError:
                    # invalid filter -> no match
                    return False
                if mfg_id not in mfg:
                    return False

            if mfg_data_hex_contains:
                needle = mfg_data_hex_contains.strip().lower().replace("0x", "").replace(" ", "")
                # allow commas
                needle = needle.replace(",", "")
                if needle:
                    found = False
                    items = mfg.items() if mfg_id is None else [(mfg_id, mfg.get(mfg_id, b""))]
                    for _, v in items:
                        vb = bytes(v) if not isinstance(v, (bytes, bytearray)) else bytes(v)
                        h = vb.hex().lower()
                        if needle in h:
                            found = True
                            break
                    if not found:
                        return False

        return True

    def _format_rx_payload(self, payload: bytes) -> str:
        try:
            message = DeviceAppBulletSensor_pb2.AppMessage()
            message.ParseFromString(payload)
            if message.ListFields():
                return text_format.MessageToString(message, as_one_line=False).rstrip()
        except Exception:
            pass
        try:
            return payload.decode("utf-8", errors="replace")
        except Exception:
            return payload.hex(" ")

    def _pb_message_type(self, payload: bytes) -> str:
        try:
            message = DeviceAppBulletSensor_pb2.AppMessage()
            message.ParseFromString(payload)
            return message.WhichOneof("_messages") or "(none)"
        except Exception:
            return "(parse_error)"

    def _hex_short(self, payload: bytes, max_len: int = 48) -> str:
        if payload is None:
            return ""
        if len(payload) <= max_len:
            return payload.hex(" ")
        return payload[:max_len].hex(" ") + f" ... ({len(payload)} bytes)"


    def _extract_waveform_sample_rows(self, app_msg) -> list:
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


    def _pretty_label_from_enum_token(self, token: str) -> str:
        """
        Convert enum tokens like 'ENVIROMENTAL_TEMPERATURE_CURRENT' into
        a human-friendly label like 'Temperature (Current)'.
        """
        if not token:
            return "Value"

        t = token.strip()

        # Common typos / naming in firmware
        t = t.replace("ENVIROMENTAL", "ENVIRONMENTAL")

        # Preserve common suffixes as "(...)" instead of dropping them
        suffix = ""
        m = re.search(r"_(CURRENT|AVG|MEAN|RMS|MIN|MAX)$", t)
        if m:
            # nicer casing: Current, Avg, Mean, RMS, Min, Max
            suf = m.group(1)
            if suf in ("RMS", "AVG"):
                suf = suf.upper()
            else:
                suf = suf.capitalize()
            suffix = f" ({suf})"
            t = t[: -len(m.group(0))]  # remove "_SUFFIX" from token

        # Keep last 2-3 words usually relevant, but avoid losing context for VOLTAGE, TEMPERATURE, HUMIDITY, etc.
        parts = [p for p in t.split("_") if p]
        if len(parts) >= 2 and parts[-1] in ("TEMPERATURE", "HUMIDITY", "VOLTAGE", "PRESSURE"):
            parts = parts[-2:]
        elif len(parts) >= 1:
            parts = parts[-3:] if len(parts) > 3 else parts

        s = " ".join(p.capitalize() if p.lower() not in ("rms", "avg") else p.upper() for p in parts)

        # Small cleanup
        s = s.replace("Environmental ", "")

        base = s.strip() or "Value"
        return base + suffix

    def _pretty_field_name(self, name: str) -> str:
        """Humanize proto field names like 'acc_rms_mg' -> 'Acc rms mg'."""
        if not name:
            return ""
        return name.replace("_", " ").strip().capitalize()

    def _format_nested_message(self, msg) -> str:
        """
        Format a nested protobuf message into a short, demo-friendly 'A: 1.2, B: 3.4' string.
        Only includes scalar/enum/string fields (no bytes blobs).
        """
        parts = []
        try:
            for fd, v in msg.ListFields():
                # skip internal-ish fields
                if fd.name in ("measure_type", "measurement_type", "type"):
                    continue
                if fd.label == fd.LABEL_REPEATED:
                    try:
                        n = len(v)
                    except Exception:
                        n = 0
                    if n == 0:
                        continue
                    # show small vectors nicely if they look like XYZ
                    if n <= 6 and all(isinstance(x, (int, float, bool)) for x in v):
                        parts.append(f"{self._pretty_field_name(fd.name)}: " + ", ".join(str(x) for x in v))
                    else:
                        parts.append(f"{self._pretty_field_name(fd.name)}: {n} values")
                    continue

                # scalar / enum / string
                if fd.cpp_type in (fd.CPPTYPE_INT32, fd.CPPTYPE_INT64, fd.CPPTYPE_UINT32, fd.CPPTYPE_UINT64,
                                   fd.CPPTYPE_FLOAT, fd.CPPTYPE_DOUBLE, fd.CPPTYPE_BOOL):
                    parts.append(f"{self._pretty_field_name(fd.name)}: {v}")
                elif fd.cpp_type == fd.CPPTYPE_STRING:
                    parts.append(f"{self._pretty_field_name(fd.name)}: {v}")
                elif fd.cpp_type == fd.CPPTYPE_ENUM:
                    try:
                        parts.append(f"{self._pretty_field_name(fd.name)}: {fd.enum_type.values_by_number[int(v)].name}")
                    except Exception:
                        parts.append(f"{self._pretty_field_name(fd.name)}: {v}")
                else:
                    # bytes / nested message inside nested message: ignore to keep summary clean
                    continue
        except Exception:
            pass

        if not parts:
            return "(details unavailable)"
        # Prefer common axis ordering if present
        axis_order = ["X", "Y", "Z"]
        if all(any(p.startswith(a + ":") for p in parts) for a in axis_order):
            # not likely with our format, keep generic
            pass
        return "; ".join(parts)

    def _extract_overall_values(self, data_upload_msg) -> list:
        """
        Extract all (available) measurement values from an overall data_upload message
        into a list of dicts: [{'label': str, 'value': str}, ...]
        Robust to proto changes by using reflection + text_format as fallback.
        """
        out = []
        try:
            pairs = list(getattr(data_upload_msg, "data_pair", []))
        except Exception:
            pairs = []
        for pair in pairs:
            label = None
            # First try: text_format contains "measure_type: XYZ"
            try:
                ptxt = text_format.MessageToString(pair, as_one_line=False)
                m = re.search(r"\bmeasure_type\s*:\s*([A-Z0-9_]+)", ptxt)
                if m:
                    label = self._pretty_label_from_enum_token(m.group(1))
            except Exception:
                pass

            # Second try: direct field
            if label is None:
                try:
                    mt = getattr(pair, "measure_type", None)
                    if isinstance(mt, int):
                        # Try to map through Common_pb2 enums if possible
                        enum_name = None
                        try:
                            for enum_desc in getattr(Common_pb2, "DESCRIPTOR", None).enum_types:
                                if mt in enum_desc.values_by_number:
                                    enum_name = enum_desc.values_by_number[mt].name
                                    break
                        except Exception:
                            enum_name = None
                        label = self._pretty_label_from_enum_token(enum_name or str(mt))
                except Exception:
                    label = None

            # Value(s): collect scalar numeric/string-ish fields excluding measure_type
            values = []
            try:
                for fd, v in pair.ListFields():
                    if fd.name in ("measure_type", "measurement_type", "type"):
                        continue
                    if fd.label == fd.LABEL_REPEATED:
                        # For overall we expect singletons; if array, show count
                        try:
                            n = len(v)
                        except Exception:
                            n = 0
                        if n == 1:
                            values.append(str(v[0]))
                        elif n > 1:
                            values.append(f"{n} values")
                        continue

                    # scalar
                    if fd.cpp_type in (fd.CPPTYPE_INT32, fd.CPPTYPE_INT64, fd.CPPTYPE_UINT32, fd.CPPTYPE_UINT64,
                                       fd.CPPTYPE_FLOAT, fd.CPPTYPE_DOUBLE, fd.CPPTYPE_BOOL):
                        values.append(str(v))
                    elif fd.cpp_type == fd.CPPTYPE_STRING:
                        values.append(str(v))
                    elif fd.cpp_type == fd.CPPTYPE_ENUM:
                        # show enum name if possible
                        try:
                            values.append(fd.enum_type.values_by_number[int(v)].name)
                        except Exception:
                            values.append(str(v))
                    else:
                        # bytes / message
                        try:
                            if hasattr(v, "ListFields"):
                                values.append(self._format_nested_message(v))
                            else:
                                values.append(str(v))
                        except Exception:
                            pass
            except Exception:
                values = []

            if not values:
                # fallback: try to parse "value:" from text
                try:
                    ptxt = text_format.MessageToString(pair, as_one_line=False)
                    m = re.search(r"\bvalue\s*:\s*([-+]?\d+(?:\.\d+)?)", ptxt)
                    if m:
                        values = [m.group(1)]
                except Exception:
                    pass

            if label is None:
                label = f"Metric {len(out) + 1}"
            value_str = ", ".join(values) if values else "—"
            out.append({"label": label, "value": value_str})
        return out

    def _export_waveform_capture(self, tile_id: int, payloads: list, parsed_msgs: list) -> dict:
        os.makedirs(CAPTURE_DIR, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        base = os.path.join(CAPTURE_DIR, f"waveform_tile{tile_id}_{ts}")
        raw_path = base + ".bin"
        idx_path = base + "_index.csv"
        samples_path = base + "_samples.csv"
        with open(raw_path, "wb") as f:
            for payload in payloads:
                f.write(len(payload).to_bytes(4, "little"))
                f.write(payload)
        sample_rows = []
        with open(idx_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["block_index", "payload_len", "msg_type", "total_block", "msg_seq_no", "hex_preview"])
            for i, (payload, msg) in enumerate(zip(payloads, parsed_msgs), start=1):
                msg_type = msg.WhichOneof("_messages") or "(none)"
                total_block = ""
                msg_seq_no = ""
                try:
                    total_block = getattr(msg.data_upload.header, "total_block", "")
                    msg_seq_no = getattr(msg.data_upload.header, "message_seq_no", "")
                except Exception:
                    pass
                w.writerow([i, len(payload), msg_type, total_block, msg_seq_no, self._hex_short(payload, 32)])
                if msg_type == "data_upload":
                    sample_rows.extend((i,) + r for r in self._extract_waveform_sample_rows(msg))
        if sample_rows:
            with open(samples_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["block_index", "pair_index", "field_name", "sample_index", "value"])
                w.writerows(sample_rows)
        else:
            samples_path = ""
        return {"raw": raw_path, "index": idx_path, "samples": samples_path, "count": len(payloads)}

    async def _run_manual_action(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float, action: str, record_sessions: bool, session_root: str,
                            name_contains: str = "", service_uuid_contains: str = "", mfg_id_hex: str = "", mfg_data_hex_contains: str = "") -> None:
        address_prefix = address_prefix.upper()
        name_contains = (name_contains or "").strip()
        service_uuid_contains = (service_uuid_contains or "").strip()
        mfg_id_hex = (mfg_id_hex or "").strip()
        mfg_data_hex_contains = (mfg_data_hex_contains or "").strip()
        # Per-session recorder
        recorder = None
        session_dir = None
        if record_sessions:
            ts = time.strftime("%Y%m%d_%H%M%S")
            session_name = f"sensor{tile_id}_{ts}_{action}"
            recorder = SessionRecorder(session_root, session_name)
            session_dir = recorder.session_dir
            self.ui_queue.put(("tile_update", tile_id, {"session_dir": session_dir}))
            recorder.log_text(f"manual_start:{action}")
        self._emit(tile_id, {"status": f"Manual: {action} / scanning...", "phase": "scanning"})
        self._emit(tile_id, {"checklist": {"waiting_connection": "in_progress"}})
        matched_device = {"value": None}
        found_event = asyncio.Event()

        def _on_device_found(device, advertisement_data):
            if not getattr(device, "address", None):
                return
            if self._adv_matches(device, advertisement_data, address_prefix, name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains):
                if not found_event.is_set():
                    matched_device["value"] = device
                    found_event.set()

        scanner = BleakScanner(_on_device_found)
        await scanner.start()
        try:
            try:
                await asyncio.wait_for(found_event.wait(), timeout=scan_timeout)
            except asyncio.TimeoutError:
                self._emit(tile_id, {"status": "Not found", "address": "—"})
                return
        finally:
            await scanner.stop()

        matched = matched_device["value"]
        if not matched:
            self._emit(tile_id, {"status": "Not found", "address": "—"})
            if recorder is not None:
                recorder.log_text("not_found")
                recorder.close()
            return

        self._emit(tile_id, {"status": f"Manual: {action} / connecting...", "address": matched.address, "phase": "connecting"})
        client = BleakClient(matched.address)
        rx_queue = []
        rx_event = asyncio.Event()

        def _on_notify(_sender: int, data: bytearray) -> None:
            try:
                payload = bytes(data)
                rx_queue.append(payload)
                rx_event.set()
                if recorder is not None:
                    recorder.log("RX", "notify", self._pb_message_type(payload), payload)
            except Exception:
                pass

        async def _wait_next_rx(timeout_s: float) -> bytes:
            loop = asyncio.get_running_loop()
            end_time = loop.time() + timeout_s
            while True:
                if rx_queue:
                    return rx_queue.pop(0)
                rx_event.clear()
                if rx_queue:
                    return rx_queue.pop(0)
                remaining = end_time - loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                await asyncio.wait_for(rx_event.wait(), timeout=remaining)

        next_seq_no = 1
        def _alloc_seq() -> int:
            nonlocal next_seq_no
            v = next_seq_no
            next_seq_no += 1
            return v

        async def _write_app_message(app_msg) -> bytes:
            payload = app_msg.SerializeToString()
            await client.write_gatt_char(self.uart_rx_uuid, payload)
            if recorder is not None:
                recorder.log("TX", "write", self._pb_message_type(payload), payload)
            self.ui_queue.put(("tile_update", tile_id, {"status": f"TX {self._pb_message_type(payload)} ({len(payload)} B)"}))
            return payload

        def _safe_parse_app(payload: bytes):
            msg = DeviceAppBulletSensor_pb2.AppMessage()
            msg.ParseFromString(payload)
            return msg

        def _mk_header() -> Froto_pb2.FrotoHeader:
            return Froto_pb2.FrotoHeader(
                version=1,
                is_up=False,
                message_seq_no=_alloc_seq(),
                time_to_live=3,
                primitive_type=Froto_pb2.SIMPLE_DISSEMINATE,
                message_type=Froto_pb2.NORMAL_MESSAGE,
                total_block=1,
            )

        async def _send_config_time() -> None:
            current_time_ms = int(time.time() * 1000)
            config_pair = ConfigurationAndCommand_pb2.ConfigPair(
                specific_config_item=Common_pb2.CURRENT_TIME,
                time_config_content=ConfigurationAndCommand_pb2.TimeArray(
                    time=[ConfigurationAndCommand_pb2.TimeArrayElement(time=current_time_ms)]
                ),
            )
            config_dissem = ConfigurationAndCommand_pb2.ConfigDisseminate(
                header=_mk_header(),
                appVer=1,
                product=Common_pb2.UNKNOWN_PRODUCT,
                config_pair=[config_pair],
            )
            await _write_app_message(DeviceAppBulletSensor_pb2.AppMessage(appVer=1, config_dissem=config_dissem))

        async def _send_version_retrieve() -> None:
            msg = FirmwareUpdateOverTheAir_pb2.VersionRetrieve(
                header=_mk_header(),
                appVer=1,
                payload=FirmwareUpdateOverTheAir_pb2.CURRENT_VERSION,
            )
            await _write_app_message(DeviceAppBulletSensor_pb2.AppMessage(appVer=1, version_retrieve=msg))

        async def _send_config_hash_retrieve() -> None:
            msg = ConfigurationAndCommand_pb2.ConfigRetrieve(
                header=_mk_header(),
                appVer=1,
                payload=ConfigurationAndCommand_pb2.CURRENT_CONFIG_HASH,
            )
            await _write_app_message(DeviceAppBulletSensor_pb2.AppMessage(appVer=1, config_retrieve=msg))

        async def _send_metrics_selection(sample_time_end_ms: int) -> None:
            measure_types = [
                SensingDataUpload_pb2.MeasurementTypeMsg(measure_type=Common_pb2.ENVIROMENTAL_TEMPERATURE_CURRENT),
                SensingDataUpload_pb2.MeasurementTypeMsg(measure_type=Common_pb2.ENVIROMENTAL_HUMIDITY_CURRENT),
                SensingDataUpload_pb2.MeasurementTypeMsg(measure_type=Common_pb2.VOLTAGE_CURRENT),
            ]
            msg = SensingDataUpload_pb2.DataSelectionDisseminate(
                header=_mk_header(),
                appVer=1,
                product=Common_pb2.UNKNOWN_PRODUCT,
                measure_type=measure_types,
                sample_time_start=0,
                sample_time_end=sample_time_end_ms,
            )
            await _write_app_message(DeviceAppBulletSensor_pb2.AppMessage(appVer=1, data_selection=msg))

        async def _send_vibration_selection(sample_time_end_ms: int) -> None:
            msg = SensingDataUpload_pb2.DataSelectionDisseminate(
                header=_mk_header(),
                appVer=1,
                product=Common_pb2.UNKNOWN_PRODUCT,
                measure_type=[SensingDataUpload_pb2.MeasurementTypeMsg(measure_type=Common_pb2.VIBRATION_ACC_WAVE)],
                sample_time_start=0,
                sample_time_end=sample_time_end_ms,
            )
            await _write_app_message(DeviceAppBulletSensor_pb2.AppMessage(appVer=1, data_selection=msg))

        async def _send_close_session() -> None:
            msg = ConfigurationAndCommand_pb2.CommandDisseminate(
                header=_mk_header(),
                appVer=1,
                command_pair=ConfigurationAndCommand_pb2.CommandPair(command=Common_pb2.CLOSE_SESSION),
            )
            await _write_app_message(DeviceAppBulletSensor_pb2.AppMessage(appVer=1, command_dissem=msg))

        async def _recv_app(timeout_s: float):
            payload = await _wait_next_rx(timeout_s)
            msg = _safe_parse_app(payload)
            msg_type = msg.WhichOneof("_messages") or "(none)"
            return payload, msg, msg_type

        try:
            await client.connect()
            if recorder is not None:
                recorder.log_text(f"connected:{matched.address}")
            self._emit(tile_id, {"checklist": {"waiting_connection": "done", "connected": "done"}, "phase": "connected"})
            if mtu and hasattr(client, "request_mtu"):
                try:
                    await client.request_mtu(mtu)
                except Exception:
                    pass
            await client.start_notify(self.uart_tx_uuid, _on_notify)

            # optional pre-steps required by sensor for many commands
            if action in ("version", "config_hash", "metrics", "waveform", "close_session"):
                await _send_config_time()
                await asyncio.sleep(0.1)

            if action == "connect_test":
                self.ui_queue.put(("tile_update", tile_id, {"status": "Connected (test OK)"}))

            elif action == "discover_gatt":
                try:
                    services = client.services
                    if services is None:
                        services = await client.get_services()
                except Exception:
                    services = await client.get_services()
                gatt_lines = []
                for svc in services:
                    gatt_lines.append(f"[SERVICE] {svc.uuid} ({getattr(svc, 'description', '')})")
                    for ch in getattr(svc, "characteristics", []):
                        props = ",".join(getattr(ch, "properties", []) or [])
                        gatt_lines.append(f"  [CHAR] {ch.uuid} props=[{props}]")
                self.ui_queue.put(("tile_update", tile_id, {
                    "status": "GATT discovered",
                    "rx_text": "\n".join(gatt_lines) if gatt_lines else "(no services)",
                }))

            elif action == "notify_test":
                self.ui_queue.put(("tile_update", tile_id, {"status": "Notify active for 2s (test)"}))
                try:
                    payload = await _wait_next_rx(2.0)
                    rx_type = self._pb_message_type(payload)
                    self.ui_queue.put(("tile_update", tile_id, {
                        "status": f"Notify RX {rx_type}",
                        "rx_text": f"TYPE: {rx_type}\nHEX: {self._hex_short(payload)}\n\n" + self._format_rx_payload(payload),
                    }))
                except asyncio.TimeoutError:
                    self.ui_queue.put(("tile_update", tile_id, {"status": "Notify test timeout (no unsolicited RX)"}))

            elif action == "sync_time":

                self.ui_queue.put(("tile_update", tile_id, {"status": "Time sync sent", "checklist": {"general_info_exchange": "done"}}))

            elif action == "version":
                await _send_version_retrieve()
                payload, _msg, msg_type = await _recv_app(rx_timeout)
                self.ui_queue.put(("tile_update", tile_id, {
                    "status": f"RX {msg_type}",
                    "checklist": {"general_info_exchange": "done"},
                    "rx_text": f"TYPE: {msg_type}\nHEX: {self._hex_short(payload)}\n\n" + self._format_rx_payload(payload),
                }))

            elif action == "config_hash":
                await _send_version_retrieve()
                _, _, _ = await _recv_app(rx_timeout)  # consume version
                await asyncio.sleep(0.1)
                await _send_config_hash_retrieve()
                payload, _msg, msg_type = await _recv_app(rx_timeout)
                self.ui_queue.put(("tile_update", tile_id, {
                    "status": f"RX {msg_type}",
                    "checklist": {"general_info_exchange": "done"},
                    "rx_text": f"TYPE: {msg_type}\nHEX: {self._hex_short(payload)}\n\n" + self._format_rx_payload(payload),
                }))

            elif action == "metrics":
                await _send_version_retrieve()
                _, _, _ = await _recv_app(rx_timeout)
                await asyncio.sleep(0.1)
                await _send_config_hash_retrieve()
                _, _, _ = await _recv_app(rx_timeout)
                await asyncio.sleep(0.1)
                await _send_metrics_selection(int(time.time() * 1000))
                payload, msg, msg_type = await _recv_app(rx_timeout)
                status = f"RX {msg_type}"
                if msg_type == "data_upload":
                    try:
                        status += f" ({len(list(msg.data_upload.data_pair))} metrics)"
                    except Exception:
                        pass
                self.ui_queue.put(("tile_update", tile_id, {
                    "status": status,
                    "checklist": {"general_info_exchange": "done", "data_collection": "done"},
                    "rx_text": f"TYPE: {msg_type}\nHEX: {self._hex_short(payload)}\n\n" + self._format_rx_payload(payload),
                }))

            elif action == "waveform":
                await _send_version_retrieve()
                _, _, _ = await _recv_app(rx_timeout)
                await asyncio.sleep(0.1)
                await _send_config_hash_retrieve()
                _, _, _ = await _recv_app(rx_timeout)
                await asyncio.sleep(0.1)
                await _send_vibration_selection(int(time.time() * 1000))
                received = 0
                expected = None
                last_payload = b""
                last_type = "(none)"
                wave_payloads = []
                wave_msgs = []
                while True:
                    payload, msg, msg_type = await _recv_app(rx_timeout)
                    last_payload, last_type = payload, msg_type
                    if msg_type != "data_upload":
                        break
                    wave_payloads.append(payload)
                    wave_msgs.append(msg)
                    received += 1
                    if expected is None:
                        try:
                            expected = int(msg.data_upload.header.total_block)
                        except Exception:
                            expected = None
                        if expected is not None and expected <= 0:
                            expected = None
                    self._emit(tile_id, {
                        "phase": "waveform",
                        "status": f"Waveform blocks {received}/{expected or '?'}",
                        "checklist": {"general_info_exchange": "done", "data_collection": "in_progress"},
                        "rx_text": f"TYPE: {msg_type}\nHEX: {self._hex_short(payload)}\n\n" + self._format_rx_payload(payload),
                    })
                    if expected is not None and received >= expected:
                        break
                export_info = None
                if wave_payloads:
                    try:
                        export_info = self._export_waveform_capture(tile_id, wave_payloads, wave_msgs)
                    except Exception as export_exc:
                        export_info = {"error": str(export_exc)}
                status_text = f"Waveform done ({received}/{expected or '?'}) last={last_type}"
                rx_text = f"TYPE: {last_type}\nHEX: {self._hex_short(last_payload)}\n\n" + self._format_rx_payload(last_payload) if last_payload else "RX: —"
                if export_info is not None:
                    if "error" in export_info:
                        status_text += " / export failed"
                        rx_text += f"\n\nEXPORT ERROR: {export_info['error']}"
                    else:
                        status_text += f" / exported {export_info['count']} blocks"
                        rx_text += f"\n\nEXPORT:\n- raw: {export_info['raw']}\n- index: {export_info['index']}"
                        if export_info.get("samples"):
                            rx_text += f"\n- samples: {export_info['samples']}"
                self.ui_queue.put(("tile_update", tile_id, {
                    "status": status_text,
                    "checklist": {"general_info_exchange": "done", "data_collection": "done"},
                    "rx_text": rx_text,
                    "export_info": export_info,
                }))

            elif action == "close_session":
                await _send_close_session()
                self._emit(tile_id, {"phase": "close_session", "status": "Close session sent", "checklist": {"close_session": "done"}})

            else:
                raise ValueError(f"Unknown action: {action}")

            try:
                await client.stop_notify(self.uart_tx_uuid)
            except Exception:
                pass

        except Exception as exc:
            self._emit(tile_id, {"status": f"Error: {type(exc).__name__}: {exc}"})
        finally:
            self._emit(tile_id, {"checklist": {"disconnect": "in_progress"}})
            try:
                if client.is_connected:
                    try:
                        await client.stop_notify(self.uart_tx_uuid)
                    except Exception:
                        pass
                    await asyncio.sleep(0.2)
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
            except Exception:
                pass
            if recorder is not None:
                recorder.log_text("disconnect_done")
                recorder.close()
            self._emit(tile_id, {"checklist": {"disconnect": "done"}})
            self._emit(tile_id, {"status": "Disconnected", "phase": "disconnected"})
            self.ui_queue.put(("cycle_done", tile_id))
    async def _collect_waveform_export(self, tile_id: int, _recv_app, rx_timeout: float) -> dict:
        """
        Receive waveform data_upload blocks until total_block is reached (if provided),
        export them to capture files, and return a structured result dict:
            {
              'ok': bool,
              'received': int,
              'expected': int|None,
              'export_info': dict|None,
              'last_payload': bytes,
              'last_type': str,
              'last_rx_text': str,
              'error_info': dict|None
            }
        """
        received = 0
        expected = None
        last_payload = b""
        last_type = "(none)"
        wave_payloads = []
        wave_msgs = []

        wave_rx_timeout = max(float(rx_timeout), 10.0)

        try:
            while True:
                try:
                    data_payload, data_message, data_type = await _recv_app(wave_rx_timeout)
                except asyncio.TimeoutError as exc:
                    return {
                        "ok": False,
                        "received": received,
                        "expected": expected,
                        "export_info": None,
                        "last_payload": last_payload,
                        "last_type": last_type,
                        "last_rx_text": "",
                        "error_info": {"where": "waveform_recv_timeout", "type": type(exc).__name__, "msg": str(exc)},
                    }

                last_payload, last_type = data_payload, data_type

                if data_type != "data_upload":
                    rx_text = (
                        f"TYPE: {self._pb_message_type(data_payload)}\n"
                        f"HEX: {self._hex_short(data_payload)}\n\n"
                        + self._format_rx_payload(data_payload)
                    )
                    return {
                        "ok": False,
                        "received": received,
                        "expected": expected,
                        "export_info": None,
                        "last_payload": last_payload,
                        "last_type": last_type,
                        "last_rx_text": rx_text,
                        "error_info": {"where": "waveform_unexpected_type", "type": "UnexpectedType", "msg": str(data_type)},
                    }

                wave_payloads.append(data_payload)
                wave_msgs.append(data_message)
                received += 1

                if expected is None:
                    try:
                        expected = int(data_message.data_upload.header.total_block)
                        if expected <= 0:
                            expected = None
                    except Exception:
                        expected = None

                rx_text = (
                    f"TYPE: {self._pb_message_type(data_payload)}\n"
                    f"HEX: {self._hex_short(data_payload)}\n\n"
                    + self._format_rx_payload(data_payload)
                )

                self._emit(tile_id, {
                    "phase": "waveform",
                    "status": f"Waveform blocks {received}/{expected or '?'}",
                    "checklist": {"data_collection": "in_progress"},
                    "rx_text": rx_text,
                })

                if expected is not None and received >= expected:
                    break

            export_info = None
            if wave_payloads:
                try:
                    export_info = self._export_waveform_capture(tile_id, wave_payloads, wave_msgs)
                except Exception as export_exc:
                    return {
                        "ok": False,
                        "received": received,
                        "expected": expected,
                        "export_info": None,
                        "last_payload": last_payload,
                        "last_type": last_type,
                        "last_rx_text": rx_text,
                        "error_info": {"where": "waveform_export", "type": type(export_exc).__name__, "msg": str(export_exc)},
                    }

            return {
                "ok": True,
                "received": received,
                "expected": expected,
                "export_info": export_info,
                "last_payload": last_payload,
                "last_type": last_type,
                "last_rx_text": rx_text,
                "error_info": None,
            }
        except Exception as exc:
            return {
                "ok": False,
                "received": received,
                "expected": expected,
                "export_info": None,
                "last_payload": last_payload,
                "last_type": last_type,
                "last_rx_text": "",
                "error_info": {"where": "waveform_collect", "type": type(exc).__name__, "msg": str(exc)},
            }


    async def _run_cycle_impl(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float, record_sessions: bool, session_root: str,
                        name_contains: str = "", service_uuid_contains: str = "", mfg_id_hex: str = "", mfg_data_hex_contains: str = "") -> None:
        address_prefix = address_prefix.upper()
        name_contains = (name_contains or "").strip()
        service_uuid_contains = (service_uuid_contains or "").strip()
        mfg_id_hex = (mfg_id_hex or "").strip()
        mfg_data_hex_contains = (mfg_data_hex_contains or "").strip()
        # Per-session recorder
        recorder = None
        session_dir = None
        if record_sessions:
            ts = time.strftime("%Y%m%d_%H%M%S")
            session_name = f"sensor{tile_id}_{ts}_auto"
            recorder = SessionRecorder(session_root, session_name)
            session_dir = recorder.session_dir
            self.ui_queue.put(("tile_update", tile_id, {"session_dir": session_dir}))
            recorder.log_text("cycle_start")
        self._emit(tile_id, {"status": "Scanning...", "phase": "scanning"})
        self._emit(tile_id, {"checklist": {"waiting_connection": "in_progress"}})
        matched_device = {"value": None}
        found_event = asyncio.Event()

        def _on_device_found(device, advertisement_data):
            if not getattr(device, "address", None):
                return
            if self._adv_matches(device, advertisement_data, address_prefix, name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains):
                if not found_event.is_set():
                    matched_device["value"] = device
                    found_event.set()

        scanner = BleakScanner(_on_device_found)
        await scanner.start()
        try:
            try:
                await asyncio.wait_for(found_event.wait(), timeout=scan_timeout)
            except asyncio.TimeoutError:
                self._emit(tile_id, {"status": "Not found", "address": "—"})
                return
        finally:
            await scanner.stop()

        matched = matched_device["value"]
        if not matched:
            self._emit(tile_id, {"status": "Not found", "address": "—"})
            if recorder is not None:
                recorder.log_text("not_found")
                recorder.close()
            return

        self._emit(tile_id, {"status": "Connecting...", "address": matched.address, "phase": "connecting"})
        client = BleakClient(matched.address)
        rx_queue = []
        rx_event = asyncio.Event()

        def _on_notify(_sender: int, data: bytearray) -> None:
            try:
                payload = bytes(data)
                rx_queue.append(payload)
                rx_event.set()
                if recorder is not None:
                    recorder.log("RX", "notify", self._pb_message_type(payload), payload)
            except Exception:
                pass

        async def _wait_next_rx(timeout_s: float) -> bytes:
            loop = asyncio.get_running_loop()
            end_time = loop.time() + timeout_s
            while True:
                if rx_queue:
                    return rx_queue.pop(0)
                rx_event.clear()
                if rx_queue:
                    return rx_queue.pop(0)
                remaining = end_time - loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                await asyncio.wait_for(rx_event.wait(), timeout=remaining)

        next_seq_no = 1
        def _alloc_seq() -> int:
            nonlocal next_seq_no
            v = next_seq_no
            next_seq_no += 1
            return v

        async def _write_app_message(app_msg) -> bytes:
            payload = app_msg.SerializeToString()
            await client.write_gatt_char(self.uart_rx_uuid, payload)
            if recorder is not None:
                recorder.log("TX", "write", self._pb_message_type(payload), payload)
            self.ui_queue.put(("tile_update", tile_id, {
                "status": f"TX {self._pb_message_type(payload)} ({len(payload)} B)",
            }))
            return payload

        def _safe_parse_app(payload: bytes):
            msg = DeviceAppBulletSensor_pb2.AppMessage()
            msg.ParseFromString(payload)
            return msg

        def _mk_header() -> Froto_pb2.FrotoHeader:
            return Froto_pb2.FrotoHeader(
                version=1,
                is_up=False,
                message_seq_no=_alloc_seq(),
                time_to_live=3,
                primitive_type=Froto_pb2.SIMPLE_DISSEMINATE,
                message_type=Froto_pb2.NORMAL_MESSAGE,
                total_block=1,
            )

        async def _send_config_time() -> None:
            current_time_ms = int(time.time() * 1000)
            config_pair = ConfigurationAndCommand_pb2.ConfigPair(
                specific_config_item=Common_pb2.CURRENT_TIME,
                time_config_content=ConfigurationAndCommand_pb2.TimeArray(
                    time=[ConfigurationAndCommand_pb2.TimeArrayElement(time=current_time_ms)]
                ),
            )
            config_dissem = ConfigurationAndCommand_pb2.ConfigDisseminate(
                header=_mk_header(),
                appVer=1,
                product=Common_pb2.UNKNOWN_PRODUCT,
                config_pair=[config_pair],
            )
            app_message = DeviceAppBulletSensor_pb2.AppMessage(appVer=1, config_dissem=config_dissem)
            await _write_app_message(app_message)

        async def _send_version_retrieve() -> None:
            msg = FirmwareUpdateOverTheAir_pb2.VersionRetrieve(
                header=_mk_header(),
                appVer=1,
                payload=FirmwareUpdateOverTheAir_pb2.CURRENT_VERSION,
            )
            app_message = DeviceAppBulletSensor_pb2.AppMessage(appVer=1, version_retrieve=msg)
            await _write_app_message(app_message)

        async def _send_config_hash_retrieve() -> None:
            msg = ConfigurationAndCommand_pb2.ConfigRetrieve(
                header=_mk_header(),
                appVer=1,
                payload=ConfigurationAndCommand_pb2.CURRENT_CONFIG_HASH,
            )
            app_message = DeviceAppBulletSensor_pb2.AppMessage(appVer=1, config_retrieve=msg)
            await _write_app_message(app_message)

        def _default_metric_measure_types():
            return [
                SensingDataUpload_pb2.MeasurementTypeMsg(measure_type=Common_pb2.ENVIROMENTAL_TEMPERATURE_CURRENT),
                SensingDataUpload_pb2.MeasurementTypeMsg(measure_type=Common_pb2.ENVIROMENTAL_HUMIDITY_CURRENT),
                SensingDataUpload_pb2.MeasurementTypeMsg(measure_type=Common_pb2.VOLTAGE_CURRENT),
            ]

        async def _send_metrics_selection(sample_time_end_ms: int) -> None:
            data_selection = SensingDataUpload_pb2.DataSelectionDisseminate(
                header=_mk_header(),
                appVer=1,
                product=Common_pb2.UNKNOWN_PRODUCT,
                measure_type=_default_metric_measure_types(),
                sample_time_start=0,
                sample_time_end=sample_time_end_ms,
            )
            app_message = DeviceAppBulletSensor_pb2.AppMessage(appVer=1, data_selection=data_selection)
            await _write_app_message(app_message)

        async def _send_vibration_selection(sample_time_end_ms: int) -> None:
            vibration_types = [SensingDataUpload_pb2.MeasurementTypeMsg(measure_type=Common_pb2.VIBRATION_ACC_WAVE)]
            data_selection = SensingDataUpload_pb2.DataSelectionDisseminate(
                header=_mk_header(),
                appVer=1,
                product=Common_pb2.UNKNOWN_PRODUCT,
                measure_type=vibration_types,
                sample_time_start=0,
                sample_time_end=sample_time_end_ms,
            )
            app_message = DeviceAppBulletSensor_pb2.AppMessage(appVer=1, data_selection=data_selection)
            await _write_app_message(app_message)

        async def _send_close_session() -> None:
            command_dissem = ConfigurationAndCommand_pb2.CommandDisseminate(
                header=_mk_header(),
                appVer=1,
                command_pair=ConfigurationAndCommand_pb2.CommandPair(command=Common_pb2.CLOSE_SESSION),
            )
            app_message = DeviceAppBulletSensor_pb2.AppMessage(appVer=1, command_dissem=command_dissem)
            await _write_app_message(app_message)

        async def _recv_app(timeout_s: float):
            payload = await _wait_next_rx(timeout_s)
            msg = _safe_parse_app(payload)
            msg_type = msg.WhichOneof("_messages") or "(none)"
            return payload, msg, msg_type

        try:
            await client.connect()
            if recorder is not None:
                recorder.log_text(f"connected:{matched.address}")
            self._emit(tile_id, {"checklist": {"waiting_connection": "done", "connected": "done"}, "phase": "connected"})
            if mtu and hasattr(client, "request_mtu"):
                try:
                    await client.request_mtu(mtu)
                    self.ui_queue.put(("tile_update", tile_id, {"status": f"MTU requested: {mtu}"}))
                except Exception as exc:
                    self.ui_queue.put(("tile_update", tile_id, {"status": f"MTU request failed: {exc}"}))

            await client.start_notify(self.uart_tx_uuid, _on_notify)
            self.ui_queue.put(("tile_update", tile_id, {"status": "Sending config_dissem...", "checklist": {"general_info_exchange": "in_progress"}}))

            await _send_config_time()

            await asyncio.sleep(0.1)
            self.ui_queue.put(("tile_update", tile_id, {"status": "Sending version_retrieve..."}))
            await _send_version_retrieve()

            try:
                payload, app_message, message_type = await _recv_app(rx_timeout)
            except asyncio.TimeoutError:
                self.ui_queue.put(("tile_update", tile_id, {"status": "RX timeout"}))
            else:
                latest_status = "Received"
                error_info = None
                export_info = None
                overall_values = None
                latest_rx_text = f"TYPE: {message_type}\nHEX: {self._hex_short(payload)}\n\n" + self._format_rx_payload(payload)
                try:
                    if message_type == "current_version_upload":
                        await asyncio.sleep(0.1)
                        self.ui_queue.put(("tile_update", tile_id, {"status": "Sending config_retrieve..."}))
                        await _send_config_hash_retrieve()

                        try:
                            hash_payload, hash_message, hash_type = await _recv_app(rx_timeout)
                        except asyncio.TimeoutError:
                            latest_status = "Config hash timeout"
                        else:
                            try:
                                # print(f"Config hash upload type: {hash_type}")
                                if hash_type == "config_hash_upload":
                                    data_collection_complete = True
                                    last_loop_index = -1
                                    overall_values = None
                                    for loop_index in range(6):
                                        last_loop_index = loop_index
                                        latest_status = "Config hash received"
                                        if loop_index == 0:
                                            self.ui_queue.put(("tile_update", tile_id, {"checklist": {"general_info_exchange": "done", "data_collection": "in_progress"}}))
                                        latest_rx_text = f"TYPE: {self._pb_message_type(hash_payload)}\nHEX: {self._hex_short(hash_payload)}\n\n" + self._format_rx_payload(hash_payload)

                                        current_time_ms = int(time.time() * 1000)
                                        
                                        self._emit(tile_id, {"phase": "metrics", "status": f"Sending data_selection ({loop_index + 1}/6)..."})
                                        await _send_metrics_selection(current_time_ms)

                                        try:
                                            data_payload, data_message, data_type = await _recv_app(rx_timeout)
                                        except asyncio.TimeoutError:
                                            latest_status = "Data upload timeout"
                                            data_collection_complete = False
                                            self.ui_queue.put(("tile_update", tile_id, {"checklist": {"data_collection": "pending"}}))
                                            break
                                        else:
                                            try:
                                                if data_type == "data_upload":
                                                    data_pairs = list(data_message.data_upload.data_pair)
                                                    overall_values = self._extract_overall_values(data_message.data_upload)
                                                    if len(data_pairs) >= 3:
                                                        latest_status = "Data upload received"
                                                    else:
                                                        latest_status = f"Data upload missing metrics ({len(data_pairs)})"
                                                        data_collection_complete = False
                                                    latest_rx_text = f"TYPE: {self._pb_message_type(data_payload)}\nHEX: {self._hex_short(data_payload)}\n\n" + self._format_rx_payload(data_payload)
                                                else:
                                                    latest_status = f"Unexpected reply: {data_type}"
                                                    data_collection_complete = False
                                                    break
                                            except Exception as exc:
                                                latest_status = "Data upload parse error"
                                                error_info = {"where": f"metrics_data_upload_parse(loop_index={loop_index})", "type": type(exc).__name__, "msg": str(exc)}
                                                data_collection_complete = False
                                                self.ui_queue.put(("tile_update", tile_id, {"checklist": {"data_collection": "pending"}}))
                                                break

                                    if data_collection_complete and last_loop_index == 5 and latest_status == "Data upload received":
                                        self.ui_queue.put(("tile_update", tile_id, {"checklist": {"data_collection": "done"}}))
                                    else:
                                        data_collection_complete = False
                                        self.ui_queue.put(("tile_update", tile_id, {"checklist": {"data_collection": "pending"}}))

                                    if data_collection_complete:
                                        current_time_ms = int(time.time() * 1000)
                                        self._emit(tile_id, {"phase": "waveform", "status": "Sending vibration data_selection...", "checklist": {"data_collection": "in_progress"}})
                                        await _send_vibration_selection(current_time_ms)
                                        wf_res = await self._collect_waveform_export(tile_id, _recv_app, rx_timeout)
                                        if wf_res.get("ok"):
                                            export_info = wf_res.get("export_info")
                                            received = int(wf_res.get("received") or 0)
                                            expected = wf_res.get("expected")
                                            latest_rx_text = wf_res.get("last_rx_text") or latest_rx_text
                                            if export_info and isinstance(export_info, dict) and ("error" not in export_info):
                                                latest_status = f"Waveform done ({received}/{expected or '?'}) / exported {export_info.get('count','?')} blocks"
                                                latest_rx_text = latest_rx_text + f"\n\nEXPORT:\n- raw: {export_info.get('raw','')}\n- index: {export_info.get('index','')}"
                                                if export_info.get('samples'):
                                                    latest_rx_text = latest_rx_text + f"\n- samples: {export_info.get('samples','')}"
                                            else:
                                                latest_status = f"Waveform done ({received}/{expected or '?'}) / export failed"
                                                if export_info and isinstance(export_info, dict) and export_info.get('error'):
                                                    latest_rx_text = latest_rx_text + f"\n\nEXPORT ERROR: {export_info.get('error')}"
                                            self._emit(tile_id, {"phase": "waveform", "checklist": {"data_collection": "done"}})
                                            self._emit(tile_id, {"phase": "close_session", "checklist": {"close_session": "in_progress"}})
                                            await asyncio.sleep(0.1)
                                            await _send_close_session()
                                            self._emit(tile_id, {"phase": "close_session", "checklist": {"close_session": "done"}})
                                        else:
                                            data_collection_complete = False
                                            export_info = None
                                            err = wf_res.get('error_info') if isinstance(wf_res, dict) else None
                                            if err:
                                                self._emit(tile_id, {"phase": "waveform", "status": f"Waveform error: {err.get('where','?')} {err.get('type','')} {err.get('msg','')}", "error_info": err})
                                            self.ui_queue.put(("tile_update", tile_id, {"checklist": {"data_collection": "pending"}}))

                                        # end waveform collect

                                else:
                                    latest_status = f"Unexpected reply: {hash_type}"
                                    print(f"--> Config hash upload type: {hash_type}")
                            except Exception as exc:
                                latest_status = "Config hash parse error"
                                error_info = {"where": "config_hash_parse", "type": type(exc).__name__, "msg": str(exc)}
                except Exception as exc:
                    latest_status = "Top-level parse error"
                    error_info = {"where": "top_level_parse", "type": type(exc).__name__, "msg": str(exc)}
                self.ui_queue.put(("tile_update", tile_id, {"status": latest_status, "rx_text": latest_rx_text, "export_info": export_info, "overall_values": overall_values, "error": error_info}))

            try:
                await client.stop_notify(self.uart_tx_uuid)
            except Exception:
                pass
        except Exception as exc:
            self._emit(tile_id, {"status": f"Error: {type(exc).__name__}: {exc}"})
        finally:
            self._emit(tile_id, {"checklist": {"disconnect": "in_progress"}})
            try:
                if client.is_connected:
                    try:
                        await client.stop_notify(self.uart_tx_uuid)
                    except Exception:
                        pass
                    await asyncio.sleep(0.2)
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
            except Exception:
                pass
            # await asyncio.sleep(0.8)
            if recorder is not None:
                recorder.log_text("disconnect_done")
                recorder.close()
            self._emit(tile_id, {"checklist": {"disconnect": "done"}})
            self._emit(tile_id, {"status": "Disconnected", "phase": "disconnected"})
            self.ui_queue.put(("cycle_done", tile_id))


class SimGwV2App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._tk_root = root
        self.root.title("SimGW v2 BLE Loop")
        self.root.geometry("860x620")
        self.root.configure(bg="#0f1115")

        self.ui_queue: Queue = Queue()
        self.worker = BleCycleWorker(self.ui_queue)
        self.worker.start()

        self.tile_counter = 0
        self.tiles: Dict[int, Dict[str, tk.Label]] = {}
        self.auto_run = False
        self._auto_generation = 0
        self._auto_cycle_running = False
        self._auto_active_tile_id = None
        self.latest_export_info = None
        self.latest_overall_values = None
        self.tile_export_info: Dict[int, dict] = {}
        self.tile_state: Dict[int, TileState] = {}
        self._demo_mirrored_tile_id: Optional[int] = None
        self._demo_last_plotted_raw: str = ""

        # Demo tab state
        self.demo_status_var = tk.StringVar(value="Idle")
        self.demo_auto_state_var = tk.StringVar(value="AUTO: OFF")
        self.demo_cycle_state_var = tk.StringVar(value="CYCLE: IDLE")
        self.demo_device_var = tk.StringVar(value="")
        self.demo_export_var = tk.StringVar(value="")
        self.demo_last_overall_values = None
        self.demo_last_overall_rx_text = ""
        self.demo_last_wave_rx_text = ""
        # Demo embedded waveform plot (optional)
        self.demo_plot_fig = None
        self.demo_plot_canvas = None
        self.demo_plot_widget = None
        self.demo_plot_label = None
        self._demo_last_plotted_raw = None
        self.demo_overall_var = tk.StringVar(value="—")
        self.demo_waveform_var = tk.StringVar(value="—")
        self.demo_summary = None
        self.demo_debug = None
        self._log_max_lines = 2000
        # Demo timeline (mirrors the latest Expert tile checklist)
        self.demo_checklist_state = {key: "pending" for key, _title in CHECKLIST_ITEMS}
        self.demo_timeline_labels = {}  # key -> (dot_label, text_label)


        # Devices tab state
        self.devices_tree = None
        self.devices_detail = None
        self._devices_last_scan = []

        self.address_prefix_var = tk.StringVar(value="C4:BD:6A:")
        # Optional advertising-content filter (applied in addition to address prefix when set)
        self.adv_name_contains_var = tk.StringVar(value="IMx-1_ELO")
        self.adv_service_uuid_contains_var = tk.StringVar(value="")
        self.adv_mfg_id_hex_var = tk.StringVar(value="")  # e.g. "004C" or "0x004C"
        self.adv_mfg_data_hex_contains_var = tk.StringVar(value="")  # e.g. "01 02" or "0102"
        self.scan_timeout_var = tk.StringVar(value="60")
        self.rx_timeout_var = tk.StringVar(value="5")
        self.record_sessions_var = tk.BooleanVar(value=True)
        self.session_root_var = tk.StringVar(value="sessions")
        self.mtu_var = tk.StringVar(value="247")

        self._apply_theme()
        self._build_ui()
        self._poll_queue()

    def _apply_theme(self) -> None:
        self.colors = {
            "bg": "#0f1115",
            "panel": "#171a21",
            "panel_alt": "#1f2430",
            "text": "#e6e6e6",
            "muted": "#8b93a1",
            "accent": "#4361ee",
            "accent_alt": "#4cc9f0",
            "ok": "#22c55e",
            "warn": "#f59e0b",
            "bad": "#ef4444",
            "border": "#2a2f3a",
        }

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=self.colors["bg"])
        style.configure("TLabel", background=self.colors["bg"], foreground=self.colors["text"], font=("Segoe UI", 10))
        style.configure("Header.TLabel", background=self.colors["panel"], foreground=self.colors["text"], font=("Segoe UI", 14, "bold"))
        style.configure("Subtle.TLabel", background=self.colors["bg"], foreground=self.colors["muted"])
        style.configure("TEntry", fieldbackground=self.colors["panel_alt"], foreground=self.colors["text"], insertcolor=self.colors["text"])
        style.configure("TButton", background=self.colors["panel"], foreground=self.colors["text"], padding=(10, 6))
        style.configure("Accent.TButton", background=self.colors["accent"], foreground="#0b0f14", padding=(10, 6))
        style.map("Accent.TButton", background=[("active", self.colors["accent_alt"])])

    def _log(self, level: str, msg: str) -> None:
        """Append a timestamped line to the Demo debug console (if present)."""
        try:
            if self.demo_debug is None:
                return
            ts = time.strftime("%H:%M:%S")
            line = f"[{ts}] {level}: {msg}\n"
            self.demo_debug.configure(state=tk.NORMAL)
            self.demo_debug.insert(tk.END, line)
            # Trim to last N lines
            try:
                n_lines = int(self.demo_debug.index("end-1c").split(".")[0])
                if n_lines > int(getattr(self, "_log_max_lines", 2000)):
                    cut = max(1, n_lines // 4)
                    self.demo_debug.delete("1.0", f"{cut}.0")
            except Exception:
                pass
            self.demo_debug.see(tk.END)
            self.demo_debug.configure(state=tk.DISABLED)
        except Exception:
            pass

    
    def _demo_clear_debug(self) -> None:
        """Clear the Demo debug console."""
        try:
            if self.demo_debug is None:
                return
            self.demo_debug.configure(state=tk.NORMAL)
            self.demo_debug.delete("1.0", tk.END)
            self.demo_debug.configure(state=tk.DISABLED)
        except Exception:
            pass


    def _demo_reset_ui_state(self, keep_debug: bool = True) -> None:
        """Reset Demo tab UI state (KPIs, timeline, summary, plot)."""
        try:
            self.demo_status_var.set("Idle")
            self.demo_device_var.set("")
            self.demo_export_var.set("")
            self.demo_overall_var.set("—")
            self.demo_waveform_var.set("—")
        except Exception:
            pass

        # Clear summary box (if present)
        try:
            if self.demo_summary is not None:
                self.demo_summary.configure(state=tk.NORMAL)
                self.demo_summary.delete("1.0", tk.END)
                self.demo_summary.insert(tk.END, "—\n")
                self.demo_summary.configure(state=tk.DISABLED)
        except Exception:
            pass

        # Reset timeline to pending
        try:
            self.demo_checklist_state = {key: "pending" for key, _title in CHECKLIST_ITEMS}
            self._demo_update_timeline({})
        except Exception:
            pass

        # Reset plot
        try:
            if getattr(self, "demo_plot_label", None) is not None:
                self.demo_plot_label.config(text="(waiting for waveform...)")
            if getattr(self, "demo_plot_fig", None) is not None:
                ax = self.demo_plot_fig.axes[0] if self.demo_plot_fig.axes else self.demo_plot_fig.add_subplot(111)
                ax.clear()
                ax.set_title("Waveform (latest)")
                ax.set_xlabel("Sample")
                ax.set_ylabel("Value")
                ax.grid(True, alpha=0.2)
                if getattr(self, "demo_plot_canvas", None) is not None:
                    self.demo_plot_canvas.draw()
        except Exception:
            pass

        # Reset last cached demo data
        try:
            self.demo_last_overall_values = None
            self.demo_last_overall_rx_text = ""
            self.demo_last_wave_rx_text = ""
        except Exception:
            pass

        if not keep_debug:
            self._demo_clear_debug()


    def _build_ui_demo(self, parent: tk.Frame) -> None:
        """Demo-friendly UI: no hex dumps, just KPIs + a timeline + a short summary."""
        panel = tk.Frame(parent, bg=self.colors["bg"])
        panel.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        # Header
        card = tk.Frame(panel, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
        card.pack(fill=tk.X, pady=(0, 12))
        inner = tk.Frame(card, bg=self.colors["panel"])
        inner.pack(fill=tk.X, padx=14, pady=12)

        left = tk.Frame(inner, bg=self.colors["panel"])
        left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            left,
            text="SimGW Demo",
            bg=self.colors["panel"],
            fg=self.colors["text"],
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")
        tk.Label(
            left,
            text="Scan → Connect → Overall → Waveform → Close",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(2, 0))

        right = tk.Frame(inner, bg=self.colors["panel"])
        right.pack(side=tk.RIGHT)
        btns = tk.Frame(right, bg=self.colors["panel"])
        btns.pack(anchor="e")

        self.demo_start_button = ttk.Button(btns, text="Start Auto", style="Accent.TButton", command=self._on_start)
        self.demo_start_button.pack(side=tk.LEFT, padx=(0, 6))

        self.demo_stop_button = ttk.Button(btns, text="Stop", command=self._stop_auto)
        self.demo_stop_button.pack(side=tk.LEFT, padx=(0, 6))

        # Run-state indicators (do not depend on sensor status text)
        run_row = tk.Frame(right, bg=self.colors["panel"])
        run_row.pack(anchor="e", pady=(6, 0))

        tk.Label(run_row, textvariable=self.demo_auto_state_var, bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(run_row, textvariable=self.demo_cycle_state_var, bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)

        # Ensure buttons reflect current state
        self._update_demo_run_controls()

        # KPI grid
        kpi = tk.Frame(panel, bg=self.colors["bg"])
        kpi.pack(fill=tk.X, pady=(0, 12))

        def _kpi_card(title: str, var: tk.StringVar) -> None:
            c = tk.Frame(kpi, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            c.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
            ci = tk.Frame(c, bg=self.colors["panel"])
            ci.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
            tk.Label(ci, text=title, bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
            tk.Label(ci, textvariable=var, bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(2, 0))

        _kpi_card("Status", self.demo_status_var)
        _kpi_card("Device", self.demo_device_var)
        _kpi_card("Overall", self.demo_overall_var)
        _kpi_card("Waveform", self.demo_waveform_var)

        # Timeline (driven by checklist updates from the Expert cycle)
        tl_box = tk.Frame(panel, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
        tl_box.pack(fill=tk.X, pady=(0, 12))
        tl_in = tk.Frame(tl_box, bg=self.colors["panel"])
        tl_in.pack(fill=tk.X, padx=14, pady=10)

        tk.Label(tl_in, text="Timeline", bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")

        tl_row = tk.Frame(tl_in, bg=self.colors["panel"])
        tl_row.pack(fill=tk.X, pady=(6, 0))

        self.demo_timeline_labels = {}
        for key, title in CHECKLIST_ITEMS:
            item = tk.Frame(tl_row, bg=self.colors["panel"])
            item.pack(side=tk.LEFT, padx=(0, 14))

            dot = tk.Label(item, text="●", bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 12, "bold"))
            dot.pack(side=tk.LEFT)
            txt = tk.Label(item, text=title, bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 10))
            txt.pack(side=tk.LEFT, padx=(6, 0))

            self.demo_timeline_labels[key] = (dot, txt)

        # Splitter: Overall (summary) on top, Waveform plot below (resizable)
        panes = tk.PanedWindow(
            panel,
            orient=tk.VERTICAL,
            bg=self.colors["bg"],
            sashrelief=tk.RAISED,
            bd=0,
        )
        panes.pack(fill=tk.BOTH, expand=True)

        # --- Overall / Summary (top pane)
        sum_box = tk.Frame(panes, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
        sum_in = tk.Frame(sum_box, bg=self.colors["panel"])
        sum_in.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)

        tk.Label(
            sum_in,
            text="Overalls",
            bg=self.colors["panel"],
            fg=self.colors["text"],
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")

        self.demo_summary = tk.Text(
            sum_in,
            height=10,
            wrap=tk.WORD,
            bg=self.colors["panel"],
            fg=self.colors["text"],
            bd=0,
        )
        self.demo_summary.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.demo_summary.configure(state=tk.DISABLED)

        # --- Waveform plot (bottom pane)
        plot_box = tk.Frame(panes, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
        plot_in = tk.Frame(plot_box, bg=self.colors["panel"])
        plot_in.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)

        header_row = tk.Frame(plot_in, bg=self.colors["panel"])
        header_row.pack(fill=tk.X)

        tk.Label(
            header_row,
            text="Waveform",
            bg=self.colors["panel"],
            fg=self.colors["text"],
            font=("Segoe UI", 11, "bold"),
        ).pack(side=tk.LEFT)

        self.demo_plot_label = tk.Label(
            header_row,
            text="(waiting for waveform...)",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=("Segoe UI", 10),
        )
        self.demo_plot_label.pack(side=tk.LEFT, padx=(10, 0))

        plot_area = tk.Frame(plot_in, bg=self.colors["panel"])
        plot_area.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        if Figure is None or FigureCanvasTkAgg is None:
            tk.Label(
                plot_area,
                text="Matplotlib/TkAgg not available. Install matplotlib and ensure Tk support to view the waveform plot here.",
                bg=self.colors["panel"],
                fg=self.colors["muted"],
                justify=tk.LEFT,
                wraplength=900,
                font=("Segoe UI", 10),
            ).pack(anchor="w")
            self.demo_plot_fig = None
            self.demo_plot_canvas = None
            self.demo_plot_widget = None
        else:
            self.demo_plot_fig = Figure(figsize=(7.5, 2.6), dpi=100)
            ax = self.demo_plot_fig.add_subplot(111)
            ax.set_title("Waveform (latest)")
            ax.set_xlabel("Sample")
            ax.set_ylabel("Value")
            ax.grid(True, alpha=0.2)

            self.demo_plot_canvas = FigureCanvasTkAgg(self.demo_plot_fig, master=plot_area)
            self.demo_plot_widget = self.demo_plot_canvas.get_tk_widget()
            self.demo_plot_widget.pack(fill=tk.BOTH, expand=True)

        # Add panes with initial proportions (user can resize with the sash)
        panes.add(sum_box, stretch="always")
        panes.add(plot_box, stretch="always")
        # Debug console (last events/errors) — essential for diagnosing parsing/flow issues
        dbg_box = tk.Frame(panel, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
        dbg_box.pack(fill=tk.BOTH, expand=False, pady=(12, 0))
        dbg_in = tk.Frame(dbg_box, bg=self.colors["panel"])
        dbg_in.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)

        hdr = tk.Frame(dbg_in, bg=self.colors["panel"])
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Debug", bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)

        ttk.Button(hdr, text="Clear", command=self._demo_clear_debug).pack(side=tk.RIGHT)

        self.demo_debug = tk.Text(
            dbg_in,
            height=7,
            wrap=tk.NONE,
            bg=self.colors["panel"],
            fg=self.colors["text"],
            bd=0,
            highlightthickness=0,
            font=("Consolas", 9),
        )
        self.demo_debug.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.demo_debug.configure(state=tk.DISABLED)

    def _demo_plot_waveform_from_samples(self, samples_csv_path: str) -> None:
        """Load the exported *_samples.csv and render it in the embedded Demo plot."""
        if not samples_csv_path:
            return
        if self.demo_plot_canvas is None or self.demo_plot_fig is None:
            return
        if not os.path.isfile(samples_csv_path):
            return

        # Read rows and pick the longest series (field_name) to plot
        series = {}  # field_name -> list of (global_index, value)
        try:
            with open(samples_csv_path, "r", encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    try:
                        field = (row.get("field_name") or "").strip()
                        block_i = int(row.get("block_index") or 0)
                        sample_i = int(row.get("sample_index") or 0)
                        val = float(row.get("value") or 0)
                    except Exception:
                        continue
                    # Create a monotonically increasing index across blocks
                    global_i = (block_i - 1) * 10_000_000 + sample_i
                    if field not in series:
                        series[field] = []
                    series[field].append((global_i, val))
        except Exception:
            return

        if not series:
            return

        # Choose the field with most samples
        field = max(series.keys(), key=lambda k: len(series.get(k) or []))
        try:
            if self.demo_plot_label is not None:
                self.demo_plot_label.configure(text=f"{len(series[field])} points")
        except Exception:
            pass
        pts = series[field]
        pts.sort(key=lambda x: x[0])
        # Normalize index to 0..N-1 for display
        y = [v for _, v in pts]
        x = list(range(len(y)))

        try:
            ax = self.demo_plot_fig.axes[0] if self.demo_plot_fig.axes else self.demo_plot_fig.add_subplot(111)
            ax.clear()
            ax.plot(x, y)
            title = "Waveform (latest)"
            if field:
                title = f"Waveform (latest) • {field}"
            ax.set_title(title)
            ax.set_xlabel("Sample")
            ax.set_ylabel("Value")
            ax.grid(True, alpha=0.2)
            self.demo_plot_canvas.draw()
        except Exception:
            pass

    # Tags for nicer key/value rendering
        self.demo_summary.tag_configure("k", foreground=self.colors["muted"], font=("Segoe UI", 10, "bold"))
        self.demo_summary.tag_configure("v", foreground=self.colors["text"], font=("Segoe UI", 10, "normal"))
        self.demo_summary.tag_configure("h", foreground=self.colors["text"], font=("Segoe UI", 10, "bold"))

        # Initialize timeline colors
        self._demo_update_timeline({})

    def _demo_plot_waveform_from_raw_export(self, raw_path: str) -> None:
        """Render waveform in the embedded Demo matplotlib canvas from a raw export .bin file."""
        if not raw_path:
            return
        if self.demo_plot_canvas is None or self.demo_plot_fig is None:
            return
        if not os.path.isfile(raw_path):
            raise FileNotFoundError(raw_path)

        y, meta = WaveformExportTools.extract_true_twf_samples_from_raw_export(raw_path)

        # Update label
        try:
            n = int(meta.get("samples") or len(y))
        except Exception:
            n = len(y)
        if self.demo_plot_label is not None:
            self.demo_plot_label.configure(text=f"{n} samples • {os.path.basename(raw_path)}")

        ax = self.demo_plot_fig.axes[0] if self.demo_plot_fig.axes else self.demo_plot_fig.add_subplot(111)
        ax.clear()
        ax.plot(y)
        ax.set_title("Waveform (latest)")
        ax.set_xlabel("Sample")
        ax.set_ylabel("Amplitude (int16)")
        ax.grid(True, alpha=0.2)
        self.demo_plot_canvas.draw()


    def _build_ui_devices(self, parent: tk.Frame) -> None:
        header = tk.Frame(parent, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
        header.pack(fill=tk.X, padx=16, pady=(16, 10))

        left = tk.Frame(header, bg=self.colors["panel"])
        left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=12, pady=12)
        tk.Label(left, text="Devices & Advertising", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 14, "bold")).pack(anchor="w")
        tk.Label(left, text="Scan BLE devices and inspect advertising payloads", bg=self.colors["panel"], fg=self.colors["muted"]).pack(anchor="w", pady=(2, 0))

        controls = tk.Frame(header, bg=self.colors["panel"])
        controls.pack(side=tk.RIGHT, padx=12, pady=12)

        ttk.Button(controls, text="Scan", style="Accent.TButton", command=self._devices_scan).pack(side=tk.TOP, pady=(0, 6))
        ttk.Button(controls, text="Dump ADV (text)", command=self._on_dump_adv).pack(side=tk.TOP, pady=(0, 6))
        ttk.Button(controls, text="Copy details", command=self._devices_copy_details).pack(side=tk.TOP)

        body = tk.Frame(parent, bg=self.colors["bg"])
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))

        cols = ("address", "name", "rssi", "matched")
        tree = ttk.Treeview(body, columns=cols, show="headings", height=14)
        tree.heading("address", text="Address")
        tree.heading("name", text="Name")
        tree.heading("rssi", text="RSSI")
        tree.heading("matched", text="Match")
        tree.column("address", width=180, anchor="w")
        tree.column("name", width=220, anchor="w")
        tree.column("rssi", width=80, anchor="e")
        tree.column("matched", width=80, anchor="center")
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tree.bind("<<TreeviewSelect>>", self._devices_on_select)
        self.devices_tree = tree

        detail = tk.Frame(body, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
        detail.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(12, 0))

        detail_in = tk.Frame(detail, bg=self.colors["panel"])
        detail_in.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
        tk.Label(detail_in, text="Advertising details", bg=self.colors["panel"], fg=self.colors["muted"]).pack(anchor="w")
        self.devices_detail = tk.Text(detail_in, wrap="none", bg=self.colors["panel"], fg=self.colors["text"], relief=tk.FLAT)
        self.devices_detail.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.devices_detail.insert("1.0", "Click Scan, then select a device.")
        self.devices_detail.configure(state=tk.DISABLED)

        self._devices_last_scan = []  # list of (device, adv)

    def _build_ui_settings(self, parent: tk.Frame) -> None:
        header = tk.Frame(parent, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
        header.pack(fill=tk.X, padx=16, pady=(16, 10))

        left = tk.Frame(header, bg=self.colors["panel"])
        left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=12, pady=12)
        tk.Label(left, text="Settings", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 14, "bold")).pack(anchor="w")
        tk.Label(left, text="Configuration and defaults", bg=self.colors["panel"], fg=self.colors["muted"]).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(parent, bg=self.colors["bg"])
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))

        # Keep settings simple here: record + session dir + timeouts + MTU.
        box = tk.Frame(body, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
        box.pack(fill=tk.X)
        inner = tk.Frame(box, bg=self.colors["panel"])
        inner.pack(fill=tk.X, padx=12, pady=12)

        ttk.Checkbutton(inner, text="Record sessions", variable=self.record_sessions_var).grid(row=0, column=0, sticky="w", padx=(0, 12))
        tk.Label(inner, text="Session dir", bg=self.colors["panel"], fg=self.colors["muted"]).grid(row=0, column=1, sticky="e", padx=(12, 6))
        ttk.Entry(inner, textvariable=self.session_root_var, width=24).grid(row=0, column=2, sticky="w")

        tk.Label(inner, text="Scan timeout (s)", bg=self.colors["panel"], fg=self.colors["muted"]).grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(inner, textvariable=self.scan_timeout_var, width=10).grid(row=1, column=1, sticky="w", pady=(10, 0))

        tk.Label(inner, text="RX timeout (s)", bg=self.colors["panel"], fg=self.colors["muted"]).grid(row=1, column=2, sticky="w", padx=(12, 0), pady=(10, 0))
        ttk.Entry(inner, textvariable=self.rx_timeout_var, width=10).grid(row=1, column=3, sticky="w", pady=(10, 0))

        tk.Label(inner, text="MTU", bg=self.colors["panel"], fg=self.colors["muted"]).grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(inner, textvariable=self.mtu_var, width=10).grid(row=2, column=1, sticky="w", pady=(10, 0))

        util = tk.Frame(body, bg=self.colors["bg"])
        util.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(util, text="Clear Logs", command=self._clear_tiles).pack(side=tk.LEFT)
        ttk.Button(util, text="Stop Auto", command=self._stop_auto).pack(side=tk.LEFT, padx=(8, 0))

    def _devices_scan(self) -> None:
        # Run scan in a background thread to avoid blocking Tkinter.
        timeout = float(self.scan_timeout_var.get() or 5.0)
        self.devices_tree.delete(*self.devices_tree.get_children())
        self._devices_last_scan = []
        self._devices_set_details("Scanning...")

        def worker():
            try:
                res = asyncio.run(BleakScanner.discover(timeout=timeout, return_adv=True))
            except Exception as e:
                self.root.after(0, lambda: self._devices_set_details(f"Scan failed: {e}"))
                return

            pairs = []
            if isinstance(res, dict):
                for _addr, val in res.items():
                    if isinstance(val, tuple) and len(val) == 2:
                        dev, adv = val
                    else:
                        dev, adv = val, None
                    pairs.append((dev, adv))
            elif isinstance(res, list):
                for item in res:
                    if isinstance(item, tuple) and len(item) == 2:
                        dev, adv = item
                    else:
                        dev, adv = item, None
                    pairs.append((dev, adv))

            self.root.after(0, lambda: self._devices_populate(pairs))

        threading.Thread(target=worker, daemon=True).start()

    def _devices_populate(self, pairs):
        self._devices_last_scan = pairs
        addr_prefix, _mtu, _scan_timeout, _rx_timeout, _rec, _sess, name_contains, svc_contains, mfg_id_hex, mfg_data_hex = self._read_runtime_params()
        # reuse existing matching logic by using the same filters as main loop
        matched = []
        for idx, (dev, adv) in enumerate(pairs):
            addr = getattr(dev, "address", "") if not isinstance(dev, str) else dev
            name = getattr(dev, "name", "") if not isinstance(dev, str) else ""
            rssi = getattr(adv, "rssi", None) if adv is not None else None
            ok = self._adv_matches(dev, adv, addr_prefix, name_contains, svc_contains, mfg_id_hex, mfg_data_hex)
            m = "✔" if ok else ""
            self.devices_tree.insert("", "end", iid=str(idx), values=(addr, name or getattr(adv, "local_name", "") if adv else "", rssi if rssi is not None else "", m))
            if ok:
                matched.append(idx)
        self._devices_set_details(f"Found {len(pairs)} devices, matched {len(matched)}. Select a row for details.")

    def _devices_on_select(self, _evt):
        sel = self.devices_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self._devices_last_scan):
            return
        dev, adv = self._devices_last_scan[idx]
        txt = self._format_adv_details(dev, adv)
        self._devices_set_details(txt)

    def _devices_set_details(self, txt: str):
        self.devices_detail.configure(state=tk.NORMAL)
        self.devices_detail.delete("1.0", tk.END)
        self.devices_detail.insert("1.0", txt)
        self.devices_detail.configure(state=tk.DISABLED)

    def _devices_copy_details(self):
        try:
            txt = self.devices_detail.get("1.0", tk.END)
            self._tk_root.clipboard_clear()
            self._tk_root.clipboard_append(txt)
        except Exception:
            pass

    def _format_adv_details(self, device, adv) -> str:
        lines = []
        lines.append(f"Address: {getattr(device, 'address', device)}")
        lines.append(f"Name: {getattr(device, 'name', '')}")
        if adv is None:
            lines.append("No AdvertisingData available.")
            return "\n".join(lines)

        lines.append(f"Local name: {getattr(adv, 'local_name', None)}")
        lines.append(f"RSSI: {getattr(adv, 'rssi', None)}")
        lines.append(f"TX power: {getattr(adv, 'tx_power', None)}")
        su = getattr(adv, "service_uuids", None) or []
        if su:
            lines.append("Service UUIDs:")
            for u in su:
                lines.append(f"  - {u}")
        md = getattr(adv, "manufacturer_data", None) or {}
        if md:
            lines.append("Manufacturer data:")
            for k, v in md.items():
                vv = bytes(v) if not isinstance(v, (bytes, bytearray)) else v
                lines.append(f"  - 0x{k:04X}: {vv.hex()}")
        sd = getattr(adv, "service_data", None) or {}
        if sd:
            lines.append("Service data:")
            for k, v in sd.items():
                vv = bytes(v) if not isinstance(v, (bytes, bytearray)) else v
                lines.append(f"  - {k}: {vv.hex()}")
        return "\n".join(lines)

    def _adv_matches(self, dev, adv, addr_prefix: str, name_contains: str, svc_contains: str, mfg_id_hex: str, mfg_data_hex: str) -> bool:
        # Mirrors the filtering used in the BLE loop; safe for missing fields.
        addr_prefix = (addr_prefix or "").strip().upper()
        if addr_prefix:
            addr = (getattr(dev, "address", "") if not isinstance(dev, str) else str(dev)).upper()
            if not addr.startswith(addr_prefix):
                return False

        if not adv:
            # If no adv data, only address prefix can match.
            return True if addr_prefix else False

        if name_contains:
            n = (getattr(adv, "local_name", "") or "") + " " + (getattr(dev, "name", "") or "")
            if name_contains.lower() not in n.lower():
                return False

        if svc_contains:
            su = getattr(adv, "service_uuids", None) or []
            if not any(svc_contains.lower() in (u or "").lower() for u in su):
                return False

        mfg_id_hex = (mfg_id_hex or "").strip().lower().replace("0x", "")
        mfg_data_hex = (mfg_data_hex or "").strip().lower().replace("0x", "")

        if mfg_id_hex:
            try:
                want_id = int(mfg_id_hex, 16)
            except ValueError:
                want_id = None
            if want_id is not None:
                md = getattr(adv, "manufacturer_data", None) or {}
                if want_id not in md:
                    return False
                if mfg_data_hex:
                    sub = "".join(ch for ch in mfg_data_hex if ch in "0123456789abcdef")
                    try:
                        sub_b = bytes.fromhex(sub)
                    except ValueError:
                        sub_b = b""
                    if sub_b:
                        vv = bytes(md[want_id]) if not isinstance(md[want_id], (bytes, bytearray)) else md[want_id]
                        if sub_b not in vv:
                            return False
        else:
            if mfg_data_hex:
                # if data specified but no id, match any mfg value containing it
                sub = "".join(ch for ch in mfg_data_hex if ch in "0123456789abcdef")
                try:
                    sub_b = bytes.fromhex(sub)
                except ValueError:
                    sub_b = b""
                if sub_b:
                    md = getattr(adv, "manufacturer_data", None) or {}
                    found = False
                    for _k, v in md.items():
                        vv = bytes(v) if not isinstance(v, (bytes, bytearray)) else v
                        if sub_b in vv:
                            found = True
                            break
                    if not found:
                        return False

        return True

    def _build_ui(self) -> None:
        """Build a 4-tab UI (Demo / Expert / Devices / Settings) without changing backend logic."""
        nb = ttk.Notebook(self.root)
        nb.pack(fill=tk.BOTH, expand=True)
        self.notebook = nb

        demo_tab = tk.Frame(nb, bg=self.colors["bg"])
        expert_tab = tk.Frame(nb, bg=self.colors["bg"])
        devices_tab = tk.Frame(nb, bg=self.colors["bg"])
        settings_tab = tk.Frame(nb, bg=self.colors["bg"])

        nb.add(demo_tab, text="Demo")
        nb.add(expert_tab, text="Expert")
        nb.add(devices_tab, text="Devices")
        nb.add(settings_tab, text="Settings")

        self._build_ui_demo(demo_tab)

        # Build existing UI inside Expert tab by temporarily swapping self.root.
        tk_root = self._tk_root
        orig_root = self.root
        self.root = expert_tab
        try:
            self._build_ui_expert()
        finally:
            self.root = orig_root
            self._tk_root = tk_root

        self._build_ui_devices(devices_tab)
        self._build_ui_settings(settings_tab)

    def _demo_update_timeline(self, checklist_update: Dict[str, str]) -> None:
        """Update the Demo timeline dots based on the merged checklist state."""
        # Merge incremental updates
        if checklist_update:
            for k, v in checklist_update.items():
                if k in self.demo_checklist_state:
                    self.demo_checklist_state[k] = v

        # Apply colors
        for key, _title in CHECKLIST_ITEMS:
            state = self.demo_checklist_state.get(key, "pending")
            dot, txt = self.demo_timeline_labels.get(key, (None, None))
            if dot is None or txt is None:
                continue

            if state == "done":
                fg = self.colors.get("ok", self.colors["accent_alt"])
                tfg = self.colors["text"]
            elif state == "in_progress":
                fg = self.colors["accent_alt"]
                tfg = self.colors["text"]
            else:
                fg = self.colors["muted"]
                tfg = self.colors["muted"]

            dot.configure(fg=fg)
            txt.configure(fg=tfg)

    def _demo_extract_key_metrics(self, rx_text: str) -> Dict[str, str]:
        """Best-effort extraction of a few key metrics from protobuf text output."""
        if not rx_text:
            return {}

        # Remove HEX and EXPORT lines
        lines = []
        for ln in (rx_text or "").splitlines():
            if ln.startswith("HEX:") or ln.startswith("EXPORT"):
                continue
            lines.append(ln)
        s = "\n".join(lines)

        def _find_after(token: str) -> Optional[str]:
            # Find token, then look ahead for the first numeric value in the next ~10 lines
            m = re.search(re.escape(token), s)
            if not m:
                return None
            tail = s[m.end():]
            tail_lines = tail.splitlines()[:10]
            tail2 = "\n".join(tail_lines)
            m2 = re.search(r"([-+]?\d+(?:\.\d+)?)", tail2)
            return m2.group(1) if m2 else None

        out = {}
        # These tokens are based on Common_pb2 enum names as they appear in text_format output.
        temp = _find_after("ENVIROMENTAL_TEMPERATURE_CURRENT")
        hum = _find_after("ENVIROMENTAL_HUMIDITY_CURRENT")
        volt = _find_after("VOLTAGE_CURRENT")
        if temp is not None:
            out["Temperature"] = f"{temp}"
        if hum is not None:
            out["Humidity"] = f"{hum}"
        if volt is not None:
            out["Voltage"] = f"{volt}"
        return out

    def _demo_set_kpis_from_rx_text(self, rx_text: str, export_info: Optional[dict]) -> None:
        """Update Demo KPIs (Overall/Waveform) based on the latest received message text."""
        if not rx_text:
            return
        # Identify message type
        msg_type = ""
        m = re.search(r"^TYPE:\s*([^\n]+)", rx_text.strip(), flags=re.MULTILINE)
        if m:
            msg_type = m.group(1).strip()

        # Waveform KPI: prefer export_info when available
        if export_info:
            # If samples were exported we consider waveform OK
            if export_info.get("samples") or export_info.get("raw") or export_info.get("index"):
                # Estimate points (int16, 128 bytes per block => 64 points/block)
                try:
                    count = int(export_info.get("count") or 0)
                except Exception:
                    count = 0
                pts = count * 64 if count else 4096
                self.demo_waveform_var.set(f"OK ({pts} points)")
                # keep export path for expert use only
                path = export_info.get("samples") or export_info.get("index") or export_info.get("raw") or ""
                self.demo_export_var.set(path)

    def _demo_render_summary(self, rx_text: str, overall_values: Optional[list] = None) -> None:
        """Render the Demo 'Overalls' panel.

        Design goals:
        - readable (no protobuf dumps)
        - stable (driven by structured overall_values when available)
        - raw values (no unit conversions)
        """
        if self.demo_summary is None:
            return

        items = overall_values or []

        # Header (use local time for human feedback)
        now_s = time.strftime("%H:%M:%S")
        header = f"Last update: {now_s}   •   Metrics: {len(items) if items else 0}\n\n"

        # Build compact lines: left label column + raw value column
        lines = []
        if items:
            # Stable sorting by label; keep original order for identical labels
            def _key(it):
                try:
                    return (str(it.get("label", "")).strip().lower(),)
                except Exception:
                    return ("",)

            for it in sorted(items, key=_key):
                try:
                    lbl = str(it.get("label", "")).strip() or "Value"
                    val = str(it.get("value", "")).strip() or "—"
                except Exception:
                    lbl, val = "Value", "—"
                # Keep it compact: avoid multi-line values in the list view
                val = " ".join(val.split())
                lines.append(f"{lbl:<28} {val}")
        else:
            # Fallback: show only message type if available (kept minimal)
            msg_type = ""
            try:
                mm = re.search(r"^TYPE:\s*([^\n]+)", (rx_text or "").strip(), flags=re.MULTILINE)
                msg_type = mm.group(1).strip() if mm else ""
            except Exception:
                msg_type = ""
            lines.append("—")
            if msg_type:
                lines.append(f"(last message: {msg_type})")

        self.demo_summary.configure(state=tk.NORMAL)
        self.demo_summary.delete("1.0", tk.END)

        # Use a monospaced feel for alignment if available
        try:
            self.demo_summary.configure(font=("Consolas", 10))
        except Exception:
            pass

        self.demo_summary.insert(tk.END, header)
        self.demo_summary.insert(tk.END, "\n".join(lines) + "\n")
        self.demo_summary.configure(state=tk.DISABLED)

    
    def _demo_render_summary_combined(self) -> None:
        """Render Demo summary with two sections: Overall values + Waveform info (if available)."""
        if self.demo_summary is None:
            return

        overall_values = self.demo_last_overall_values or []
        overall_txt = self.demo_last_overall_rx_text or ""
        wave_txt = self.demo_last_wave_rx_text or ""

        total_block = None
        if wave_txt:
            m2 = re.search(r"\btotal_block:\s*(\d+)", wave_txt)
            if m2:
                try:
                    total_block = int(m2.group(1))
                except Exception:
                    total_block = None

        self.demo_summary.configure(state=tk.NORMAL)
        self.demo_summary.delete("1.0", tk.END)

        self.demo_summary.insert(tk.END, "Overall\n", ("h",))
        if overall_values:
            self.demo_summary.insert(tk.END, f"{len(overall_values)} values\n", ("v",))
            for item in overall_values:
                try:
                    lbl = str(item.get("label", "")).strip()
                    val = str(item.get("value", "")).strip()
                except Exception:
                    lbl, val = "", ""
                if not lbl:
                    lbl = "Value"
                if not val:
                    val = "—"
                self.demo_summary.insert(tk.END, f"• {lbl}: ", ("k",))
                self.demo_summary.insert(tk.END, f"{val}\n", ("v",))
        else:
            if overall_txt:
                pairs = len(re.findall(r"\bdata_pair\s*\{", overall_txt))
                self.demo_summary.insert(tk.END, f"{pairs} pairs\n", ("v",))
            else:
                self.demo_summary.insert(tk.END, "—\n", ("v",))

        self.demo_summary.insert(tk.END, "\nWaveform\n", ("h",))
        if wave_txt:
            blocks = total_block if total_block is not None else "?"
            pts = (total_block * 64) if isinstance(total_block, int) else "?"
            self.demo_summary.insert(tk.END, "Blocks: ", ("k",))
            self.demo_summary.insert(tk.END, f"{blocks}\n", ("v",))
            self.demo_summary.insert(tk.END, "Points: ", ("k",))
            self.demo_summary.insert(tk.END, f"{pts} (int16)\n", ("v",))
        else:
            self.demo_summary.insert(tk.END, "—\n", ("v",))

        self.demo_summary.configure(state=tk.DISABLED)

    def _build_ui_expert(self) -> None:
        header = tk.Frame(self.root, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
        header.pack(fill=tk.X, padx=16, pady=(16, 10))

        left = tk.Frame(header, bg=self.colors["panel"])
        left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=12, pady=12)
        
        tk.Label(left, text="SimGW v2 BLE Loop", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 14, "bold")).pack(anchor="w")
        tk.Label(left, text="Auto-connect / send / receive / disconnect", bg=self.colors["panel"], fg=self.colors["muted"]).pack(anchor="w", pady=(2, 0))

        controls = tk.Frame(header, bg=self.colors["panel"])
        controls.pack(side=tk.RIGHT, padx=12, pady=12)

        self.start_button = ttk.Button(controls, text="Start", style="Accent.TButton", command=self._on_start)
        self.start_button.pack(side=tk.TOP, pady=(0, 6))
        self.stop_auto_button = ttk.Button(controls, text="Stop Auto", command=self._stop_auto)
        self.stop_auto_button.pack(side=tk.TOP, pady=(0, 6))
        self.clear_logs_button = ttk.Button(controls, text="Clear Logs", command=self._clear_tiles)
        self.clear_logs_button.pack(side=tk.TOP)

        self.dump_adv_button = ttk.Button(controls, text="Dump ADV", command=self._on_dump_adv)
        self.dump_adv_button.pack(side=tk.TOP, pady=(6, 0))

        self.record_sessions_check = ttk.Checkbutton(controls, text="Record sessions", variable=self.record_sessions_var)
        self.record_sessions_check.pack(side=tk.TOP, pady=(8, 0))

        form = tk.Frame(self.root, bg=self.colors["bg"])
        form.pack(fill=tk.X, padx=16)

        self._build_field(form, "Address prefix", self.address_prefix_var)
        # Optional advertising filters (leave empty to disable)
        self._build_field(form, "ADV name contains", self.adv_name_contains_var)
        self._build_field(form, "ADV service UUID contains", self.adv_service_uuid_contains_var)
        self._build_field(form, "ADV mfg id (hex)", self.adv_mfg_id_hex_var, width=10)
        self._build_field(form, "ADV mfg data contains (hex)", self.adv_mfg_data_hex_contains_var)
        self._build_field(form, "MTU", self.mtu_var, width=8)
        self._build_field(form, "Scan timeout (s)", self.scan_timeout_var, width=8)
        self._build_field(form, "RX timeout (s)", self.rx_timeout_var, width=8)
        self._build_field(form, "Session dir", self.session_root_var, width=18)

        manual = tk.Frame(self.root, bg=self.colors["bg"])
        manual.pack(fill=tk.X, padx=16, pady=(8, 0))
        tk.Label(manual, text="Manual commands:", bg=self.colors["bg"], fg=self.colors["muted"], font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 8))
        for text_, action_ in MANUAL_ACTIONS:
            ttk.Button(manual, text=text_, command=lambda a=action_: self._start_manual_action(a)).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(manual, text="Plot Latest", command=self._plot_latest_waveform).pack(side=tk.LEFT, padx=(12, 6))

        tiles_frame = tk.Frame(self.root, bg=self.colors["bg"])
        tiles_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(12, 16))

        self.canvas = tk.Canvas(tiles_frame, bg=self.colors["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(tiles_frame, orient="vertical", command=self.canvas.yview)
        self.tiles_container = tk.Frame(self.canvas, bg=self.colors["bg"])

        self.tiles_container.bind(
            "<Configure>",
            lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.create_window((0, 0), window=self.tiles_container, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas.bind_all("<MouseWheel>", self._on_mouse_wheel)
        self.canvas.bind_all("<Shift-MouseWheel>", self._on_mouse_wheel)

    def _build_field(self, parent: tk.Frame, label: str, variable: tk.StringVar, width: int = 16) -> None:
        row = tk.Frame(parent, bg=self.colors["bg"])
        row.pack(side=tk.LEFT, padx=(0, 12))
        tk.Label(row, text=label, bg=self.colors["bg"], fg=self.colors["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        entry = ttk.Entry(row, textvariable=variable, width=width)
        entry.pack(anchor="w")

    def _on_mouse_wheel(self, event: tk.Event) -> None:
        if not self.canvas.winfo_exists():
            return
        if event.delta == 0:
            return
        direction = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(direction, "units")

    def _parse_int_var(self, var: tk.StringVar, default: int) -> int:
        try:
            return int(var.get())
        except ValueError:
            return default

    def _parse_float_var(self, var: tk.StringVar, default: float) -> float:
        try:
            return float(var.get())
        except ValueError:
            return default

    def _read_runtime_params(self) -> tuple:
        address_prefix = self.address_prefix_var.get().strip()
        mtu = self._parse_int_var(self.mtu_var, 247)
        scan_timeout = self._parse_float_var(self.scan_timeout_var, 6.0)
        rx_timeout = self._parse_float_var(self.rx_timeout_var, 5.0)
        record_sessions = bool(self.record_sessions_var.get())
        session_root = self.session_root_var.get().strip() or "sessions"
        name_contains = self.adv_name_contains_var.get().strip()
        service_uuid_contains = self.adv_service_uuid_contains_var.get().strip()
        mfg_id_hex = self.adv_mfg_id_hex_var.get().strip()
        mfg_data_hex_contains = self.adv_mfg_data_hex_contains_var.get().strip()
        return address_prefix, mtu, scan_timeout, rx_timeout, record_sessions, session_root, name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains

    def _safe_destroy(self, widget) -> None:
        if widget is None:
            return
        try:
            widget.destroy()
        except Exception:
            pass

    def _clear_tiles(self) -> None:
        self._stop_auto()
        for tile in list(self.tiles.values()):
            self._safe_destroy(tile.get("card"))
        self.tiles.clear()
        self.tile_export_info.clear()
        self.latest_export_info = None
        self.latest_overall_values = None
        self.tile_counter = 0

    def _reset_auto_state(self, increment_generation: bool = True) -> None:
        self.auto_run = False
        if increment_generation:
            self._auto_generation += 1
        self._auto_cycle_running = False
        self._auto_active_tile_id = None


    def _update_demo_run_controls(self) -> None:
        """
        Update Demo Start/Stop controls and explicit run indicators.
        Notes:
        - "Stop" stops auto-restart immediately, but the currently running BLE cycle
          is not forcibly cancelled (it will finish and then auto_run stays OFF).
        """
        auto = bool(getattr(self, "auto_run", False))
        running = bool(getattr(self, "_auto_cycle_running", False))

        if auto and running:
            cycle = "RUNNING"
        elif auto and (not running):
            cycle = "WAITING"
        elif (not auto) and running:
            cycle = "STOPPING"
        else:
            cycle = "IDLE"

        try:
            self.demo_auto_state_var.set("AUTO: ON" if auto else "AUTO: OFF")
            self.demo_cycle_state_var.set(f"CYCLE: {cycle}")
        except Exception:
            pass

        # Button enable/disable
        try:
            if hasattr(self, "demo_start_button") and self.demo_start_button is not None:
                self.demo_start_button.configure(state=("disabled" if auto else "normal"))
        except Exception:
            pass

        try:
            if hasattr(self, "demo_stop_button") and self.demo_stop_button is not None:
                # Allow stop while auto is ON, or while a cycle is still running (stopping)
                enable_stop = auto or running
                self.demo_stop_button.configure(state=("normal" if enable_stop else "disabled"))
                # Clarify semantics when a cycle is active
                if running:
                    self.demo_stop_button.configure(text="Stop (after cycle)")
                else:
                    self.demo_stop_button.configure(text="Stop")
        except Exception:
            pass
    def _new_tile_for_run(self) -> int:
        self.tile_counter += 1
        tile_id = self.tile_counter
        self._create_tile(tile_id)
        return tile_id

    def _start_worker_cycle(self, tile_id: int, action: str = None) -> None:
        address_prefix, mtu, scan_timeout, rx_timeout, record_sessions, session_root, name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains = self._read_runtime_params()
        if action is None:
            self.worker.run_cycle(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, record_sessions, session_root, name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains)
        else:
            self.worker.run_manual_action(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, action, record_sessions, session_root, name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains)

    def _on_start(self) -> None:
        self._reset_auto_state()
        self.auto_run = True
        self._update_demo_run_controls()
        self._start_cycle(expected_generation=self._auto_generation)

    def _start_cycle(self, expected_generation: int = None) -> None:
        if not self.auto_run:
            return
        if expected_generation is not None and expected_generation != self._auto_generation:
            return
        if self._auto_cycle_running:
            return
        self._auto_cycle_running = True
        self._update_demo_run_controls()
        tile_id = self._new_tile_for_run()
        self._auto_active_tile_id = tile_id
        self._start_worker_cycle(tile_id)

    def _start_manual_action(self, action: str) -> None:
        self._reset_auto_state()
        self._update_demo_run_controls()
        tile_id = self._new_tile_for_run()
        self._start_worker_cycle(tile_id, action=action)

    def _stop_auto(self) -> None:
        self._reset_auto_state()
        try:
            self.demo_status_var.set("Idle")
        except Exception:
            pass
        self._update_demo_run_controls()

    def _schedule_next_auto(self, generation: int) -> None:
        def _cb() -> None:
            self._start_cycle(expected_generation=generation)
        self.root.after(AUTO_RESTART_DELAY_MS, _cb)

    def _create_tile(self, tile_id: int) -> None:
        card = tk.Frame(
            self.tiles_container,
            bg=self.colors["panel"],
            highlightbackground=self.colors["border"],
            highlightthickness=1,
        )
        card.pack(fill=tk.X, padx=6, pady=6)

        header = tk.Frame(card, bg=self.colors["panel"])
        header.pack(fill=tk.X, padx=12, pady=(10, 4))

        index_label = tk.Label(header, text=f"Sensor #{tile_id}", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 11, "bold"))
        index_label.pack(side=tk.LEFT)

        status_label = tk.Label(header, text="Queued", bg=self.colors["panel"], fg=self.colors["accent_alt"], font=("Segoe UI", 10, "bold"))
        status_label.pack(side=tk.RIGHT)

        body = tk.Frame(card, bg=self.colors["panel"])
        body.pack(fill=tk.X, padx=12, pady=(0, 10))

        address_label = tk.Label(body, text="Address: —", bg=self.colors["panel"], fg=self.colors["muted"])
        address_label.pack(anchor="w")

        session_label = tk.Label(body, text="Session: —", bg=self.colors["panel"], fg=self.colors["muted"])
        session_label.pack(anchor="w")

        checklist_frame = tk.Frame(body, bg=self.colors["panel"])
        checklist_frame.pack(anchor="w", pady=(6, 2))

        checklist_items = CHECKLIST_ITEMS
        checklist_labels: Dict[str, tk.Label] = {}
        checklist_titles: Dict[str, str] = {}
        for key, title in checklist_items:
            label = tk.Label(checklist_frame, text=f"☐ {title}", bg=self.colors["panel"], fg=self.colors["muted"])
            label.pack(anchor="w")
            checklist_labels[key] = label
            checklist_titles[key] = title

        rx_label = tk.Label(body, text="RX: —", bg=self.colors["panel"], fg=self.colors["text"], wraplength=720, justify="left")
        rx_label.pack(anchor="w", pady=(4, 0))

        plot_btn = ttk.Button(body, text="Plot export", command=lambda tid=tile_id: self._plot_tile_waveform(tid))
        plot_btn.pack(anchor="w", pady=(6, 0))

        self.tiles[tile_id] = {
            "card": card,
            "status": status_label,
            "address": address_label,
            "session": session_label,
            "rx": rx_label,
            "checklist": checklist_labels,
            "checklist_titles": checklist_titles,
            "plot_btn": plot_btn,
        }


    def _plot_export_info(self, export_info: Optional[dict], title: str, empty_msg: str) -> None:
        if not export_info:
            messagebox.showinfo("Waveform plot", empty_msg)
            return
        self._plot_waveform_from_export(export_info, title=title)

    def _plot_tile_waveform(self, tile_id: int) -> None:
        self._plot_export_info(
            self.tile_export_info.get(tile_id),
            title=f"Tile {tile_id}",
            empty_msg=f"No export available yet for tile {tile_id}.",
        )

    def _plot_latest_waveform(self) -> None:
        self._plot_export_info(
            self.latest_export_info,
            title="Latest waveform export",
            empty_msg="No waveform export available yet.",
        )


    def _plot_waveform_from_export(self, export_info: dict, title: str = "Waveform") -> None:
        if plt is None:
            messagebox.showerror("Waveform plot", "matplotlib is not installed.\nInstall with: pip install matplotlib")
            return
        raw_path = export_info.get("raw") if isinstance(export_info, dict) else None
        samples_path = export_info.get("samples") if isinstance(export_info, dict) else None
        index_path = export_info.get("index") if isinstance(export_info, dict) else None
        try:
            # Preferred path: reconstruct true time waveform from raw protobuf payloads export
            if raw_path and os.path.exists(raw_path):
                y, meta = WaveformExportTools.extract_true_twf_samples_from_raw_export(raw_path)
                fs = float(meta.get("fs_hz", 0.0) or 0.0)
                x = list(range(len(y)))
                xlabel = "Sample index"
                if fs > 0.0:
                    x = [i / fs for i in range(len(y))]
                    xlabel = f"Time (s) @ Fs={fs:g} Hz"
                plt.figure()
                plt.plot(x, y)
                plt.title(f"{title} (reconstructed TWF, {meta.get('samples', len(y))} samples)")
                plt.xlabel(xlabel)
                plt.ylabel("Acceleration (raw int16)")
                plt.grid(True)
                plt.show()
                return

            # Fallback 1: generic samples.csv plot (debug)
            if samples_path and os.path.exists(samples_path):
                with open(samples_path, "r", newline="", encoding="utf-8") as f:
                    r = csv.DictReader(f)
                    rows = list(r)
                if not rows:
                    raise RuntimeError("samples.csv is empty")
                numeric_cols = []
                for h in (r.fieldnames or []):
                    vals = []
                    ok = True
                    for row in rows[: min(len(rows), 200)]:
                        v = row.get(h, "")
                        if v in (None, ""):
                            continue
                        try:
                            vals.append(float(v))
                        except Exception:
                            ok = False
                            break
                    if ok and vals:
                        numeric_cols.append(h)
                if not numeric_cols:
                    raise RuntimeError("No numeric columns in samples.csv")
                prefer = [h for h in numeric_cols if h.lower() not in ("block_index", "msg_seq_no", "total_block")]
                plot_cols = (prefer or numeric_cols)[:4]
                x = list(range(len(rows)))
                plt.figure()
                for col in plot_cols:
                    y = []
                    for row in rows:
                        try:
                            y.append(float(row.get(col, "nan")))
                        except Exception:
                            y.append(float("nan"))
                    plt.plot(x, y, label=col)
                plt.title(f"{title} (samples.csv fallback)")
                plt.xlabel("Row")
                plt.ylabel("Value")
                if len(plot_cols) > 1:
                    plt.legend()
                plt.grid(True)
                plt.show()
                return

            # Fallback 2: payload lengths only (debug)
            if index_path and os.path.exists(index_path):
                with open(index_path, "r", newline="", encoding="utf-8") as f:
                    r = csv.DictReader(f)
                    rows = list(r)
                if not rows:
                    raise RuntimeError("index.csv is empty")
                x = []
                y = []
                for i, row in enumerate(rows, start=1):
                    x.append(i)
                    try:
                        y.append(float(row.get("payload_len", "nan")))
                    except Exception:
                        y.append(float("nan"))
                plt.figure()
                plt.plot(x, y, label="payload_len")
                plt.title(f"{title} (index payload lengths fallback)")
                plt.xlabel("Block")
                plt.ylabel("Payload length")
                plt.grid(True)
                plt.legend()
                plt.show()
                return
            raise RuntimeError("No export files found")
        except Exception as e:
            messagebox.showerror("Waveform plot", f"Unable to plot waveform: {e}")

    def _handle_ui_event(self, event) -> None:
        kind = event[0]
        if kind == "tile_update":
            _, tile_id, payload = event
            self._apply_tile_update(tile_id, payload)
            return
        if kind == "cycle_done":
            _, done_tile_id = event
            if done_tile_id == self._auto_active_tile_id:
                self._auto_cycle_running = False
                self._auto_active_tile_id = None
                self._update_demo_run_controls()
                if self.auto_run:
                    self._schedule_next_auto(self._auto_generation)

    def _poll_queue(self) -> None:
        try:
            while True:
                event = self.ui_queue.get_nowait()
                self._handle_ui_event(event)
                self.ui_queue.task_done()
        except Empty:
            pass
        self.root.after(UI_POLL_INTERVAL_MS, self._poll_queue)

    
    def _apply_tile_update(self, tile_id: int, payload: Dict[str, str]) -> None:

        # Surface structured errors in Demo Debug
        try:
            err = payload.get("error")
        except Exception:
            err = None
        if err:
            self._log("ERR", f"tile{tile_id}: {err.get('where','?')} {err.get('type','')} {err.get('msg','')}")
        tile = self.tiles.get(tile_id)
        if not tile:
            return

        # --- Update structured state first (never derive logic from rx_text) ---
        st = self.tile_state.get(tile_id)
        if st is None:
            st = TileState(checklist={key: "pending" for key, _t in CHECKLIST_ITEMS})
            self.tile_state[tile_id] = st

        if "status" in payload:
            st.status = payload.get("status", "") or st.status
        if "phase" in payload:
            st.phase = payload.get("phase", st.phase) or st.phase
        if "address" in payload:
            st.address = payload.get("address", st.address) or st.address
        if "session_dir" in payload:
            st.session_dir = payload.get("session_dir", st.session_dir) or st.session_dir
        if "rx_text" in payload:
            st.rx_text = payload.get("rx_text", st.rx_text) or st.rx_text
        if "overall_values" in payload and payload.get("overall_values") is not None:
            st.overall_values = payload.get("overall_values")
            self.latest_overall_values = st.overall_values
        if "export_info" in payload and payload.get("export_info"):
            st.export_info = payload.get("export_info")
            self.tile_export_info[tile_id] = st.export_info
            self.latest_export_info = st.export_info
            try:
                st.last_export_raw = (st.export_info or {}).get("raw") or st.last_export_raw
            except Exception:
                pass
        if "checklist" in payload:
            try:
                for k, v in (payload.get("checklist") or {}).items():
                    st.checklist[k] = v
            except Exception:
                pass

        # --- Update Expert tile widgets ---
        if "status" in payload:
            tile["status"].configure(text=payload["status"])
        if "address" in payload:
            tile["address"].configure(text=f"Address: {payload['address']}")
        if "session_dir" in payload:
            tile["session"].configure(text=f"Session: {payload['session_dir']}")
        if "rx_text" in payload:
            tile["rx"].configure(text=f"RX: {payload['rx_text']}")

        if "checklist" in payload:
            labels = tile.get("checklist", {})
            titles = tile.get("checklist_titles", {})
            for key, state in (payload.get("checklist") or {}).items():
                label = labels.get(key)
                title = titles.get(key, key)
                if label:
                    symbol = CHECKLIST_STATE_MAP.get(state, "☐")
                    label.configure(text=f"{symbol} {title}")


        # --- Demo mirror: mirror ONE active tile (structured payload only) ---
        # We keep showing the last connected tile while the next scan runs.
        # Switch the Demo mirror to a new tile only when it starts connecting / becomes connected.
        active_demo_tile = getattr(self, "_demo_mirrored_tile_id", None)
        if active_demo_tile is None:
            active_demo_tile = tile_id
            self._demo_mirrored_tile_id = tile_id

        if tile_id != active_demo_tile:
            status_txt = (st.status or "").lower()
            checklist = st.checklist or {}
            is_connected = (checklist.get("connected") == "done") or (checklist.get("waiting_connection") == "done")
            phase = (st.phase or "").lower()
            is_connecting = (phase == "connecting") or ("connecting" in status_txt)
            if is_connected or is_connecting:
                # Switch Demo to this new tile and reset panels at connection start.
                self._demo_mirrored_tile_id = tile_id
                active_demo_tile = tile_id
                try:
                    self.demo_last_overall_values = None
                    self.demo_overall_var.set("—")
                    self.demo_waveform_var.set("—")
                    self.demo_export_var.set("")
                    self._demo_last_plotted_raw = None
                    if self.demo_plot_label is not None:
                        self.demo_plot_label.configure(text="(waiting for waveform...)")
                    if self.demo_plot_canvas is not None and self.demo_plot_fig is not None:
                        ax = self.demo_plot_fig.axes[0] if self.demo_plot_fig.axes else self.demo_plot_fig.add_subplot(111)
                        ax.clear()
                        ax.set_title("Waveform (latest)")
                        ax.set_xlabel("Sample")
                        ax.set_ylabel("Amplitude (int16)")
                        ax.grid(True, alpha=0.2)
                        self.demo_plot_canvas.draw()
                except Exception:
                    pass

        # If this update is not for the active Demo tile, do not overwrite Demo UI.
        if tile_id != active_demo_tile:
            # Keep overall/waveform from the last connected tile, but reflect current activity
            # (Scanning/Connecting/Disconnected) so the Demo doesn't look "stuck".
            try:
                self.demo_status_var.set(st.status or "")
                name_txt = tile.get("name").cget("text") if tile.get("name") else ""
                addr_txt = tile.get("address").cget("text") if tile.get("address") else ""
                self.demo_device_var.set((name_txt + " " + addr_txt).strip())
                if st.checklist:
                    self._demo_update_timeline(st.checklist)
            except Exception:
                pass
            return

        try:
            self.demo_status_var.set(st.status or "")
            # device label uses the tile's rendered labels
            name_txt = tile.get("name").cget("text") if tile.get("name") else ""
            addr_txt = tile.get("address").cget("text") if tile.get("address") else ""
            self.demo_device_var.set((name_txt + " " + addr_txt).strip())

            # timeline
            if st.checklist:
                self._demo_update_timeline(st.checklist)

            # KPIs driven by structured info + rx_text only for display
            self._demo_set_kpis_from_rx_text(st.rx_text or "", st.export_info if st.export_info else None)

            # Overalls: driven only by structured overall_values
            if st.overall_values is not None:
                self.demo_last_overall_values = st.overall_values
                try:
                    n = len(self.demo_last_overall_values) if self.demo_last_overall_values is not None else 0
                    self.demo_overall_var.set(f"{n} metrics" if n > 0 else "—")
                except Exception:
                    self.demo_overall_var.set("—")

            # Waveform: plot from export_info (raw preferred), once per new raw file.
            if st.export_info and isinstance(st.export_info, dict):
                raw_path = st.export_info.get("raw")
                samples_path = st.export_info.get("samples")
                if raw_path and raw_path != self._demo_last_plotted_raw:
                    self._demo_last_plotted_raw = raw_path
                    try:
                        self.demo_plot_label.config(text="Rendering waveform...")
                        self._demo_plot_waveform_from_raw_export(raw_path)
                        self.demo_waveform_var.set("Waveform received")
                    except Exception as e:
                        self.demo_plot_label.config(text=f"(plot error: {type(e).__name__})")
                        try:
                            self._log("ERROR", f"Waveform plot failed: {e}")
                        except Exception:
                            pass
                elif (not raw_path) and samples_path:
                    # fallback
                    try:
                        self.demo_plot_label.config(text="Rendering waveform (samples)...")
                        self._demo_plot_waveform_from_samples(samples_path)
                        self.demo_waveform_var.set("Waveform received")
                    except Exception as e:
                        self.demo_plot_label.config(text=f"(plot error: {type(e).__name__})")
                        try:
                            self._log("ERROR", f"Waveform plot (samples) failed: {e}")
                        except Exception:
                            pass

            # Summary: show overall values + last RX text (human readable)
            self._demo_render_summary(st.rx_text or "", st.overall_values)

        except Exception as e:
            try:
                self._log("ERROR", f"Demo mirror update failed: {type(e).__name__}: {e}")
            except Exception:
                pass

    def _on_dump_adv(self) -> None:
        """Scan and display advertising data in a readable window."""
        # Disable button while scanning
        try:
            self.dump_adv_button.configure(state="disabled")
        except Exception:
            pass

        address_prefix, _mtu, scan_timeout, _rx_timeout, _record_sessions, _session_root, name_contains, svc_contains, mfg_id_hex, mfg_data_hex = self._read_runtime_params()

        # Normalize filters
        addr_prefix = (address_prefix or "").strip().upper()
        name_contains = (name_contains or "").strip()
        svc_contains = (svc_contains or "").strip().lower()

        mfg_id = None
        mfg_id_hex = (mfg_id_hex or "").strip().lower()
        if mfg_id_hex:
            mfg_id_hex = mfg_id_hex.replace("0x", "")
            try:
                mfg_id = int(mfg_id_hex, 16)
            except ValueError:
                mfg_id = None

        mfg_data_sub = b""
        mfg_data_hex = (mfg_data_hex or "").strip().lower().replace("0x", "")
        if mfg_data_hex:
            mfg_data_hex = "".join(ch for ch in mfg_data_hex if ch in "0123456789abcdef")
            try:
                mfg_data_sub = bytes.fromhex(mfg_data_hex)
            except ValueError:
                mfg_data_sub = b""

        # Create window immediately
        win = tk.Toplevel(self._tk_root)
        win.title("Advertising dump")
        win.geometry("980x700")
        win.configure(bg=self.colors["bg"])

        header = tk.Frame(win, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
        header.pack(fill=tk.X, padx=12, pady=12)

        tk.Label(header, text="Advertising dump", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Label(header, text="Scan running...").pack(anchor="w", padx=12, pady=(0, 10))

        body = tk.Frame(win, bg=self.colors["bg"])
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        text = tk.Text(body, wrap="none", bg=self.colors["panel_alt"], fg=self.colors["text"], insertbackground=self.colors["text"])
        text.pack(fill=tk.BOTH, expand=True)

        btns = tk.Frame(win, bg=self.colors["bg"])
        btns.pack(fill=tk.X, padx=12, pady=(0, 12))

        def _copy():
            try:
                data = text.get("1.0", tk.END)
                self.root.clipboard_clear()
                self.root.clipboard_append(data)
            except Exception:
                pass

        ttk.Button(btns, text="Copy", command=_copy).pack(side=tk.LEFT)

        async def _scan_adv():
            from bleak import BleakScanner
            res = await BleakScanner.discover(timeout=scan_timeout, return_adv=True)
            pairs = []
            if isinstance(res, dict):
                for _addr, val in res.items():
                    if isinstance(val, tuple) and len(val) == 2:
                        dev, adv = val
                    else:
                        dev, adv = val, None
                    pairs.append((dev, adv))
            elif isinstance(res, list):
                for item in res:
                    if isinstance(item, tuple) and len(item) == 2:
                        dev, adv = item
                    else:
                        dev, adv = item, None
                    pairs.append((dev, adv))
            return pairs

        def _matches(dev, adv) -> bool:
            # Address prefix
            addr = ""
            if isinstance(dev, str):
                addr = dev
            else:
                addr = getattr(dev, "address", "") or ""
            addr_u = addr.upper()
            if addr_prefix and not addr_u.startswith(addr_prefix):
                return False

            # Name contains
            if name_contains:
                n1 = (getattr(dev, "name", "") or "") if not isinstance(dev, str) else ""
                n2 = (getattr(adv, "local_name", "") or "") if adv is not None else ""
                combo = (n1 + " " + n2).lower()
                if name_contains.lower() not in combo:
                    return False

            # Service UUID contains
            if svc_contains:
                uus = []
                if adv is not None and getattr(adv, "service_uuids", None):
                    uus = list(getattr(adv, "service_uuids", []) or [])
                joined = " ".join(u.lower() for u in uus)
                if svc_contains not in joined:
                    return False

            # Manufacturer data filters
            if mfg_id is not None or mfg_data_sub:
                md = getattr(adv, "manufacturer_data", None) if adv is not None else None
                md = md or {}
                if mfg_id is not None:
                    if mfg_id not in md:
                        return False
                    if mfg_data_sub:
                        payload = bytes(md.get(mfg_id, b"")) if md.get(mfg_id) is not None else b""
                        if mfg_data_sub not in payload:
                            return False
                else:
                    # mfg id not specified: match any payload containing substring
                    if mfg_data_sub:
                        ok = False
                        for _k, _v in md.items():
                            payload = bytes(_v) if _v is not None else b""
                            if mfg_data_sub in payload:
                                ok = True
                                break
                        if not ok:
                            return False

            return True

        def _render(pairs):
            # Sort by RSSI when available
            def rssi_of(item):
                _dev, _adv = item
                r = getattr(_adv, "rssi", None) if _adv is not None else None
                return r if isinstance(r, int) else -999
            pairs2 = [p for p in pairs if _matches(p[0], p[1])]
            pairs2.sort(key=rssi_of, reverse=True)

            lines = []
            lines.append(f"Filters: addr_prefix={addr_prefix or '-'} name_contains={name_contains or '-'} svc_contains={svc_contains or '-'} mfg_id={('0x%04X'%mfg_id) if mfg_id is not None else '-'} mfg_data_sub={(mfg_data_sub.hex() if mfg_data_sub else '-')}")
            lines.append("")

            for dev, adv in pairs2:
                if isinstance(dev, str):
                    addr = dev
                    name = "<?>"
                else:
                    addr = getattr(dev, "address", "") or ""
                    name = getattr(dev, "name", "") or "<?>"

                local_name = getattr(adv, "local_name", None) if adv is not None else None
                rssi = getattr(adv, "rssi", None) if adv is not None else None
                tx = getattr(adv, "tx_power", None) if adv is not None else None
                svcs = getattr(adv, "service_uuids", None) if adv is not None else None
                svcs = svcs or []
                md = getattr(adv, "manufacturer_data", None) if adv is not None else None
                md = md or {}
                sd = getattr(adv, "service_data", None) if adv is not None else None
                sd = sd or {}

                lines.append("=" * 72)
                lines.append(f"Address: {addr}")
                lines.append(f"Name   : {name}")
                if local_name:
                    lines.append(f"Local  : {local_name}")
                lines.append(f"RSSI   : {rssi}")
                lines.append(f"TX Pwr : {tx}")
                if svcs:
                    lines.append("Service UUIDs:")
                    for u in svcs:
                        lines.append(f"  - {u}")
                if md:
                    lines.append("Manufacturer data:")
                    for k, v in md.items():
                        payload = bytes(v) if v is not None else b""
                        lines.append(f"  - 0x{k:04X}: {payload.hex()}")
                if sd:
                    lines.append("Service data:")
                    for k, v in sd.items():
                        payload = bytes(v) if v is not None else b""
                        lines.append(f"  - {k}: {payload.hex()}")
            lines.append("=" * 72)
            lines.append(f"Matched devices: {len(pairs2)}")

            text.delete("1.0", tk.END)
            text.insert(tk.END, "\n".join(lines))
            text.see("1.0")

            try:
                self.dump_adv_button.configure(state="normal")
            except Exception:
                pass

        def thread_main():
            try:
                pairs = asyncio.run(_scan_adv())
            except Exception as e:
                pairs = []
                self.root.after(0, lambda: text.insert(tk.END, f"Scan failed: {e}\n"))
            self.root.after(0, lambda: _render(pairs))

        threading.Thread(target=thread_main, daemon=True).start()



def main() -> None:
    root = tk.Tk()
    SimGwV2App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
