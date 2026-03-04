"""Waveform collection/export helper used by worker flows.

Return contract of `collect_waveform_export` is intentionally stable:
- ok: success flag
- received / expected: waveform block counters
- export_info: exporter result on success
- last_payload / last_type / last_rx_text: latest RX context for UI/debug
- error_info: structured error details when ok is False
"""

import asyncio
from typing import Any, Awaitable, Callable, Optional

from display_formatters import format_rx_summary
from protobuf_formatters import ProtobufFormatter
from ui_events import TileUpdatePayload

_MIN_WAVEFORM_RX_TIMEOUT_S = 10.0
WaveformExportResult = dict[str, Any]


def _make_result(
    *,
    ok: bool,
    received: int,
    expected: Optional[int],
    export_info: Optional[dict],
    last_payload: bytes,
    last_type: str,
    last_rx_text: str,
    error_info: Optional[dict],
) -> WaveformExportResult:
    return {
        "ok": ok,
        "received": received,
        "expected": expected,
        "export_info": export_info,
        "last_payload": last_payload,
        "last_type": last_type,
        "last_rx_text": last_rx_text,
        "error_info": error_info,
    }


def _make_error(where: str, exc_or_type: Any, msg: str = "") -> dict:
    if isinstance(exc_or_type, Exception):
        return {"where": where, "type": type(exc_or_type).__name__, "msg": str(exc_or_type)}
    return {"where": where, "type": str(exc_or_type), "msg": msg}


def _format_rx_text(payload: bytes, msg_type: str) -> str:
    return format_rx_summary(
        msg_type,
        payload,
        ProtobufFormatter.format_payload_readable(payload),
    )


def _extract_expected_fragments(app_message: Any) -> Optional[int]:
    try:
        total_fragments = int(app_message.header.total_fragments)
        return total_fragments if total_fragments > 0 else None
    except Exception:
        return None


async def collect_waveform_export(
    *,
    tile_id: int,
    recv_app: Callable[[float], Awaitable[tuple]],
    rx_timeout: float,
    is_cancelled: Callable[[], bool],
    emit: Callable[[TileUpdatePayload], None],
    export_waveform_capture: Callable[[int, list], dict],
) -> WaveformExportResult:
    """Collect waveform `send_measurement` frames and export them.

    Notes:
    - Scan stops when `expected` fragments are reached (if provided by header).
    - Any non-`send_measurement` frame ends collection with a structured error.
    - RX timeout is clamped to a minimum value to tolerate long waveform transfers.

    Returns:
        dict: Stable structure with keys
            ok, received, expected, export_info,
            last_payload, last_type, last_rx_text, error_info.
    """
    received = 0
    expected: Optional[int] = None
    last_payload = b""
    last_type = "(none)"
    last_rx_text = ""
    wave_payloads = []

    wave_rx_timeout = max(float(rx_timeout), _MIN_WAVEFORM_RX_TIMEOUT_S)

    try:
        while True:
            if is_cancelled():
                emit({"phase": "disconnected", "status": "Cancelled (waveform)"})
                return _make_result(
                    ok=False,
                    received=received,
                    expected=expected,
                    export_info=None,
                    last_payload=last_payload,
                    last_type=last_type,
                    last_rx_text=last_rx_text,
                    error_info=_make_error("waveform", "Cancelled", "cancel requested"),
                )

            try:
                data_payload, data_message, data_type = await recv_app(wave_rx_timeout)
            except asyncio.TimeoutError as exc:
                return _make_result(
                    ok=False,
                    received=received,
                    expected=expected,
                    export_info=None,
                    last_payload=last_payload,
                    last_type=last_type,
                    last_rx_text=last_rx_text,
                    error_info=_make_error("waveform_recv_timeout", exc),
                )

            last_payload, last_type = data_payload, data_type

            if data_type != "send_measurement":
                last_rx_text = _format_rx_text(data_payload, data_type)
                return _make_result(
                    ok=False,
                    received=received,
                    expected=expected,
                    export_info=None,
                    last_payload=last_payload,
                    last_type=last_type,
                    last_rx_text=last_rx_text,
                    error_info=_make_error("waveform_unexpected_type", "UnexpectedType", str(data_type)),
                )

            wave_payloads.append(data_payload)
            received += 1

            if expected is None:
                expected = _extract_expected_fragments(data_message)

            last_rx_text = _format_rx_text(data_payload, data_type)
            emit(
                {
                    "phase": "waveform",
                    "status": f"Waveform blocks {received}/{expected or '?'}",
                    "checklist": {"data_collection": "in_progress"},
                    "rx_text": last_rx_text,
                }
            )

            if expected is not None and received >= expected:
                break

        export_info = None
        if wave_payloads:
            try:
                export_info = export_waveform_capture(tile_id, wave_payloads)
            except Exception as export_exc:
                return _make_result(
                    ok=False,
                    received=received,
                    expected=expected,
                    export_info=None,
                    last_payload=last_payload,
                    last_type=last_type,
                    last_rx_text=last_rx_text,
                    error_info=_make_error("waveform_export", export_exc),
                )

        return _make_result(
            ok=True,
            received=received,
            expected=expected,
            export_info=export_info,
            last_payload=last_payload,
            last_type=last_type,
            last_rx_text=last_rx_text,
            error_info=None,
        )
    except Exception as exc:
        return _make_result(
            ok=False,
            received=received,
            expected=expected,
            export_info=None,
            last_payload=last_payload,
            last_type=last_type,
            last_rx_text=last_rx_text,
            error_info=_make_error("waveform_collect", exc),
        )
