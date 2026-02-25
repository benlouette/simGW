import asyncio
import csv
import os
import sys
import struct
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from queue import Queue, Empty
from tkinter import ttk, messagebox
from typing import Dict, Optional

from google.protobuf import text_format
from bleak import BleakClient, BleakScanner

try:
	import matplotlib.pyplot as plt
except Exception:
	plt = None

BASE_DIR = os.path.dirname(__file__)
FROTO_DIR = os.path.join(BASE_DIR, "froto")
CAPTURE_DIR = os.path.join(BASE_DIR, "captures")
if FROTO_DIR not in sys.path:
	sys.path.insert(0, FROTO_DIR)

import DeviceAppBulletSensor_pb2
import ConfigurationAndCommand_pb2
import Common_pb2
import FirmwareUpdateOverTheAir_pb2
import Froto_pb2
import SensingDataUpload_pb2


UART_SERVICE_BYTES = [
	0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0,
	0x93, 0xF3, 0xA3, 0xB5, 0x01, 0x00, 0x40, 0x6E,
]
UART_RX_BYTES = [
	0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0,
	0x93, 0xF3, 0xA3, 0xB5, 0x02, 0x00, 0x40, 0x6E,
]
UART_TX_BYTES = [
	0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0,
	0x93, 0xF3, 0xA3, 0xB5, 0x03, 0x00, 0x40, 0x6E,
]


def _uuid_from_bytes(bytes_list, reverse: bool) -> str:
	ordered = list(reversed(bytes_list)) if reverse else list(bytes_list)
	hex_bytes = [f"{b:02x}" for b in ordered]
	return (
		f"{''.join(hex_bytes[0:4])}-"
		f"{''.join(hex_bytes[4:6])}-"
		f"{''.join(hex_bytes[6:8])}-"
		f"{''.join(hex_bytes[8:10])}-"
		f"{''.join(hex_bytes[10:16])}"
	)


def _get_uart_uuids(reverse: bool) -> tuple:
	service_uuid = _uuid_from_bytes(UART_SERVICE_BYTES, reverse)
	rx_uuid = _uuid_from_bytes(UART_RX_BYTES, reverse)
	tx_uuid = _uuid_from_bytes(UART_TX_BYTES, reverse)
	return service_uuid, rx_uuid, tx_uuid


@dataclass
class TileStatus:
	address: str = "—"
	status: str = "Queued"
	rx_text: str = ""


