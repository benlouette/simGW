import argparse
from pathlib import Path

from generate_message import load_proto_module


def _resolve_proto_path(base_dir: Path, proto_arg: str) -> Path:
    if proto_arg:
        proto_path = Path(proto_arg).resolve()
        if not proto_path.exists():
            fallback = base_dir / "proto" / proto_arg
            if fallback.exists():
                proto_path = fallback
    else:
        default_proto = base_dir / "proto" / "app.proto"
        proto_path = default_proto if default_proto.exists() else base_dir / "clem.proto"
    if not proto_path.exists():
        raise FileNotFoundError(f"Proto not found: {proto_path}")
    return proto_path


def _resolve_include_dirs(base_dir: Path, include_args: list[str], proto_path: Path) -> list[Path]:
    include_dirs = [Path(item).resolve() for item in include_args]
    default_include = base_dir / "proto"
    if default_include.exists() and default_include != proto_path.parent:
        include_dirs.append(default_include)
    return include_dirs

def build_open_session(clem_pb2: object) -> object:
    open_session_message = clem_pb2.App()
    open_session_message.header.version = 1
    open_session_message.header.message_id = 123
    open_session_message.open_session.current_sync_time = 1700000000
    return open_session_message


def build_accept_session(clem_pb2: object) -> object:
    accept_session_message = clem_pb2.App()

    accept_session_message.header.version = 1
    accept_session_message.header.message_id = 124

    accept_session_message.accept_session.virtual_id = 424242
    accept_session_message.accept_session.hardware_type = clem_pb2.session__pb2.HardwareType.HardwareTypeCmwa6120_std
    accept_session_message.accept_session.serial = b"\x01\x02\x03\x04\x05\x06"
    accept_session_message.accept_session.hw_version = 1
    accept_session_message.accept_session.fw_version = 0x00010203
    accept_session_message.accept_session.fw_cache_version = 0x00010204
    accept_session_message.accept_session.config_hash = 123456
    accept_session_message.accept_session.self_diag = 0
    accept_session_message.accept_session.battery_indicator = 95
    return accept_session_message


def build_get_measurement(clem_pb2: object) -> object:
    get_measurement_message = clem_pb2.App()

    get_measurement_message.header.version = 1
    get_measurement_message.header.message_id = 125

    request = get_measurement_message.measurement_request.measurement.add()
    request.measurement_type = clem_pb2.measurement__pb2.MeasurementType.MeasurementTypeAccelerationOverall

    request = get_measurement_message.measurement_request.measurement.add()
    request.measurement_type = clem_pb2.measurement__pb2.MeasurementType.MeasurementTypeVelocityOverall

    request = get_measurement_message.measurement_request.measurement.add()
    request.measurement_type = clem_pb2.measurement__pb2.MeasurementType.MeasurementTypeEnveloper3Overall

    request = get_measurement_message.measurement_request.measurement.add()
    request.measurement_type = clem_pb2.measurement__pb2.MeasurementType.MeasurementTypeTemperatureOverall

    return get_measurement_message


def build_send_measurement(clem_pb2: object) -> object:
    send_measurement_message = clem_pb2.App()

    send_measurement_message.header.version = 1
    send_measurement_message.header.message_id = 126

    send_measurement_message.send_measurement.common_meta_data.time = 1700000000

    # acceleration overall measurement
    measurement = send_measurement_message.send_measurement.measurement_data.add()
    measurement.metadata.elo_metadata.vibration_path = clem_pb2.measurement__pb2.MeasurementType.MeasurementTypeAccelerationOverall
    measurement.metadata.elo_metadata.alarm = 0
    measurement.metadata.elo_metadata.duration = 1520
    measurement.data.measurement_overall.peak2peak = 5412
    measurement.data.measurement_overall.rms = 5413
    measurement.data.measurement_overall.peak = 5414
    measurement.data.measurement_overall.std = 5415
    measurement.data.measurement_overall.Mean = -5416

    # velocity overall measurement
    measurement = send_measurement_message.send_measurement.measurement_data.add()
    measurement.metadata.elo_metadata.vibration_path = clem_pb2.measurement__pb2.MeasurementType.MeasurementTypeVelocityOverall
    measurement.metadata.elo_metadata.alarm = 0
    measurement.metadata.elo_metadata.duration = 1520
    measurement.data.measurement_overall.peak2peak = 5412
    measurement.data.measurement_overall.rms = 5413
    measurement.data.measurement_overall.peak = 5414
    measurement.data.measurement_overall.std = 5415
    measurement.data.measurement_overall.Mean = -5416

    # enveloper3 overall measurement
    measurement = send_measurement_message.send_measurement.measurement_data.add()
    measurement.metadata.elo_metadata.vibration_path = clem_pb2.measurement__pb2.MeasurementType.MeasurementTypeEnveloper3Overall
    measurement.metadata.elo_metadata.alarm = 0
    measurement.metadata.elo_metadata.duration = 1520
    measurement.data.measurement_overall.peak2peak = 5412
    measurement.data.measurement_overall.rms = 5413
    measurement.data.measurement_overall.peak = 5414
    measurement.data.measurement_overall.std = 5415
    measurement.data.measurement_overall.Mean = -5416

    # temperature overall measurement
    measurement = send_measurement_message.send_measurement.measurement_data.add()
    measurement.metadata.elo_metadata.vibration_path = clem_pb2.measurement__pb2.MeasurementType.MeasurementTypeTemperatureOverall
    measurement.metadata.elo_metadata.alarm = 0
    measurement.metadata.elo_metadata.duration = 1520
    measurement.data.uint32_data = 12345

    return send_measurement_message

