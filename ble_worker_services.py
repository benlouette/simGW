"""
BLE Worker Services - Shared helpers for BleCycleWorker flows.

Contains reusable helpers for:
- BLE filter normalization
- Session recorder creation
- Device scanning with optional cancellation polling
"""

import asyncio
import time
from typing import Callable, Optional, Tuple

from bleak import BleakScanner

from ble_filters import adv_matches as ble_adv_matches
from session_recorder import SessionRecorder
from ui_events import make_tile_update


def normalize_ble_filters(
    address_prefix: str,
    name_contains: str = "",
    service_uuid_contains: str = "",
    mfg_id_hex: str = "",
    mfg_data_hex_contains: str = "",
) -> Tuple[str, str, str, str, str]:
    """Normalize BLE filter inputs for consistent matching."""
    return (
        (address_prefix or "").upper(),
        (name_contains or "").strip(),
        (service_uuid_contains or "").strip(),
        (mfg_id_hex or "").strip(),
        (mfg_data_hex_contains or "").strip(),
    )


def create_session_recorder(
    tile_id: int,
    action: Optional[str],
    record_sessions: bool,
    session_root: str,
    ui_queue,
):
    """
    Create and initialize a SessionRecorder for a cycle/action.

    Returns:
        tuple: (recorder|None, session_dir|None)
    """
    if not record_sessions:
        return None, None

    ts = time.strftime("%Y%m%d_%H%M%S")
    suffix = action if action else "auto"
    session_name = f"sensor{tile_id}_{ts}_{suffix}"
    recorder = SessionRecorder(session_root, session_name)
    session_dir = recorder.session_dir
    ui_queue.put(make_tile_update(tile_id, {"session_dir": session_dir}))

    if action:
        recorder.log_text(f"manual_start:{action}")
    else:
        recorder.log_text("cycle_start")

    return recorder, session_dir


async def scan_for_matching_device(
    *,
    address_prefix: str,
    name_contains: str,
    service_uuid_contains: str,
    mfg_id_hex: str,
    mfg_data_hex_contains: str,
    scan_timeout: float,
    is_cancelled: Optional[Callable[[], bool]] = None,
    poll_interval_s: float = 0.25,
):
    """
    Scan for the first BLE device matching current filters.

    Returns:
        tuple: (matched_device|None, was_cancelled: bool)
    """
    matched_device = {"value": None}
    found_event = asyncio.Event()

    def _on_device_found(device, advertisement_data):
        if not getattr(device, "address", None):
            return
        if is_cancelled is not None and is_cancelled():
            return
        if ble_adv_matches(
            device,
            advertisement_data,
            address_prefix,
            name_contains,
            service_uuid_contains,
            mfg_id_hex,
            mfg_data_hex_contains,
        ):
            if not found_event.is_set():
                matched_device["value"] = device
                found_event.set()

    scanner = BleakScanner(_on_device_found)
    await scanner.start()

    was_cancelled = False
    try:
        loop = asyncio.get_running_loop()
        start_t = loop.time()
        while True:
            if is_cancelled is not None and is_cancelled():
                was_cancelled = True
                break

            remaining = float(scan_timeout) - (loop.time() - start_t)
            if remaining <= 0:
                break

            try:
                await asyncio.wait_for(found_event.wait(), timeout=min(float(poll_interval_s), remaining))
                break
            except asyncio.TimeoutError:
                continue
    finally:
        await scanner.stop()

    return matched_device["value"], was_cancelled
