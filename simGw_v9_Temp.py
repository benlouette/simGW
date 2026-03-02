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

# Refactored: centralized modules
from ble_session_helpers import BleSessionHelpers
from protobuf_formatters import ProtobufFormatter, OverallValuesExtractor
from data_exporters import WaveformExporter, WaveformParser
from session_recorder import SessionRecorder
from config import (
    BASE_DIR, FROTO_DIR, CAPTURE_DIR,
    UART_SERVICE_BYTES, UART_RX_BYTES, UART_TX_BYTES,
    AUTO_RESTART_DELAY_MS, UI_POLL_INTERVAL_MS,
    PHASE_SCANNING, PHASE_CONNECTING, PHASE_CONNECTED, PHASE_METRICS, 
    PHASE_WAVEFORM, PHASE_CLOSE_SESSION, PHASE_DISCONNECTED, PHASE_ERROR,
    _phase_rank, MANUAL_ACTIONS, CHECKLIST_ITEMS, CHECKLIST_STATE_MAP,
    _uuid_from_bytes, _get_uart_uuids, _PHASE_ORDER
)

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

# Add FROTO_DIR to sys.path for protobuf imports
if FROTO_DIR not in sys.path:
    sys.path.insert(0, FROTO_DIR)

import DeviceAppBulletSensor_pb2
import ConfigurationAndCommand_pb2
import Common_pb2
import FirmwareUpdateOverTheAir_pb2
import Froto_pb2
import SensingDataUpload_pb2

# REFACTORED: WaveformExportTools replaced by WaveformParser from data_exporters module  
# Keep alias for backward compatibility
WaveformExportTools = WaveformParser


@dataclass
class TileStatus:
    address: str = "•"
    status: str = "Queued"
    rx_text: str = ""