def build_send_twf_measurement (clem_pb2: object) -> object:
    all_send_twf_measurement_message = []
    
    twf_size = 4096*2
    chuck_size = 192
    total_fragments = twf_size // chuck_size + (1 if twf_size % chuck_size > 0 else 0)
    already_sent = 0

    for i in range(0, total_fragments):

        send_twf_measurement_message = clem_pb2.App()

        send_twf_measurement_message.header.version = 1
        send_twf_measurement_message.header.message_id = 127

        send_twf_measurement_message.header.current_fragment = i
        send_twf_measurement_message.header.total_fragments = total_fragments
        if i == 0:
            send_twf_measurement_message.send_measurement.common_meta_data.time = 1700000000

        measurement = send_twf_measurement_message.send_measurement.measurement_data.add()
        if i == 0:
            measurement.metadata.elo_metadata.vibration_path = clem_pb2.measurement__pb2.MeasurementType.MeasurementTypeAccelerationTwf
            measurement.metadata.elo_metadata.alarm = 0
            measurement.metadata.elo_metadata.duration = 1520
            send_twf_measurement_message.send_measurement.common_meta_data.config_hash = 123456
        if i == total_fragments - 1:
            remaining_bytes = twf_size - already_sent
            measurement.data.data_bytes = bytes(range(remaining_bytes))
        else:
            measurement.data.data_bytes = bytes(range(chuck_size))
        already_sent += chuck_size

        all_send_twf_measurement_message.append(send_twf_measurement_message)

    return all_send_twf_measurement_message


def build_close_session(clem_pb2: object) -> object:
    close_session_message = clem_pb2.App()

    close_session_message.header.version = 1
    close_session_message.header.message_id = 12

    close_session_message.command.command = clem_pb2.command__pb2.CommandType.CommandTypeCloseSession
    return close_session_message


def build_exchange_messages(clem_pb2: object) -> list[tuple[str, object]]:
    sequence = [
        ("open_session", build_open_session),
        ("accept_session", build_accept_session),
        ("get_measurement", build_get_measurement),
        ("send_measurement", build_send_measurement),
        # ("send_twf_measurement", build_send_twf_measurement),
        ("close_session", build_close_session),
    ]
    messages: list[tuple[str, object]] = []
    for label, builder in sequence:
        built = builder(clem_pb2)
        if isinstance(built, list):
            for index, message in enumerate(built, start=1):
                messages.append((f"{label}_{index:04d}", message))
            continue
        messages.append((label, built))
    return messages


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create the session exchange messages and display hex data."
    )
    parser.add_argument(
        "--proto",
        default="",
        help="Path to app.proto (defaults to proto/app.proto or clem.proto)",
    )
    parser.add_argument(
        "--proto-include",
        action="append",
        default=["proto"],
        help="Additional proto include directories (repeatable)",
    )
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    proto_path = _resolve_proto_path(base_dir, args.proto)
    include_dirs = _resolve_include_dirs(base_dir, args.proto_include, proto_path)

    clem_pb2 = load_proto_module(proto_path, include_dirs)
    messages = build_exchange_messages(clem_pb2)
    total_bytes = 0
    total_message_exchange = 0
    print("Exchange message sequence:")
    for label, message in messages:
        raw_bytes = message.SerializeToString()
        print(f"{label}: {len(raw_bytes)} bytes")
        total_bytes += len(raw_bytes)
        print(f"{label} hex: {raw_bytes.hex()}")
        total_message_exchange += 1
        
    print(f"Total bytes for exchange: {total_bytes}")
    print(f"Total messages in exchange: {total_message_exchange}")


    return 0


if __name__ == "__main__":
    raise SystemExit(main())
