"""
Centralized protobuf module imports for the SKF protocol.

Ensures the generated protobuf modules in /protocol are importable from a single place.
"""

import sys

from protocol_utils import PROTOCOL_DIR

if PROTOCOL_DIR not in sys.path:
    sys.path.insert(0, PROTOCOL_DIR)

import app_pb2
import command_pb2
import common_pb2
import configuration_pb2
import fota_pb2
import measurement_pb2
import session_pb2

__all__ = [
    "app_pb2",
    "command_pb2",
    "common_pb2",
    "configuration_pb2",
    "fota_pb2",
    "measurement_pb2",
    "session_pb2",
]
