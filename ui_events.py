"""
Shared UI event types and helpers for worker <-> Tkinter queue communication.
"""

from typing import Any, Dict, Mapping, Optional, Tuple, TypedDict, Union, Literal


class UiErrorInfo(TypedDict, total=False):
    where: str
    type: str
    msg: str


class TileUpdatePayload(TypedDict, total=False):
    status: str
    phase: str
    address: str
    session_dir: str
    rx_text: str
    checklist: Dict[str, str]
    overall_values: list
    export_info: dict
    error: UiErrorInfo
    error_info: UiErrorInfo
    ts_ms: int


TileUpdateEvent = Tuple[Literal["tile_update"], int, TileUpdatePayload]
CycleDoneEvent = Tuple[Literal["cycle_done"], int]
UiEvent = Union[TileUpdateEvent, CycleDoneEvent]


def make_tile_update(tile_id: int, payload: Optional[Mapping[str, Any]] = None) -> TileUpdateEvent:
    return ("tile_update", int(tile_id), dict(payload or {}))


def make_cycle_done(tile_id: int) -> CycleDoneEvent:
    return ("cycle_done", int(tile_id))
