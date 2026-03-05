import asyncio
import threading
import time
from dataclasses import dataclass
from queue import Queue
from typing import Any, Callable, Dict, List, Optional, Tuple

from bleak import BleakClient

# Refactored: centralized modules
from ble_session_helpers import BleSessionHelpers
from ble_worker_services import (
    normalize_ble_filters,
    create_session_recorder,
    scan_for_matching_device,
)
from protobuf_formatters import ProtobufFormatter, OverallValuesExtractor
from display_formatters import format_session_and_overall_text, format_rx_summary
from data_exporters import WaveformExporter
from protocol_utils import (
    CAPTURE_DIR,
    phase_rank,
    PHASE_ORDER,
)
from ble_config import (
    MEASUREMENT_TYPE_ACCELERATION_TWF,
    MEASUREMENT_TYPE_VELOCITY_TWF,
    MEASUREMENT_TYPE_ENVELOPER3_TWF,
    get_uart_uuids,
)
from ui_events import TileUpdatePayload, UiEvent, make_cycle_done, make_tile_update


_METRICS_COLLECTION_LOOPS = 6
_FULL_CYCLE_TWF_TYPES = (
    MEASUREMENT_TYPE_ACCELERATION_TWF,
    MEASUREMENT_TYPE_VELOCITY_TWF,
    MEASUREMENT_TYPE_ENVELOPER3_TWF,
)
_WAVEFORM_KEY_BY_TYPE = {
    MEASUREMENT_TYPE_ACCELERATION_TWF: "acceleration_twf",
    MEASUREMENT_TYPE_VELOCITY_TWF: "velocity_twf",
    MEASUREMENT_TYPE_ENVELOPER3_TWF: "enveloper3_twf",
}
_WAVEFORM_LABEL_BY_KEY = {
    "acceleration_twf": "Acceleration TWF",
    "velocity_twf": "Velocity TWF",
    "enveloper3_twf": "Enveloper3 TWF",
}
_DEFAULT_WAVEFORM_KEY = "acceleration_twf"


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
    export_infos: Optional[dict] = None
    phase: str = "idle"
    last_export_raw: str = ""


