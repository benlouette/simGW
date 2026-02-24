import asyncio
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox

from bleak import BleakScanner, BleakClient


# ====== UUIDs NUS-like (modifiable dans l'UI si besoin) ======
DEFAULT_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
DEFAULT_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # write (GW -> sensor)
DEFAULT_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # notify (sensor -> GW)


# ===================== Helpers =====================

def bytes_to_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def bytes_to_ascii_preview(data: bytes) -> str:
    out = []
    for b in data:
        if 32 <= b <= 126:
            out.append(chr(b))
        else:
            out.append(".")
    return "".join(out)


def parse_hex_string(s: str) -> bytes:
    s = s.strip().replace(",", " ").replace("0x", "").replace("0X", "")
    if not s:
        return b""
    parts = [p for p in s.split() if p]
    try:
        return bytes(int(p, 16) for p in parts)
    except ValueError as e:
        raise ValueError(f"Hex invalide: {e}")


def fmt_adv(device, adv):
    lines = []
    lines.append(f"Name: {getattr(device, 'name', None)}")
    lines.append(f"Address: {getattr(device, 'address', None)}")

    rssi = getattr(adv, "rssi", None) if adv is not None else None
    if rssi is None:
        rssi = getattr(device, "rssi", None)
    lines.append(f"RSSI: {rssi}")

    if adv is not None:
        lines.append(f"Local name (adv): {getattr(adv, 'local_name', None)}")
        lines.append(f"TX power: {getattr(adv, 'tx_power', None)}")

        service_uuids = getattr(adv, "service_uuids", None) or []
        if service_uuids:
            lines.append("Service UUIDs:")
            for u in service_uuids:
                lines.append(f"  - {u}")

        manufacturer_data = getattr(adv, "manufacturer_data", None) or {}
        if manufacturer_data:
            lines.append("Manufacturer data:")
            for k, v in manufacturer_data.items():
                vv = bytes(v) if not isinstance(v, (bytes, bytearray)) else v
                lines.append(f"  - 0x{k:04X}: {vv.hex()}")

        service_data = getattr(adv, "service_data", None) or {}
        if service_data:
            lines.append("Service data:")
            for k, v in service_data.items():
                vv = bytes(v) if not isinstance(v, (bytes, bytearray)) else v
                lines.append(f"  - {k}: {vv.hex()}")

    return "\n".join(lines)


async def do_scan(timeout_s=5.0):
    """Robuste aux différents formats de retour Bleak."""
    res = await BleakScanner.discover(timeout=timeout_s, return_adv=True)

    pairs = []

    # Case A: dict { addr: (device, adv) } or { addr: device }
    if isinstance(res, dict):
        for _addr, val in res.items():
            if isinstance(val, tuple) and len(val) == 2:
                dev, adv = val
            else:
                dev, adv = val, None
            pairs.append((dev, adv))
        return pairs

    # Case B: list[(device, adv)] or list[device]
    if isinstance(res, list):
        for item in res:
            if isinstance(item, tuple) and len(item) == 2:
                dev, adv = item
            else:
                dev, adv = item, None
            pairs.append((dev, adv))
        return pairs

    return pairs


# ===================== BLE worker thread =====================

