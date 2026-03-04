"""Waveform export and parsing helpers.

This module has two responsibilities:
- persist captured protobuf payloads to disk (`WaveformExporter`)
- reconstruct true int16 waveform samples from raw capture files (`WaveformParser`)

Export outputs:
- `.bin` is always written (length-prefixed raw protobuf payloads)
- `.txt` is written when sample reconstruction succeeds (space-separated int16 samples)

The public API used by UI/worker layers:
- `WaveformExporter.export_waveform_capture(...)`
- `WaveformParser.extract_true_waveform_samples(...)`

Quick flow:
1) Worker collects raw protobuf payloads.
2) `WaveformExporter` writes `.bin` with `[len][payload]` records.
3) `WaveformParser` re-reads `.bin`, extracts TWF `data_bytes` blocks,
   rebuilds int16 samples, and writes `.txt` when reconstruction succeeds.
"""

import os
import struct
import time
from typing import Any, Optional

from protocol_utils import CAPTURE_DIR

_INT16_BYTES = 2
_TWF_TYPE_NAMES = {5: "AccelerationTwf", 6: "VelocityTwf", 7: "Enveloper3Twf"}
_DATA_TYPE_NAMES = {
    0: "Unknown",
    1: "U8",
    2: "S8",
    3: "U16",
    4: "S16",
    5: "U32",
    6: "S32",
    7: "F32",
}


def _read_raw_payloads(raw_bytes: bytes) -> list[bytes]:
    """Decode repeated `[uint32_le len][payload]` records from a capture file."""
    offset = 0
    payloads: list[bytes] = []
    raw_len = len(raw_bytes)

    while offset + 4 <= raw_len:
        payload_len = int.from_bytes(raw_bytes[offset:offset + 4], "little", signed=False)
        offset += 4

        payload = raw_bytes[offset:offset + payload_len]
        if len(payload) != payload_len:
            break

        payloads.append(payload)
        offset += payload_len

    return payloads


class WaveformExporter:
    """Persist waveform captures to disk and optionally dump reconstructed samples."""

    def __init__(self, capture_dir: str = CAPTURE_DIR):
        self.capture_dir = capture_dir
        os.makedirs(self.capture_dir, exist_ok=True)

    def export_waveform_capture(self, tile_id: int, payloads: list) -> dict[str, Any]:
        """Export one waveform capture as `.bin` + optional `.txt` sample dump.

        Args:
            tile_id: Worker tile identifier.
            payloads: Ordered list of raw protobuf payload bytes.

        Returns:
            dict[str, Any]:
                - raw: path to binary capture
                - txt: path to sample text file (or None on parse failure)
                - count: number of payloads written
        """
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        base = os.path.join(self.capture_dir, f"waveform_tile{tile_id}_{timestamp}")
        raw_path = base + ".bin"
        txt_path: Optional[str] = base + ".txt"

        self._write_payload_capture(raw_path, payloads)

        try:
            samples, _meta = WaveformParser.extract_true_waveform_samples(raw_path)
            self._write_samples_text(txt_path, samples)
        except Exception as exc:
            txt_path = None
            print(f"Warning: Failed to export samples to text: {exc}")

        return {"raw": raw_path, "txt": txt_path, "count": len(payloads)}

    @staticmethod
    def _write_payload_capture(raw_path: str, payloads: list) -> None:
        with open(raw_path, "wb") as handle:
            for payload in payloads:
                handle.write(len(payload).to_bytes(4, "little"))
                handle.write(payload)

    @staticmethod
    def _write_samples_text(txt_path: str, samples: list[int]) -> None:
        with open(txt_path, "w") as handle:
            handle.write(" ".join(str(sample) for sample in samples))


