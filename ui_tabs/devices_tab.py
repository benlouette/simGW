import asyncio
import threading
import time
import tkinter as tk
from tkinter import ttk
from ble_filters import adv_matches as ble_adv_matches, format_adv_details as ble_format_adv_details


def build_ui_devices(app, parent: tk.Frame) -> None:
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

    tk.Label(filters_in, text="Service UUID:", bg=app.colors["panel"], fg=app.colors["muted"]).pack(side=tk.LEFT, padx=(0, 4))
    ttk.Entry(filters_in, textvariable=app.adv_service_uuid_contains_var, width=12).pack(side=tk.LEFT)

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
    tree.bind("<<TreeviewSelect>>", app._devices_on_select)
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
    app.devices_detail.insert("1.0", "Waiting for scan...\nDevices will appear automatically.\nSelect a device to see details.")
    app.devices_detail.configure(state=tk.DISABLED)


def devices_scan(app) -> None:
    if app._devices_scan_in_progress:
        return

    app._devices_scan_in_progress = True

    try:
        app.devices_scan_status_var.set("🔍 Scanning...")
        app.root.update_idletasks()
    except Exception:
        pass

    addr_prefix, _mtu, _scan_timeout, _rx_timeout, _rec, _sess, name_contains, svc_contains, mfg_id_hex, mfg_data_hex, _twf_type = app._read_runtime_params()
    timeout_s = 5.0

    def worker():
        try:
            async def _do():
                from bleak import BleakScanner
                res = await BleakScanner.discover(timeout=timeout_s, return_adv=True)
                pairs = []
                if isinstance(res, dict):
                    for _addr, val in res.items():
                        if isinstance(val, tuple) and len(val) == 2:
                            pairs.append(val)
                        else:
                            pairs.append((val, None))
                elif isinstance(res, list):
                    for item in res:
                        if isinstance(item, tuple) and len(item) == 2:
                            pairs.append(item)
                        else:
                            pairs.append((item, None))
                return pairs

            pairs = asyncio.run(_do())
            app.root.after(0, lambda: app._devices_populate(pairs))
        except Exception as exc:
            app.root.after(0, lambda: app.devices_scan_status_var.set(f"❌ Error: {type(exc).__name__}"))
        finally:
            app.root.after(0, lambda: setattr(app, '_devices_scan_in_progress', False))

    threading.Thread(target=worker, daemon=True).start()


def devices_populate(app, pairs) -> None:
    if not hasattr(app, "_devices_by_addr"):
        app._devices_by_addr = {}

    now_ms = int(time.time() * 1000)
    addr_prefix, _mtu, _scan_timeout, _rx_timeout, _rec, _sess, name_contains, svc_contains, mfg_id_hex, mfg_data_hex, _twf_type = app._read_runtime_params()

    added = 0
    updated = 0

    for (dev, adv) in pairs:
        try:
            addr = getattr(dev, "address", "") if not isinstance(dev, str) else str(dev)
            addr = (addr or "").upper()
        except Exception:
            continue
        if not addr:
            continue

        ok = ble_adv_matches(dev, adv, addr_prefix, name_contains, svc_contains, mfg_id_hex, mfg_data_hex)
        if not ok:
            continue

        name = ""
        try:
            name = getattr(dev, "name", "") if not isinstance(dev, str) else ""
        except Exception:
            name = ""
        if not name and adv is not None:
            try:
                name = getattr(adv, "local_name", "") or ""
            except Exception:
                name = ""

        rssi = ""
        if adv is not None:
            try:
                rv = getattr(adv, "rssi", None)
                rssi = "" if rv is None else str(rv)
            except Exception:
                rssi = ""

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
        app.devices_scan_status_var.set(f"✓ {total} devices (+{added} new)")
    else:
        app.devices_scan_status_var.set(f"✓ {total} devices")


def devices_on_select(app, _evt) -> None:
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
    txt = ble_format_adv_details(dev, adv)
    app.devices_detail.configure(state=tk.NORMAL)
    app.devices_detail.delete("1.0", tk.END)
    app.devices_detail.insert("1.0", txt)
    app.devices_detail.configure(state=tk.DISABLED)


def devices_set_details(app, txt: str) -> None:
    app.devices_detail.configure(state=tk.NORMAL)
    app.devices_detail.delete("1.0", tk.END)
    app.devices_detail.insert("1.0", txt)
    app.devices_detail.configure(state=tk.DISABLED)
