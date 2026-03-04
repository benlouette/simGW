"""Devices tab UI and scan helpers.

Public API consumed by `ui_application.py`:
- build_ui_devices
- devices_scan
- devices_populate
- devices_on_select

Responsibilities:
- render the Devices tab UI
- perform asynchronous BLE discovery in a worker thread
- apply address/name filters and update table rows
- render detailed advertising data for selected rows
"""

import asyncio
import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Any, Iterable

from ble_filters import adv_matches as ble_adv_matches, format_adv_details as ble_format_adv_details

_SCAN_TIMEOUT_S = 5.0
_INITIAL_DETAILS_TEXT = "Waiting for scan...\nDevices will appear automatically.\nSelect a device to see details."


def _read_device_filters(app) -> tuple[str, str]:
    """Read current address/name filters from runtime params."""
    params = app._read_runtime_params()
    address_prefix = (params[0] if len(params) > 0 else "") or ""
    name_contains = (params[6] if len(params) > 6 else "") or ""
    return str(address_prefix), str(name_contains)


def _set_scan_status(app, message: str) -> None:
    try:
        app.devices_scan_status_var.set(message)
    except Exception:
        pass


def _set_details_text(app, text: str) -> None:
    if app.devices_detail is None:
        return
    app.devices_detail.configure(state=tk.NORMAL)
    app.devices_detail.delete("1.0", tk.END)
    app.devices_detail.insert("1.0", text)
    app.devices_detail.configure(state=tk.DISABLED)


def _iter_discovery_pairs(discovery_result: Any) -> Iterable[tuple[Any, Any]]:
    """Normalize bleak discovery results to `(device, adv)` pairs."""
    if isinstance(discovery_result, dict):
        for _addr, value in discovery_result.items():
            if isinstance(value, tuple) and len(value) == 2:
                yield value
            else:
                yield value, None
        return

    if isinstance(discovery_result, list):
        for value in discovery_result:
            if isinstance(value, tuple) and len(value) == 2:
                yield value
            else:
                yield value, None


def _device_address_upper(device: Any) -> str:
    try:
        raw = getattr(device, "address", "") if not isinstance(device, str) else str(device)
    except Exception:
        raw = ""
    return (raw or "").upper()


def _device_name(device: Any, advertisement_data: Any) -> str:
    name = ""
    try:
        name = getattr(device, "name", "") if not isinstance(device, str) else ""
    except Exception:
        name = ""

    if name:
        return name

    if advertisement_data is not None:
        try:
            return getattr(advertisement_data, "local_name", "") or ""
        except Exception:
            return ""

    return ""


def _device_rssi(advertisement_data: Any) -> str:
    if advertisement_data is None:
        return ""
    try:
        value = getattr(advertisement_data, "rssi", None)
        return "" if value is None else str(value)
    except Exception:
        return ""


def build_ui_devices(app, parent: tk.Frame) -> None:
    """Build the Devices tab (filters, table, and advertising details)."""
    header = tk.Frame(parent, bg=app.colors["panel"], highlightbackground=app.colors["border"], highlightthickness=1)
    header.pack(fill=tk.X, padx=16, pady=(16, 10))

    left = tk.Frame(header, bg=app.colors["panel"])
    left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=12, pady=12)
    tk.Label(left, text="Devices & Advertising", bg=app.colors["panel"], fg=app.colors["text"], font=("Segoe UI", 14, "bold")).pack(anchor="w")
    tk.Label(left, text="Auto-scan every 3s (5s timeout)", bg=app.colors["panel"], fg=app.colors["muted"]).pack(anchor="w", pady=(2, 0))

    status_frame = tk.Frame(header, bg=app.colors["panel"])
    status_frame.pack(side=tk.RIGHT, padx=12, pady=12)
    tk.Label(status_frame, textvariable=app.devices_scan_status_var, bg=app.colors["panel"], fg=app.colors["text"], font=("Segoe UI", 10, "bold")).pack()

    filters = tk.Frame(parent, bg=app.colors["panel"], highlightbackground=app.colors["border"], highlightthickness=1)
    filters.pack(fill=tk.X, padx=16, pady=(0, 10))
    filters_in = tk.Frame(filters, bg=app.colors["panel"])
    filters_in.pack(fill=tk.X, padx=12, pady=8)

    tk.Label(filters_in, text="🔍 Filters:", bg=app.colors["panel"], fg=app.colors["text"], font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 10))

    tk.Label(filters_in, text="Address:", bg=app.colors["panel"], fg=app.colors["muted"]).pack(side=tk.LEFT, padx=(0, 4))
    ttk.Entry(filters_in, textvariable=app.address_prefix_var, width=15).pack(side=tk.LEFT, padx=(0, 12))

    tk.Label(filters_in, text="Name:", bg=app.colors["panel"], fg=app.colors["muted"]).pack(side=tk.LEFT, padx=(0, 4))
    ttk.Entry(filters_in, textvariable=app.adv_name_contains_var, width=15).pack(side=tk.LEFT, padx=(0, 12))

    body = tk.Frame(parent, bg=app.colors["bg"])
    body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))

    left_panel = tk.Frame(body, bg=app.colors["bg"])
    left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

    list_header = tk.Frame(left_panel, bg=app.colors["panel"], highlightbackground=app.colors["border"], highlightthickness=1)
    list_header.pack(fill=tk.X, pady=(0, 6))
    tk.Label(list_header, text="📡 BLE Devices", bg=app.colors["panel"], fg=app.colors["text"], font=("Segoe UI", 10, "bold")).pack(padx=10, pady=6, anchor="w")

    cols = ("address", "name", "rssi", "matched")
    tree = ttk.Treeview(left_panel, columns=cols, show="headings", height=14)
    tree.heading("address", text="Address")
    tree.heading("name", text="Name")
    tree.heading("rssi", text="RSSI")
    tree.heading("matched", text="Match")
    tree.column("address", width=180, anchor="w")
    tree.column("name", width=220, anchor="w")
    tree.column("rssi", width=80, anchor="e")
    tree.column("matched", width=80, anchor="center")

    tree_style = ttk.Style()
    tree_style.configure("Treeview", background=app.colors["panel"], foreground=app.colors["text"], fieldbackground=app.colors["panel"], borderwidth=0)
    tree_style.configure("Treeview.Heading", background=app.colors["panel_alt"], foreground=app.colors["text"], borderwidth=1, relief="flat")
    tree_style.map("Treeview", background=[("selected", app.colors["accent"])], foreground=[("selected", "#ffffff")])

    tree.pack(fill=tk.BOTH, expand=True)
    tree.bind("<<TreeviewSelect>>", lambda event: devices_on_select(app, event))
    app.devices_tree = tree

    right_panel = tk.Frame(body, bg=app.colors["bg"])
    right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(6, 0))

    detail_header = tk.Frame(right_panel, bg=app.colors["panel"], highlightbackground=app.colors["border"], highlightthickness=1)
    detail_header.pack(fill=tk.X, pady=(0, 6))
    tk.Label(detail_header, text="📋 Advertising Details", bg=app.colors["panel"], fg=app.colors["text"], font=("Segoe UI", 10, "bold")).pack(padx=10, pady=6, anchor="w")

    detail = tk.Frame(right_panel, bg=app.colors["panel"], highlightbackground=app.colors["border"], highlightthickness=1)
    detail.pack(fill=tk.BOTH, expand=True)

    detail_in = tk.Frame(detail, bg=app.colors["panel"])
    detail_in.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
    app.devices_detail = tk.Text(detail_in, wrap="none", bg=app.colors["panel"], fg=app.colors["text"], relief=tk.FLAT)
    app.devices_detail.pack(fill=tk.BOTH, expand=True)
    _set_details_text(app, _INITIAL_DETAILS_TEXT)