class BleCycleWorker:
    def __init__(self, ui_queue: Queue[UiEvent]):
        self.ui_queue = ui_queue
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.waveform_exporter = WaveformExporter(CAPTURE_DIR)
        self.uart_service_uuid, self.uart_rx_uuid, self.uart_tx_uuid = get_uart_uuids(True)
        self._tile_phase_rank = {}  # tile_id -> last phase rank
        # Hard-stop support (cancellation)
        self._cancel_lock = threading.Lock()
        self._cancel_all = False
        self._cancel_tiles = set()

    def _clear_cancel_state_for_tile(self, tile_id: int) -> None:
        """Clear cancellation flags before starting one run for a tile."""
        with self._cancel_lock:
            self._cancel_all = False
            self._cancel_tiles.discard(int(tile_id))

    def _close_recorder(self, recorder: Any, end_text: Optional[str] = None) -> None:
        """Safely write an optional closing event and close recorder."""
        if recorder is None:
            return
        try:
            if end_text:
                recorder.log_text(end_text)
        except Exception:
            pass
        try:
            recorder.close()
        except Exception:
            pass

    async def _disconnect_client(self, client: BleakClient, helpers: BleSessionHelpers) -> None:
        """Safely stop notifications and disconnect BLE client when connected."""
        try:
            if client.is_connected:
                await helpers.stop_notifications()
                await asyncio.sleep(0.2)
                await client.disconnect()
        except Exception:
            pass

    async def _finalize_run(self, tile_id: int, client: BleakClient, helpers: BleSessionHelpers, recorder: Any) -> None:
        """Finalize one worker run with disconnect checklist/status and cycle_done event."""
        self._emit(tile_id, {"checklist": {"disconnect": "in_progress"}})
        await self._disconnect_client(client, helpers)
        self._close_recorder(recorder, "disconnect_done")
        self._emit(tile_id, {"checklist": {"disconnect": "done"}})
        self._emit(tile_id, {"status": "Disconnected", "phase": "disconnected"})
        self.ui_queue.put(make_cycle_done(tile_id))

    
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
        """Centralized UI emitter for tile updates with monotonic phase ordering."""
        try:
            out = dict(payload) if payload is not None else {}
            out.setdefault("ts_ms", int(time.time() * 1000))

            if "phase" in out and out["phase"]:
                pr = phase_rank(str(out["phase"]))
                prev = self._tile_phase_rank.get(tile_id, -1)
                if pr >= 0:
                    if prev >= 0 and pr < prev:
                        out["phase"] = PHASE_ORDER[prev]
                    else:
                        self._tile_phase_rank[tile_id] = pr

            self._queue_tile_update(tile_id, out)
        except Exception:
            pass

    def _queue_tile_update(self, tile_id: int, payload: TileUpdatePayload) -> None:
        """Queue one tile update event without phase normalization."""
        self.ui_queue.put(make_tile_update(tile_id, payload))

    @staticmethod
    def _waveform_key_for_type(twf_type: int) -> str:
        return _WAVEFORM_KEY_BY_TYPE.get(int(twf_type), f"twf_{int(twf_type)}")

    @staticmethod
    def _waveform_label_for_key(waveform_key: str) -> str:
        return _WAVEFORM_LABEL_BY_KEY.get(waveform_key, waveform_key)

    @staticmethod
    def _primary_export_info(export_infos: Dict[str, Optional[dict]]) -> Optional[dict]:
        if not export_infos:
            return None
        primary = export_infos.get(_DEFAULT_WAVEFORM_KEY)
        if primary:
            return primary
        for info in export_infos.values():
            if info:
                return info
        return None

    def _format_multi_export_text(self, export_infos: Dict[str, Optional[dict]]) -> str:
        lines = []
        for twf_type in _FULL_CYCLE_TWF_TYPES:
            key = self._waveform_key_for_type(twf_type)
            label = self._waveform_label_for_key(key)
            info = export_infos.get(key)
            if not info:
                lines.append(f"- {label}: no data")
                continue
            if "error" in info:
                lines.append(f"- {label}: ERROR {info.get('error')}")
                continue
            lines.append(f"- {label}:")
            lines.append(f"  - raw: {info.get('raw', '')}")
            if info.get("txt"):
                lines.append(f"  - txt: {info.get('txt', '')}")
            if info.get("samples"):
                lines.append(f"  - samples: {info.get('samples', '')}")
        return "\n".join(lines)

    def _create_ui_callback(self, tile_id: int) -> Callable[[TileUpdatePayload], None]:
        """Create a UI callback function for BLE helpers to avoid duplication."""
        def ui_callback(update_dict: TileUpdatePayload) -> None:
            self._queue_tile_update(tile_id, update_dict)
        return ui_callback

    async def _request_waveform_capture(
        self,
        tile_id: int,
        helpers: BleSessionHelpers,
        rx_timeout: float,
        twf_type: int,
        status_prefix: str,
        include_rx_text: bool,
    ) -> dict:
        waveform_key = self._waveform_key_for_type(twf_type)
        waveform_label = self._waveform_label_for_key(waveform_key)

        await asyncio.sleep(0.1)
        await helpers.send_vibration_selection(twf_type=twf_type)

        wave_payloads, received, expected, last_wave_rx = await self._collect_waveform_measurements(
            tile_id=tile_id,
            helpers=helpers,
            rx_timeout=rx_timeout,
            status_prefix=f"{status_prefix} {waveform_label}",
            include_rx_text=include_rx_text,
        )

        export_info = self._export_wave_payloads(tile_id, wave_payloads, waveform_name=waveform_key)
        return {
            "waveform_key": waveform_key,
            "export_info": export_info,
            "received": received,
            "expected": expected,
            "last_rx_text": last_wave_rx,
        }

    async def _collect_waveform_measurements(
        self,
        tile_id: int,
        helpers: BleSessionHelpers,
        rx_timeout: float,
        status_prefix: str,
        include_rx_text: bool,
    ) -> Tuple[List[bytes], int, Optional[int], Optional[str]]:
        """Collect send_measurement waveform payloads and emit progress updates."""
        received = 0
        expected: Optional[int] = None
        wave_payloads: List[bytes] = []
        last_rx_text: Optional[str] = None

        while True:
            payload, msg, msg_type = await helpers.recv_app(rx_timeout)
            if msg_type != "send_measurement":
                break

            wave_payloads.append(payload)
            received += 1

            if expected is None:
                try:
                    expected = int(msg.header.total_fragments)
                    if expected <= 0:
                        expected = None
                except Exception:
                    pass

            update_payload: TileUpdatePayload = {
                "phase": "waveform",
                "status": f"{status_prefix} {received}/{expected or '?'}",
                "checklist": {"general_info_exchange": "done", "data_collection": "in_progress"},
            }

            if include_rx_text:
                rx_text = format_rx_summary(msg_type, payload, ProtobufFormatter.format_payload_readable(payload))
                update_payload["rx_text"] = rx_text
                last_rx_text = rx_text

            self._emit(tile_id, update_payload)

            if expected and received >= expected:
                break

        return wave_payloads, received, expected, last_rx_text

    def _export_wave_payloads(self, tile_id: int, wave_payloads: List[bytes], waveform_name: Optional[str] = None) -> Optional[dict]:
        """Export waveform payloads, returning exporter output or error dict."""
        if not wave_payloads:
            return None
        try:
            return self.waveform_exporter.export_waveform_capture(tile_id, wave_payloads, waveform_name=waveform_name)
        except Exception as export_exc:
            return {"error": str(export_exc)}

    def run_cycle(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float, record_sessions: bool, session_root: str,
                name_contains: str = "") -> None:
        self._clear_cancel_state_for_tile(tile_id)
        self._call_soon(self._run_cycle_impl(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, record_sessions, session_root,
                        name_contains))

    def run_manual_action(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float, action: str, record_sessions: bool, session_root: str,
                name_contains: str = "") -> None:
        self._clear_cancel_state_for_tile(tile_id)
        self._call_soon(self._run_manual_action(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, action, record_sessions, session_root,
                        name_contains))

    async def _run_manual_action(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float, action: str, record_sessions: bool, session_root: str,
                            name_contains: str = "") -> None:
        """
        REFACTORED: Execute manual BLE action using centralized BleSessionHelpers.
        Reduced from ~400 lines to ~150 lines.
        """
        address_prefix, name_contains = normalize_ble_filters(address_prefix, name_contains)
        
        # Setup session recorder
        recorder, _session_dir = create_session_recorder(
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
            scan_timeout=scan_timeout,
            is_cancelled=lambda: self._is_cancelled(tile_id),
        )

        if was_cancelled:
            self._emit(tile_id, {"phase": "disconnected", "status": "Cancelled (scan)", "checklist": {"waiting_connection": "pending"}})
            return

        if not matched:
            self._emit(tile_id, {"status": "Not found", "address": "•"})
            self._close_recorder(recorder, "not_found")
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

            accept_session_msg = None
            accept_session_payload = None

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
                self._queue_tile_update(tile_id, {"status": "Connected (test OK)"})

            elif action == "overall":
                # Session already open, directly request metrics
                await asyncio.sleep(0.1)
                await helpers.send_metrics_selection()
                payload, msg, msg_type = await helpers.recv_app(rx_timeout)
                status = f"RX {msg_type}"
                if msg_type == "send_measurement":
                    try:
                        status += f" ({len(list(msg.send_measurement.measurement_data))} measurements)"
                    except Exception:
                        pass
                self._queue_tile_update(tile_id, {
                    "status": status,
                    "checklist": {"general_info_exchange": "done", "data_collection": "done"},
                    "rx_text": format_rx_summary(msg_type, payload, ProtobufFormatter.format_payload_readable(payload)),
                })

            elif action == "session_test":
                # Just display session info (already received in AcceptSession above)
                if accept_session_msg is None or accept_session_payload is None:
                    self._emit(tile_id, {"status": "Session test failed: no AcceptSession"})
                    raise RuntimeError("No AcceptSession received for session_test")
                session_info = {"accept_msg": accept_session_msg, "payload": accept_session_payload}
                rx_text = format_session_and_overall_text(session_info, [])
                await helpers.send_close_session()
                self._queue_tile_update(tile_id, {
                    "status": "Session test OK",
                    "checklist": {"general_info_exchange": "done", "close_session": "done"},
                    "rx_text": rx_text,
                })

            elif action in ("acceleration_twf", "velocity_twf", "enveloper3_twf"):
                # Map action to TWF type
                twf_map = {
                    "acceleration_twf": MEASUREMENT_TYPE_ACCELERATION_TWF,
                    "velocity_twf": MEASUREMENT_TYPE_VELOCITY_TWF,
                    "enveloper3_twf": MEASUREMENT_TYPE_ENVELOPER3_TWF,
                }
                req_twf_type = twf_map[action]
                capture = await self._request_waveform_capture(
                    tile_id=tile_id,
                    helpers=helpers,
                    rx_timeout=rx_timeout,
                    twf_type=req_twf_type,
                    status_prefix="Waveform blocks",
                    include_rx_text=True,
                )

                waveform_key = capture["waveform_key"]
                export_info = capture["export_info"]
                received = int(capture["received"] or 0)
                expected = capture["expected"]
                
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
                
                self._queue_tile_update(tile_id, {
                    "status": status_text,
                    "checklist": {"general_info_exchange": "done", "data_collection": "done", "close_session": "done"},
                    "rx_text": rx_text,
                    "export_info": export_info,
                    "export_infos": {waveform_key: export_info},
                })

            elif action == "full_cycle":
                if accept_session_msg is None or accept_session_payload is None:
                    self._emit(tile_id, {"status": "Full cycle failed: no AcceptSession"})
                    raise RuntimeError("No AcceptSession received for full_cycle")
                # Request overall measurements first
                await asyncio.sleep(0.1)
                await helpers.send_metrics_selection()
                payload, msg, msg_type = await helpers.recv_app(rx_timeout)
                
                # Extract overall values using the proper method
                overall_values = []
                if msg_type == "send_measurement":
                    try:
                        overall_values = OverallValuesExtractor.extract_overall_values(msg.send_measurement)
                    except Exception:
                        pass

                export_infos: Dict[str, Optional[dict]] = {}
                waveform_done = 0
                for req_twf_type in _FULL_CYCLE_TWF_TYPES:
                    capture = await self._request_waveform_capture(
                        tile_id=tile_id,
                        helpers=helpers,
                        rx_timeout=rx_timeout,
                        twf_type=req_twf_type,
                        status_prefix="Full cycle",
                        include_rx_text=False,
                    )
                    waveform_key = capture["waveform_key"]
                    export_info = capture["export_info"]
                    export_infos[waveform_key] = export_info
                    if export_info and "error" not in export_info:
                        waveform_done += 1

                export_info = self._primary_export_info(export_infos)
                
                # Close session
                await helpers.send_close_session()
                
                # Format display with session info + overall + export info
                session_info = {"accept_msg": accept_session_msg, "payload": accept_session_payload}
                rx_text = format_session_and_overall_text(session_info, overall_values)
                rx_text += "\n\n--- WAVEFORM EXPORTS ---\n"
                rx_text += self._format_multi_export_text(export_infos)
                
                self._queue_tile_update(tile_id, {
                    "status": f"Full cycle done (overall + waveforms {waveform_done}/3)",
                    "checklist": {"general_info_exchange": "done", "data_collection": "done", "close_session": "done"},
                    "rx_text": rx_text,
                    "export_info": export_info,
                    "export_infos": export_infos,
                })

            else:
                raise ValueError(f"Unknown action: {action}")

            await helpers.stop_notifications()

        except Exception as exc:
            self._emit(tile_id, {"status": f"Error: {type(exc).__name__}: {exc}"})
        finally:
            await self._finalize_run(tile_id, client, helpers, recorder)

    async def _run_cycle_impl(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float, record_sessions: bool, session_root: str,
                        name_contains: str = "") -> None:
        """
        REFACTORED: Full auto cycle using centralized BleSessionHelpers.
        Reduced from ~350 lines to ~180 lines.
        """
        address_prefix, name_contains = normalize_ble_filters(address_prefix, name_contains)
        
        # Setup session recorder
        recorder, _session_dir = create_session_recorder(
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
            scan_timeout=scan_timeout,
            is_cancelled=None,
        )

        if not matched:
            self._emit(tile_id, {"status": "Not found", "address": "•"})
            self._close_recorder(recorder, "not_found")
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
                    self._queue_tile_update(tile_id, {"status": f"MTU requested: {mtu}"})
                except Exception as exc:
                    self._queue_tile_update(tile_id, {"status": f"MTU request failed: {exc}"})

            await helpers.start_notifications()
            self._queue_tile_update(tile_id, {"status": "Opening session...", "checklist": {"general_info_exchange": "in_progress"}})

            # REFACTORED: New protocol - send OpenSession once
            await helpers.send_open_session()
            await asyncio.sleep(0.1)

            try:
                payload, app_message, message_type = await helpers.recv_app(rx_timeout)
            except asyncio.TimeoutError:
                self._queue_tile_update(tile_id, {"status": "AcceptSession timeout"})
            else:
                latest_status = "Received"
                error_info = None
                export_info = None
                export_infos = None
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
                        self._queue_tile_update(tile_id, {"status": latest_status})
                        
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
                        for loop_index in range(_METRICS_COLLECTION_LOOPS):
                            if self._is_cancelled(tile_id):
                                self._emit(tile_id, {"phase": "disconnected", "status": "Cancelled (metrics)"})
                                data_collection_complete = False
                                break
                            
                            last_loop_index = loop_index
                            latest_status = "Session accepted"
                            if loop_index == 0:
                                self._queue_tile_update(tile_id, {"checklist": {"general_info_exchange": "done", "data_collection": "in_progress"}})
                            
                            self._emit(tile_id, {"phase": "metrics", "status": f"Sending measurement_request ({loop_index + 1}/6)..."})
                            await helpers.send_metrics_selection()

                            try:
                                data_payload, data_message, data_type = await helpers.recv_app(rx_timeout)
                            except asyncio.TimeoutError:
                                latest_status = "Measurement timeout"
                                data_collection_complete = False
                                self._queue_tile_update(tile_id, {"checklist": {"data_collection": "pending"}})
                                break
                            else:
                                try:
                                    if data_type == "send_measurement":
                                        measurement_data_list = list(data_message.send_measurement.measurement_data)
                                        overall_values = OverallValuesExtractor.extract_overall_values(data_message.send_measurement)
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
                                    self._queue_tile_update(tile_id, {"checklist": {"data_collection": "pending"}})
                                    break

                        if data_collection_complete and last_loop_index == (_METRICS_COLLECTION_LOOPS - 1) and latest_status == "Measurement data received":
                            self._queue_tile_update(tile_id, {"checklist": {"data_collection": "done"}})
                        else:
                            data_collection_complete = False
                            self._queue_tile_update(tile_id, {"checklist": {"data_collection": "pending"}})

                        if data_collection_complete:
                            export_infos = {}
                            waveform_done = 0
                            for req_twf_type in _FULL_CYCLE_TWF_TYPES:
                                capture = await self._request_waveform_capture(
                                    tile_id=tile_id,
                                    helpers=helpers,
                                    rx_timeout=rx_timeout,
                                    twf_type=req_twf_type,
                                    status_prefix="Waveform",
                                    include_rx_text=True,
                                )
                                waveform_key = capture["waveform_key"]
                                one_export = capture["export_info"]
                                export_infos[waveform_key] = one_export
                                if capture.get("last_rx_text"):
                                    latest_rx_text = capture["last_rx_text"]
                                if one_export and isinstance(one_export, dict) and ("error" not in one_export):
                                    waveform_done += 1

                            export_info = self._primary_export_info(export_infos)
                            if waveform_done == 3:
                                latest_status = "Waveforms done (3/3)"
                            else:
                                latest_status = f"Waveforms done ({waveform_done}/3)"

                            latest_rx_text = latest_rx_text + "\n\nEXPORTS:\n" + self._format_multi_export_text(export_infos)
                            if export_infos is not None:
                                self._emit(tile_id, {"phase": "waveform", "checklist": {"data_collection": "done"}})
                                self._emit(tile_id, {"phase": "close_session", "checklist": {"close_session": "in_progress"}})
                                await asyncio.sleep(0.1)
                                await helpers.send_close_session()
                                self._emit(tile_id, {"phase": "close_session", "checklist": {"close_session": "done"}})
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
                
                self._queue_tile_update(tile_id, {
                    "status": latest_status,
                    "rx_text": latest_rx_text,
                    "export_info": export_info,
                    "export_infos": export_infos,
                    "overall_values": overall_values,
                    "error": error_info,
                })

            await helpers.stop_notifications()
            
        except Exception as exc:
            self._emit(tile_id, {"status": f"Error: {type(exc).__name__}: {exc}"})
        finally:
            await self._finalize_run(tile_id, client, helpers, recorder)


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