class BleWorker:
    """
    Thread dédié asyncio pour Bleak, pour éviter de bloquer Tkinter.
    Communication vers GUI via self.gui_queue.
    """

    def __init__(self, gui_queue: queue.Queue):
        self.gui_queue = gui_queue
        self.loop = None
        self.thread = None
        self.client = None
        self.connected_address = None
        self.notify_enabled_uuid = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._thread_main, daemon=True)
        self.thread.start()

    def _thread_main(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro):
        if self.loop is None:
            raise RuntimeError("BLE worker not started")
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _post(self, kind, **kwargs):
        self.gui_queue.put((kind, kwargs))

    async def connect(self, address: str):
        try:
            # Nettoyage connexion existante
            if self.client is not None:
                try:
                    if self.client.is_connected:
                        await self.client.disconnect()
                except Exception:
                    pass
                self.client = None
                self.connected_address = None
                self.notify_enabled_uuid = None

            client = BleakClient(address)
            await client.connect()

            self.client = client
            self.connected_address = address
            self.notify_enabled_uuid = None

            self._post("connected", address=address)

        except Exception as e:
            self._post("error", message=f"Connect failed: {e}")

    async def disconnect(self):
        try:
            if self.client is not None:
                if self.client.is_connected:
                    await self.client.disconnect()
            self._post("disconnected")
        except Exception as e:
            self._post("error", message=f"Disconnect failed: {e}")
        finally:
            self.client = None
            self.connected_address = None
            self.notify_enabled_uuid = None

    async def discover_services(self):
        try:
            if self.client is None or not self.client.is_connected:
                raise RuntimeError("Not connected")

            services = self.client.services
            # Selon backend, parfois il faut déclencher get_services implicitement
            if services is None:
                services = await self.client.get_services()

            lines = []
            for svc in services:
                lines.append(f"[SERVICE] {svc.uuid}  ({svc.description})")
                for ch in svc.characteristics:
                    props = ",".join(ch.properties) if ch.properties else "?"
                    lines.append(f"  [CHAR] {ch.uuid}  props=[{props}]")
                    for d in ch.descriptors:
                        lines.append(f"    [DESC] handle={d.handle} uuid={d.uuid}")

            self._post("services", text="\n".join(lines) if lines else "(no services)")
        except Exception as e:
            self._post("error", message=f"Discover services failed: {e}")

    async def start_notify(self, char_uuid: str):
        try:
            if self.client is None or not self.client.is_connected:
                raise RuntimeError("Not connected")

            def cb(sender, data):
                b = bytes(data)
                self._post("rx", sender=str(sender), data=b)

            await self.client.start_notify(char_uuid, cb)
            self.notify_enabled_uuid = char_uuid
            self._post("notify_started", uuid=char_uuid)

        except Exception as e:
            self._post("error", message=f"Start notify failed ({char_uuid}): {e}")

    async def stop_notify(self, char_uuid: str):
        try:
            if self.client is None or not self.client.is_connected:
                raise RuntimeError("Not connected")
            await self.client.stop_notify(char_uuid)
            if self.notify_enabled_uuid == char_uuid:
                self.notify_enabled_uuid = None
            self._post("notify_stopped", uuid=char_uuid)
        except Exception as e:
            self._post("error", message=f"Stop notify failed ({char_uuid}): {e}")

    async def write_char(self, char_uuid: str, data: bytes, response: bool):
        try:
            if self.client is None or not self.client.is_connected:
                raise RuntimeError("Not connected")
            await self.client.write_gatt_char(char_uuid, data, response=response)
            self._post("tx", uuid=char_uuid, data=data, response=response)
        except Exception as e:
            self._post("error", message=f"Write failed ({char_uuid}): {e}")


