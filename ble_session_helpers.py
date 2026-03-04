"""
BLE Session Helpers - Centralized BLE communication logic
Updated for new simplified SKF protocol
"""

import asyncio
import time
import struct
from typing import Callable, Optional
import os
import sys

from protocol_utils import BASE_DIR, PROTOCOL_DIR, CAPTURE_DIR
if PROTOCOL_DIR not in sys.path:
    sys.path.insert(0, PROTOCOL_DIR)
    
import app_pb2
import session_pb2
import measurement_pb2
import command_pb2
import common_pb2
import configuration_pb2
import fota_pb2


class BleSessionHelpers:
    """
    Encapsulates all BLE session helpers (notify, rx/tx, message building).
    Eliminates ~400 lines of duplication between _run_manual_action and _run_cycle_impl.
    """

    def __init__(self, client, uart_rx_uuid: str, uart_tx_uuid: str, 
                 recorder=None, ui_callback: Optional[Callable] = None):
        """
        Args:
            client: BleakClient instance
            uart_rx_uuid: UUID for writing (RX characteristic)
            uart_tx_uuid: UUID for reading (TX characteristic / notifications)
            recorder: Optional SessionRecorder for logging
            ui_callback: Optional callback(dict) for UI updates
        """
        self.client = client
        self.uart_rx_uuid = uart_rx_uuid
        self.uart_tx_uuid = uart_tx_uuid
        self.recorder = recorder
        self.ui_callback = ui_callback
        
        # RX queue and event for async notification handling
        self.rx_queue = []
        self.rx_event = asyncio.Event()
        
        # Message sequence number
        self.next_seq_no = 1

    def _on_notify(self, _sender: int, data: bytearray) -> None:
        """Notification handler - queues received data."""
        try:
            payload = bytes(data)
            self.rx_queue.append(payload)
            self.rx_event.set()
            
            if self.recorder is not None:
                msg_type = self._pb_message_type(payload)
                self.recorder.log("RX", "notify", msg_type, payload)
        except Exception:
            pass

    async def start_notifications(self) -> None:
        """Start BLE notifications."""
        await self.client.start_notify(self.uart_tx_uuid, self._on_notify)

    async def stop_notifications(self) -> None:
        """Stop BLE notifications (safe, ignores errors)."""
        try:
            await self.client.stop_notify(self.uart_tx_uuid)
        except Exception:
            pass

    async def wait_next_rx(self, timeout_s: float) -> bytes:
        """
        Wait for next notification with timeout.
        
        Returns:
            bytes: Received payload
            
        Raises:
            asyncio.TimeoutError: If timeout expires
        """
        loop = asyncio.get_running_loop()
        end_time = loop.time() + timeout_s
        
        while True:
            if self.rx_queue:
                return self.rx_queue.pop(0)
            
            self.rx_event.clear()
            
            if self.rx_queue:
                return self.rx_queue.pop(0)
            
            remaining = end_time - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            
            await asyncio.wait_for(self.rx_event.wait(), timeout=remaining)

    def _alloc_seq(self) -> int:
        """Allocate next message sequence number (message_id in new protocol)."""
        v = self.next_seq_no
        self.next_seq_no += 1
        return v

    def _mk_header(self, total_fragments: int = 1, current_fragment: int = 1) -> common_pb2.Header:
        """Create standard header for new protocol."""
        return common_pb2.Header(
            version=1,
            message_id=self._alloc_seq(),
            current_fragment=current_fragment,
            total_fragments=total_fragments,
        )

    async def write_app_message(self, app_msg) -> bytes:
        """
        Serialize and write App message to device.
        
        Returns:
            bytes: Serialized payload
        """
        payload = app_msg.SerializeToString()
        await self.client.write_gatt_char(self.uart_rx_uuid, payload)
        
        if self.recorder is not None:
            msg_type = self._pb_message_type(payload)
            self.recorder.log("TX", "write", msg_type, payload)
        
        if self.ui_callback is not None:
            msg_type = self._pb_message_type(payload)
            self.ui_callback({
                "status": f"TX {msg_type} ({len(payload)} B)"
            })
        
        return payload

    def _safe_parse_app(self, payload: bytes):
        """Parse App message from bytes."""
        msg = app_pb2.App()
        msg.ParseFromString(payload)
        return msg

    def _pb_message_type(self, payload: bytes) -> str:
        """Extract message type from protobuf payload."""
        try:
            message = app_pb2.App()
            message.ParseFromString(payload)
            return message.WhichOneof("payload") or "(none)"
        except Exception:
            return "(parse_error)"

    async def recv_app(self, timeout_s: float) -> tuple:
        """
        Receive and parse next App message.
        
        Returns:
            tuple: (payload: bytes, msg: App, msg_type: str)
            
        Raises:
            asyncio.TimeoutError: If timeout expires
        """
        payload = await self.wait_next_rx(timeout_s)
        msg = self._safe_parse_app(payload)
        msg_type = msg.WhichOneof("payload") or "(none)"
        return payload, msg, msg_type

    # --- Protocol-specific message senders (new protocol) ---

    async def send_open_session(self) -> None:
        """Send OpenSession message to start a session with the sensor."""
        current_sync_time = int(time.time())  # Unix time in seconds
        open_session = session_pb2.OpenSession(
            current_sync_time=current_sync_time
        )
        await self.write_app_message(
            app_pb2.App(header=self._mk_header(), open_session=open_session)
        )

    # Legacy compatibility: send_config_time now calls send_open_session
    async def send_config_time(self) -> None:
        """Legacy method - redirects to send_open_session."""
        await self.send_open_session()

    async def send_version_retrieve(self) -> None:
        """
        Legacy method - no longer needed in new protocol.
        Version info comes automatically in AcceptSession.
        This now sends AcceptSession request by sending OpenSession.
        """
        await self.send_open_session()

    async def send_config_hash_retrieve(self) -> None:
        """
        Legacy method - no longer needed in new protocol.
        Config hash comes automatically in AcceptSession.
        This is now a no-op for compatibility.
        """
        pass  # No-op: config hash is in AcceptSession already

    async def send_measurement_request(self, measurement_types: list) -> None:
        """
        Request measurements from sensor.
        
        Args:
            measurement_types: List of MeasurementType enum values (integers)
        """
        measurement_type_msgs = [
            measurement_pb2.measurementType(measurement_type=mt) 
            for mt in measurement_types
        ]
        meas_request = measurement_pb2.measurementRequest(
            measurement=measurement_type_msgs
        )
        await self.write_app_message(
            app_pb2.App(header=self._mk_header(), measurement_request=meas_request)
        )

    async def send_metrics_selection(self, sample_time_end_ms: int = 0) -> None:
        """
        Request all overall metrics (acceleration, velocity, enveloper3, temperature).
        Legacy compatibility method - sample_time_end_ms parameter ignored in new protocol.
        """
        measurement_types = [
            1,  # MeasurementTypeAccelerationOverall
            2,  # MeasurementTypeVelocityOverall
            3,  # MeasurementTypeEnveloper3Overall
            4,  # MeasurementTypeTemperatureOverall
        ]
        await self.send_measurement_request(measurement_types)

    async def send_vibration_selection(self, sample_time_end_ms: int = 0, twf_type: int = None) -> None:
        """
        Request vibration waveform data (TWF).
        
        IMPORTANT: Sensor supports only ONE TWF measurement per request.
        
        Args:
            sample_time_end_ms: Legacy parameter, ignored in new protocol
            twf_type: TWF measurement type to request (5=Acceleration, 6=Velocity, 7=Enveloper3)
                     If None, uses DEFAULT_TWF_TYPE from config
        """
        from ble_config import DEFAULT_TWF_TYPE
        if twf_type is None:
            twf_type = DEFAULT_TWF_TYPE
        
        # Sensor only accepts ONE TWF type per request
        measurement_types = [twf_type]
        await self.send_measurement_request(measurement_types)

    async def send_close_session(self) -> None:
        """Send CloseSession command."""
        close_cmd = command_pb2.Command(
            command=command_pb2.CommandTypeCloseSession
        )
        await self.write_app_message(
            app_pb2.App(header=self._mk_header(), command=close_cmd)
        )

    # --- Common sequences ---

    async def setup_sync_time_version_hash(self, rx_timeout: float) -> tuple:
        """
        Perform standard setup sequence: open session and receive AcceptSession.
        
        Returns:
            tuple: (payload, msg, msg_type) of AcceptSession or None on timeout
        """
        await self.send_open_session()
        await asyncio.sleep(0.1)
        
        try:
            payload, msg, msg_type = await self.recv_app(rx_timeout)
            if msg_type == "accept_session":
                return (payload, msg, msg_type)
            return None
        except asyncio.TimeoutError:
            return None
