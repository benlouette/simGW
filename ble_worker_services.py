"""Shared services used by worker BLE cycles.

This module groups small, reusable operations that are intentionally stateless:
- normalize user-provided BLE filters
- create/init a session recorder for one cycle/action
- scan for the first matching BLE device with optional cancellation polling

Keeping these helpers outside the worker class makes orchestration code shorter
and easier to test in isolation.

Error handling policy:
- scan helper never raises on timeout/cancel (returns structured tuple)
- scanner stop is always attempted in a finally block
"""

import asyncio
import time
from typing import Any, Callable, Optional

from bleak import BleakScanner

from ble_filters import adv_matches as ble_adv_matches
from session_recorder import SessionRecorder
from ui_events import make_tile_update

CancelFn = Optional[Callable[[], bool]]
ScanResult = tuple[object | None, bool]


def normalize_ble_filters(
    address_prefix: str,
    name_contains: str = "",
) -> tuple[str, str]:
    """Normalize BLE filter strings for consistent matching.

    Args:
        address_prefix: Device address prefix (ex: C4:BD:6A:)
        name_contains: Case-insensitive substring expected in ADV/device name

    Returns:
        tuple[str, str]: (address_prefix_upper, name_contains_lower)
    """
    address_prefix = (address_prefix or "").strip().upper()
    name_contains = (name_contains or "").strip().lower()
    return address_prefix, name_contains


def create_session_recorder(
    tile_id: int,
    action: Optional[str],
    record_sessions: bool,
    session_root: str,
    ui_queue: Any,
) -> tuple[Optional[SessionRecorder], Optional[str]]:
    """Create and initialize a `SessionRecorder` for one worker run.

    Args:
        tile_id: Logical tile/sensor slot id.
        action: Manual action name, or None for auto cycle.
        record_sessions: Enables/disables session recording.
        session_root: Root directory where sessions are written.
        ui_queue: Queue used to emit tile updates.

    Returns:
        tuple[Optional[SessionRecorder], Optional[str]]:
            (recorder, session_dir) or (None, None) when disabled.
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
    scan_timeout: float,
    is_cancelled: CancelFn = None,
    poll_interval_s: float = 0.25,
) -> ScanResult:
    """Scan for the first BLE device matching `address_prefix`/`name_contains`.

    The scanner runs until one of these conditions occurs:
    - a matching device is found
    - timeout expires
    - cancellation callback returns True

    Args:
        address_prefix: Uppercase prefix used against discovered device addresses.
        name_contains: Lowercase substring filter used by advertisement matching.
        scan_timeout: Maximum scan duration in seconds.
        is_cancelled: Optional callback polled during scan loop.
        poll_interval_s: Polling interval for cancellation/event wait.

    Returns:
        tuple[object | None, bool]: (matched_device, was_cancelled)
    """
    matched_device = None
    found_event = asyncio.Event()
    timeout_s = float(scan_timeout)
    poll_s = max(float(poll_interval_s), 0.05)

    def _on_device_found(device, advertisement_data):
        nonlocal matched_device
        if not getattr(device, "address", None):
            return
        if is_cancelled is not None and is_cancelled():
            return
        if matched_device is not None:
            return
        if ble_adv_matches(
            device,
            advertisement_data,
            address_prefix,
            name_contains,
        ):
            matched_device = device
            found_event.set()

    scanner = BleakScanner(_on_device_found)
    await scanner.start()

    was_cancelled = False
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s

        while True:
            if is_cancelled is not None and is_cancelled():
                was_cancelled = True
                break

            remaining = deadline - loop.time()
            if remaining <= 0:
                break

            try:
                await asyncio.wait_for(found_event.wait(), timeout=min(poll_s, remaining))
                break
            except asyncio.TimeoutError:
                continue
    finally:
        await scanner.stop()

    return matched_device, was_cancelled
