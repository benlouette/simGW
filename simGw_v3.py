import asyncio
import os
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from queue import Queue, Empty
from tkinter import ttk
from typing import Dict, Optional

from google.protobuf import text_format
from bleak import BleakClient, BleakScanner

BASE_DIR = os.path.dirname(__file__)
FROTO_DIR = os.path.join(BASE_DIR, "froto")
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

			current_time_ms = int(time.time() * 1000)
			config_pair = ConfigurationAndCommand_pb2.ConfigPair(
				specific_config_item=Common_pb2.CURRENT_TIME,
				time_config_content=ConfigurationAndCommand_pb2.TimeArray(
					time=[ConfigurationAndCommand_pb2.TimeArrayElement(time=current_time_ms)]
				),
			)
			config_dissem = ConfigurationAndCommand_pb2.ConfigDisseminate(
				header=Froto_pb2.FrotoHeader(
					version=1,
					is_up=False,
					message_seq_no=_alloc_seq(),
					time_to_live=3,
					primitive_type=Froto_pb2.SIMPLE_DISSEMINATE,
					message_type=Froto_pb2.NORMAL_MESSAGE,
					total_block=1,
				),
				appVer=1,
				product=Common_pb2.UNKNOWN_PRODUCT,
				config_pair=[config_pair],
			)
			app_message = DeviceAppBulletSensor_pb2.AppMessage(
				appVer=1,
				config_dissem=config_dissem,
			)
			payload = await _write_app_message(app_message)

			await asyncio.sleep(0.1)
			self.ui_queue.put(("tile_update", tile_id, {"status": "Sending version_retrieve..."}))
			version_retrieve = FirmwareUpdateOverTheAir_pb2.VersionRetrieve(
				header=Froto_pb2.FrotoHeader(
					version=1,
					is_up=False,
					message_seq_no=_alloc_seq(),
					time_to_live=3,
					primitive_type=Froto_pb2.SIMPLE_DISSEMINATE,
					message_type=Froto_pb2.NORMAL_MESSAGE,
					total_block=1,
				),
				appVer=1,
				payload=FirmwareUpdateOverTheAir_pb2.CURRENT_VERSION,
			)
			app_message = DeviceAppBulletSensor_pb2.AppMessage(
				appVer=1,
				version_retrieve=version_retrieve,
			)
			await _write_app_message(app_message)

			try:
				payload = await _wait_next_rx(rx_timeout)
			except asyncio.TimeoutError:
				self.ui_queue.put(("tile_update", tile_id, {"status": "RX timeout"}))
			else:
				latest_status = "Received"
				latest_rx_text = f"TYPE: {self._pb_message_type(payload)}\nHEX: {self._hex_short(payload)}\n\n" + self._format_rx_payload(payload)
				try:
					app_message = _safe_parse_app(payload)
					message_type = app_message.WhichOneof("_messages")
					if message_type == "current_version_upload":
						await asyncio.sleep(0.1)
						self.ui_queue.put(("tile_update", tile_id, {"status": "Sending config_retrieve..."}))
						config_retrieve = ConfigurationAndCommand_pb2.ConfigRetrieve(
							header=Froto_pb2.FrotoHeader(
								version=1,
								is_up=False,
								message_seq_no=_alloc_seq(),
								time_to_live=3,
								primitive_type=Froto_pb2.SIMPLE_DISSEMINATE,
								message_type=Froto_pb2.NORMAL_MESSAGE,
								total_block=1,
							),
							appVer=1,
							payload=ConfigurationAndCommand_pb2.CURRENT_CONFIG_HASH,
						)
						app_message = DeviceAppBulletSensor_pb2.AppMessage(
							appVer=1,
							config_retrieve=config_retrieve,
						)
						await _write_app_message(app_message)

						try:
							hash_payload = await _wait_next_rx(rx_timeout)
						except asyncio.TimeoutError:
							latest_status = "Config hash timeout"
						else:
							try:
								# print("Parsing config hash upload...")
								hash_message = _safe_parse_app(hash_payload)
								hash_type = hash_message.WhichOneof("_messages")
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
										try:
											measure_types = [
												SensingDataUpload_pb2.MeasurementTypeMsg(
													measure_type=Common_pb2.ENVIROMENTAL_TEMPERATURE_CURRENT
												),
												SensingDataUpload_pb2.MeasurementTypeMsg(
													measure_type=Common_pb2.ENVIROMENTAL_HUMIDITY_CURRENT
												),
												SensingDataUpload_pb2.MeasurementTypeMsg(
													measure_type=Common_pb2.VOLTAGE_CURRENT
												),
											]
										except Exception:
											print("Error creating measure types, using empty list")
											measure_types = []

										data_selection = SensingDataUpload_pb2.DataSelectionDisseminate(
											header=Froto_pb2.FrotoHeader(
												version=1,
												is_up=False,
												message_seq_no=_alloc_seq() + loop_index,
												time_to_live=3,
												primitive_type=Froto_pb2.SIMPLE_DISSEMINATE,
												message_type=Froto_pb2.NORMAL_MESSAGE,
												total_block=1,
											),
											appVer=1,
											product=Common_pb2.UNKNOWN_PRODUCT,
											measure_type=measure_types,
											sample_time_start=0,
											sample_time_end=current_time_ms,
										)
										app_message = DeviceAppBulletSensor_pb2.AppMessage(
											appVer=1,
											data_selection=data_selection,
										)

										self.ui_queue.put(("tile_update", tile_id, {"status": f"Sending data_selection ({loop_index + 1}/6)..."}))
										await _write_app_message(app_message)

										try:
											data_payload = await _wait_next_rx(rx_timeout)
										except asyncio.TimeoutError:
											latest_status = "Data upload timeout"
											data_collection_complete = False
											self.ui_queue.put(("tile_update", tile_id, {"checklist": {"data_collection": "pending"}}))
											break
										else:
											try:
												data_message = _safe_parse_app(data_payload)
												data_type = data_message.WhichOneof("_messages")
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
										vibration_types = [
											SensingDataUpload_pb2.MeasurementTypeMsg(
												measure_type=Common_pb2.VIBRATION_ACC_WAVE
											),
										]
										vibration_selection = SensingDataUpload_pb2.DataSelectionDisseminate(
											header=Froto_pb2.FrotoHeader(
												version=1,
												is_up=False,
												message_seq_no=_alloc_seq(),
												time_to_live=3,
												primitive_type=Froto_pb2.SIMPLE_DISSEMINATE,
												message_type=Froto_pb2.NORMAL_MESSAGE,
												total_block=1,
											),
											appVer=1,
											product=Common_pb2.UNKNOWN_PRODUCT,
											measure_type=vibration_types,
											sample_time_start=0,
											sample_time_end=current_time_ms,
										)
										app_message = DeviceAppBulletSensor_pb2.AppMessage(
											appVer=1,
											data_selection=vibration_selection,
										)
										self.ui_queue.put(("tile_update", tile_id, {"status": "Sending vibration data_selection...", "checklist": {"data_collection": "in_progress"}}))
										await _write_app_message(app_message)

										received_messages = 0
										for message_index in range(64):
											print(f"Waiting for vibration data upload {message_index + 1}/64...")
											try:
												data_payload = await _wait_next_rx(rx_timeout)
											except asyncio.TimeoutError:
												latest_status = "Data upload timeout"
												data_collection_complete = False
												self.ui_queue.put(("tile_update", tile_id, {"checklist": {"data_collection": "pending"}}))
												break
											else:
												try:
													print(f"1Waiting for vibration data upload {message_index + 1}/64...")
													data_message = _safe_parse_app(data_payload)
													data_type = data_message.WhichOneof("_messages")
													if data_type == "data_upload":
														print(f"2Waiting for vibration data upload {message_index + 1}/64...")
														received_messages += 1
														latest_status = f"Data upload received ({received_messages}/64)"
														latest_rx_text = f"TYPE: {self._pb_message_type(data_payload)}\nHEX: {self._hex_short(data_payload)}\n\n" + self._format_rx_payload(data_payload)
													else:
														print(f"3Waiting for vibration data upload {message_index + 1}/64...")
														latest_status = f"Unexpected reply: {data_type}"
														data_collection_complete = False
														break
												except Exception:
													latest_status = "Data upload parse error"
													data_collection_complete = False
													self.ui_queue.put(("tile_update", tile_id, {"checklist": {"data_collection": "pending"}}))
													break

										if received_messages == 64:
											self.ui_queue.put(("tile_update", tile_id, {"checklist": {"data_collection": "done"}}))
											self.ui_queue.put(("tile_update", tile_id, {"checklist": {"close_session": "in_progress"}}))
											await asyncio.sleep(0.1)
											command_dissem = ConfigurationAndCommand_pb2.CommandDisseminate(
												header=Froto_pb2.FrotoHeader(
													version=1,
													is_up=False,
													message_seq_no=_alloc_seq(),
													time_to_live=3,
													primitive_type=Froto_pb2.SIMPLE_DISSEMINATE,
													message_type=Froto_pb2.NORMAL_MESSAGE,
													total_block=1,
												),
												appVer=1,
												command_pair=ConfigurationAndCommand_pb2.CommandPair(
													command=Common_pb2.CLOSE_SESSION,
												),
											)
											app_message = DeviceAppBulletSensor_pb2.AppMessage(
												appVer=1,
												command_dissem=command_dissem,
											)
											self.ui_queue.put(("tile_update", tile_id, {"status": "Sending CLOSE_SESSION..."}))
											await _write_app_message(app_message)
											self.ui_queue.put(("tile_update", tile_id, {"checklist": {"close_session": "done"}}))
								else:
									latest_status = f"Unexpected reply: {hash_type}"
									print(f"--> Config hash upload type: {hash_type}")
							except Exception:
								latest_status = "Config hash parse error"
				except Exception:
					pass
				self.ui_queue.put(("tile_update", tile_id, {"status": latest_status, "rx_text": latest_rx_text}))

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

		form = tk.Frame(self.root, bg=self.colors["bg"])
		form.pack(fill=tk.X, padx=16)

		self._build_field(form, "Address prefix", self.address_prefix_var)
		self._build_field(form, "MTU", self.mtu_var, width=8)
		self._build_field(form, "Scan timeout (s)", self.scan_timeout_var, width=8)
		self._build_field(form, "RX timeout (s)", self.rx_timeout_var, width=8)

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

		self.tiles[tile_id] = {
			"status": status_label,
			"address": address_label,
			"rx": rx_label,
			"checklist": checklist_labels,
			"checklist_titles": checklist_titles,
		}

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
