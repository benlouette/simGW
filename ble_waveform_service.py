"""
BLE Waveform Service - Shared waveform collection/export logic for worker flows.
"""

import asyncio
from typing import Callable, Awaitable

from display_formatters import format_rx_summary
from protobuf_formatters import ProtobufFormatter
from ui_events import TileUpdatePayload


async def collect_waveform_export(
    *,
    tile_id: int,
    recv_app: Callable[[float], Awaitable[tuple]],
    rx_timeout: float,
    is_cancelled: Callable[[], bool],
    emit: Callable[[TileUpdatePayload], None],
    export_waveform_capture: Callable[[int, list, list], dict],
) -> dict:
    """
    Receive waveform send_measurement blocks, export capture files, and return a structured result.
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
            if is_cancelled():
                emit({"phase": "disconnected", "status": "Cancelled (waveform)"})
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
                data_payload, data_message, data_type = await recv_app(wave_rx_timeout)
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

            if data_type != "send_measurement":
                rx_text = format_rx_summary(
                    ProtobufFormatter.get_message_type(data_payload),
                    data_payload,
                    ProtobufFormatter.format_payload_readable(data_payload)
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
                    expected = int(data_message.header.total_fragments)
                    if expected <= 0:
                        expected = None
                except Exception:
                    expected = None

            rx_text = format_rx_summary(
                ProtobufFormatter.get_message_type(data_payload),
                data_payload,
                ProtobufFormatter.format_payload_readable(data_payload)
            )

            emit({
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
                export_info = export_waveform_capture(tile_id, wave_payloads, wave_msgs)
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
