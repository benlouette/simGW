"""
BLE Session Helpers - Centralized BLE communication logic
Extracted from simGw_v9_Temp.py to eliminate duplication
"""

import asyncio
import time
import struct
from typing import Callable, Optional
import os
import sys

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
        """Allocate next message sequence number."""
        v = self.next_seq_no
        self.next_seq_no += 1
        return v

    def _mk_header(self) -> Froto_pb2.FrotoHeader:
        """Create standard Froto header."""
        return Froto_pb2.FrotoHeader(
            version=1,
            is_up=False,
            message_seq_no=self._alloc_seq(),
            time_to_live=3,
            primitive_type=Froto_pb2.SIMPLE_DISSEMINATE,
            message_type=Froto_pb2.NORMAL_MESSAGE,
            total_block=1,
        )

    async def write_app_message(self, app_msg) -> bytes:
        """
        Serialize and write AppMessage to device.
        
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
        """Parse AppMessage from bytes."""
        msg = DeviceAppBulletSensor_pb2.AppMessage()
        msg.ParseFromString(payload)
        return msg

    def _pb_message_type(self, payload: bytes) -> str:
        """Extract message type from protobuf payload."""
        try:
            message = DeviceAppBulletSensor_pb2.AppMessage()
            message.ParseFromString(payload)
            return message.WhichOneof("_messages") or "(none)"
        except Exception:
            return "(parse_error)"

    async def recv_app(self, timeout_s: float) -> tuple:
        """
        Receive and parse next AppMessage.
        
        Returns:
            tuple: (payload: bytes, msg: AppMessage, msg_type: str)
            
        Raises:
            asyncio.TimeoutError: If timeout expires
        """
        payload = await self.wait_next_rx(timeout_s)
        msg = self._safe_parse_app(payload)
        msg_type = msg.WhichOneof("_messages") or "(none)"
        return payload, msg, msg_type

    # --- Protocol-specific message senders ---

    async def send_config_time(self) -> None:
        """Send current time configuration."""
        current_time_ms = int(time.time() * 1000)
        config_pair = ConfigurationAndCommand_pb2.ConfigPair(
            specific_config_item=Common_pb2.CURRENT_TIME,
            time_config_content=ConfigurationAndCommand_pb2.TimeArray(
                time=[ConfigurationAndCommand_pb2.TimeArrayElement(time=current_time_ms)]
            ),
        )
        config_dissem = ConfigurationAndCommand_pb2.ConfigDisseminate(
            header=self._mk_header(),
            appVer=1,
            product=Common_pb2.UNKNOWN_PRODUCT,
            config_pair=[config_pair],
        )
        await self.write_app_message(
            DeviceAppBulletSensor_pb2.AppMessage(appVer=1, config_dissem=config_dissem)
        )

    async def send_version_retrieve(self) -> None:
        """Request device firmware version."""
        msg = FirmwareUpdateOverTheAir_pb2.VersionRetrieve(
            header=self._mk_header(),
            appVer=1,
            payload=FirmwareUpdateOverTheAir_pb2.CURRENT_VERSION,
        )
        await self.write_app_message(
            DeviceAppBulletSensor_pb2.AppMessage(appVer=1, version_retrieve=msg)
        )

    async def send_config_hash_retrieve(self) -> None:
        """Request device configuration hash."""
        msg = ConfigurationAndCommand_pb2.ConfigRetrieve(
            header=self._mk_header(),
            appVer=1,
            payload=ConfigurationAndCommand_pb2.CURRENT_CONFIG_HASH,
        )
        await self.write_app_message(
            DeviceAppBulletSensor_pb2.AppMessage(appVer=1, config_retrieve=msg)
        )

    async def send_metrics_selection(self, sample_time_end_ms: int) -> None:
        """Request overall metrics (temperature, humidity, voltage)."""
        measure_types = [
            SensingDataUpload_pb2.MeasurementTypeMsg(
                measure_type=Common_pb2.ENVIROMENTAL_TEMPERATURE_CURRENT
            ),
            SensingDataUpload_pb2.MeasurementTypeMsg(
                measure_type=Common_pb2.ENVIROMENTAL_HUMIDITY_CURRENT
            ),
            SensingDataUpload_pb2.MeasurementTypeMsg(
                measure_type=Common_pb2.VOLTAGE_CURRENT
            ),
        ]
        msg = SensingDataUpload_pb2.DataSelectionDisseminate(
            header=self._mk_header(),
            appVer=1,
            product=Common_pb2.UNKNOWN_PRODUCT,
            measure_type=measure_types,
            sample_time_start=0,
            sample_time_end=sample_time_end_ms,
        )
        await self.write_app_message(
            DeviceAppBulletSensor_pb2.AppMessage(appVer=1, data_selection=msg)
        )

    async def send_vibration_selection(self, sample_time_end_ms: int) -> None:
        """Request vibration waveform data."""
        msg = SensingDataUpload_pb2.DataSelectionDisseminate(
            header=self._mk_header(),
            appVer=1,
            product=Common_pb2.UNKNOWN_PRODUCT,
            measure_type=[
                SensingDataUpload_pb2.MeasurementTypeMsg(
                    measure_type=Common_pb2.VIBRATION_ACC_WAVE
                )
            ],
            sample_time_start=0,
            sample_time_end=sample_time_end_ms,
        )
        await self.write_app_message(
            DeviceAppBulletSensor_pb2.AppMessage(appVer=1, data_selection=msg)
        )

    async def send_close_session(self) -> None:
        """Send close session command."""
        msg = ConfigurationAndCommand_pb2.CommandDisseminate(
            header=self._mk_header(),
            appVer=1,
            command_pair=ConfigurationAndCommand_pb2.CommandPair(
                command=Common_pb2.CLOSE_SESSION
            ),
        )
        await self.write_app_message(
            DeviceAppBulletSensor_pb2.AppMessage(appVer=1, command_dissem=msg)
        )

    # --- Common sequences ---

    async def setup_sync_time_version_hash(self, rx_timeout: float) -> tuple:
        """
        Perform standard setup sequence: sync time, get version, get config hash.
        
        Returns:
            tuple: (version_payload, version_msg, hash_payload, hash_msg) or None on timeout
        """
        await self.send_config_time()
        await asyncio.sleep(0.1)
        
        await self.send_version_retrieve()
        try:
            version_payload, version_msg, version_type = await self.recv_app(rx_timeout)
        except asyncio.TimeoutError:
            return None
        
        await asyncio.sleep(0.1)
        await self.send_config_hash_retrieve()
        
        try:
            hash_payload, hash_msg, hash_type = await self.recv_app(rx_timeout)
        except asyncio.TimeoutError:
            return None
        
        return version_payload, version_msg, hash_payload, hash_msg
