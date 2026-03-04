"""BLE session helper utilities.

Purpose:
- centralize BLE RX/TX plumbing around one active BLE client
- build and send protocol-specific protobuf App messages
- expose a small async API used by worker orchestration flows

Error handling policy:
- notification callback is fail-safe (never raises)
- public awaitable methods raise normal asyncio/protobuf exceptions
- callers decide retry/cancel policy at worker level
"""

import asyncio
import time
from collections import deque
from typing import Any, Callable, Deque, Optional, Sequence

from protocol_imports import app_pb2, command_pb2, common_pb2, measurement_pb2, session_pb2
from ui_events import TileUpdatePayload

_OVERALL_MEASUREMENT_TYPES = (1, 2, 3, 4)
RecvAppTuple = tuple[bytes, Any, str]


class BleSessionHelpers:
    """Stateful helper around a BLE client and SKF protobuf protocol flow.

    Responsibilities:
    - Start/stop notifications
    - Queue and await RX payloads
    - Serialize/emit TX app messages
    - Build protocol-specific messages (open session, metrics, waveform, close)
    """

    def __init__(
        self,
        client,
        uart_rx_uuid: str,
        uart_tx_uuid: str,
        recorder=None,
        ui_callback: Optional[Callable[[TileUpdatePayload], None]] = None,
    ):
        """Create a helper bound to one BLE client connection.

        Args:
            client: Connected (or connectable) BleakClient instance.
            uart_rx_uuid: Characteristic UUID used for writes (device RX).
            uart_tx_uuid: Characteristic UUID used for notifications (device TX).
            recorder: Optional logger with a `.log(...)` method.
            ui_callback: Optional callback used to emit compact TX status.
        """
        self.client = client
        self.uart_rx_uuid = uart_rx_uuid
        self.uart_tx_uuid = uart_tx_uuid
        self.recorder = recorder
        self.ui_callback = ui_callback

        self.rx_queue: Deque[bytes] = deque()
        self.rx_event = asyncio.Event()
        self.next_seq_no = 1

    async def start_notifications(self) -> None:
        """Start notifications on the TX characteristic."""
        await self.client.start_notify(self.uart_tx_uuid, self._on_notify)

    async def stop_notifications(self) -> None:
        """Stop notifications on the TX characteristic (best effort)."""
        try:
            await self.client.stop_notify(self.uart_tx_uuid)
        except Exception:
            pass

    async def wait_next_rx(self, timeout_s: float) -> bytes:
        """Wait for next RX payload until timeout.

        Raises:
            asyncio.TimeoutError: when no payload arrives before timeout.
        """
        loop = asyncio.get_running_loop()
        end_time = loop.time() + float(timeout_s)

        while True:
            payload = self._try_pop_rx()
            if payload is not None:
                return payload

            self.rx_event.clear()

            payload = self._try_pop_rx()
            if payload is not None:
                return payload

            remaining = end_time - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError()

            await asyncio.wait_for(self.rx_event.wait(), timeout=remaining)

    async def recv_app(self, timeout_s: float) -> RecvAppTuple:
        """Receive and parse next protobuf App payload.

        Returns:
            tuple[bytes, Any, str]: (raw_payload, parsed_app_msg, payload_oneof_name)
        """
        payload = await self.wait_next_rx(timeout_s)
        msg = self._safe_parse_app(payload)
        msg_type = msg.WhichOneof("payload") or "(none)"
        return payload, msg, msg_type

    async def write_app_message(self, app_msg) -> bytes:
        """Serialize and send an App message to device RX characteristic.

        Returns:
            bytes: Serialized payload that was written.
        """
        payload = app_msg.SerializeToString()
        await self.client.write_gatt_char(self.uart_rx_uuid, payload)

        msg_type = self._pb_message_type(payload)
        if self.recorder is not None:
            self.recorder.log("TX", "write", msg_type, payload)

        if self.ui_callback is not None:
            self.ui_callback({"status": f"TX {msg_type} ({len(payload)} B)"})

        return payload

    async def send_open_session(self) -> None:
        """Send OpenSession command with current unix time."""
        open_session = session_pb2.OpenSession(current_sync_time=int(time.time()))
        await self.write_app_message(app_pb2.App(header=self._mk_header(), open_session=open_session))

    async def send_measurement_request(self, measurement_types: Sequence[int]) -> None:
        """Send a measurementRequest with one or more measurement types."""
        measurement_type_msgs = [
            measurement_pb2.measurementType(measurement_type=int(measurement_type))
            for measurement_type in measurement_types
        ]
        request = measurement_pb2.measurementRequest(measurement=measurement_type_msgs)
        await self.write_app_message(app_pb2.App(header=self._mk_header(), measurement_request=request))

    async def send_metrics_selection(self) -> None:
        """Request all overall metrics (accel/vel/enveloper3/temp)."""
        await self.send_measurement_request(_OVERALL_MEASUREMENT_TYPES)

    async def send_vibration_selection(self, twf_type: int = None) -> None:
        """Request one TWF measurement type."""
        from ble_config import DEFAULT_TWF_TYPE

        selected_twf_type = DEFAULT_TWF_TYPE if twf_type is None else int(twf_type)
        await self.send_measurement_request([selected_twf_type])

    async def send_close_session(self) -> None:
        """Send CloseSession command."""
        close_cmd = command_pb2.Command(command=command_pb2.CommandTypeCloseSession)
        await self.write_app_message(app_pb2.App(header=self._mk_header(), command=close_cmd))

    async def setup_sync_time_version_hash(self, rx_timeout: float) -> Optional[RecvAppTuple]:
        """Open session and wait for AcceptSession reply.

        Returns:
            Optional[tuple[bytes, Any, str]]: AcceptSession tuple, or None when
            timeout occurs or a different message type is received.
        """
        await self.send_open_session()
        await asyncio.sleep(0.1)

        try:
            payload, msg, msg_type = await self.recv_app(rx_timeout)
            if msg_type == "accept_session":
                return payload, msg, msg_type
            return None
        except asyncio.TimeoutError:
            return None

    def _on_notify(self, _sender: int, data: bytearray) -> None:
        """Bleak notification callback: queue payload and notify waiters."""
        try:
            payload = bytes(data)
            self.rx_queue.append(payload)
            self.rx_event.set()

            if self.recorder is not None:
                self.recorder.log("RX", "notify", self._pb_message_type(payload), payload)
        except Exception:
            pass

    def _try_pop_rx(self) -> Optional[bytes]:
        """Pop one queued RX payload if available."""
        if self.rx_queue:
            return self.rx_queue.popleft()
        return None

    def _alloc_seq(self) -> int:
        """Allocate next monotonically increasing message id."""
        message_id = self.next_seq_no
        self.next_seq_no += 1
        return message_id

    def _mk_header(self, total_fragments: int = 1, current_fragment: int = 1) -> common_pb2.Header:
        """Build a standard App header."""
        return common_pb2.Header(
            version=1,
            message_id=self._alloc_seq(),
            current_fragment=current_fragment,
            total_fragments=total_fragments,
        )

    def _safe_parse_app(self, payload: bytes) -> Any:
        """Parse bytes into App protobuf message."""
        msg = app_pb2.App()
        msg.ParseFromString(payload)
        return msg

    def _pb_message_type(self, payload: bytes) -> str:
        """Extract payload oneof type name from App protobuf bytes."""
        try:
            message = app_pb2.App()
            message.ParseFromString(payload)
            return message.WhichOneof("payload") or "(none)"
        except Exception:
            return "(parse_error)"