class BleCycleWorker:
	def __init__(self, ui_queue: Queue):
		self.ui_queue = ui_queue
		self.loop = asyncio.new_event_loop()
		self.thread = threading.Thread(target=self._run_loop, daemon=True)
		self.uart_service_uuid, self.uart_rx_uuid, self.uart_tx_uuid = _get_uart_uuids(True)

	def start(self) -> None:
		self.thread.start()

	def _run_loop(self) -> None:
		asyncio.set_event_loop(self.loop)
		self.loop.run_forever()

	def _call_soon(self, coro: asyncio.Future) -> None:
		asyncio.run_coroutine_threadsafe(coro, self.loop)

	def run_cycle(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float) -> None:
		self._call_soon(self._run_cycle(tile_id, address_prefix, mtu, scan_timeout, rx_timeout))

	def run_manual_action(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float, action: str) -> None:
		self._call_soon(self._run_manual_action(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, action))

	def _format_rx_payload(self, payload: bytes) -> str:
		try:
			message = DeviceAppBulletSensor_pb2.AppMessage()
			message.ParseFromString(payload)
			if message.ListFields():
				return text_format.MessageToString(message, as_one_line=False).rstrip()
		except Exception:
			pass
		try:
			return payload.decode("utf-8", errors="replace")
		except Exception:
			return payload.hex(" ")

	def _pb_message_type(self, payload: bytes) -> str:
		try:
			message = DeviceAppBulletSensor_pb2.AppMessage()
			message.ParseFromString(payload)
			return message.WhichOneof("_messages") or "(none)"
		except Exception:
			return "(parse_error)"

	def _hex_short(self, payload: bytes, max_len: int = 48) -> str:
		if payload is None:
			return ""
		if len(payload) <= max_len:
			return payload.hex(" ")
		return payload[:max_len].hex(" ") + f" ... ({len(payload)} bytes)"


	def _extract_waveform_sample_rows(self, app_msg) -> list:
		rows = []
		try:
			for pair_idx, pair in enumerate(getattr(app_msg.data_upload, "data_pair", [])):
				for field_desc, value in pair.ListFields():
					if field_desc.label != field_desc.LABEL_REPEATED:
						continue
					if field_desc.cpp_type not in (
						field_desc.CPPTYPE_INT32, field_desc.CPPTYPE_INT64,
						field_desc.CPPTYPE_UINT32, field_desc.CPPTYPE_UINT64,
						field_desc.CPPTYPE_FLOAT, field_desc.CPPTYPE_DOUBLE,
					):
						continue
					for sample_idx, sample in enumerate(value):
						rows.append((pair_idx, field_desc.name, sample_idx, sample))
		except Exception:
			return []
		return rows

	def _export_waveform_capture(self, tile_id: int, payloads: list, parsed_msgs: list) -> dict:
		os.makedirs(CAPTURE_DIR, exist_ok=True)
		ts = time.strftime("%Y%m%d_%H%M%S")
		base = os.path.join(CAPTURE_DIR, f"waveform_tile{tile_id}_{ts}")
		raw_path = base + ".bin"
		idx_path = base + "_index.csv"
		samples_path = base + "_samples.csv"
		with open(raw_path, "wb") as f:
			for payload in payloads:
				f.write(len(payload).to_bytes(4, "little"))
				f.write(payload)
		sample_rows = []
		with open(idx_path, "w", newline="", encoding="utf-8") as f:
			w = csv.writer(f)
			w.writerow(["block_index", "payload_len", "msg_type", "total_block", "msg_seq_no", "hex_preview"])
			for i, (payload, msg) in enumerate(zip(payloads, parsed_msgs), start=1):
				msg_type = msg.WhichOneof("_messages") or "(none)"
				total_block = ""
				msg_seq_no = ""
				try:
					total_block = getattr(msg.data_upload.header, "total_block", "")
					msg_seq_no = getattr(msg.data_upload.header, "message_seq_no", "")
				except Exception:
					pass
				w.writerow([i, len(payload), msg_type, total_block, msg_seq_no, self._hex_short(payload, 32)])
				if msg_type == "data_upload":
					sample_rows.extend((i,) + r for r in self._extract_waveform_sample_rows(msg))
		if sample_rows:
			with open(samples_path, "w", newline="", encoding="utf-8") as f:
				w = csv.writer(f)
				w.writerow(["block_index", "pair_index", "field_name", "sample_index", "value"])
				w.writerows(sample_rows)
		else:
			samples_path = ""
		return {"raw": raw_path, "index": idx_path, "samples": samples_path, "count": len(payloads)}

	async def _run_manual_action(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float, action: str) -> None:
		address_prefix = address_prefix.upper()
		self.ui_queue.put(("tile_update", tile_id, {"status": f"Manual: {action} / scanning..."}))
		self.ui_queue.put(("tile_update", tile_id, {"checklist": {"waiting_connection": "in_progress"}}))
		matched_device = {"value": None}
		found_event = asyncio.Event()

		def _on_device_found(device, _advertisement_data):
			if not device.address:
				return
			if device.address.upper().startswith(address_prefix):
				if not found_event.is_set():
					matched_device["value"] = device
					found_event.set()

		scanner = BleakScanner(_on_device_found)
		await scanner.start()
		try:
			try:
				await asyncio.wait_for(found_event.wait(), timeout=scan_timeout)
			except asyncio.TimeoutError:
				self.ui_queue.put(("tile_update", tile_id, {"status": "Not found", "address": "—"}))
				return
		finally:
			await scanner.stop()

		matched = matched_device["value"]
		if not matched:
			self.ui_queue.put(("tile_update", tile_id, {"status": "Not found", "address": "—"}))
			return

		self.ui_queue.put(("tile_update", tile_id, {"status": f"Manual: {action} / connecting...", "address": matched.address}))
		client = BleakClient(matched.address)
		rx_queue = []
		rx_event = asyncio.Event()

		def _on_notify(_sender: int, data: bytearray) -> None:
			try:
				rx_queue.append(bytes(data))
				rx_event.set()
			except Exception:
				pass

		async def _wait_next_rx(timeout_s: float) -> bytes:
			loop = asyncio.get_running_loop()
			end_time = loop.time() + timeout_s
			while True:
				if rx_queue:
					return rx_queue.pop(0)
				rx_event.clear()
				if rx_queue:
					return rx_queue.pop(0)
				remaining = end_time - loop.time()
				if remaining <= 0:
					raise asyncio.TimeoutError()
				await asyncio.wait_for(rx_event.wait(), timeout=remaining)

		next_seq_no = 1
		def _alloc_seq() -> int:
			nonlocal next_seq_no
			v = next_seq_no
			next_seq_no += 1
			return v

		async def _write_app_message(app_msg) -> bytes:
			payload = app_msg.SerializeToString()
			await client.write_gatt_char(self.uart_rx_uuid, payload)
			self.ui_queue.put(("tile_update", tile_id, {"status": f"TX {self._pb_message_type(payload)} ({len(payload)} B)"}))
			return payload

		def _safe_parse_app(payload: bytes):
			msg = DeviceAppBulletSensor_pb2.AppMessage()
			msg.ParseFromString(payload)
			return msg

		def _mk_header() -> Froto_pb2.FrotoHeader:
			return Froto_pb2.FrotoHeader(
				version=1,
				is_up=False,
				message_seq_no=_alloc_seq(),
				time_to_live=3,
				primitive_type=Froto_pb2.SIMPLE_DISSEMINATE,
				message_type=Froto_pb2.NORMAL_MESSAGE,
				total_block=1,
			)

		async def _send_config_time() -> None:
			current_time_ms = int(time.time() * 1000)
			config_pair = ConfigurationAndCommand_pb2.ConfigPair(
				specific_config_item=Common_pb2.CURRENT_TIME,
				time_config_content=ConfigurationAndCommand_pb2.TimeArray(
					time=[ConfigurationAndCommand_pb2.TimeArrayElement(time=current_time_ms)]
				),
			)
			config_dissem = ConfigurationAndCommand_pb2.ConfigDisseminate(
				header=_mk_header(),
				appVer=1,
				product=Common_pb2.UNKNOWN_PRODUCT,
				config_pair=[config_pair],
			)
			await _write_app_message(DeviceAppBulletSensor_pb2.AppMessage(appVer=1, config_dissem=config_dissem))

		async def _send_version_retrieve() -> None:
			msg = FirmwareUpdateOverTheAir_pb2.VersionRetrieve(
				header=_mk_header(),
				appVer=1,
				payload=FirmwareUpdateOverTheAir_pb2.CURRENT_VERSION,
			)
			await _write_app_message(DeviceAppBulletSensor_pb2.AppMessage(appVer=1, version_retrieve=msg))

		async def _send_config_hash_retrieve() -> None:
			msg = ConfigurationAndCommand_pb2.ConfigRetrieve(
				header=_mk_header(),
				appVer=1,
				payload=ConfigurationAndCommand_pb2.CURRENT_CONFIG_HASH,
			)
			await _write_app_message(DeviceAppBulletSensor_pb2.AppMessage(appVer=1, config_retrieve=msg))

		async def _send_metrics_selection(sample_time_end_ms: int) -> None:
			measure_types = [
				SensingDataUpload_pb2.MeasurementTypeMsg(measure_type=Common_pb2.ENVIROMENTAL_TEMPERATURE_CURRENT),
				SensingDataUpload_pb2.MeasurementTypeMsg(measure_type=Common_pb2.ENVIROMENTAL_HUMIDITY_CURRENT),
				SensingDataUpload_pb2.MeasurementTypeMsg(measure_type=Common_pb2.VOLTAGE_CURRENT),
			]
			msg = SensingDataUpload_pb2.DataSelectionDisseminate(
				header=_mk_header(),
				appVer=1,
				product=Common_pb2.UNKNOWN_PRODUCT,
				measure_type=measure_types,
				sample_time_start=0,
				sample_time_end=sample_time_end_ms,
			)
			await _write_app_message(DeviceAppBulletSensor_pb2.AppMessage(appVer=1, data_selection=msg))

		async def _send_vibration_selection(sample_time_end_ms: int) -> None:
			msg = SensingDataUpload_pb2.DataSelectionDisseminate(
				header=_mk_header(),
				appVer=1,
				product=Common_pb2.UNKNOWN_PRODUCT,
				measure_type=[SensingDataUpload_pb2.MeasurementTypeMsg(measure_type=Common_pb2.VIBRATION_ACC_WAVE)],
				sample_time_start=0,
				sample_time_end=sample_time_end_ms,
			)
			await _write_app_message(DeviceAppBulletSensor_pb2.AppMessage(appVer=1, data_selection=msg))

		async def _send_close_session() -> None:
			msg = ConfigurationAndCommand_pb2.CommandDisseminate(
				header=_mk_header(),
				appVer=1,
				command_pair=ConfigurationAndCommand_pb2.CommandPair(command=Common_pb2.CLOSE_SESSION),
			)
			await _write_app_message(DeviceAppBulletSensor_pb2.AppMessage(appVer=1, command_dissem=msg))

		async def _recv_app(timeout_s: float):
			payload = await _wait_next_rx(timeout_s)
			msg = _safe_parse_app(payload)
			msg_type = msg.WhichOneof("_messages") or "(none)"
			return payload, msg, msg_type

		try:
			await client.connect()
			self.ui_queue.put(("tile_update", tile_id, {"checklist": {"waiting_connection": "done", "connected": "done"}}))
			if mtu and hasattr(client, "request_mtu"):
				try:
					await client.request_mtu(mtu)
				except Exception:
					pass
			await client.start_notify(self.uart_tx_uuid, _on_notify)

			# optional pre-steps required by sensor for many commands
			if action in ("version", "config_hash", "metrics", "waveform", "close_session"):
				await _send_config_time()
				await asyncio.sleep(0.1)

			if action == "connect_test":
				self.ui_queue.put(("tile_update", tile_id, {"status": "Connected (test OK)"}))

			elif action == "discover_gatt":
				try:
					services = client.services
					if services is None:
						services = await client.get_services()
				except Exception:
					services = await client.get_services()
				gatt_lines = []
				for svc in services:
					gatt_lines.append(f"[SERVICE] {svc.uuid} ({getattr(svc, 'description', '')})")
					for ch in getattr(svc, "characteristics", []):
						props = ",".join(getattr(ch, "properties", []) or [])
						gatt_lines.append(f"  [CHAR] {ch.uuid} props=[{props}]")
				self.ui_queue.put(("tile_update", tile_id, {
					"status": "GATT discovered",
					"rx_text": "\n".join(gatt_lines) if gatt_lines else "(no services)",
				}))

			elif action == "notify_test":
				self.ui_queue.put(("tile_update", tile_id, {"status": "Notify active for 2s (test)"}))
				try:
					payload = await _wait_next_rx(2.0)
					rx_type = self._pb_message_type(payload)
					self.ui_queue.put(("tile_update", tile_id, {
						"status": f"Notify RX {rx_type}",
						"rx_text": f"TYPE: {rx_type}\nHEX: {self._hex_short(payload)}\n\n" + self._format_rx_payload(payload),
					}))
				except asyncio.TimeoutError:
					self.ui_queue.put(("tile_update", tile_id, {"status": "Notify test timeout (no unsolicited RX)"}))

			elif action == "sync_time":

				self.ui_queue.put(("tile_update", tile_id, {"status": "Time sync sent", "checklist": {"general_info_exchange": "done"}}))

			elif action == "version":
				await _send_version_retrieve()
				payload, _msg, msg_type = await _recv_app(rx_timeout)
				self.ui_queue.put(("tile_update", tile_id, {
					"status": f"RX {msg_type}",
					"checklist": {"general_info_exchange": "done"},
					"rx_text": f"TYPE: {msg_type}\nHEX: {self._hex_short(payload)}\n\n" + self._format_rx_payload(payload),
				}))

			elif action == "config_hash":
				await _send_version_retrieve()
				_, _, _ = await _recv_app(rx_timeout)  # consume version
				await asyncio.sleep(0.1)
				await _send_config_hash_retrieve()
				payload, _msg, msg_type = await _recv_app(rx_timeout)
				self.ui_queue.put(("tile_update", tile_id, {
					"status": f"RX {msg_type}",
					"checklist": {"general_info_exchange": "done"},
					"rx_text": f"TYPE: {msg_type}\nHEX: {self._hex_short(payload)}\n\n" + self._format_rx_payload(payload),
				}))

			elif action == "metrics":
				await _send_version_retrieve()
				_, _, _ = await _recv_app(rx_timeout)
				await asyncio.sleep(0.1)
				await _send_config_hash_retrieve()
				_, _, _ = await _recv_app(rx_timeout)
				await asyncio.sleep(0.1)
				await _send_metrics_selection(int(time.time() * 1000))
				payload, msg, msg_type = await _recv_app(rx_timeout)
				status = f"RX {msg_type}"
				if msg_type == "data_upload":
					try:
						status += f" ({len(list(msg.data_upload.data_pair))} metrics)"
					except Exception:
						pass
				self.ui_queue.put(("tile_update", tile_id, {
					"status": status,
					"checklist": {"general_info_exchange": "done", "data_collection": "done"},
					"rx_text": f"TYPE: {msg_type}\nHEX: {self._hex_short(payload)}\n\n" + self._format_rx_payload(payload),
				}))

			elif action == "waveform":
				await _send_version_retrieve()
				_, _, _ = await _recv_app(rx_timeout)
				await asyncio.sleep(0.1)
				await _send_config_hash_retrieve()
				_, _, _ = await _recv_app(rx_timeout)
				await asyncio.sleep(0.1)
				await _send_vibration_selection(int(time.time() * 1000))
				received = 0
				expected = None
				last_payload = b""
				last_type = "(none)"
				wave_payloads = []
				wave_msgs = []
				while True:
					payload, msg, msg_type = await _recv_app(rx_timeout)
					last_payload, last_type = payload, msg_type
					if msg_type != "data_upload":
						break
					wave_payloads.append(payload)
					wave_msgs.append(msg)
					received += 1
					if expected is None:
						try:
							expected = int(msg.data_upload.header.total_block)
						except Exception:
							expected = None
						if expected is not None and expected <= 0:
							expected = None
					self.ui_queue.put(("tile_update", tile_id, {
						"status": f"Waveform blocks {received}/{expected or '?'}",
						"checklist": {"general_info_exchange": "done", "data_collection": "in_progress"},
						"rx_text": f"TYPE: {msg_type}\nHEX: {self._hex_short(payload)}\n\n" + self._format_rx_payload(payload),
					}))
					if expected is not None and received >= expected:
						break
				export_info = None
				if wave_payloads:
					try:
						export_info = self._export_waveform_capture(tile_id, wave_payloads, wave_msgs)
					except Exception as export_exc:
						export_info = {"error": str(export_exc)}
				status_text = f"Waveform done ({received}/{expected or '?'}) last={last_type}"
				rx_text = f"TYPE: {last_type}\nHEX: {self._hex_short(last_payload)}\n\n" + self._format_rx_payload(last_payload) if last_payload else "RX: —"
				if export_info is not None:
					if "error" in export_info:
						status_text += " / export failed"
						rx_text += f"\n\nEXPORT ERROR: {export_info['error']}"
					else:
						status_text += f" / exported {export_info['count']} blocks"
						rx_text += f"\n\nEXPORT:\n- raw: {export_info['raw']}\n- index: {export_info['index']}"
						if export_info.get("samples"):
							rx_text += f"\n- samples: {export_info['samples']}"
				self.ui_queue.put(("tile_update", tile_id, {
					"status": status_text,
					"checklist": {"general_info_exchange": "done", "data_collection": "done"},
					"rx_text": rx_text,
					"export_info": export_info,
				}))

			elif action == "close_session":
				await _send_close_session()
				self.ui_queue.put(("tile_update", tile_id, {"status": "Close session sent", "checklist": {"close_session": "done"}}))

			else:
				raise ValueError(f"Unknown action: {action}")

			try:
				await client.stop_notify(self.uart_tx_uuid)
			except Exception:
				pass

		except Exception as exc:
			self.ui_queue.put(("tile_update", tile_id, {"status": f"Error: {type(exc).__name__}: {exc}"}))
		finally:
			self.ui_queue.put(("tile_update", tile_id, {"checklist": {"disconnect": "in_progress"}}))
			if client.is_connected:
				try:
					await client.disconnect()
				except Exception:
					pass
			self.ui_queue.put(("tile_update", tile_id, {"checklist": {"disconnect": "done"}}))
			self.ui_queue.put(("tile_update", tile_id, {"status": "Disconnected"}))
			self.ui_queue.put(("cycle_done", tile_id))

	async def _run_cycle(self, tile_id: int, address_prefix: str, mtu: int, scan_timeout: float, rx_timeout: float) -> None:
		address_prefix = address_prefix.upper()
		self.ui_queue.put(("tile_update", tile_id, {"status": "Scanning..."}))
		self.ui_queue.put(("tile_update", tile_id, {"checklist": {"waiting_connection": "in_progress"}}))
		matched_device = {"value": None}
		found_event = asyncio.Event()

		def _on_device_found(device, _advertisement_data):
			if not device.address:
				return
			if device.address.upper().startswith(address_prefix):
				if not found_event.is_set():
					matched_device["value"] = device
					found_event.set()

		scanner = BleakScanner(_on_device_found)
		await scanner.start()
		try:
			try:
				await asyncio.wait_for(found_event.wait(), timeout=scan_timeout)
			except asyncio.TimeoutError:
				self.ui_queue.put(("tile_update", tile_id, {"status": "Not found", "address": "—"}))
				return
		finally:
			await scanner.stop()

		matched = matched_device["value"]
		if not matched:
			self.ui_queue.put(("tile_update", tile_id, {"status": "Not found", "address": "—"}))
			return

		self.ui_queue.put(("tile_update", tile_id, {"status": "Connecting...", "address": matched.address}))
		client = BleakClient(matched.address)
		rx_queue = []
		rx_event = asyncio.Event()

		def _on_notify(_sender: int, data: bytearray) -> None:
			try:
				rx_queue.append(bytes(data))
				rx_event.set()
			except Exception:
				pass

		async def _wait_next_rx(timeout_s: float) -> bytes:
			loop = asyncio.get_running_loop()
			end_time = loop.time() + timeout_s
			while True:
				if rx_queue:
					return rx_queue.pop(0)
				rx_event.clear()
				if rx_queue:
					return rx_queue.pop(0)
				remaining = end_time - loop.time()
				if remaining <= 0:
					raise asyncio.TimeoutError()
				await asyncio.wait_for(rx_event.wait(), timeout=remaining)

		next_seq_no = 1
		def _alloc_seq() -> int:
			nonlocal next_seq_no
			v = next_seq_no
			next_seq_no += 1
			return v

		async def _write_app_message(app_msg) -> bytes:
			payload = app_msg.SerializeToString()
			await client.write_gatt_char(self.uart_rx_uuid, payload)
			self.ui_queue.put(("tile_update", tile_id, {
				"status": f"TX {self._pb_message_type(payload)} ({len(payload)} B)",
			}))
			return payload

		def _safe_parse_app(payload: bytes):
			msg = DeviceAppBulletSensor_pb2.AppMessage()
			msg.ParseFromString(payload)
			return msg

		def _mk_header() -> Froto_pb2.FrotoHeader:
			return Froto_pb2.FrotoHeader(
				version=1,
				is_up=False,
				message_seq_no=_alloc_seq(),
				time_to_live=3,
				primitive_type=Froto_pb2.SIMPLE_DISSEMINATE,
				message_type=Froto_pb2.NORMAL_MESSAGE,
				total_block=1,
			)

		async def _send_config_time() -> None:
			current_time_ms = int(time.time() * 1000)
			config_pair = ConfigurationAndCommand_pb2.ConfigPair(
				specific_config_item=Common_pb2.CURRENT_TIME,
				time_config_content=ConfigurationAndCommand_pb2.TimeArray(
					time=[ConfigurationAndCommand_pb2.TimeArrayElement(time=current_time_ms)]
				),
			)
			config_dissem = ConfigurationAndCommand_pb2.ConfigDisseminate(
				header=_mk_header(),
				appVer=1,
				product=Common_pb2.UNKNOWN_PRODUCT,
				config_pair=[config_pair],
			)
			app_message = DeviceAppBulletSensor_pb2.AppMessage(appVer=1, config_dissem=config_dissem)
			await _write_app_message(app_message)

		async def _send_version_retrieve() -> None:
			msg = FirmwareUpdateOverTheAir_pb2.VersionRetrieve(
				header=_mk_header(),
				appVer=1,
				payload=FirmwareUpdateOverTheAir_pb2.CURRENT_VERSION,
			)
			app_message = DeviceAppBulletSensor_pb2.AppMessage(appVer=1, version_retrieve=msg)
			await _write_app_message(app_message)

		async def _send_config_hash_retrieve() -> None:
			msg = ConfigurationAndCommand_pb2.ConfigRetrieve(
				header=_mk_header(),
				appVer=1,
				payload=ConfigurationAndCommand_pb2.CURRENT_CONFIG_HASH,
			)
			app_message = DeviceAppBulletSensor_pb2.AppMessage(appVer=1, config_retrieve=msg)
			await _write_app_message(app_message)

		def _default_metric_measure_types():
			return [
				SensingDataUpload_pb2.MeasurementTypeMsg(measure_type=Common_pb2.ENVIROMENTAL_TEMPERATURE_CURRENT),
				SensingDataUpload_pb2.MeasurementTypeMsg(measure_type=Common_pb2.ENVIROMENTAL_HUMIDITY_CURRENT),
				SensingDataUpload_pb2.MeasurementTypeMsg(measure_type=Common_pb2.VOLTAGE_CURRENT),
			]

		async def _send_metrics_selection(sample_time_end_ms: int) -> None:
			data_selection = SensingDataUpload_pb2.DataSelectionDisseminate(
				header=_mk_header(),
				appVer=1,
				product=Common_pb2.UNKNOWN_PRODUCT,
				measure_type=_default_metric_measure_types(),
				sample_time_start=0,
				sample_time_end=sample_time_end_ms,
			)
			app_message = DeviceAppBulletSensor_pb2.AppMessage(appVer=1, data_selection=data_selection)
			await _write_app_message(app_message)

		async def _send_vibration_selection(sample_time_end_ms: int) -> None:
			vibration_types = [SensingDataUpload_pb2.MeasurementTypeMsg(measure_type=Common_pb2.VIBRATION_ACC_WAVE)]
			data_selection = SensingDataUpload_pb2.DataSelectionDisseminate(
				header=_mk_header(),
				appVer=1,
				product=Common_pb2.UNKNOWN_PRODUCT,
				measure_type=vibration_types,
				sample_time_start=0,
				sample_time_end=sample_time_end_ms,
			)
			app_message = DeviceAppBulletSensor_pb2.AppMessage(appVer=1, data_selection=data_selection)
			await _write_app_message(app_message)

		async def _send_close_session() -> None:
			command_dissem = ConfigurationAndCommand_pb2.CommandDisseminate(
				header=_mk_header(),
				appVer=1,
				command_pair=ConfigurationAndCommand_pb2.CommandPair(command=Common_pb2.CLOSE_SESSION),
			)
			app_message = DeviceAppBulletSensor_pb2.AppMessage(appVer=1, command_dissem=command_dissem)
			await _write_app_message(app_message)

		async def _recv_app(timeout_s: float):
			payload = await _wait_next_rx(timeout_s)
			msg = _safe_parse_app(payload)
			msg_type = msg.WhichOneof("_messages") or "(none)"
			return payload, msg, msg_type

		try:
			await client.connect()
			self.ui_queue.put(("tile_update", tile_id, {"checklist": {"waiting_connection": "done", "connected": "done"}}))
			if mtu and hasattr(client, "request_mtu"):
				try:
					await client.request_mtu(mtu)
					self.ui_queue.put(("tile_update", tile_id, {"status": f"MTU requested: {mtu}"}))
				except Exception as exc:
					self.ui_queue.put(("tile_update", tile_id, {"status": f"MTU request failed: {exc}"}))

			await client.start_notify(self.uart_tx_uuid, _on_notify)
			self.ui_queue.put(("tile_update", tile_id, {"status": "Sending config_dissem...", "checklist": {"general_info_exchange": "in_progress"}}))

			await _send_config_time()

			await asyncio.sleep(0.1)
			self.ui_queue.put(("tile_update", tile_id, {"status": "Sending version_retrieve..."}))
			await _send_version_retrieve()

			try:
				payload, app_message, message_type = await _recv_app(rx_timeout)
			except asyncio.TimeoutError:
				self.ui_queue.put(("tile_update", tile_id, {"status": "RX timeout"}))
			else:
				latest_status = "Received"
				latest_rx_text = f"TYPE: {message_type}\nHEX: {self._hex_short(payload)}\n\n" + self._format_rx_payload(payload)
				try:
					if message_type == "current_version_upload":
						await asyncio.sleep(0.1)
						self.ui_queue.put(("tile_update", tile_id, {"status": "Sending config_retrieve..."}))
						await _send_config_hash_retrieve()

						try:
							hash_payload, hash_message, hash_type = await _recv_app(rx_timeout)
						except asyncio.TimeoutError:
							latest_status = "Config hash timeout"
						else:
							try:
								# print(f"Config hash upload type: {hash_type}")
								if hash_type == "config_hash_upload":
									data_collection_complete = True
									last_loop_index = -1
									for loop_index in range(6):
										last_loop_index = loop_index
										latest_status = "Config hash received"
										if loop_index == 0:
											self.ui_queue.put(("tile_update", tile_id, {"checklist": {"general_info_exchange": "done", "data_collection": "in_progress"}}))
										latest_rx_text = f"TYPE: {self._pb_message_type(hash_payload)}\nHEX: {self._hex_short(hash_payload)}\n\n" + self._format_rx_payload(hash_payload)

										current_time_ms = int(time.time() * 1000)
										
										self.ui_queue.put(("tile_update", tile_id, {"status": f"Sending data_selection ({loop_index + 1}/6)..."}))
										await _send_metrics_selection(current_time_ms)

										try:
											data_payload, data_message, data_type = await _recv_app(rx_timeout)
										except asyncio.TimeoutError:
											latest_status = "Data upload timeout"
											data_collection_complete = False
											self.ui_queue.put(("tile_update", tile_id, {"checklist": {"data_collection": "pending"}}))
											break
										else:
											try:
												if data_type == "data_upload":
													data_pairs = list(data_message.data_upload.data_pair)
													if len(data_pairs) >= 3:
														latest_status = "Data upload received"
													else:
														latest_status = f"Data upload missing metrics ({len(data_pairs)})"
														data_collection_complete = False
													latest_rx_text = f"TYPE: {self._pb_message_type(data_payload)}\nHEX: {self._hex_short(data_payload)}\n\n" + self._format_rx_payload(data_payload)
												else:
													latest_status = f"Unexpected reply: {data_type}"
													data_collection_complete = False
													break
											except Exception:
												latest_status = "Data upload parse error"
												data_collection_complete = False
												self.ui_queue.put(("tile_update", tile_id, {"checklist": {"data_collection": "pending"}}))
												break

									if data_collection_complete and last_loop_index == 5 and latest_status == "Data upload received":
										self.ui_queue.put(("tile_update", tile_id, {"checklist": {"data_collection": "done"}}))
									else:
										data_collection_complete = False
										self.ui_queue.put(("tile_update", tile_id, {"checklist": {"data_collection": "pending"}}))

									if data_collection_complete:
										current_time_ms = int(time.time() * 1000)
										self.ui_queue.put(("tile_update", tile_id, {"status": "Sending vibration data_selection...", "checklist": {"data_collection": "in_progress"}}))
										await _send_vibration_selection(current_time_ms)

										received_messages = 0
										expected_wave_blocks = None
										for message_index in range(64):
											print(f"Waiting for vibration data upload {message_index + 1}/{expected_wave_blocks or 64}...")
											try:
												data_payload, data_message, data_type = await _recv_app(rx_timeout)
											except asyncio.TimeoutError:
												latest_status = "Data upload timeout"
												data_collection_complete = False
												self.ui_queue.put(("tile_update", tile_id, {"checklist": {"data_collection": "pending"}}))
												break
											else:
												try:
													print(f"1Waiting for vibration data upload {message_index + 1}/{expected_wave_blocks or 64}...")
													if data_type == "data_upload":
														wave_payloads.append(data_payload)
														wave_msgs.append(data_message)
														print(f"2Waiting for vibration data upload {message_index + 1}/{expected_wave_blocks or 64}...")
														if expected_wave_blocks is None:
															try:
																expected_wave_blocks = int(data_message.data_upload.header.total_block)
																if expected_wave_blocks <= 0:
																	expected_wave_blocks = 64
															except Exception:
																expected_wave_blocks = 64
														received_messages += 1
														latest_status = f"Data upload received ({received_messages}/{expected_wave_blocks or 64})"
														latest_rx_text = f"TYPE: {self._pb_message_type(data_payload)}\nHEX: {self._hex_short(data_payload)}\n\n" + self._format_rx_payload(data_payload)
													else:
														print(f"3Waiting for vibration data upload {message_index + 1}/{expected_wave_blocks or 64}...")
														latest_status = f"Unexpected reply: {data_type}"
														data_collection_complete = False
														break
												except Exception:
													latest_status = "Data upload parse error"
													data_collection_complete = False
													self.ui_queue.put(("tile_update", tile_id, {"checklist": {"data_collection": "pending"}}))
													break

										if received_messages == (expected_wave_blocks or 64):
											try:
												export_info = self._export_waveform_capture(tile_id, wave_payloads, wave_msgs)
												latest_status = f"{latest_status} / exported {export_info['count']} blocks"
												latest_rx_text = latest_rx_text + f"\n\nEXPORT:\n- raw: {export_info['raw']}\n- index: {export_info['index']}"
												if export_info.get("samples"):
													latest_rx_text = latest_rx_text + f"\n- samples: {export_info['samples']}"
											except Exception as export_exc:
												latest_status = f"{latest_status} / export failed"
												latest_rx_text = latest_rx_text + f"\n\nEXPORT ERROR: {export_exc}"
											self.ui_queue.put(("tile_update", tile_id, {"checklist": {"data_collection": "done"}}))
											self.ui_queue.put(("tile_update", tile_id, {"checklist": {"close_session": "in_progress"}}))
											await asyncio.sleep(0.1)
											await _send_close_session()
											self.ui_queue.put(("tile_update", tile_id, {"checklist": {"close_session": "done"}}))
								else:
									latest_status = f"Unexpected reply: {hash_type}"
									print(f"--> Config hash upload type: {hash_type}")
							except Exception:
								latest_status = "Config hash parse error"
				except Exception:
					pass
				self.ui_queue.put(("tile_update", tile_id, {"status": latest_status, "rx_text": latest_rx_text, "export_info": export_info if "export_info" in locals() else None}))

			try:
				await client.stop_notify(self.uart_tx_uuid)
			except Exception:
				pass
		except Exception as exc:
			self.ui_queue.put(("tile_update", tile_id, {"status": f"Error: {type(exc).__name__}: {exc}"}))
		finally:
			self.ui_queue.put(("tile_update", tile_id, {"checklist": {"disconnect": "in_progress"}}))
			if client.is_connected:
				try:
					await client.disconnect()
				except Exception:
					pass
			self.ui_queue.put(("tile_update", tile_id, {"checklist": {"disconnect": "done"}}))
			self.ui_queue.put(("tile_update", tile_id, {"status": "Disconnected"}))
			self.ui_queue.put(("cycle_done", tile_id))