@dataclass
class TileState:
    """Structured state for a tile, used for UI updates (never parse rx_text for logic)."""
    status: str = "Queued"
    address: str = "•"
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
        # Hard-stop support (cancellation)
        self._cancel_lock = threading.Lock()
        self._cancel_all = False
        self._cancel_tiles = set()

    
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

    
    # --- Hard-stop API (called from UI thread) ---
    def request_cancel_all(self) -> None:
        """Request cancellation of any in-flight scan/connect/download operations."""
        with self._cancel_lock:
            self._cancel_all = True
            self._cancel_tiles.clear()

    def clear_cancel_all(self) -> None:
        """Clear any pending cancellation request."""
        with self._cancel_lock:
            self._cancel_all = False
            self._cancel_tiles.clear()

    def request_cancel_tile(self, tile_id: int) -> None:
        with self._cancel_lock:
            self._cancel_tiles.add(int(tile_id))

    def _is_cancelled(self, tile_id: int) -> bool:
        with self._cancel_lock:
            return self._cancel_all or (int(tile_id) in self._cancel_tiles)

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
        """REFACTORED: Wrapper to ProtobufFormatter."""
        return ProtobufFormatter.format_payload_readable(payload)

    def _pb_message_type(self, payload: bytes) -> str:
        """REFACTORED: Wrapper to ProtobufFormatter."""
        return ProtobufFormatter.get_message_type(payload)

    def _hex_short(self, payload: bytes, max_len: int = 48) -> str:
        """REFACTORED: Wrapper to ProtobufFormatter."""
        return ProtobufFormatter.hex_short(payload, max_len)


    def _extract_waveform_sample_rows(self, app_msg) -> list:
        """REFACTORED: Wrapper to ProtobufFormatter."""
        return ProtobufFormatter.extract_waveform_sample_rows(app_msg)

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
        """REFACTORED: Wrapper to OverallValuesExtractor."""
        return OverallValuesExtractor.extract_overall_values(data_upload_msg)
    
    def _export_waveform_capture(self, tile_id: int, payloads: list, parsed_msgs: list) -> dict:
        """REFACTORED: Wrapper to WaveformExporter."""
        exporter = WaveformExporter(CAPTURE_DIR)
        return exporter.export_waveform_capture(tile_id, payloads, parsed_msgs, self._hex_short)

    async def _run_manual_action(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float, action: str, record_sessions: bool, session_root: str,
                            name_contains: str = "", service_uuid_contains: str = "", mfg_id_hex: str = "", mfg_data_hex_contains: str = "") -> None:
        """
        REFACTORED: Execute manual BLE action using centralized BleSessionHelpers.
        Reduced from ~400 lines to ~150 lines.
        """
        address_prefix = address_prefix.upper()
        name_contains = (name_contains or "").strip()
        service_uuid_contains = (service_uuid_contains or "").strip()
        mfg_id_hex = (mfg_id_hex or "").strip()
        mfg_data_hex_contains = (mfg_data_hex_contains or "").strip()
        
        # Setup session recorder
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
        
        # Scan for device
        matched_device = {"value": None}
        found_event = asyncio.Event()

        def _on_device_found(device, advertisement_data):
            if not getattr(device, "address", None):
                return
            if self._is_cancelled(tile_id):
                return
            if self._adv_matches(device, advertisement_data, address_prefix, name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains):
                if not found_event.is_set():
                    matched_device["value"] = device
                    found_event.set()

        scanner = BleakScanner(_on_device_found)
        await scanner.start()
        try:
            start_t = asyncio.get_running_loop().time()
            while True:
                if self._is_cancelled(tile_id):
                    self._emit(tile_id, {"phase": "disconnected", "status": "Cancelled (scan)", "checklist": {"waiting_connection": "pending"}})
                    return
                remaining = float(scan_timeout) - (asyncio.get_running_loop().time() - start_t)
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                try:
                    await asyncio.wait_for(found_event.wait(), timeout=min(0.25, remaining))
                    break
                except asyncio.TimeoutError:
                    continue
        except asyncio.TimeoutError:
            self._emit(tile_id, {"status": "Not found", "address": "•"})
            return
        finally:
            await scanner.stop()

        matched = matched_device["value"]
        if not matched:
            self._emit(tile_id, {"status": "Not found", "address": "•"})
            if recorder is not None:
                recorder.log_text("not_found")
                recorder.close()
            return

        # Connect
        self._emit(tile_id, {"status": f"Manual: {action} / connecting...", "address": matched.address, "phase": "connecting"})
        client = BleakClient(matched.address)
        
        # REFACTORED: Use centralized helpers
        def ui_callback(update_dict):
            self.ui_queue.put(("tile_update", tile_id, update_dict))
        
        helpers = BleSessionHelpers(client, self.uart_rx_uuid, self.uart_tx_uuid, recorder, ui_callback)

        try:
            if self._is_cancelled(tile_id):
                return
            
            await client.connect()
            
            if self._is_cancelled(tile_id):
                self._emit(tile_id, {"phase": "disconnected", "status": "Cancelled (connected)"})
                await client.disconnect()
                return

            if recorder is not None:
                recorder.log_text(f"connected:{matched.address}")
            
            self._emit(tile_id, {"checklist": {"waiting_connection": "done", "connected": "done"}, "phase": "connected"})
            
            if mtu and hasattr(client, "request_mtu"):
                try:
                    await client.request_mtu(mtu)
                except Exception:
                    pass
            
            await helpers.start_notifications()

            # Execute action
            if action in ("version", "config_hash", "metrics", "waveform", "close_session"):
                await helpers.send_config_time()
                await asyncio.sleep(0.1)

            if action == "connect_test":
                self.ui_queue.put(("tile_update", tile_id, {"status": "Connected (test OK)"}))

            elif action == "discover_gatt":
                try:
                    services = client.services or await client.get_services()
                except Exception:
                    services = await client.get_services()
                gatt_lines = [f"[SERVICE] {svc.uuid} ({getattr(svc, 'description', '')})" for svc in services]
                for svc in services:
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
                    payload = await helpers.wait_next_rx(2.0)
                    rx_type = helpers._pb_message_type(payload)
                    self.ui_queue.put(("tile_update", tile_id, {
                        "status": f"Notify RX {rx_type}",
                        "rx_text": f"TYPE: {rx_type}\nHEX: {self._hex_short(payload)}\n\n" + self._format_rx_payload(payload),
                    }))
                except asyncio.TimeoutError:
                    self.ui_queue.put(("tile_update", tile_id, {"status": "Notify test timeout (no unsolicited RX)"}))

            elif action == "sync_time":
                self.ui_queue.put(("tile_update", tile_id, {"status": "Time sync sent", "checklist": {"general_info_exchange": "done"}}))

            elif action == "version":
                await helpers.send_version_retrieve()
                payload, _msg, msg_type = await helpers.recv_app(rx_timeout)
                self.ui_queue.put(("tile_update", tile_id, {
                    "status": f"RX {msg_type}",
                    "checklist": {"general_info_exchange": "done"},
                    "rx_text": f"TYPE: {msg_type}\nHEX: {self._hex_short(payload)}\n\n" + self._format_rx_payload(payload),
                }))

            elif action == "config_hash":
                await helpers.send_version_retrieve()
                await helpers.recv_app(rx_timeout)  # consume version
                await asyncio.sleep(0.1)
                await helpers.send_config_hash_retrieve()
                payload, _msg, msg_type = await helpers.recv_app(rx_timeout)
                self.ui_queue.put(("tile_update", tile_id, {
                    "status": f"RX {msg_type}",
                    "checklist": {"general_info_exchange": "done"},
                    "rx_text": f"TYPE: {msg_type}\nHEX: {self._hex_short(payload)}\n\n" + self._format_rx_payload(payload),
                }))

            elif action == "metrics":
                await helpers.send_version_retrieve()
                await helpers.recv_app(rx_timeout)
                await asyncio.sleep(0.1)
                await helpers.send_config_hash_retrieve()
                await helpers.recv_app(rx_timeout)
                await asyncio.sleep(0.1)
                await helpers.send_metrics_selection(int(time.time() * 1000))
                payload, msg, msg_type = await helpers.recv_app(rx_timeout)
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
                await helpers.send_version_retrieve()
                await helpers.recv_app(rx_timeout)
                await asyncio.sleep(0.1)
                await helpers.send_config_hash_retrieve()
                await helpers.recv_app(rx_timeout)
                await asyncio.sleep(0.1)
                await helpers.send_vibration_selection(int(time.time() * 1000))
                
                # Collect waveform blocks
                received, expected = 0, None
                wave_payloads, wave_msgs = [], []
                while True:
                    payload, msg, msg_type = await helpers.recv_app(rx_timeout)
                    if msg_type != "data_upload":
                        break
                    wave_payloads.append(payload)
                    wave_msgs.append(msg)
                    received += 1
                    if expected is None:
                        try:
                            expected = int(msg.data_upload.header.total_block)
                            if expected <= 0:
                                expected = None
                        except Exception:
                            pass
                    self._emit(tile_id, {
                        "phase": "waveform",
                        "status": f"Waveform blocks {received}/{expected or '?'}",
                        "checklist": {"general_info_exchange": "done", "data_collection": "in_progress"},
                        "rx_text": f"TYPE: {msg_type}\nHEX: {self._hex_short(payload)}\n\n" + self._format_rx_payload(payload),
                    })
                    if expected and received >= expected:
                        break
                
                # Export
                export_info = None
                if wave_payloads:
                    try:
                        export_info = self._export_waveform_capture(tile_id, wave_payloads, wave_msgs)
                    except Exception as export_exc:
                        export_info = {"error": str(export_exc)}
                
                status_text = f"Waveform done ({received}/{expected or '?'})"
                rx_text = f"TYPE: data_upload\n"
                if export_info:
                    if "error" in export_info:
                        status_text += " / export failed"
                        rx_text += f"\nEXPORT ERROR: {export_info['error']}"
                    else:
                        status_text += f" / exported {export_info['count']} blocks"
                        rx_text += f"\nEXPORT:\n- raw: {export_info['raw']}\n- index: {export_info['index']}"
                        if export_info.get("samples"):
                            rx_text += f"\n- samples: {export_info['samples']}"
                
                self.ui_queue.put(("tile_update", tile_id, {
                    "status": status_text,
                    "checklist": {"general_info_exchange": "done", "data_collection": "done"},
                    "rx_text": rx_text,
                    "export_info": export_info,
                }))

            elif action == "close_session":
                await helpers.send_close_session()
                self._emit(tile_id, {"phase": "close_session", "status": "Close session sent", "checklist": {"close_session": "done"}})

            else:
                raise ValueError(f"Unknown action: {action}")

            await helpers.stop_notifications()

        except Exception as exc:
            self._emit(tile_id, {"status": f"Error: {type(exc).__name__}: {exc}"})
        finally:
            self._emit(tile_id, {"checklist": {"disconnect": "in_progress"}})
            try:
                if client.is_connected:
                    await helpers.stop_notifications()
                    await asyncio.sleep(0.2)
                    await client.disconnect()
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
                if self._is_cancelled(tile_id):
                    self._emit(tile_id, {"phase": "disconnected", "status": "Cancelled (waveform)"})
                    return {
                        "ok": False,
                        "received": received,
                        "expected": expected,
                        "export_info": None,
                        "last_payload": last_payload,
                        "last_type": last_type,
                        "last_rx_text": "",
                        "error_info": {"where": "waveform", "type": "Cancelled", "msg": "cancel requested"},
                    }

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
        """
        REFACTORED: Full auto cycle using centralized BleSessionHelpers.
        Reduced from ~350 lines to ~180 lines.
        """
        address_prefix = address_prefix.upper()
        name_contains = (name_contains or "").strip()
        service_uuid_contains = (service_uuid_contains or "").strip()
        mfg_id_hex = (mfg_id_hex or "").strip()
        mfg_data_hex_contains = (mfg_data_hex_contains or "").strip()
        
        # Setup session recorder
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
        
        # Scan for device
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
                self._emit(tile_id, {"status": "Not found", "address": "•"})
                return
        finally:
            await scanner.stop()

        matched = matched_device["value"]
        if not matched:
            self._emit(tile_id, {"status": "Not found", "address": "•"})
            if recorder is not None:
                recorder.log_text("not_found")
                recorder.close()
            return

        if self._is_cancelled(tile_id):
            return

        # Connect
        self._emit(tile_id, {"status": "Connecting...", "address": matched.address, "phase": "connecting"})
        client = BleakClient(matched.address)
        
        # REFACTORED: Use centralized helpers
        def ui_callback(update_dict):
            self.ui_queue.put(("tile_update", tile_id, update_dict))
        
        helpers = BleSessionHelpers(client, self.uart_rx_uuid, self.uart_tx_uuid, recorder, ui_callback)

        try:
            if self._is_cancelled(tile_id):
                self._emit(tile_id, {"phase": "disconnected", "status": "Cancelled (before connect)", "checklist": {"waiting_connection": "pending"}})
                return
            
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

            await helpers.start_notifications()
            self.ui_queue.put(("tile_update", tile_id, {"status": "Sending config_dissem...", "checklist": {"general_info_exchange": "in_progress"}}))

            # REFACTORED: Use helper methods
            await helpers.send_config_time()
            await asyncio.sleep(0.1)
            
            self.ui_queue.put(("tile_update", tile_id, {"status": "Sending version_retrieve..."}))
            await helpers.send_version_retrieve()

            try:
                payload, app_message, message_type = await helpers.recv_app(rx_timeout)
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
                        await helpers.send_config_hash_retrieve()

                        try:
                            hash_payload, hash_message, hash_type = await helpers.recv_app(rx_timeout)
                        except asyncio.TimeoutError:
                            latest_status = "Config hash timeout"
                        else:
                            try:
                                if hash_type == "config_hash_upload":
                                    data_collection_complete = True
                                    last_loop_index = -1
                                    overall_values = None
                                    
                                    # REFACTORED: Metric collection loop simplified
                                    for loop_index in range(6):
                                        if self._is_cancelled(tile_id):
                                            self._emit(tile_id, {"phase": "disconnected", "status": "Cancelled (metrics)"})
                                            data_collection_complete = False
                                            break
                                        
                                        last_loop_index = loop_index
                                        latest_status = "Config hash received"
                                        if loop_index == 0:
                                            self.ui_queue.put(("tile_update", tile_id, {"checklist": {"general_info_exchange": "done", "data_collection": "in_progress"}}))
                                        latest_rx_text = f"TYPE: {helpers._pb_message_type(hash_payload)}\nHEX: {self._hex_short(hash_payload)}\n\n" + self._format_rx_payload(hash_payload)

                                        current_time_ms = int(time.time() * 1000)
                                        
                                        self._emit(tile_id, {"phase": "metrics", "status": f"Sending data_selection ({loop_index + 1}/6)..."})
                                        await helpers.send_metrics_selection(current_time_ms)

                                        try:
                                            data_payload, data_message, data_type = await helpers.recv_app(rx_timeout)
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
                                        await helpers.send_vibration_selection(current_time_ms)
                                        wf_res = await self._collect_waveform_export(tile_id, helpers.recv_app, rx_timeout)
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
                                            await helpers.send_close_session()
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

            await helpers.stop_notifications()
            
        except Exception as exc:
            self._emit(tile_id, {"status": f"Error: {type(exc).__name__}: {exc}"})
        finally:
            self._emit(tile_id, {"checklist": {"disconnect": "in_progress"}})
            try:
                if client.is_connected:
                    await helpers.stop_notifications()
                    await asyncio.sleep(0.2)
                    await client.disconnect()
            except Exception:
                pass
            if recorder is not None:
                recorder.log_text("disconnect_done")
                recorder.close()
            self._emit(tile_id, {"checklist": {"disconnect": "done"}})
            self._emit(tile_id, {"status": "Disconnected", "phase": "disconnected"})
            self.ui_queue.put(("cycle_done", tile_id))


# Import UI application class (extracted for maintainability)
from ui_application import create_app_class
SimGwV2App = create_app_class(BleCycleWorker, TileState)


def main() -> None:
    root = tk.Tk()
    SimGwV2App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
