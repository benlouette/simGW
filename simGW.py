import asyncio
import threading
import tkinter as tk
from tkinter import ttk

from bleak import BleakScanner

# --- Helpers: format advertising data nicely ---
def fmt_adv(device, adv):
    lines = []
    lines.append(f"Name: {device.name}")
    lines.append(f"Address: {device.address}")
    rssi = getattr(adv, "rssi", None) if adv is not None else None
    if rssi is None:
        rssi = getattr(device, "rssi", None)
    lines.append(f"RSSI: {rssi}")
    if adv is not None:
        lines.append(f"Local name (adv): {adv.local_name}")
        lines.append(f"TX power: {adv.tx_power}")
        if adv.service_uuids:
            lines.append("Service UUIDs:")
            for u in adv.service_uuids:
                lines.append(f"  - {u}")
        if adv.manufacturer_data:
            lines.append("Manufacturer data:")
            for k, v in adv.manufacturer_data.items():
                lines.append(f"  - 0x{k:04X}: {v.hex()}")
        if adv.service_data:
            lines.append("Service data:")
            for k, v in adv.service_data.items():
                lines.append(f"  - {k}: {v.hex()}")
    return "\n".join(lines)

async def do_scan(timeout_s=5.0):
    res = await BleakScanner.discover(timeout=timeout_s, return_adv=True)

    pairs = []

    # Case A: dict { address: (device, adv) }  (seen on some Bleak versions)
    if isinstance(res, dict):
        for addr, val in res.items():
            if isinstance(val, tuple) and len(val) == 2:
                dev, adv = val
            else:
                dev, adv = val, None
            pairs.append((dev, adv))
        return pairs

    # Case B: list of (device, adv) or list of devices
    if isinstance(res, list):
        for item in res:
            if isinstance(item, tuple) and len(item) == 2:
                dev, adv = item
            else:
                dev, adv = item, None
            pairs.append((dev, adv))
        return pairs

    # Fallback: unknown type
    return pairs

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BLE Scanner (Bleak + Tkinter)")
        self.geometry("900x500")

        self.devices = []  # list[(device, adv)]

        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=8)

        self.scan_btn = ttk.Button(top, text="Scan (5s)", command=self.scan_clicked)
        self.scan_btn.pack(side="left")

        self.filter_var = tk.StringVar(value="C4:BD:6A")
        ttk.Label(top, text="Prefix filter (optional):").pack(side="left", padx=(12, 4))
        ttk.Entry(top, textvariable=self.filter_var, width=16).pack(side="left")

        main = ttk.Panedwindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=8, pady=8)

        left = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=1)
        main.add(right, weight=2)

        self.listbox = tk.Listbox(left)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        self.details = tk.Text(right, wrap="none")
        self.details.pack(fill="both", expand=True)

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status).pack(anchor="w", padx=8, pady=(0, 6))

    def scan_clicked(self):
        self.scan_btn.configure(state="disabled")
        self.status.set("Scanning...")
        self.listbox.delete(0, tk.END)
        self.details.delete("1.0", tk.END)
        self.devices = []

        def worker():
            try:
                results = asyncio.run(do_scan(5.0))
            except Exception as e:
                self.after(0, self.scan_failed, e)
                return
            self.after(0, self.scan_done, results)

        threading.Thread(target=worker, daemon=True).start()

    def scan_failed(self, e):
        self.scan_btn.configure(state="normal")
        self.status.set(f"Scan failed: {e}")

    def scan_done(self, results):
        prefix = (self.filter_var.get() or "").strip().upper()
        filtered = []

        for dev, adv in results:
            # dev can be BleakDevice OR sometimes an address string
            if isinstance(dev, str):
                addr = dev.upper()
                name = "<?>"
                rssi = None
            else:
                addr = (getattr(dev, "address", "") or "").upper()
                name = (
                    getattr(dev, "name", None)
                    or (getattr(adv, "local_name", "") if adv else "")
                    or "<?>"
                )

                # RSSI: Bleak version dependent
                rssi = getattr(adv, "rssi", None) if adv is not None else None
                if rssi is None:
                    rssi = getattr(dev, "rssi", None)
                if rssi is None:
                    rssi = "?"

            if prefix and not addr.startswith(prefix):
                continue

            filtered.append((dev, adv))

        self.devices = filtered
        self.listbox.delete(0, tk.END)

        for dev, adv in self.devices:
            if isinstance(dev, str):
                addr = dev
                name = "<?>"
                rssi = "?"
            else:
                addr = getattr(dev, "address", "<?>")
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

            self.listbox.insert(tk.END, f"{name}   [{addr}]   RSSI={rssi}")

        self.scan_btn.configure(state="normal")
        self.status.set(f"Found {len(self.devices)} device(s). Click one to view adv details.")

    def on_select(self, _evt):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        dev, adv = self.devices[idx]

        self.details.delete("1.0", tk.END)

        if isinstance(dev, str):
            self.details.insert(tk.END, f"Address: {dev}\n(No device object / adv details available)")
            return

        self.details.insert(tk.END, fmt_adv(dev, adv))

if __name__ == "__main__":
    App().mainloop()