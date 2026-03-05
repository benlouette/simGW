"""
Shared UI event types and helpers for worker <-> Tkinter queue communication.
"""

from typing import Any, Dict, Literal, Mapping, Optional, Tuple, TypedDict, Union


EVENT_TILE_UPDATE: Literal["tile_update"] = "tile_update"
EVENT_CYCLE_DONE: Literal["cycle_done"] = "cycle_done"

ChecklistStateMap = Dict[str, str]
OverallValues = list
ExportInfo = dict


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
    checklist: ChecklistStateMap
    overall_values: OverallValues
    export_info: ExportInfo
    export_infos: Dict[str, ExportInfo]
    error: UiErrorInfo
    error_info: UiErrorInfo
    ts_ms: int


TileUpdateEvent = Tuple[Literal["tile_update"], int, TileUpdatePayload]
CycleDoneEvent = Tuple[Literal["cycle_done"], int]
UiEvent = Union[TileUpdateEvent, CycleDoneEvent]


def make_tile_update(tile_id: int, payload: Optional[Mapping[str, Any]] = None) -> TileUpdateEvent:
    """Build a normalized tile-update event tuple."""
    return (EVENT_TILE_UPDATE, int(tile_id), dict(payload or {}))


def make_cycle_done(tile_id: int) -> CycleDoneEvent:
    """Build a normalized cycle-done event tuple."""
    return (EVENT_CYCLE_DONE, int(tile_id))


__all__ = [
    "UiErrorInfo",
    "TileUpdatePayload",
    "TileUpdateEvent",
    "CycleDoneEvent",
    "UiEvent",
    "EVENT_TILE_UPDATE",
    "EVENT_CYCLE_DONE",
    "make_tile_update",
    "make_cycle_done",
]