class WaveformParser:
    """Reconstruct waveform samples and metadata from raw capture files."""

    @classmethod
    def extract_true_waveform_samples(cls, raw_path: str) -> tuple[list[int], dict[str, Any]]:
        """Extract int16 waveform samples from a `.bin` payload capture file.

        Processing steps:
        - decode `[uint32_le len][payload]` records
        - parse protobuf payloads and keep waveform `data_bytes` blocks
        - read `metadata_twf.elo_metadata_twf.sampling_rate` when available
        - order blocks by fragment number
        - concatenate bytes and unpack little-endian int16 samples
        - produce metadata (`blocks`, `samples`, `fs_hz`, `data_type`, `twf_type`)
        """
        try:
            from protocol_imports import app_pb2
        except ImportError as exc:
            raise RuntimeError(f"Cannot import protocol modules: {exc}")

        with open(raw_path, "rb") as handle:
            raw_bytes = handle.read()

        payloads = _read_raw_payloads(raw_bytes)
        blocks, fs_hz, twf_type, data_type = cls._extract_waveform_blocks(payloads, app_pb2)

        if not blocks:
            raise RuntimeError("No TWF data_bytes found in export (new protocol format)")

        samples = cls._reconstruct_int16_samples(blocks)
        metadata = cls._build_metadata(blocks, samples, fs_hz, twf_type, data_type)
        return samples, metadata

    @classmethod
    def _extract_waveform_blocks(cls, payloads: list[bytes], app_pb2):
        """Extract `(fragment_number, data_bytes)` blocks and stream metadata."""
        blocks: list[tuple[int, bytes]] = []
        fs_hz: Optional[float] = None
        twf_type: Optional[int] = None
        data_type: Optional[int] = None

        for fallback_index, payload in enumerate(payloads):
            try:
                app_msg = app_pb2.App()
                app_msg.ParseFromString(payload)
            except Exception:
                continue

            if not app_msg.HasField("send_measurement"):
                continue

            fragment_num = app_msg.header.current_fragment if app_msg.HasField("header") else fallback_index
            measurement_list = app_msg.send_measurement.measurement_data

            for measurement_data in measurement_list:
                twf_type = cls._extract_twf_type(measurement_data, twf_type)
                fs_hz, data_type = cls._extract_stream_info(measurement_data, fs_hz, data_type)

                data_bytes = cls._extract_data_bytes(measurement_data)
                if data_bytes:
                    blocks.append((fragment_num, data_bytes))

        return blocks, fs_hz, twf_type, data_type

    @staticmethod
    def _extract_twf_type(measurement_data, current_twf_type: Optional[int]) -> Optional[int]:
        if not measurement_data.HasField("metadata"):
            return current_twf_type

        metadata = measurement_data.metadata
        if not metadata.HasField("elo_metadata"):
            return current_twf_type

        vibration_path = metadata.elo_metadata.vibration_path
        if vibration_path in (5, 6, 7):
            return vibration_path
        return current_twf_type

    @staticmethod
    def _extract_stream_info(
        measurement_data,
        current_fs_hz: Optional[float],
        current_data_type: Optional[int],
    ) -> tuple[Optional[float], Optional[int]]:
        if not measurement_data.HasField("metadata_twf"):
            return current_fs_hz, current_data_type

        metadata_twf = measurement_data.metadata_twf
        if not metadata_twf.HasField("elo_metadata_twf"):
            return current_fs_hz, current_data_type

        elo_metadata_twf = metadata_twf.elo_metadata_twf

        fs_hz = current_fs_hz
        if hasattr(elo_metadata_twf, "sampling_rate") and elo_metadata_twf.sampling_rate > 0:
            fs_hz = float(elo_metadata_twf.sampling_rate)

        data_type = current_data_type
        if hasattr(elo_metadata_twf, "data_type") and elo_metadata_twf.data_type > 0:
            data_type = int(elo_metadata_twf.data_type)

        return fs_hz, data_type

    @staticmethod
    def _extract_data_bytes(measurement_data) -> Optional[bytes]:
        if not measurement_data.HasField("data"):
            return None
        if not measurement_data.data.HasField("data_bytes"):
            return None

        data_bytes = bytes(measurement_data.data.data_bytes)
        return data_bytes if data_bytes else None

    @staticmethod
    def _reconstruct_int16_samples(blocks: list[tuple[int, bytes]]) -> list[int]:
        """Sort blocks, merge payload bytes, and unpack little-endian int16 samples."""
        blocks.sort(key=lambda item: item[0])
        blob = b"".join(data_bytes for _fragment_num, data_bytes in blocks)

        if len(blob) < _INT16_BYTES:
            raise RuntimeError("Waveform blob too small")
        if (len(blob) % _INT16_BYTES) != 0:
            blob = blob[:-1]

        sample_count = len(blob) // _INT16_BYTES
        if sample_count <= 0:
            raise RuntimeError("No int16 samples reconstructed")

        return list(struct.unpack("<" + "h" * sample_count, blob))

    @staticmethod
    def _build_metadata(
        blocks: list[tuple[int, bytes]],
        samples: list[int],
        fs_hz: Optional[float],
        twf_type: Optional[int],
        data_type: Optional[int],
    ) -> dict[str, Any]:
        return {
            "blocks": len(blocks),
            "samples": len(samples),
            "fs_hz": fs_hz,
            "data_type": _DATA_TYPE_NAMES.get(data_type, "S16") if data_type else "S16",
            "twf_type": _TWF_TYPE_NAMES.get(twf_type, "Unknown") if twf_type else "Unknown",
        }