# ===================== Tkinter App =====================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BLE Scanner / GATT Monitor (Tkinter + Bleak)")
        self.geometry("1250x760")

        self.devices = []  # list[(dev, adv)]
        self.gui_queue = queue.Queue()
        self.ble = BleWorker(self.gui_queue)
        self.ble.start()

        self._build_ui()
        self.after(100, self._poll_gui_queue)

    # ---------- UI ----------

    def _build_ui(self):
        # Top controls
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)

        self.scan_btn = ttk.Button(top, text="Scan (5s)", command=self.scan_clicked)
        self.scan_btn.pack(side="left")

        ttk.Label(top, text="MAC prefix filter:").pack(side="left", padx=(10, 4))
        self.filter_var = tk.StringVar(value="C4:BD:6A")
        ttk.Entry(top, textvariable=self.filter_var, width=16).pack(side="left")

        ttk.Label(top, text="Service UUID:").pack(side="left", padx=(14, 4))
        self.service_uuid_var = tk.StringVar(value=DEFAULT_SERVICE_UUID)
        ttk.Entry(top, textvariable=self.service_uuid_var, width=38).pack(side="left")

        ttk.Label(top, text="RX UUID (write):").pack(side="left", padx=(14, 4))
        self.rx_uuid_var = tk.StringVar(value=DEFAULT_RX_UUID)
        ttk.Entry(top, textvariable=self.rx_uuid_var, width=38).pack(side="left")

        ttk.Label(top, text="TX UUID (notify):").pack(side="left", padx=(14, 4))
        self.tx_uuid_var = tk.StringVar(value=DEFAULT_TX_UUID)
        ttk.Entry(top, textvariable=self.tx_uuid_var, width=38).pack(side="left")

        # Main split
        main = ttk.Panedwindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=8, pady=6)

        # Left pane (devices + adv)
        left = ttk.Panedwindow(main, orient="vertical")
        main.add(left, weight=1)

        left_top = ttk.Frame(left)
        left_bot = ttk.Frame(left)
        left.add(left_top, weight=1)
        left.add(left_bot, weight=1)

        ttk.Label(left_top, text="Devices").pack(anchor="w")
        self.listbox = tk.Listbox(left_top)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        dev_btns = ttk.Frame(left_top)
        dev_btns.pack(fill="x", pady=(4, 0))
        self.connect_btn = ttk.Button(dev_btns, text="Connect", command=self.connect_selected)
        self.connect_btn.pack(side="left")
        self.disconnect_btn = ttk.Button(dev_btns, text="Disconnect", command=self.disconnect_clicked)
        self.disconnect_btn.pack(side="left", padx=(6, 0))
        self.discover_btn = ttk.Button(dev_btns, text="Discover GATT", command=self.discover_gatt_clicked)
        self.discover_btn.pack(side="left", padx=(6, 0))

        ttk.Label(left_bot, text="Advertising details").pack(anchor="w")
        self.details = tk.Text(left_bot, wrap="none", height=12)
        self.details.pack(fill="both", expand=True)

        # Right pane (GATT + logs + TX)
        right = ttk.Panedwindow(main, orient="vertical")
        main.add(right, weight=2)

        right_top = ttk.Frame(right)
        right_mid = ttk.Frame(right)
        right_bot = ttk.Frame(right)
        right.add(right_top, weight=1)
        right.add(right_mid, weight=2)
        right.add(right_bot, weight=1)

        # GATT browse output
        ttk.Label(right_top, text="GATT services / characteristics").pack(anchor="w")
        self.gatt_text = tk.Text(right_top, wrap="none", height=12)
        self.gatt_text.pack(fill="both", expand=True)

        gatt_btns = ttk.Frame(right_top)
        gatt_btns.pack(fill="x", pady=(4, 0))
        self.notify_start_btn = ttk.Button(gatt_btns, text="Start Notify (TX UUID)", command=self.start_notify_clicked)
        self.notify_start_btn.pack(side="left")
        self.notify_stop_btn = ttk.Button(gatt_btns, text="Stop Notify (TX UUID)", command=self.stop_notify_clicked)
        self.notify_stop_btn.pack(side="left", padx=(6, 0))

        # RX/TX log
        ttk.Label(right_mid, text="RX / TX log").pack(anchor="w")
        self.log_text = tk.Text(right_mid, wrap="none")
        self.log_text.pack(fill="both", expand=True)

        log_btns = ttk.Frame(right_mid)
        log_btns.pack(fill="x", pady=(4, 0))
        ttk.Button(log_btns, text="Clear log", command=lambda: self.log_text.delete("1.0", tk.END)).pack(side="left")

        # TX panel
        ttk.Label(right_bot, text="Write raw hex to RX UUID").pack(anchor="w")

        tx_opts = ttk.Frame(right_bot)
        tx_opts.pack(fill="x", pady=(2, 4))
        self.write_with_response_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            tx_opts,
            text="Write with response",
            variable=self.write_with_response_var
        ).pack(side="left")

        ex_btns = ttk.Frame(right_bot)
        ex_btns.pack(fill="x", pady=(0, 4))
        ttk.Button(ex_btns, text="Example: 01 02 03", command=lambda: self.tx_hex_var.set("01 02 03")).pack(side="left")
        ttk.Button(ex_btns, text="Example ASCII 'test'", command=lambda: self.tx_hex_var.set("74 65 73 74")).pack(side="left", padx=(6, 0))

        self.tx_hex_var = tk.StringVar()
        tx_entry = ttk.Entry(right_bot, textvariable=self.tx_hex_var)
        tx_entry.pack(fill="x", pady=(0, 4))
        tx_entry.bind("<Return>", lambda e: self.write_hex_clicked())

        ttk.Button(right_bot, text="Send", command=self.write_hex_clicked).pack(anchor="w")

        # Status bar
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status_var).pack(fill="x", padx=8, pady=(0, 6))

    # ---------- GUI utils ----------

    def set_status(self, txt: str):
        self.status_var.set(txt)

    def append_text(self, widget: tk.Text, txt: str):
        widget.insert(tk.END, txt)
        widget.see(tk.END)

    def log(self, txt: str):
        self.append_text(self.log_text, txt + "\n")

    def get_selected_device(self):
        sel = self.listbox.curselection()
        if not sel:
            return None, None
        idx = sel[0]
        return self.devices[idx]

    # ---------- Scan ----------

    def scan_clicked(self):
        self.scan_btn.configure(state="disabled")
        self.set_status("Scanning...")
        self.listbox.delete(0, tk.END)
        self.details.delete("1.0", tk.END)
        self.devices = []

        def worker():
            try:
                results = asyncio.run(do_scan(5.0))
            except Exception as e:
                self.after(0, lambda: self._scan_failed(e))
                return
            self.after(0, lambda: self.scan_done(results))

        threading.Thread(target=worker, daemon=True).start()

    def _scan_failed(self, e):
        self.scan_btn.configure(state="normal")
        self.set_status(f"Scan failed: {e}")

    def scan_done(self, results):
        prefix = (self.filter_var.get() or "").strip().upper()
        filtered = []

        for dev, adv in results:
            if isinstance(dev, str):
                addr = dev.upper()
                name = "<?>"
                rssi = "?"
            else:
                addr = (getattr(dev, "address", "") or "").upper()
                name = (
                    getattr(dev, "name", None)
                    or (getattr(adv, "local_name", "") if adv else "")
                    or "<?>"
                )
                rssi = getattr(adv, "rssi", None) if adv is not None else None
                if rssi is None:
                    rssi = getattr(dev, "rssi", None)
                if rssi is None:
                    rssi = "?"

            if prefix and not addr.startswith(prefix):
                continue

            filtered.append((dev, adv, name, addr, rssi))

        self.devices = [(d, a) for (d, a, _, _, _) in filtered]
        self.listbox.delete(0, tk.END)

        for _dev, _adv, name, addr, rssi in filtered:
            self.listbox.insert(tk.END, f"{name}   [{addr}]   RSSI={rssi}")

        self.scan_btn.configure(state="normal")
        self.set_status(f"Found {len(self.devices)} device(s). Click one to view adv details.")

    def on_select(self, _evt):
        dev, adv = self.get_selected_device()
        if dev is None:
            return
        self.details.delete("1.0", tk.END)

        if isinstance(dev, str):
            self.details.insert(tk.END, f"Address: {dev}\n(No device object / adv details available)")
            return

        self.details.insert(tk.END, fmt_adv(dev, adv))

    # ---------- BLE actions ----------

    def connect_selected(self):
        dev, adv = self.get_selected_device()
        if dev is None:
            messagebox.showwarning("Connect", "Sélectionne un device dans la liste.")
            return

        if isinstance(dev, str):
            address = dev
        else:
            address = getattr(dev, "address", None)

        if not address:
            messagebox.showerror("Connect", "Adresse BLE introuvable.")
            return

        self.set_status(f"Connecting to {address}...")
        self.ble.submit(self.ble.connect(address))

    def disconnect_clicked(self):
        self.set_status("Disconnecting...")
        self.ble.submit(self.ble.disconnect())

    def discover_gatt_clicked(self):
        self.set_status("Discovering GATT services...")
        self.ble.submit(self.ble.discover_services())

    def start_notify_clicked(self):
        tx_uuid = self.tx_uuid_var.get().strip()
        if not tx_uuid:
            messagebox.showwarning("Notify", "TX UUID vide.")
            return
        self.set_status(f"Starting notify on {tx_uuid}...")
        self.ble.submit(self.ble.start_notify(tx_uuid))

    def stop_notify_clicked(self):
        tx_uuid = self.tx_uuid_var.get().strip()
        if not tx_uuid:
            messagebox.showwarning("Notify", "TX UUID vide.")
            return
        self.set_status(f"Stopping notify on {tx_uuid}...")
        self.ble.submit(self.ble.stop_notify(tx_uuid))

    def write_hex_clicked(self):
        rx_uuid = self.rx_uuid_var.get().strip()
        if not rx_uuid:
            messagebox.showwarning("Write", "RX UUID vide.")
            return

        try:
            data = parse_hex_string(self.tx_hex_var.get())
        except ValueError as e:
            messagebox.showerror("Hex", str(e))
            return

        if len(data) == 0:
            messagebox.showwarning("Write", "Payload hex vide.")
            return

        response = bool(self.write_with_response_var.get())
        self.set_status(f"Writing {len(data)} byte(s) to {rx_uuid}...")
        self.ble.submit(self.ble.write_char(rx_uuid, data, response=response))

    # ---------- GUI queue polling ----------

    def _poll_gui_queue(self):
        try:
            while True:
                kind, payload = self.gui_queue.get_nowait()
                self._handle_gui_event(kind, payload)
        except queue.Empty:
            pass
        finally:
            self.after(100, self._poll_gui_queue)

    def _handle_gui_event(self, kind, payload):
        if kind == "error":
            msg = payload.get("message", "Unknown error")
            self.set_status(msg)
            self.log(f"[ERR] {msg}")

        elif kind == "connected":
            addr = payload.get("address")
            self.set_status(f"Connected: {addr}")
            self.log(f"[BLE] Connected to {addr}")

        elif kind == "disconnected":
            self.set_status("Disconnected")
            self.log("[BLE] Disconnected")

        elif kind == "services":
            text = payload.get("text", "")
            self.gatt_text.delete("1.0", tk.END)
            self.gatt_text.insert(tk.END, text)
            self.set_status("GATT discovery done.")
            self.log("[BLE] GATT discovery done")

        elif kind == "notify_started":
            uuid = payload.get("uuid")
            self.set_status(f"Notify started on {uuid}")
            self.log(f"[BLE] Notify started on {uuid}")

        elif kind == "notify_stopped":
            uuid = payload.get("uuid")
            self.set_status(f"Notify stopped on {uuid}")
            self.log(f"[BLE] Notify stopped on {uuid}")

        elif kind == "tx":
            uuid = payload.get("uuid", "?")
            data = payload.get("data", b"")
            response = payload.get("response", False)
            self.set_status(f"TX {len(data)} byte(s)")
            self.log(f"[TX] uuid={uuid} len={len(data)} response={response}")
            self.log(f"     HEX  : {bytes_to_hex(data)}")
            self.log(f"     ASCII: {bytes_to_ascii_preview(data)}")

        elif kind == "rx":
            sender = payload.get("sender", "?")
            data = payload.get("data", b"")
            self.set_status(f"RX {len(data)} byte(s)")
            self.log(f"[RX] sender={sender} len={len(data)}")
            self.log(f"     HEX  : {bytes_to_hex(data)}")
            self.log(f"     ASCII: {bytes_to_ascii_preview(data)}")

        else:
            self.log(f"[DBG] unknown event: {kind} {payload}")


if __name__ == "__main__":
    app = App()
    app.mainloop()