class SimGwV2App:
	def __init__(self, root: tk.Tk) -> None:
		self.root = root
		self.root.title("SimGW v2 BLE Loop")
		self.root.geometry("860x620")
		self.root.configure(bg="#0f1115")

		self.ui_queue: Queue = Queue()
		self.worker = BleCycleWorker(self.ui_queue)
		self.worker.start()

		self.tile_counter = 0
		self.tiles: Dict[int, Dict[str, tk.Label]] = {}
		self.auto_run = False
		self.latest_export_info = None
		self.tile_export_info: Dict[int, dict] = {}

		self.address_prefix_var = tk.StringVar(value="C4:BD:6A:01:02:03")
		self.scan_timeout_var = tk.StringVar(value="60")
		self.rx_timeout_var = tk.StringVar(value="5")
		self.mtu_var = tk.StringVar(value="247")

		self._apply_theme()
		self._build_ui()
		self._poll_queue()

	def _apply_theme(self) -> None:
		self.colors = {
			"bg": "#0f1115",
			"panel": "#171a21",
			"panel_alt": "#1f2430",
			"text": "#e6e6e6",
			"muted": "#8b93a1",
			"accent": "#4361ee",
			"accent_alt": "#4cc9f0",
			"border": "#2a2f3a",
		}

		style = ttk.Style(self.root)
		style.theme_use("clam")
		style.configure("TFrame", background=self.colors["bg"])
		style.configure("TLabel", background=self.colors["bg"], foreground=self.colors["text"], font=("Segoe UI", 10))
		style.configure("Header.TLabel", background=self.colors["panel"], foreground=self.colors["text"], font=("Segoe UI", 14, "bold"))
		style.configure("Subtle.TLabel", background=self.colors["bg"], foreground=self.colors["muted"])
		style.configure("TEntry", fieldbackground=self.colors["panel_alt"], foreground=self.colors["text"], insertcolor=self.colors["text"])
		style.configure("TButton", background=self.colors["panel"], foreground=self.colors["text"], padding=(10, 6))
		style.configure("Accent.TButton", background=self.colors["accent"], foreground="#0b0f14", padding=(10, 6))
		style.map("Accent.TButton", background=[("active", self.colors["accent_alt"])])

	def _build_ui(self) -> None:
		header = tk.Frame(self.root, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
		header.pack(fill=tk.X, padx=16, pady=(16, 10))

		left = tk.Frame(header, bg=self.colors["panel"])
		left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=12, pady=12)
		
		tk.Label(left, text="SimGW v2 BLE Loop", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 14, "bold")).pack(anchor="w")
		tk.Label(left, text="Auto-connect / send / receive / disconnect", bg=self.colors["panel"], fg=self.colors["muted"]).pack(anchor="w", pady=(2, 0))

		controls = tk.Frame(header, bg=self.colors["panel"])
		controls.pack(side=tk.RIGHT, padx=12, pady=12)

		self.start_button = ttk.Button(controls, text="Start", style="Accent.TButton", command=self._on_start)
		self.start_button.pack(side=tk.TOP, pady=(0, 6))
		self.stop_auto_button = ttk.Button(controls, text="Stop Auto", command=lambda: setattr(self, "auto_run", False))
		self.stop_auto_button.pack(side=tk.TOP)

		form = tk.Frame(self.root, bg=self.colors["bg"])
		form.pack(fill=tk.X, padx=16)

		self._build_field(form, "Address prefix", self.address_prefix_var)
		self._build_field(form, "MTU", self.mtu_var, width=8)
		self._build_field(form, "Scan timeout (s)", self.scan_timeout_var, width=8)
		self._build_field(form, "RX timeout (s)", self.rx_timeout_var, width=8)

		manual = tk.Frame(self.root, bg=self.colors["bg"])
		manual.pack(fill=tk.X, padx=16, pady=(8, 0))
		tk.Label(manual, text="Manual commands:", bg=self.colors["bg"], fg=self.colors["muted"], font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 8))
		for text_, action_ in [
			("Sync Time", "sync_time"),
			("Version", "version"),
			("Config Hash", "config_hash"),
			("Metrics", "metrics"),
			("Waveform", "waveform"),
			("Close", "close_session"),
			("Connect Test", "connect_test"),
			("Discover GATT", "discover_gatt"),
			("Notify Test", "notify_test"),
		]:
			ttk.Button(manual, text=text_, command=lambda a=action_: self._start_manual_action(a)).pack(side=tk.LEFT, padx=(0, 6))
		ttk.Button(manual, text="Plot Latest", command=self._plot_latest_waveform).pack(side=tk.LEFT, padx=(12, 6))

		tiles_frame = tk.Frame(self.root, bg=self.colors["bg"])
		tiles_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(12, 16))

		self.canvas = tk.Canvas(tiles_frame, bg=self.colors["bg"], highlightthickness=0)
		scrollbar = ttk.Scrollbar(tiles_frame, orient="vertical", command=self.canvas.yview)
		self.tiles_container = tk.Frame(self.canvas, bg=self.colors["bg"])

		self.tiles_container.bind(
			"<Configure>",
			lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
		)
		self.canvas.create_window((0, 0), window=self.tiles_container, anchor="nw")
		self.canvas.configure(yscrollcommand=scrollbar.set)

		self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
		scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

		self.canvas.bind_all("<MouseWheel>", self._on_mouse_wheel)
		self.canvas.bind_all("<Shift-MouseWheel>", self._on_mouse_wheel)

	def _build_field(self, parent: tk.Frame, label: str, variable: tk.StringVar, width: int = 16) -> None:
		row = tk.Frame(parent, bg=self.colors["bg"])
		row.pack(side=tk.LEFT, padx=(0, 12))
		tk.Label(row, text=label, bg=self.colors["bg"], fg=self.colors["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
		entry = ttk.Entry(row, textvariable=variable, width=width)
		entry.pack(anchor="w")

	def _on_mouse_wheel(self, event: tk.Event) -> None:
		if not self.canvas.winfo_exists():
			return
		if event.delta == 0:
			return
		direction = -1 if event.delta > 0 else 1
		self.canvas.yview_scroll(direction, "units")

	def _on_start(self) -> None:
		self.auto_run = True
		self._start_cycle()

	def _start_cycle(self) -> None:
		self.tile_counter += 1
		tile_id = self.tile_counter
		self._create_tile(tile_id)

		address_prefix = self.address_prefix_var.get().strip() or "C4:BD:6A"
		try:
			mtu = int(self.mtu_var.get())
		except ValueError:
			mtu = 247
		try:
			scan_timeout = float(self.scan_timeout_var.get())
		except ValueError:
			scan_timeout = 6.0
		try:
			rx_timeout = float(self.rx_timeout_var.get())
		except ValueError:
			rx_timeout = 5.0

		self.worker.run_cycle(tile_id, address_prefix, mtu, scan_timeout, rx_timeout)

	def _start_manual_action(self, action: str) -> None:
		self.auto_run = False
		self.tile_counter += 1
		tile_id = self.tile_counter
		self._create_tile(tile_id)
		address_prefix = self.address_prefix_var.get().strip() or "C4:BD:6A"
		try:
			mtu = int(self.mtu_var.get())
		except ValueError:
			mtu = 247
		try:
			scan_timeout = float(self.scan_timeout_var.get())
		except ValueError:
			scan_timeout = 6.0
		try:
			rx_timeout = float(self.rx_timeout_var.get())
		except ValueError:
			rx_timeout = 5.0
		self.worker.run_manual_action(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, action)

	def _create_tile(self, tile_id: int) -> None:
		card = tk.Frame(
			self.tiles_container,
			bg=self.colors["panel"],
			highlightbackground=self.colors["border"],
			highlightthickness=1,
		)
		card.pack(fill=tk.X, padx=6, pady=6)

		header = tk.Frame(card, bg=self.colors["panel"])
		header.pack(fill=tk.X, padx=12, pady=(10, 4))

		index_label = tk.Label(header, text=f"Sensor #{tile_id}", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 11, "bold"))
		index_label.pack(side=tk.LEFT)

		status_label = tk.Label(header, text="Queued", bg=self.colors["panel"], fg=self.colors["accent_alt"], font=("Segoe UI", 10, "bold"))
		status_label.pack(side=tk.RIGHT)

		body = tk.Frame(card, bg=self.colors["panel"])
		body.pack(fill=tk.X, padx=12, pady=(0, 10))

		address_label = tk.Label(body, text="Address: —", bg=self.colors["panel"], fg=self.colors["muted"])
		address_label.pack(anchor="w")

		checklist_frame = tk.Frame(body, bg=self.colors["panel"])
		checklist_frame.pack(anchor="w", pady=(6, 2))

		checklist_items = [
			("waiting_connection", "Waiting connection"),
			("connected", "Connected"),
			("general_info_exchange", "General info exchange"),
			("data_collection", "Data collection"),
			("close_session", "Close session"),
			("disconnect", "Disconnect"),
		]
		checklist_labels: Dict[str, tk.Label] = {}
		checklist_titles: Dict[str, str] = {}
		for key, title in checklist_items:
			label = tk.Label(checklist_frame, text=f"☐ {title}", bg=self.colors["panel"], fg=self.colors["muted"])
			label.pack(anchor="w")
			checklist_labels[key] = label
			checklist_titles[key] = title

		rx_label = tk.Label(body, text="RX: —", bg=self.colors["panel"], fg=self.colors["text"], wraplength=720, justify="left")
		rx_label.pack(anchor="w", pady=(4, 0))

		plot_btn = ttk.Button(body, text="Plot export", command=lambda tid=tile_id: self._plot_tile_waveform(tid))
		plot_btn.pack(anchor="w", pady=(6, 0))

		self.tiles[tile_id] = {
			"status": status_label,
			"address": address_label,
			"rx": rx_label,
			"checklist": checklist_labels,
			"checklist_titles": checklist_titles,
			"plot_btn": plot_btn,
		}


	def _plot_tile_waveform(self, tile_id: int) -> None:
		export_info = self.tile_export_info.get(tile_id)
		if not export_info:
			messagebox.showinfo("Waveform plot", f"No export available yet for tile {tile_id}.")
			return
		self._plot_waveform_from_export(export_info, title=f"Tile {tile_id}")

	def _plot_latest_waveform(self) -> None:
		if not self.latest_export_info:
			messagebox.showinfo("Waveform plot", "No waveform export available yet.")
			return
		self._plot_waveform_from_export(self.latest_export_info, title="Latest waveform export")

	def _pb_read_varint(self, buf: bytes, i: int):
		shift = 0
		val = 0
		n = len(buf)
		while True:
			if i >= n:
				raise ValueError("Truncated varint")
			b = buf[i]
			i += 1
			val |= (b & 0x7F) << shift
			if (b & 0x80) == 0:
				return val, i
			shift += 7
			if shift > 70:
				raise ValueError("Varint too long")

	def _pb_parse_fields(self, buf: bytes):
		i = 0
		n = len(buf)
		out = []
		while i < n:
			tag, i = self._pb_read_varint(buf, i)
			field_no = tag >> 3
			wt = tag & 0x07
			if wt == 0:
				v, i = self._pb_read_varint(buf, i)
				out.append((field_no, wt, v))
			elif wt == 2:
				ln, i = self._pb_read_varint(buf, i)
				v = buf[i:i+ln]
				if len(v) != ln:
					raise ValueError("Truncated length-delimited field")
				i += ln
				out.append((field_no, wt, v))
			elif wt == 5:
				v = buf[i:i+4]
				if len(v) != 4:
					raise ValueError("Truncated 32-bit field")
				i += 4
				out.append((field_no, wt, v))
			elif wt == 1:
				v = buf[i:i+8]
				if len(v) != 8:
					raise ValueError("Truncated 64-bit field")
				i += 8
				out.append((field_no, wt, v))
			else:
				raise ValueError(f"Unsupported wire type {wt}")
		return out

	def _extract_true_twf_samples_from_raw_export(self, raw_path: str):
		# patch6 export format: repeated [uint32_le payload_len][payload]
		with open(raw_path, "rb") as f:
			raw = f.read()
		off = 0
		payloads = []
		while off + 4 <= len(raw):
			ln = int.from_bytes(raw[off:off+4], "little", signed=False)
			off += 4
			p = raw[off:off+ln]
			if len(p) != ln:
				break
			off += ln
			payloads.append(p)

		# Extract measurement_data.data bytes from AppMessage.data_upload / data_pair / measurement_data
		blocks = []  # (start_point, bytes)
		for payload in payloads:
			try:
				top = self._pb_parse_fields(payload)
			except Exception:
				continue
			# AppMessage.data_upload observed as field #2 in this protocol export
			du_list = [v for fn, wt, v in top if fn == 2 and wt == 2]
			if not du_list:
				continue
			du = du_list[0]
			try:
				du_fields = self._pb_parse_fields(du)
			except Exception:
				continue
			# data_pair repeated observed as field #4
			for fn, wt, dp_bytes in du_fields:
				if fn != 4 or wt != 2:
					continue
				try:
					dp_fields = self._pb_parse_fields(dp_bytes)
				except Exception:
					continue
				# measurement_data observed as field #2 in data_pair
				md_list = [v for f, w, v in dp_fields if f == 2 and w == 2]
				for md in md_list:
					try:
						md_fields = self._pb_parse_fields(md)
					except Exception:
						continue
					start_point = None
					data_bytes = None
					for f, w, v in md_fields:
						if f == 1 and w == 0:  # start_point
							start_point = int(v)
						elif f == 2 and w == 2:  # measurement_data.data
							data_bytes = bytes(v)
					if data_bytes:
						blocks.append((start_point, data_bytes))

		if not blocks:
			raise RuntimeError("No measurement_data.data blocks found in raw export")

		if all(sp is not None for sp, _ in blocks):
			blocks.sort(key=lambda x: x[0])

		blob = b"".join(b for _sp, b in blocks)
		if len(blob) < 2:
			raise RuntimeError("Waveform blob too small")
		if (len(blob) % 2) != 0:
			blob = blob[:-1]

		# VIBRATION_ACC_WAVE from provided docs/com.c is INT16, little-endian bytes on device export
		count = len(blob) // 2
		if count <= 0:
			raise RuntimeError("No int16 samples reconstructed")
		y = list(struct.unpack("<" + "h" * count, blob))
		meta = {
			"blocks": len(blocks),
			"samples": len(y),
			"fs_hz": 25600.0,
			"raw_unit": "int16",
		}
		return y, meta

	def _plot_waveform_from_export(self, export_info: dict, title: str = "Waveform") -> None:
		if plt is None:
			messagebox.showerror("Waveform plot", "matplotlib is not installed.\nInstall with: pip install matplotlib")
			return
		raw_path = export_info.get("raw") if isinstance(export_info, dict) else None
		samples_path = export_info.get("samples") if isinstance(export_info, dict) else None
		index_path = export_info.get("index") if isinstance(export_info, dict) else None
		try:
			# Preferred path: reconstruct true time waveform from raw protobuf payloads export
			if raw_path and os.path.exists(raw_path):
				y, meta = self._extract_true_twf_samples_from_raw_export(raw_path)
				fs = float(meta.get("fs_hz", 0.0) or 0.0)
				x = list(range(len(y)))
				xlabel = "Sample index"
				if fs > 0.0:
					x = [i / fs for i in range(len(y))]
					xlabel = f"Time (s) @ Fs={fs:g} Hz"
				plt.figure()
				plt.plot(x, y)
				plt.title(f"{title} (reconstructed TWF, {meta.get('samples', len(y))} samples)")
				plt.xlabel(xlabel)
				plt.ylabel("Acceleration (raw int16)")
				plt.grid(True)
				plt.show()
				return

			# Fallback 1: generic samples.csv plot (debug)
			if samples_path and os.path.exists(samples_path):
				with open(samples_path, "r", newline="", encoding="utf-8") as f:
					r = csv.DictReader(f)
					rows = list(r)
				if not rows:
					raise RuntimeError("samples.csv is empty")
				numeric_cols = []
				for h in (r.fieldnames or []):
					vals = []
					ok = True
					for row in rows[: min(len(rows), 200)]:
						v = row.get(h, "")
						if v in (None, ""):
							continue
						try:
							vals.append(float(v))
						except Exception:
							ok = False
							break
					if ok and vals:
						numeric_cols.append(h)
				if not numeric_cols:
					raise RuntimeError("No numeric columns in samples.csv")
				prefer = [h for h in numeric_cols if h.lower() not in ("block_index", "msg_seq_no", "total_block")]
				plot_cols = (prefer or numeric_cols)[:4]
				x = list(range(len(rows)))
				plt.figure()
				for col in plot_cols:
					y = []
					for row in rows:
						try:
							y.append(float(row.get(col, "nan")))
						except Exception:
							y.append(float("nan"))
					plt.plot(x, y, label=col)
				plt.title(f"{title} (samples.csv fallback)")
				plt.xlabel("Row")
				plt.ylabel("Value")
				if len(plot_cols) > 1:
					plt.legend()
				plt.grid(True)
				plt.show()
				return

			# Fallback 2: payload lengths only (debug)
			if index_path and os.path.exists(index_path):
				with open(index_path, "r", newline="", encoding="utf-8") as f:
					r = csv.DictReader(f)
					rows = list(r)
				if not rows:
					raise RuntimeError("index.csv is empty")
				x = []
				y = []
				for i, row in enumerate(rows, start=1):
					x.append(i)
					try:
						y.append(float(row.get("payload_len", "nan")))
					except Exception:
						y.append(float("nan"))
				plt.figure()
				plt.plot(x, y, label="payload_len")
				plt.title(f"{title} (index payload lengths fallback)")
				plt.xlabel("Block")
				plt.ylabel("Payload length")
				plt.grid(True)
				plt.legend()
				plt.show()
				return
			raise RuntimeError("No export files found")
		except Exception as e:
			messagebox.showerror("Waveform plot", f"Unable to plot waveform: {e}")

	def _poll_queue(self) -> None:
		try:
			while True:
				event = self.ui_queue.get_nowait()
				if event[0] == "tile_update":
					_, tile_id, payload = event
					self._apply_tile_update(tile_id, payload)
				elif event[0] == "cycle_done":
					if self.auto_run:
						self.root.after(100, self._start_cycle)
				self.ui_queue.task_done()
		except Empty:
			pass
		self.root.after(150, self._poll_queue)

	def _apply_tile_update(self, tile_id: int, payload: Dict[str, str]) -> None:
		tile = self.tiles.get(tile_id)
		if not tile:
			return
		if "status" in payload:
			tile["status"].configure(text=payload["status"])
		if "address" in payload:
			tile["address"].configure(text=f"Address: {payload['address']}")
		if "rx_text" in payload:
			tile["rx"].configure(text=f"RX: {payload['rx_text']}")
		if "export_info" in payload and payload["export_info"]:
			self.tile_export_info[tile_id] = payload["export_info"]
			self.latest_export_info = payload["export_info"]
		if "checklist" in payload:
			state_map = {"pending": "☐", "in_progress": "⧗", "done": "☑"}
			labels = tile.get("checklist", {})
			titles = tile.get("checklist_titles", {})
			for key, state in payload["checklist"].items():
				label = labels.get(key)
				title = titles.get(key, key)
				if label:
					symbol = state_map.get(state, "☐")
					label.configure(text=f"{symbol} {title}")


def main() -> None:
	root = tk.Tk()
	SimGwV2App(root)
	root.mainloop()


if __name__ == "__main__":
	main()