def devices_scan(app) -> None:
    """Start one background BLE scan and schedule table update on UI thread."""
    if app._devices_scan_in_progress:
        return

    app._devices_scan_in_progress = True

    _set_scan_status(app, "🔍 Scanning...")
    try:
        app.root.update_idletasks()
    except Exception:
        pass

    scan_timeout_s = _SCAN_TIMEOUT_S

    def worker():
        try:
            async def _do():
                from bleak import BleakScanner
                result = await BleakScanner.discover(timeout=scan_timeout_s, return_adv=True)
                return list(_iter_discovery_pairs(result))

            pairs = asyncio.run(_do())
            app.root.after(0, lambda: devices_populate(app, pairs))
        except Exception as exc:
            app.root.after(0, lambda: _set_scan_status(app, f"❌ Error: {type(exc).__name__}"))
        finally:
            app.root.after(0, lambda: setattr(app, '_devices_scan_in_progress', False))

    threading.Thread(target=worker, daemon=True).start()


def devices_populate(app, pairs) -> None:
    """Populate/refresh device rows from discovery `(device, adv)` pairs."""
    if not hasattr(app, "_devices_by_addr"):
        app._devices_by_addr = {}

    now_ms = int(time.time() * 1000)
    addr_prefix, name_contains = _read_device_filters(app)

    added = 0
    updated = 0

    for dev, adv in pairs:
        addr = _device_address_upper(dev)
        if not addr:
            continue

        ok = ble_adv_matches(dev, adv, addr_prefix, name_contains)
        if not ok:
            continue

        name = _device_name(dev, adv)
        rssi = _device_rssi(adv)

        mark = "✔"
        prev = app._devices_by_addr.get(addr)
        app._devices_by_addr[addr] = {"dev": dev, "adv": adv, "last_seen_ms": now_ms}

        if prev is None:
            try:
                app.devices_tree.insert("", "end", iid=addr, values=(addr, name, rssi, mark))
                added += 1
            except Exception:
                try:
                    app.devices_tree.item(addr, values=(addr, name, rssi, mark))
                    updated += 1
                except Exception:
                    pass
        else:
            try:
                app.devices_tree.item(addr, values=(addr, name, rssi, mark))
                updated += 1
            except Exception:
                pass

    total = len(app._devices_by_addr)
    if added > 0:
        _set_scan_status(app, f"✓ {total} devices (+{added} new)")
    else:
        _set_scan_status(app, f"✓ {total} devices")


def devices_on_select(app, _evt) -> None:
    """Render advertising details for selected row."""
    sel = app.devices_tree.selection()
    if not sel:
        return
    addr = sel[0]
    if not hasattr(app, "_devices_by_addr"):
        return
    item = app._devices_by_addr.get(addr)
    if not item:
        return
    dev = item.get("dev")
    adv = item.get("adv")
    details_text = ble_format_adv_details(dev, adv)
    _set_details_text(app, details_text)
