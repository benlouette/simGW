import asyncio
import threading
import time
from dataclasses import dataclass
from queue import Queue
from typing import Callable, Dict, Optional

from bleak import BleakClient

# Refactored: centralized modules
from ble_session_helpers import BleSessionHelpers
from ble_worker_services import (
    normalize_ble_filters,
    create_session_recorder,
    scan_for_matching_device,
)
from ble_waveform_service import collect_waveform_export
from protobuf_formatters import ProtobufFormatter, OverallValuesExtractor
from display_formatters import format_session_and_overall_text, format_rx_summary
from data_exporters import WaveformExporter
from protocol_utils import (
    CAPTURE_DIR,
    phase_rank,
    _PHASE_ORDER
)
from ble_config import get_uart_uuids
from ui_events import TileUpdatePayload, UiEvent, make_cycle_done, make_tile_update


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
    def __init__(self, ui_queue: Queue[UiEvent]):
        self.ui_queue = ui_queue
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.uart_service_uuid, self.uart_rx_uuid, self.uart_tx_uuid = get_uart_uuids(True)
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

    def _emit(self, tile_id: int, payload: TileUpdatePayload) -> None:
                """Centralized UI emitter for tile updates.
                Adds ts_ms automatically. Never raises.
                Also enforces a monotonic 'phase' progression per tile (best-effort).
                """
                try:
                    out = dict(payload) if payload is not None else {}
                    out.setdefault("ts_ms", int(time.time() * 1000))

                    # Keep phase monotonic per tile to avoid confusing UI regressions.
                    if "phase" in out and out["phase"]:
                        pr = phase_rank(str(out["phase"]))
                        prev = self._tile_phase_rank.get(tile_id, -1)
                        if pr >= 0:
                            if prev >= 0 and pr < prev:
                                # Don't regress; keep the last known phase.
                                out["phase"] = _PHASE_ORDER[prev]
                            else:
                                self._tile_phase_rank[tile_id] = pr

                    self.ui_queue.put(make_tile_update(tile_id, out))
                except Exception:
                    # Never crash worker on UI update failure
                    pass

    def _create_ui_callback(self, tile_id: int) -> Callable[[TileUpdatePayload], None]:
        """Create a UI callback function for BLE helpers to avoid duplication."""
        def ui_callback(update_dict: TileUpdatePayload) -> None:
            self.ui_queue.put(make_tile_update(tile_id, update_dict))
        return ui_callback

    async def _run_cycle(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float, record_sessions: bool, session_root: str,
                        name_contains: str = "", service_uuid_contains: str = "", mfg_id_hex: str = "", mfg_data_hex_contains: str = "", twf_type: int = None) -> None:
        """Backward-compatible wrapper (some versions referenced _run_cycle)."""
        await self._run_cycle_impl(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, record_sessions, session_root,
                                  name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains, twf_type)

    def run_cycle(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float, record_sessions: bool, session_root: str,
                name_contains: str = "", service_uuid_contains: str = "", mfg_id_hex: str = "", mfg_data_hex_contains: str = "", twf_type: int = None) -> None:
        # Clear any previous cancelled state before starting
        with self._cancel_lock:
            self._cancel_all = False
            self._cancel_tiles.discard(int(tile_id))
        self._call_soon(self._run_cycle_impl(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, record_sessions, session_root,
                        name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains, twf_type))

    def run_manual_action(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float, action: str, record_sessions: bool, session_root: str,
                name_contains: str = "", service_uuid_contains: str = "", mfg_id_hex: str = "", mfg_data_hex_contains: str = "", twf_type: int = None) -> None:
        # Clear any previous cancelled state before starting
        with self._cancel_lock:
            self._cancel_all = False
            self._cancel_tiles.discard(int(tile_id))
        self._call_soon(self._run_manual_action(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, action, record_sessions, session_root,
                        name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains, twf_type))

    def _extract_overall_values(self, data_upload_msg) -> list:
        """REFACTORED: Wrapper to OverallValuesExtractor."""
        return OverallValuesExtractor.extract_overall_values(data_upload_msg)
    
    def _export_waveform_capture(self, tile_id: int, payloads: list, parsed_msgs: list) -> dict:
        """REFACTORED: Wrapper to WaveformExporter."""
        exporter = WaveformExporter(CAPTURE_DIR)
        return exporter.export_waveform_capture(tile_id, payloads, parsed_msgs, ProtobufFormatter.hex_short)

    async def _run_manual_action(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float, action: str, record_sessions: bool, session_root: str,
                            name_contains: str = "", service_uuid_contains: str = "", mfg_id_hex: str = "", mfg_data_hex_contains: str = "", twf_type: int = None) -> None:
        """
        REFACTORED: Execute manual BLE action using centralized BleSessionHelpers.
        Reduced from ~400 lines to ~150 lines.
        """
        address_prefix, name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains = normalize_ble_filters(
            address_prefix,
            name_contains,
            service_uuid_contains,
            mfg_id_hex,
            mfg_data_hex_contains,
        )
        
        # Setup session recorder
        recorder, session_dir = create_session_recorder(
            tile_id=tile_id,
            action=action,
            record_sessions=record_sessions,
            session_root=session_root,
            ui_queue=self.ui_queue,
        )
        
        self._emit(tile_id, {"status": f"Manual: {action} / scanning...", "phase": "scanning"})
        self._emit(tile_id, {"checklist": {"waiting_connection": "in_progress"}})
        
        # Scan for device
        matched, was_cancelled = await scan_for_matching_device(
            address_prefix=address_prefix,
            name_contains=name_contains,
            service_uuid_contains=service_uuid_contains,
            mfg_id_hex=mfg_id_hex,
            mfg_data_hex_contains=mfg_data_hex_contains,
            scan_timeout=scan_timeout,
            is_cancelled=lambda: self._is_cancelled(tile_id),
        )

        if was_cancelled:
            self._emit(tile_id, {"phase": "disconnected", "status": "Cancelled (scan)", "checklist": {"waiting_connection": "pending"}})
            return

        if not matched:
            self._emit(tile_id, {"status": "Not found", "address": "•"})
            if recorder is not None:
                recorder.log_text("not_found")
                recorder.close()
            return

        # Connect
        self._emit(tile_id, {"status": f"Manual: {action} / connecting...", "address": matched.address, "phase": "connecting"})
        client = BleakClient(matched.address)
        
        helpers = BleSessionHelpers(client, self.uart_rx_uuid, self.uart_tx_uuid, recorder, self._create_ui_callback(tile_id))

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
            if action in ("session_test", "overall", "acceleration_twf", "velocity_twf", "enveloper3_twf", "full_cycle"):
                # New protocol: send OpenSession once and wait for AcceptSession
                await helpers.send_open_session()
                await asyncio.sleep(0.1)
                try:
                    payload, msg, msg_type = await helpers.recv_app(rx_timeout)
                    if msg_type == "accept_session":
                        self._emit(tile_id, {
                            "status": f"Session accepted (FW: 0x{msg.accept_session.fw_version:X})",
                            "rx_text": format_rx_summary(msg_type, payload, ProtobufFormatter.format_payload_readable(payload)),
                        })
                        # Save session info for actions that need it
                        accept_session_msg = msg.accept_session
                        accept_session_payload = payload
                    else:
                        self._emit(tile_id, {"status": f"Unexpected response: {msg_type}"})
                except asyncio.TimeoutError:
                    self._emit(tile_id, {"status": "No AcceptSession received"})
                    raise

            if action == "connect_test":
                self.ui_queue.put(make_tile_update(tile_id, {"status": "Connected (test OK)"}))

            elif action == "overall":
                # Session already open, directly request metrics
                await asyncio.sleep(0.1)
                await helpers.send_metrics_selection(int(time.time() * 1000))
                payload, msg, msg_type = await helpers.recv_app(rx_timeout)
                status = f"RX {msg_type}"
                if msg_type == "send_measurement":
                    try:
                        status += f" ({len(list(msg.send_measurement.measurement_data))} measurements)"
                    except Exception:
                        pass
                self.ui_queue.put(make_tile_update(tile_id, {
                    "status": status,
                    "checklist": {"general_info_exchange": "done", "data_collection": "done"},
                    "rx_text": format_rx_summary(msg_type, payload, ProtobufFormatter.format_payload_readable(payload)),
                }))

            elif action == "session_test":
                # Just display session info (already received in AcceptSession above)
                session_info = {"accept_msg": accept_session_msg, "payload": accept_session_payload}
                rx_text = format_session_and_overall_text(session_info, [])
                await helpers.send_close_session()
                self.ui_queue.put(make_tile_update(tile_id, {
                    "status": "Session test OK",
                    "checklist": {"general_info_exchange": "done", "close_session": "done"},
                    "rx_text": rx_text,
                }))

            elif action in ("acceleration_twf", "velocity_twf", "enveloper3_twf"):
                # Map action to TWF type
                twf_map = {"acceleration_twf": 5, "velocity_twf": 6, "enveloper3_twf": 7}
                req_twf_type = twf_map[action]
                
                # Request specific waveform type
                await asyncio.sleep(0.1)
                await helpers.send_vibration_selection(int(time.time() * 1000), twf_type=req_twf_type)
                
                # Collect waveform blocks
                received, expected = 0, None
                wave_payloads, wave_msgs = [], []
                while True:
                    payload, msg, msg_type = await helpers.recv_app(rx_timeout)
                    if msg_type != "send_measurement":
                        break
                    wave_payloads.append(payload)
                    wave_msgs.append(msg)
                    received += 1
                    if expected is None:
                        try:
                            expected = int(msg.header.total_fragments)
                            if expected <= 0:
                                expected = None
                        except Exception:
                            pass
                    self._emit(tile_id, {
                        "phase": "waveform",
                        "status": f"Waveform blocks {received}/{expected or '?'}",
                        "checklist": {"general_info_exchange": "done", "data_collection": "in_progress"},
                        "rx_text": format_rx_summary(msg_type, payload, ProtobufFormatter.format_payload_readable(payload)),
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
                rx_text = f"TYPE: send_measurement\n"
                if export_info:
                    if "error" in export_info:
                        status_text += " / export failed"
                        rx_text += f"\nEXPORT ERROR: {export_info['error']}"
                    else:
                        status_text += f" / exported {export_info['count']} blocks"
                        rx_text += f"\nEXPORT:\n- raw: {export_info['raw']}"
                        if export_info.get('txt'):
                            rx_text += f"\n- txt: {export_info['txt']}"
                        if export_info.get('index'):
                            rx_text += f"\n- index: {export_info['index']}"
                        if export_info.get("samples"):
                            rx_text += f"\n- samples: {export_info['samples']}"
                
                # Close session
                await helpers.send_close_session()
                
                self.ui_queue.put(make_tile_update(tile_id, {
                    "status": status_text,
                    "checklist": {"general_info_exchange": "done", "data_collection": "done", "close_session": "done"},
                    "rx_text": rx_text,
                    "export_info": export_info,
                }))

            elif action == "full_cycle":
                # Request overall measurements first
                await asyncio.sleep(0.1)
                await helpers.send_metrics_selection(int(time.time() * 1000))
                payload, msg, msg_type = await helpers.recv_app(rx_timeout)
                
                # Extract overall values using the proper method
                overall_values = []
                if msg_type == "send_measurement":
                    try:
                        overall_values = self._extract_overall_values(msg.send_measurement)
                    except Exception:
                        pass
                
                # Request waveform with twf_type from settings
                await asyncio.sleep(0.1)
                await helpers.send_vibration_selection(int(time.time() * 1000), twf_type=twf_type)
                
                # Collect waveform blocks
                received, expected = 0, None
                wave_payloads, wave_msgs = [], []
                while True:
                    payload, msg, msg_type = await helpers.recv_app(rx_timeout)
                    if msg_type != "send_measurement":
                        break
                    wave_payloads.append(payload)
                    wave_msgs.append(msg)
                    received += 1
                    if expected is None:
                        try:
                            expected = int(msg.header.total_fragments)
                            if expected <= 0:
                                expected = None
                        except Exception:
                            pass
                    self._emit(tile_id, {
                        "phase": "waveform",
                        "status": f"Full cycle: waveform {received}/{expected or '?'}",
                        "checklist": {"general_info_exchange": "done", "data_collection": "in_progress"},
                    })
                    if expected and received >= expected:
                        break
                
                # Export waveform
                export_info = None
                if wave_payloads:
                    try:
                        export_info = self._export_waveform_capture(tile_id, wave_payloads, wave_msgs)
                    except Exception as export_exc:
                        export_info = {"error": str(export_exc)}
                
                # Close session
                await helpers.send_close_session()
                
                # Format display with session info + overall + export info
                session_info = {"accept_msg": accept_session_msg, "payload": accept_session_payload}
                rx_text = format_session_and_overall_text(session_info, overall_values)
                rx_text += f"\n\n--- WAVEFORM EXPORT ---\n"
                if export_info:
                    if "error" in export_info:
                        rx_text += f"EXPORT ERROR: {export_info['error']}"
                    else:
                        rx_text += f"- raw: {export_info['raw']}\n"
                        if export_info.get('txt'):
                            rx_text += f"- txt: {export_info['txt']}\n"
                        if export_info.get('samples'):
                            rx_text += f"- samples: {export_info['samples']}"
                
                self.ui_queue.put(make_tile_update(tile_id, {
                    "status": f"Full cycle done (overall + waveform {received}/{expected or '?'})",
                    "checklist": {"general_info_exchange": "done", "data_collection": "done", "close_session": "done"},
                    "rx_text": rx_text,
                    "export_info": export_info,
                }))

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
            self.ui_queue.put(make_cycle_done(tile_id))
    async def _collect_waveform_export(self, tile_id: int, _recv_app, rx_timeout: float) -> dict:
        return await collect_waveform_export(
            tile_id=tile_id,
            recv_app=_recv_app,
            rx_timeout=rx_timeout,
            is_cancelled=lambda: self._is_cancelled(tile_id),
            emit=lambda payload: self._emit(tile_id, payload),
            export_waveform_capture=self._export_waveform_capture,
        )


    async def _run_cycle_impl(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float, record_sessions: bool, session_root: str,
                        name_contains: str = "", service_uuid_contains: str = "", mfg_id_hex: str = "", mfg_data_hex_contains: str = "", twf_type: int = None) -> None:
        """
        REFACTORED: Full auto cycle using centralized BleSessionHelpers.
        Reduced from ~350 lines to ~180 lines.
        """
        address_prefix, name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains = normalize_ble_filters(
            address_prefix,
            name_contains,
            service_uuid_contains,
            mfg_id_hex,
            mfg_data_hex_contains,
        )
        
        # Setup session recorder
        recorder, session_dir = create_session_recorder(
            tile_id=tile_id,
            action=None,
            record_sessions=record_sessions,
            session_root=session_root,
            ui_queue=self.ui_queue,
        )
        
        self._emit(tile_id, {"status": "Scanning...", "phase": "scanning"})
        self._emit(tile_id, {"checklist": {"waiting_connection": "in_progress"}})
        
        # Scan for device
        matched, _was_cancelled = await scan_for_matching_device(
            address_prefix=address_prefix,
            name_contains=name_contains,
            service_uuid_contains=service_uuid_contains,
            mfg_id_hex=mfg_id_hex,
            mfg_data_hex_contains=mfg_data_hex_contains,
            scan_timeout=scan_timeout,
            is_cancelled=None,
        )

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
        
        helpers = BleSessionHelpers(client, self.uart_rx_uuid, self.uart_tx_uuid, recorder, self._create_ui_callback(tile_id))

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
                    self.ui_queue.put(make_tile_update(tile_id, {"status": f"MTU requested: {mtu}"}))
                except Exception as exc:
                    self.ui_queue.put(make_tile_update(tile_id, {"status": f"MTU request failed: {exc}"}))

            await helpers.start_notifications()
            self.ui_queue.put(make_tile_update(tile_id, {"status": "Opening session...", "checklist": {"general_info_exchange": "in_progress"}}))

            # REFACTORED: New protocol - send OpenSession once
            await helpers.send_open_session()
            await asyncio.sleep(0.1)

            try:
                payload, app_message, message_type = await helpers.recv_app(rx_timeout)
            except asyncio.TimeoutError:
                self.ui_queue.put(make_tile_update(tile_id, {"status": "AcceptSession timeout"}))
            else:
                latest_status = "Received"
                error_info = None
                export_info = None
                overall_values = None
                session_info = None
                latest_rx_text = format_rx_summary(message_type, payload, ProtobufFormatter.format_payload_readable(payload))
                try:
                    if message_type == "accept_session":
                        # AcceptSession contains version, config_hash, battery, etc.
                        accept_msg = app_message.accept_session
                        fw_version = getattr(accept_msg, "fw_version", 0)
                        config_hash = getattr(accept_msg, "config_hash", 0)
                        battery = getattr(accept_msg, "battery_indicator", 0)
                        latest_status = f"Session accepted (FW: 0x{fw_version:X}, Battery: {battery}%)"
                        self.ui_queue.put(make_tile_update(tile_id, {"status": latest_status}))
                        
                        # Store session info for final display
                        session_info = {
                            "accept_msg": accept_msg,
                            "payload": payload
                        }
                        
                        # Now ready for data collection
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
                            latest_status = "Session accepted"
                            if loop_index == 0:
                                self.ui_queue.put(make_tile_update(tile_id, {"checklist": {"general_info_exchange": "done", "data_collection": "in_progress"}}))

                            current_time_ms = int(time.time() * 1000)
                            
                            self._emit(tile_id, {"phase": "metrics", "status": f"Sending measurement_request ({loop_index + 1}/6)..."})
                            await helpers.send_metrics_selection(current_time_ms)

                            try:
                                data_payload, data_message, data_type = await helpers.recv_app(rx_timeout)
                            except asyncio.TimeoutError:
                                latest_status = "Measurement timeout"
                                data_collection_complete = False
                                self.ui_queue.put(make_tile_update(tile_id, {"checklist": {"data_collection": "pending"}}))
                                break
                            else:
                                try:
                                    if data_type == "send_measurement":
                                        measurement_data_list = list(data_message.send_measurement.measurement_data)
                                        overall_values = self._extract_overall_values(data_message.send_measurement)
                                        if len(measurement_data_list) >= 3:
                                            latest_status = "Measurement data received"
                                        else:
                                            latest_status = f"Measurement data missing ({len(measurement_data_list)})"
                                            data_collection_complete = False
                                        latest_rx_text = format_rx_summary(
                                            ProtobufFormatter.get_message_type(data_payload),
                                            data_payload,
                                            ProtobufFormatter.format_payload_readable(data_payload)
                                        )
                                    else:
                                        latest_status = f"Unexpected reply: {data_type}"
                                        data_collection_complete = False
                                        break
                                except Exception as exc:
                                    latest_status = "Measurement data parse error"
                                    error_info = {"where": f"metrics_send_measurement_parse(loop_index={loop_index})", "type": type(exc).__name__, "msg": str(exc)}
                                    data_collection_complete = False
                                    self.ui_queue.put(make_tile_update(tile_id, {"checklist": {"data_collection": "pending"}}))
                                    break

                        if data_collection_complete and last_loop_index == 5 and latest_status == "Measurement data received":
                            self.ui_queue.put(make_tile_update(tile_id, {"checklist": {"data_collection": "done"}}))
                        else:
                            data_collection_complete = False
                            self.ui_queue.put(make_tile_update(tile_id, {"checklist": {"data_collection": "pending"}}))

                        if data_collection_complete:
                            current_time_ms = int(time.time() * 1000)
                            self._emit(tile_id, {"phase": "waveform", "status": "Sending vibration request...", "checklist": {"data_collection": "in_progress"}})
                            await helpers.send_vibration_selection(current_time_ms, twf_type=twf_type)
                            wf_res = await self._collect_waveform_export(tile_id, helpers.recv_app, rx_timeout)
                            if wf_res.get("ok"):
                                export_info = wf_res.get("export_info")
                                received = int(wf_res.get("received") or 0)
                                expected = wf_res.get("expected")
                                latest_rx_text = wf_res.get("last_rx_text") or latest_rx_text
                                if export_info and isinstance(export_info, dict) and ("error" not in export_info):
                                    latest_status = f"Waveform done ({received}/{expected or '?'}) / exported {export_info.get('count','?')} blocks"
                                    latest_rx_text = latest_rx_text + f"\n\nEXPORT:\n- raw: {export_info.get('raw','')}"
                                    if export_info.get('txt'):
                                        latest_rx_text = latest_rx_text + f"\n- txt: {export_info.get('txt','')}"
                                    if export_info.get('index'):
                                        latest_rx_text = latest_rx_text + f"\n- index: {export_info.get('index','')}"
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
                                self.ui_queue.put(make_tile_update(tile_id, {"checklist": {"data_collection": "pending"}}))
                    else:
                        latest_status = f"Unexpected reply: {message_type}"
                except Exception as exc:
                    latest_status = "Top-level parse error"
                    error_info = {"where": "top_level_parse", "type": type(exc).__name__, "msg": str(exc)}
                
                # Generate formatted rx_text from session_info and overall_values if available
                if session_info or (overall_values and len(overall_values) > 0):
                    formatted_rx_text = format_session_and_overall_text(session_info, overall_values)
                    if formatted_rx_text:
                        latest_rx_text = formatted_rx_text
                
                self.ui_queue.put(make_tile_update(tile_id, {"status": latest_status, "rx_text": latest_rx_text, "export_info": export_info, "overall_values": overall_values, "error": error_info}))

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
            self.ui_queue.put(make_cycle_done(tile_id))


# Import UI application class (extracted for maintainability)
from ui_application import create_app_class
SimGwV2App = create_app_class(BleCycleWorker, TileState)


def main() -> None:
    import tkinter as tk
    root = tk.Tk()
    SimGwV2App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
