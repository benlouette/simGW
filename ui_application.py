"""
UI Application module for simGW - Tkinter GUI components.

Contains the main SimGwV2App class with:
- 4-tab interface (Demo/Expert/Devices/Settings)
- BLE device management
- Waveform plotting
"""
import asyncio
import csv
import os
import re
import threading
import time
import tkinter as tk
from queue import Queue, Empty
from tkinter import ttk, messagebox
from typing import Dict, Optional

try:
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    try:
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    except Exception:
        FigureCanvasTkAgg = None
except Exception:
    plt = None
    Figure = None
    FigureCanvasTkAgg = None

from config import AUTO_RESTART_DELAY_MS, UI_POLL_INTERVAL_MS, CHECKLIST_ITEMS, CHECKLIST_STATE_MAP, MANUAL_ACTIONS
from data_exporters import WaveformParser
WaveformExportTools = WaveformParser


def create_app_class(BleCycleWorker, TileState):
    """Factory function to create SimGwV2App class with injected dependencies."""
    
    class SimGwV2App:
        def __init__(self, root: tk.Tk) -> None:
            self.root = root
            self._tk_root = root
            self.root.title("SimGW v2 BLE Loop")
            self.root.geometry("860x620")
            self.root.configure(bg="#0f1115")
    
            self.ui_queue: Queue = Queue()
            self.worker = BleCycleWorker(self.ui_queue)
            self.worker.start()
    
            self.tile_counter = 0
            self.tiles: Dict[int, Dict[str, tk.Label]] = {}
            self.auto_run = False
            self._auto_generation = 0
            self._auto_cycle_running = False
            self._auto_active_tile_id = None
            self.latest_export_info = None
            self.latest_overall_values = None
            self.tile_export_info: Dict[int, dict] = {}
            self.tile_state: Dict[int, TileState] = {}
            self._demo_mirrored_tile_id: Optional[int] = None
            self._demo_last_plotted_raw: str = ""
    
            # Demo tab state
            self.demo_status_var = tk.StringVar(value="Idle")
            self.demo_auto_state_var = tk.StringVar(value="AUTO: OFF")
            self.demo_cycle_state_var = tk.StringVar(value="CYCLE: IDLE")
            self.demo_device_var = tk.StringVar(value="")
            self.demo_export_var = tk.StringVar(value="")
            self.demo_last_overall_values = None
            self.demo_last_overall_rx_text = ""
            self.demo_last_wave_rx_text = ""
            # Demo embedded waveform plot (optional)
            self.demo_plot_fig = None
            self.demo_plot_canvas = None
            self.demo_plot_widget = None
            self.demo_plot_label = None
            self._demo_last_plotted_raw = None
            self.demo_overall_var = tk.StringVar(value="•")
            self.demo_waveform_var = tk.StringVar(value="•")
            self.demo_summary = None
            self.demo_debug = None
            self._log_max_lines = 2000
            #  Demo timeline (mirrors the latest Expert tile checklist)
            self.demo_checklist_state = {key: "pending" for key, _title in CHECKLIST_ITEMS}
            self.demo_timeline_labels = {}  # key -> (dot_label, text_label)


            # Devices tab state
            self.devices_tree = None
            self.devices_detail = None
            self._devices_last_scan = []
            self.devices_scan_status_var = tk.StringVar(value="Ready")
            self._devices_scan_in_progress = False  # Prevent concurrent scans

            self._devices_by_addr = {}  # addr -> {"dev":..., "adv":..., "last_seen_ms":...}
            self._devices_autoscan_job = None
            self._devices_autoscan_interval_ms = 3000
            self._devices_tab_widget = None  # set in _build_ui


            self.address_prefix_var = tk.StringVar(value="C4:BD:6A:")
            # Optional advertising-content filter (applied in addition to address prefix when set)
            self.adv_name_contains_var = tk.StringVar(value="IMx-1_ELO")
            self.adv_service_uuid_contains_var = tk.StringVar(value="")
            self.adv_mfg_id_hex_var = tk.StringVar(value="")  # e.g. "004C" or "0x004C"
            self.adv_mfg_data_hex_contains_var = tk.StringVar(value="")  # e.g. "01 02" or "0102"
            self.scan_timeout_var = tk.StringVar(value="60")
            self.rx_timeout_var = tk.StringVar(value="5")
            self.record_sessions_var = tk.BooleanVar(value=True)
            self.session_root_var = tk.StringVar(value="sessions")
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
                "ok": "#22c55e",
                "warn": "#f59e0b",
                "bad": "#ef4444",
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
    
        def _log(self, level: str, msg: str) -> None:
            """Append a timestamped line to the Demo debug console (if present)."""
            try:
                if self.demo_debug is None:
                    return
                ts = time.strftime("%H:%M:%S")
                line = f"[{ts}] {level}: {msg}\n"
                self.demo_debug.configure(state=tk.NORMAL)
                self.demo_debug.insert(tk.END, line)
                # Trim to last N lines
                try:
                    n_lines = int(self.demo_debug.index("end-1c").split(".")[0])
                    if n_lines > int(getattr(self, "_log_max_lines", 2000)):
                        cut = max(1, n_lines // 4)
                        self.demo_debug.delete("1.0", f"{cut}.0")
                except Exception:
                    pass
                self.demo_debug.see(tk.END)
                self.demo_debug.configure(state=tk.DISABLED)
            except Exception:
                pass
    
        
        def _demo_clear_debug(self) -> None:
            """Clear the Demo debug console."""
            try:
                if self.demo_debug is None:
                    return
                self.demo_debug.configure(state=tk.NORMAL)
                self.demo_debug.delete("1.0", tk.END)
                self.demo_debug.configure(state=tk.DISABLED)
            except Exception:
                pass
    
    
        def _demo_reset_ui_state(self, keep_debug: bool = True) -> None:
            """Reset Demo tab UI state (KPIs, timeline, summary, plot)."""
            try:
                self.demo_status_var.set("Idle")
                self.demo_device_var.set("")
                self.demo_export_var.set("")
                self.demo_overall_var.set("•")
                self.demo_waveform_var.set("•")
            except Exception:
                pass
    
            # Clear summary box (if present)
            try:
                if self.demo_summary is not None:
                    self.demo_summary.configure(state=tk.NORMAL)
                    self.demo_summary.delete("1.0", tk.END)
                    self.demo_summary.insert(tk.END, "•\n")
                    self.demo_summary.configure(state=tk.DISABLED)
            except Exception:
                pass
    
            # Reset timeline to pending
            try:
                self.demo_checklist_state = {key: "pending" for key, _title in CHECKLIST_ITEMS}
                self._demo_update_timeline({})
            except Exception:
                pass
    
            # Reset plot
            try:
                if getattr(self, "demo_plot_label", None) is not None:
                    self.demo_plot_label.config(text="(waiting for waveform...)")
                if getattr(self, "demo_plot_fig", None) is not None:
                    ax = self.demo_plot_fig.axes[0] if self.demo_plot_fig.axes else self.demo_plot_fig.add_subplot(111)
                    ax.clear()
                    ax.set_title("Waveform (latest)")
                    ax.set_xlabel("Sample")
                    ax.set_ylabel("Value")
                    ax.grid(True, alpha=0.2)
                    if getattr(self, "demo_plot_canvas", None) is not None:
                        self.demo_plot_canvas.draw()
            except Exception:
                pass
    
            # Reset last cached demo data
            try:
                self.demo_last_overall_values = None
                self.demo_last_overall_rx_text = ""
                self.demo_last_wave_rx_text = ""
            except Exception:
                pass
    
            if not keep_debug:
                self._demo_clear_debug()
    
    
    
        def _ui_build_run_header_card(self, parent: tk.Widget) -> tuple:
            """Build the standard header (used in Demo and Expert) with Start Auto / Stop and run-state labels."""
            card = tk.Frame(parent, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            card.pack(fill=tk.X, pady=(0, 12))
            inner = tk.Frame(card, bg=self.colors["panel"])
            inner.pack(fill=tk.X, padx=14, pady=12)
    
            left = tk.Frame(inner, bg=self.colors["panel"])
            left.pack(side=tk.LEFT, fill=tk.X, expand=True)
            tk.Label(left, text="SimGW Demo", bg=self.colors["panel"], fg=self.colors["text"],
                    font=("Segoe UI", 14, "bold")).pack(anchor="w")
            tk.Label(left, text="Scan → Connect → Overall → Waveform → Close", bg=self.colors["panel"],
                    fg=self.colors["muted"], font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 0))
    
            right = tk.Frame(inner, bg=self.colors["panel"])
            right.pack(side=tk.RIGHT)
            btns = tk.Frame(right, bg=self.colors["panel"])
            btns.pack(anchor="e")
    
            start_btn = ttk.Button(btns, text="Start Auto", style="Accent.TButton", command=self._on_start)
            start_btn.pack(side=tk.LEFT, padx=(0, 6))
            stop_btn = ttk.Button(btns, text="Stop", command=self._stop_auto)
            stop_btn.pack(side=tk.LEFT, padx=(0, 6))
    
            run_row = tk.Frame(right, bg=self.colors["panel"])
            run_row.pack(anchor="e", pady=(6, 0))
            tk.Label(run_row, textvariable=self.demo_auto_state_var, bg=self.colors["panel"], fg=self.colors["muted"],
                    font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 10))
            tk.Label(run_row, textvariable=self.demo_cycle_state_var, bg=self.colors["panel"], fg=self.colors["muted"],
                    font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
    
            return card, start_btn, stop_btn
    
        def _build_ui_demo(self, parent: tk.Frame) -> None:
            """Demo-friendly UI: no hex dumps, just KPIs + a timeline + a short summary."""
            panel = tk.Frame(parent, bg=self.colors["bg"])
            panel.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
            # Header
            _card, self.demo_start_button, self.demo_stop_button = self._ui_build_run_header_card(panel)
    
            # Ensure buttons reflect current state
            self._update_demo_run_controls()
    
            # KPI grid
            kpi = tk.Frame(panel, bg=self.colors["bg"])
            kpi.pack(fill=tk.X, pady=(0, 12))
    
            def _kpi_card(title: str, var: tk.StringVar) -> None:
                c = tk.Frame(kpi, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
                c.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
                ci = tk.Frame(c, bg=self.colors["panel"])
                ci.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
                tk.Label(ci, text=title, bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
                tk.Label(ci, textvariable=var, bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(2, 0))
    
            _kpi_card("Status", self.demo_status_var)
            _kpi_card("Device", self.demo_device_var)
            _kpi_card("Overall", self.demo_overall_var)
            _kpi_card("Waveform", self.demo_waveform_var)
    
            # Timeline (driven by checklist updates from the Expert cycle)
            tl_box = tk.Frame(panel, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            tl_box.pack(fill=tk.X, pady=(0, 12))
            tl_in = tk.Frame(tl_box, bg=self.colors["panel"])
            tl_in.pack(fill=tk.X, padx=14, pady=10)
    
            tk.Label(tl_in, text="Timeline", bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
    
            tl_row = tk.Frame(tl_in, bg=self.colors["panel"])
            tl_row.pack(fill=tk.X, pady=(6, 0))
    
            self.demo_timeline_labels = {}
            for key, title in CHECKLIST_ITEMS:
                item = tk.Frame(tl_row, bg=self.colors["panel"])
                item.pack(side=tk.LEFT, padx=(0, 14))
    
                dot = tk.Label(item, text="●", bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 12, "bold"))
                dot.pack(side=tk.LEFT)
                txt = tk.Label(item, text=title, bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 10))
                txt.pack(side=tk.LEFT, padx=(6, 0))
    
                self.demo_timeline_labels[key] = (dot, txt)
    
            # Splitter: Overall (summary) on top, Waveform plot below (resizable)
            panes = tk.PanedWindow(
                panel,
                orient=tk.VERTICAL,
                bg=self.colors["bg"],
                sashrelief=tk.RAISED,
                bd=0,
            )
            panes.pack(fill=tk.BOTH, expand=True)
    
            # --- Overall / Summary (top pane)
            sum_box = tk.Frame(panes, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            sum_in = tk.Frame(sum_box, bg=self.colors["panel"])
            sum_in.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)
    
            tk.Label(
                sum_in,
                text="Overalls",
                bg=self.colors["panel"],
                fg=self.colors["text"],
                font=("Segoe UI", 11, "bold"),
            ).pack(anchor="w")
    
            self.demo_summary = tk.Text(
                sum_in,
                height=10,
                wrap=tk.WORD,
                bg=self.colors["panel"],
                fg=self.colors["text"],
                bd=0,
            )
            self.demo_summary.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
            self.demo_summary.configure(state=tk.DISABLED)
    
            # --- Waveform plot (bottom pane)
            plot_box = tk.Frame(panes, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            plot_in = tk.Frame(plot_box, bg=self.colors["panel"])
            plot_in.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)
    
            header_row = tk.Frame(plot_in, bg=self.colors["panel"])
            header_row.pack(fill=tk.X)
    
            tk.Label(
                header_row,
                text="Waveform",
                bg=self.colors["panel"],
                fg=self.colors["text"],
                font=("Segoe UI", 11, "bold"),
            ).pack(side=tk.LEFT)
    
            self.demo_plot_label = tk.Label(
                header_row,
                text="(waiting for waveform...)",
                bg=self.colors["panel"],
                fg=self.colors["muted"],
                font=("Segoe UI", 10),
            )
            self.demo_plot_label.pack(side=tk.LEFT, padx=(10, 0))
    
            plot_area = tk.Frame(plot_in, bg=self.colors["panel"])
            plot_area.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
    
            if Figure is None or FigureCanvasTkAgg is None:
                tk.Label(
                    plot_area,
                    text="Matplotlib/TkAgg not available. Install matplotlib and ensure Tk support to view the waveform plot here.",
                    bg=self.colors["panel"],
                    fg=self.colors["muted"],
                    justify=tk.LEFT,
                    wraplength=900,
                    font=("Segoe UI", 10),
                ).pack(anchor="w")
                self.demo_plot_fig = None
                self.demo_plot_canvas = None
                self.demo_plot_widget = None
            else:
                self.demo_plot_fig = Figure(figsize=(7.5, 2.6), dpi=100)
                ax = self.demo_plot_fig.add_subplot(111)
                ax.set_title("Waveform (latest)")
                ax.set_xlabel("Sample")
                ax.set_ylabel("Value")
                ax.grid(True, alpha=0.2)
                self._demo_style_plot_axes(ax)
    
                self.demo_plot_canvas = FigureCanvasTkAgg(self.demo_plot_fig, master=plot_area)
                self.demo_plot_widget = self.demo_plot_canvas.get_tk_widget()
                try:
                    self.demo_plot_widget.configure(bg=self.colors.get("panel", "#171a21"))
                except Exception:
                    pass
                self.demo_plot_widget.pack(fill=tk.BOTH, expand=True)
    
            # Add panes with initial proportions (user can resize with the sash)
            panes.add(sum_box, stretch="always")
            panes.add(plot_box, stretch="always")
            # Debug console (last events/errors) • essential for diagnosing parsing/flow issues
            dbg_box = tk.Frame(panel, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            dbg_box.pack(fill=tk.BOTH, expand=False, pady=(12, 0))
            dbg_in = tk.Frame(dbg_box, bg=self.colors["panel"])
            dbg_in.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)
    
            hdr = tk.Frame(dbg_in, bg=self.colors["panel"])
            hdr.pack(fill=tk.X)
            tk.Label(hdr, text="Debug", bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
    
            ttk.Button(hdr, text="Clear", command=self._demo_clear_debug).pack(side=tk.RIGHT)
    
            self.demo_debug = tk.Text(
                dbg_in,
                height=7,
                wrap=tk.NONE,
                bg=self.colors["panel"],
                fg=self.colors["text"],
                bd=0,
                highlightthickness=0,
                font=("Consolas", 9),
            )
            self.demo_debug.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
            self.demo_debug.configure(state=tk.DISABLED)
    
    
        def _demo_style_plot_axes(self, ax) -> None:
            """Apply dark-theme styling to the embedded matplotlib axes."""
            try:
                fc = self.colors.get("panel", "#171a21")
                tc = self.colors.get("text", "#e6e6e6")
                mc = self.colors.get("muted", "#8b93a1")
                bc = self.colors.get("border", "#2a2f3a")
    
                # Figure + axes background
                if getattr(self, "demo_plot_fig", None) is not None:
                    self.demo_plot_fig.patch.set_facecolor(fc)
                ax.set_facecolor(fc)
    
                # Titles / labels / ticks
                ax.title.set_color(tc)
                ax.xaxis.label.set_color(mc)
                ax.yaxis.label.set_color(mc)
                ax.tick_params(colors=mc)
    
                # Spines + grid
                for sp in ax.spines.values():
                    sp.set_color(bc)
                try:
                    ax.grid(True, alpha=0.25, color=bc)
                except Exception:
                    ax.grid(True, alpha=0.25)
            except Exception:
                pass
    
        def _demo_plot_waveform_from_samples(self, samples_csv_path: str) -> None:
            """Load the exported *_samples.csv and render it in the embedded Demo plot."""
            if not samples_csv_path:
                return
            if self.demo_plot_canvas is None or self.demo_plot_fig is None:
                return
            if not os.path.isfile(samples_csv_path):
                return
    
            # Read rows and pick the longest series (field_name) to plot
            series = {}  # field_name -> list of (global_index, value)
            try:
                with open(samples_csv_path, "r", encoding="utf-8") as f:
                    r = csv.DictReader(f)
                    for row in r:
                        try:
                            field = (row.get("field_name") or "").strip()
                            block_i = int(row.get("block_index") or 0)
                            sample_i = int(row.get("sample_index") or 0)
                            val = float(row.get("value") or 0)
                        except Exception:
                            continue
                        # Create a monotonically increasing index across blocks
                        global_i = (block_i - 1) * 10_000_000 + sample_i
                        if field not in series:
                            series[field] = []
                        series[field].append((global_i, val))
            except Exception:
                return
    
            if not series:
                return
    
            # Choose the field with most samples
            field = max(series.keys(), key=lambda k: len(series.get(k) or []))
            try:
                if self.demo_plot_label is not None:
                    self.demo_plot_label.configure(text=f"{len(series[field])} points")
            except Exception:
                pass
            pts = series[field]
            pts.sort(key=lambda x: x[0])
            # Normalize index to 0..N-1 for display
            y = [v for _, v in pts]
            x = list(range(len(y)))
    
            try:
                ax = self.demo_plot_fig.axes[0] if self.demo_plot_fig.axes else self.demo_plot_fig.add_subplot(111)
                ax.clear()
                ax.plot(x, y)
                title = "Waveform (latest)"
                if field:
                    title = f"Waveform (latest) • {field}"
                ax.set_title(title)
                ax.set_xlabel("Sample")
                ax.set_ylabel("Value")
                ax.grid(True, alpha=0.2)
                self._demo_style_plot_axes(ax)
                self.demo_plot_canvas.draw()
            except Exception:
                pass
    
        # Tags for nicer key/value rendering
            self.demo_summary.tag_configure("k", foreground=self.colors["muted"], font=("Segoe UI", 10, "bold"))
            self.demo_summary.tag_configure("v", foreground=self.colors["text"], font=("Segoe UI", 10, "normal"))
            self.demo_summary.tag_configure("h", foreground=self.colors["text"], font=("Segoe UI", 10, "bold"))
    
            # Initialize timeline colors
            self._demo_update_timeline({})
    
        def _demo_plot_waveform_from_raw_export(self, raw_path: str) -> None:
            """Render waveform in the embedded Demo matplotlib canvas from a raw export .bin file."""
            if not raw_path:
                return
            if self.demo_plot_canvas is None or self.demo_plot_fig is None:
                return
            if not os.path.isfile(raw_path):
                raise FileNotFoundError(raw_path)
    
            y, meta = WaveformExportTools.extract_true_waveform_samples(raw_path)
    
            # Update label
            try:
                n = int(meta.get("samples") or len(y))
            except Exception:
                n = len(y)
            if self.demo_plot_label is not None:
                self.demo_plot_label.configure(text=f"{n} samples • {os.path.basename(raw_path)}")
    
            ax = self.demo_plot_fig.axes[0] if self.demo_plot_fig.axes else self.demo_plot_fig.add_subplot(111)
            ax.clear()
            ax.plot(y)
            ax.set_title("Waveform (latest)")
            ax.set_xlabel("Sample")
            ax.set_ylabel("Amplitude (int16)")
            ax.grid(True, alpha=0.2)
            self._demo_style_plot_axes(ax)
            self.demo_plot_canvas.draw()
    
    
        def _build_ui_devices(self, parent: tk.Frame) -> None:
            header = tk.Frame(parent, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            header.pack(fill=tk.X, padx=16, pady=(16, 10))
    
            left = tk.Frame(header, bg=self.colors["panel"])
            left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=12, pady=12)
            tk.Label(left, text="Devices & Advertising", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 14, "bold")).pack(anchor="w")
            tk.Label(left, text="Auto-scan every 3s (5s timeout)", bg=self.colors["panel"], fg=self.colors["muted"]).pack(anchor="w", pady=(2, 0))

            status_frame = tk.Frame(header, bg=self.colors["panel"])
            status_frame.pack(side=tk.RIGHT, padx=12, pady=12)
            tk.Label(status_frame, textvariable=self.devices_scan_status_var, bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 10, "bold")).pack()

            # Filters row
            filters = tk.Frame(parent, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            filters.pack(fill=tk.X, padx=16, pady=(0, 10))
            filters_in = tk.Frame(filters, bg=self.colors["panel"])
            filters_in.pack(fill=tk.X, padx=12, pady=8)

            tk.Label(filters_in, text="\U0001F50D Filters:", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 10))

            tk.Label(filters_in, text="Address:", bg=self.colors["panel"], fg=self.colors["muted"]).pack(side=tk.LEFT, padx=(0, 4))
            ttk.Entry(filters_in, textvariable=self.address_prefix_var, width=15).pack(side=tk.LEFT, padx=(0, 12))

            tk.Label(filters_in, text="Name:", bg=self.colors["panel"], fg=self.colors["muted"]).pack(side=tk.LEFT, padx=(0, 4))
            ttk.Entry(filters_in, textvariable=self.adv_name_contains_var, width=15).pack(side=tk.LEFT, padx=(0, 12))

            tk.Label(filters_in, text="Service UUID:", bg=self.colors["panel"], fg=self.colors["muted"]).pack(side=tk.LEFT, padx=(0, 4))
            ttk.Entry(filters_in, textvariable=self.adv_service_uuid_contains_var, width=12).pack(side=tk.LEFT)

            body = tk.Frame(parent, bg=self.colors["bg"])
            body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))

            # Left: Devices list with its own header
            left_panel = tk.Frame(body, bg=self.colors["bg"])
            left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

            list_header = tk.Frame(left_panel, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            list_header.pack(fill=tk.X, pady=(0, 6))
            tk.Label(list_header, text="\U0001F4E1 BLE Devices", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 10, "bold")).pack(padx=10, pady=6, anchor="w")

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
            tree.pack(fill=tk.BOTH, expand=True)

            tree.bind("<<TreeviewSelect>>", self._devices_on_select)
            self.devices_tree = tree

            # Right: Advertising details with its own header
            right_panel = tk.Frame(body, bg=self.colors["bg"])
            right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(6, 0))

            detail_header = tk.Frame(right_panel, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            detail_header.pack(fill=tk.X, pady=(0, 6))
            tk.Label(detail_header, text="\U0001F4CB Advertising Details", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 10, "bold")).pack(padx=10, pady=6, anchor="w")

            detail = tk.Frame(right_panel, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            detail.pack(fill=tk.BOTH, expand=True)

            detail_in = tk.Frame(detail, bg=self.colors["panel"])
            detail_in.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
            self.devices_detail = tk.Text(detail_in, wrap="none", bg=self.colors["panel"], fg=self.colors["text"], relief=tk.FLAT)
            self.devices_detail.pack(fill=tk.BOTH, expand=True)
            self.devices_detail.insert("1.0", "Waiting for scan...\nDevices will appear automatically.\nSelect a device to see details.")
            self.devices_detail.configure(state=tk.DISABLED)

            self._devices_last_scan = []  # list of (device, adv)

        def _build_ui_settings(self, parent: tk.Frame) -> None:
            header = tk.Frame(parent, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            header.pack(fill=tk.X, padx=16, pady=(16, 10))

            left = tk.Frame(header, bg=self.colors["panel"])
            left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=12, pady=12)
            tk.Label(left, text="Settings", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 14, "bold")).pack(anchor="w")
            tk.Label(left, text="Configuration and defaults", bg=self.colors["panel"], fg=self.colors["muted"]).pack(anchor="w", pady=(2, 0))

            body = tk.Frame(parent, bg=self.colors["bg"])
            body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))

            # Keep settings simple here: record + session dir + timeouts + MTU.
            box = tk.Frame(body, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            box.pack(fill=tk.X)
            inner = tk.Frame(box, bg=self.colors["panel"])
            inner.pack(fill=tk.X, padx=12, pady=12)

            ttk.Checkbutton(inner, text="Record sessions", variable=self.record_sessions_var).grid(row=0, column=0, sticky="w", padx=(0, 12))
            tk.Label(inner, text="Session dir", bg=self.colors["panel"], fg=self.colors["muted"]).grid(row=0, column=1, sticky="e", padx=(12, 6))
            ttk.Entry(inner, textvariable=self.session_root_var, width=24).grid(row=0, column=2, sticky="w")

            tk.Label(inner, text="Scan timeout (s)", bg=self.colors["panel"], fg=self.colors["muted"]).grid(row=1, column=0, sticky="w", pady=(10, 0))
            ttk.Entry(inner, textvariable=self.scan_timeout_var, width=10).grid(row=1, column=1, sticky="w", pady=(10, 0))

            tk.Label(inner, text="RX timeout (s)", bg=self.colors["panel"], fg=self.colors["muted"]).grid(row=1, column=2, sticky="w", padx=(12, 0), pady=(10, 0))
            ttk.Entry(inner, textvariable=self.rx_timeout_var, width=10).grid(row=1, column=3, sticky="w", pady=(10, 0))

            tk.Label(inner, text="MTU", bg=self.colors["panel"], fg=self.colors["muted"]).grid(row=2, column=0, sticky="w", pady=(10, 0))
            ttk.Entry(inner, textvariable=self.mtu_var, width=10).grid(row=2, column=1, sticky="w", pady=(10, 0))

            util = tk.Frame(body, bg=self.colors["bg"])
            util.pack(fill=tk.X, pady=(12, 0))
            ttk.Button(util, text="Clear Logs", command=self._clear_tiles).pack(side=tk.LEFT)
            ttk.Button(util, text="Stop Auto", command=self._stop_auto).pack(side=tk.LEFT, padx=(8, 0))
        
        def _devices_scan(self) -> None:
            """Trigger one scan pass and merge results into the Devices table (no clear, no dup)."""
            # Prevent concurrent scans (fix thread leak)
            if self._devices_scan_in_progress:
                return
            
            self._devices_scan_in_progress = True
            
            try:
                self.devices_scan_status_var.set("\U0001F50D Scanning...")
                self.root.update_idletasks()
            except Exception:
                pass

            # Read current filters (use fixed 5s timeout)
            addr_prefix, _mtu, _scan_timeout, _rx_timeout, _rec, _sess, name_contains, svc_contains, mfg_id_hex, mfg_data_hex = self._read_runtime_params()
            timeout_s = 5.0  # Fixed 5 second timeout

            def worker():
                try:
                    async def _do():
                        from bleak import BleakScanner
                        # return_adv=True gives (device, adv) pairs on most backends
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
                    self.root.after(0, lambda: self._devices_populate(pairs))
                except Exception as exc:
                    # Do not crash autoscan; just report
                    self.root.after(0, lambda: self.devices_scan_status_var.set(f"\u274c Error: {type(exc).__name__}"))
                finally:
                    # Always reset flag when scan completes
                    self.root.after(0, lambda: setattr(self, '_devices_scan_in_progress', False))

            threading.Thread(target=worker, daemon=True).start()

        def _devices_populate(self, pairs):
            """Merge scan results into the tree (no clear, no duplicates)."""
            if not hasattr(self, "_devices_by_addr"):
                self._devices_by_addr = {}  # addr -> dict(dev=..., adv=..., last_seen_ms=...)
    
            now_ms = int(time.time() * 1000)
    
            # apply filters consistently with the rest of the app
            addr_prefix, _mtu, _scan_timeout, _rx_timeout, _rec, _sess, name_contains, svc_contains, mfg_id_hex, mfg_data_hex = self._read_runtime_params()
    
            added = 0
            updated = 0
            matched = 0
    
            for (dev, adv) in pairs:
                try:
                    addr = getattr(dev, "address", "") if not isinstance(dev, str) else str(dev)
                    addr = (addr or "").upper()
                except Exception:
                    continue
                if not addr:
                    continue
    
                ok = self._adv_matches(dev, adv, addr_prefix, name_contains, svc_contains, mfg_id_hex, mfg_data_hex)
                
                # Skip devices that don't match filters
                if not ok:
                    continue
                
                matched += 1

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

                mark = "✔"  # All displayed devices match

                prev = self._devices_by_addr.get(addr)
                self._devices_by_addr[addr] = {"dev": dev, "adv": adv, "last_seen_ms": now_ms}

                if prev is None:
                    try:
                        # iid = address => stable mapping (no mismatch)
                        self.devices_tree.insert("", "end", iid=addr, values=(addr, name, rssi, mark))
                        added += 1
                    except Exception:
                        # if iid already exists for some reason, fall back to update
                        try:
                            self.devices_tree.item(addr, values=(addr, name, rssi, mark))
                            updated += 1
                        except Exception:
                            pass
                else:
                    try:
                        self.devices_tree.item(addr, values=(addr, name, rssi, mark))
                        updated += 1
                    except Exception:
                        pass
    
            # Update status with results (don't overwrite selected device details!)
            total = len(self._devices_by_addr)
            if added > 0:
                self.devices_scan_status_var.set(f"\u2713 {total} devices (+{added} new)")
            else:
                self.devices_scan_status_var.set(f"\u2713 {total} devices")
        def _devices_on_select(self, _evt):
            sel = self.devices_tree.selection()
            if not sel:
                return
            addr = sel[0]
            if not hasattr(self, "_devices_by_addr"):
                return
            item = self._devices_by_addr.get(addr)
            if not item:
                return
            dev = item.get("dev")
            adv = item.get("adv")
            txt = self._format_adv_details(dev, adv)
            # Display device details (don't use _devices_set_details to avoid confusion)
            self.devices_detail.configure(state=tk.NORMAL)
            self.devices_detail.delete("1.0", tk.END)
            self.devices_detail.insert("1.0", txt)
            self.devices_detail.configure(state=tk.DISABLED)
        def _devices_set_details(self, txt: str):
            """Legacy method - now only used for initial message. Don't use for stats!"""
            self.devices_detail.configure(state=tk.NORMAL)
            self.devices_detail.delete("1.0", tk.END)
            self.devices_detail.insert("1.0", txt)
            self.devices_detail.configure(state=tk.DISABLED)
    
        def _devices_copy_details(self):
            try:
                txt = self.devices_detail.get("1.0", tk.END)
                self._tk_root.clipboard_clear()
                self._tk_root.clipboard_append(txt)
            except Exception:
                pass
    
        def _format_adv_details(self, device, adv) -> str:
            lines = []
            lines.append("=" * 60)
            lines.append(f"📱 DEVICE INFORMATION")
            lines.append("=" * 60)
            lines.append(f"Address:     {getattr(device, 'address', device)}")
            lines.append(f"Name:        {getattr(device, 'name', '') or '(unnamed)'}")
            
            if adv is None:
                lines.append("No AdvertisingData available.")
                return "\n".join(lines)
    
            lines.append("")
            lines.append("=" * 60)
            lines.append(f"📡 ADVERTISING DATA")
            lines.append("=" * 60)
            lines.append(f"Local name:  {getattr(adv, 'local_name', None) or '(not set)'}")
            lines.append(f"RSSI:        {getattr(adv, 'rssi', None)} dBm")
            
            tx = getattr(adv, 'tx_power', None)
            lines.append(f"TX power:    {tx if tx is not None else '(not advertised)'}")
            
            # Platform data (if any)
            platform = getattr(adv, 'platform_data', None)
            if platform:
                lines.append(f"Platform:    {platform}")
            
            lines.append("")
            
            # Service UUIDs
            su = getattr(adv, "service_uuids", None) or []
            if su:
                lines.append(f"🔧 SERVICE UUIDs ({len(su)}):")
                for u in su:
                    # Try to show short UUID for standard services
                    if len(u) > 8:
                        lines.append(f"  • {u}")
                    else:
                        lines.append(f"  • {u} (short)")
            else:
                lines.append("🔧 SERVICE UUIDs: (none)")
            
            lines.append("")
            
            # Manufacturer data with known IDs
            md = getattr(adv, "manufacturer_data", None) or {}
            if md:
                lines.append(f"🏭 MANUFACTURER DATA ({len(md)} entries):")
                
                # Known manufacturer IDs
                known_mfg = {
                    0x004C: "Apple Inc.",
                    0x0059: "Nordic Semiconductor ASA",
                    0x006A: "Abbott Diabetes Care",
                    0x0075: "Samsung Electronics Co. Ltd.",
                    0x00E0: "Google LLC",
                    0x0087: "Garmin International, Inc.",
                    0x0157: "Huawei Technologies Co., Ltd.",
                }
                
                for k, v in md.items():
                    vv = bytes(v) if not isinstance(v, (bytes, bytearray)) else v
                    mfg_name = known_mfg.get(k, "Unknown")
                    lines.append(f"  • ID: 0x{k:04X} ({mfg_name})")
                    lines.append(f"    Data: {vv.hex().upper()}")
                    lines.append(f"    Len:  {len(vv)} bytes")
            else:
                lines.append("🏭 MANUFACTURER DATA: (none)")
            
            lines.append("")
            
            # Service data
            sd = getattr(adv, "service_data", None) or {}
            if sd:
                lines.append(f"🔐 SERVICE DATA ({len(sd)} entries):")
                for k, v in sd.items():
                    vv = bytes(v) if not isinstance(v, (bytes, bytearray)) else v
                    lines.append(f"  • UUID: {k}")
                    lines.append(f"    Data: {vv.hex().upper()}")
                    lines.append(f"    Len:  {len(vv)} bytes")
            else:
                lines.append("🔐 SERVICE DATA: (none)")
            
            lines.append("")
            lines.append("=" * 60)
            
            return "\n".join(lines)
    
        def _adv_matches(self, dev, adv, addr_prefix: str, name_contains: str, svc_contains: str, mfg_id_hex: str, mfg_data_hex: str) -> bool:
            # Mirrors the filtering used in the BLE loop; safe for missing fields.
            addr_prefix = (addr_prefix or "").strip().upper()
            if addr_prefix:
                addr = (getattr(dev, "address", "") if not isinstance(dev, str) else str(dev)).upper()
                if not addr.startswith(addr_prefix):
                    return False
    
            if not adv:
                # If no adv data, only address prefix can match.
                return True if addr_prefix else False
    
            if name_contains:
                n = (getattr(adv, "local_name", "") or "") + " " + (getattr(dev, "name", "") or "")
                if name_contains.lower() not in n.lower():
                    return False
    
            if svc_contains:
                su = getattr(adv, "service_uuids", None) or []
                if not any(svc_contains.lower() in (u or "").lower() for u in su):
                    return False
    
            mfg_id_hex = (mfg_id_hex or "").strip().lower().replace("0x", "")
            mfg_data_hex = (mfg_data_hex or "").strip().lower().replace("0x", "")
    
            if mfg_id_hex:
                try:
                    want_id = int(mfg_id_hex, 16)
                except ValueError:
                    want_id = None
                if want_id is not None:
                    md = getattr(adv, "manufacturer_data", None) or {}
                    if want_id not in md:
                        return False
                    if mfg_data_hex:
                        sub = "".join(ch for ch in mfg_data_hex if ch in "0123456789abcdef")
                        try:
                            sub_b = bytes.fromhex(sub)
                        except ValueError:
                            sub_b = b""
                        if sub_b:
                            vv = bytes(md[want_id]) if not isinstance(md[want_id], (bytes, bytearray)) else md[want_id]
                            if sub_b not in vv:
                                return False
            else:
                if mfg_data_hex:
                    # if data specified but no id, match any mfg value containing it
                    sub = "".join(ch for ch in mfg_data_hex if ch in "0123456789abcdef")
                    try:
                        sub_b = bytes.fromhex(sub)
                    except ValueError:
                        sub_b = b""
                    if sub_b:
                        md = getattr(adv, "manufacturer_data", None) or {}
                        found = False
                        for _k, v in md.items():
                            vv = bytes(v) if not isinstance(v, (bytes, bytearray)) else v
                            if sub_b in vv:
                                found = True
                                break
                        if not found:
                            return False
    
            return True
    
        def _build_ui(self) -> None:
            """Build a 4-tab UI (Demo / Expert / Devices / Settings) without changing backend logic."""
            nb = ttk.Notebook(self.root)
            nb.pack(fill=tk.BOTH, expand=True)
            self.notebook = nb
    
            demo_tab = tk.Frame(nb, bg=self.colors["bg"])
            expert_tab = tk.Frame(nb, bg=self.colors["bg"])
            devices_tab = tk.Frame(nb, bg=self.colors["bg"])
            settings_tab = tk.Frame(nb, bg=self.colors["bg"])
    
            nb.add(demo_tab, text="Demo")
            nb.add(expert_tab, text="Expert")
            nb.add(devices_tab, text="Devices")
            nb.add(settings_tab, text="Settings")
    
            self._devices_tab_widget = devices_tab
            nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)
    
            self._build_ui_demo(demo_tab)
    
            # Build existing UI inside Expert tab by temporarily swapping self.root.
            tk_root = self._tk_root
            orig_root = self.root
            self.root = expert_tab
            try:
                self._build_ui_expert()
            finally:
                self.root = orig_root
                self._tk_root = tk_root
    
            self._build_ui_devices(devices_tab)
            self._build_ui_settings(settings_tab)
    
        def _demo_update_timeline(self, checklist_update: Dict[str, str]) -> None:
            """Update the Demo timeline dots based on the merged checklist state."""
            # Merge incremental updates
            if checklist_update:
                for k, v in checklist_update.items():
                    if k in self.demo_checklist_state:
                        self.demo_checklist_state[k] = v
    
            # Apply colors
            for key, _title in CHECKLIST_ITEMS:
                state = self.demo_checklist_state.get(key, "pending")
                dot, txt = self.demo_timeline_labels.get(key, (None, None))
                if dot is None or txt is None:
                    continue
    
                if state == "done":
                    fg = self.colors.get("ok", self.colors["accent_alt"])
                    tfg = self.colors["text"]
                elif state == "in_progress":
                    fg = self.colors["accent_alt"]
                    tfg = self.colors["text"]
                else:
                    fg = self.colors["muted"]
                    tfg = self.colors["muted"]
    
                dot.configure(fg=fg)
                txt.configure(fg=tfg)
    
        def _demo_extract_key_metrics(self, rx_text: str) -> Dict[str, str]:
            """Best-effort extraction of a few key metrics from protobuf text output."""
            if not rx_text:
                return {}
    
            # Remove HEX and EXPORT lines
            lines = []
            for ln in (rx_text or "").splitlines():
                if ln.startswith("HEX:") or ln.startswith("EXPORT"):
                    continue
                lines.append(ln)
            s = "\n".join(lines)
    
            def _find_after(token: str) -> Optional[str]:
                # Find token, then look ahead for the first numeric value in the next ~10 lines
                m = re.search(re.escape(token), s)
                if not m:
                    return None
                tail = s[m.end():]
                tail_lines = tail.splitlines()[:10]
                tail2 = "\n".join(tail_lines)
                m2 = re.search(r"([-+]?\d+(?:\.\d+)?)", tail2)
                return m2.group(1) if m2 else None
    
            out = {}
            # These tokens are based on Common_pb2 enum names as they appear in text_format output.
            temp = _find_after("ENVIROMENTAL_TEMPERATURE_CURRENT")
            hum = _find_after("ENVIROMENTAL_HUMIDITY_CURRENT")
            volt = _find_after("VOLTAGE_CURRENT")
            if temp is not None:
                out["Temperature"] = f"{temp}"
            if hum is not None:
                out["Humidity"] = f"{hum}"
            if volt is not None:
                out["Voltage"] = f"{volt}"
            return out
    
        def _demo_set_kpis_from_rx_text(self, rx_text: str, export_info: Optional[dict]) -> None:
            """Update Demo KPIs (Overall/Waveform) based on the latest received message text."""
            if not rx_text:
                return
            # Identify message type
            msg_type = ""
            m = re.search(r"^TYPE:\s*([^\n]+)", rx_text.strip(), flags=re.MULTILINE)
            if m:
                msg_type = m.group(1).strip()
    
            # Waveform KPI: prefer export_info when available
            if export_info:
                # If samples were exported we consider waveform OK
                if export_info.get("samples") or export_info.get("raw") or export_info.get("index"):
                    # Estimate points (int16, 128 bytes per block => 64 points/block)
                    try:
                        count = int(export_info.get("count") or 0)
                    except Exception:
                        count = 0
                    pts = count * 64 if count else 4096
                    self.demo_waveform_var.set(f"OK ({pts} points)")
                    # keep export path for expert use only
                    path = export_info.get("samples") or export_info.get("index") or export_info.get("raw") or ""
                    self.demo_export_var.set(path)
    
        def _demo_render_summary(self, rx_text: str, overall_values: Optional[list] = None) -> None:
            """Render the Demo 'Overalls' panel.
    
            Design goals:
            - readable (no protobuf dumps)
            - stable (driven by structured overall_values when available)
            - raw values (no unit conversions)
            """
            if self.demo_summary is None:
                return
    
            items = overall_values or []
    
            # Header (use local time for human feedback)
            now_s = time.strftime("%H:%M:%S")
            header = f"Last update: {now_s}   •   Metrics: {len(items) if items else 0}\n\n"
    
            # Build compact lines: left label column + raw value column
            lines = []
            if items:
                # Stable sorting by label; keep original order for identical labels
                def _key(it):
                    try:
                        return (str(it.get("label", "")).strip().lower(),)
                    except Exception:
                        return ("",)
    
                for it in sorted(items, key=_key):
                    try:
                        lbl = str(it.get("label", "")).strip() or "Value"
                        val = str(it.get("value", "")).strip() or "•"
                    except Exception:
                        lbl, val = "Value", "•"
                    # Keep it compact: avoid multi-line values in the list view
                    val = " ".join(val.split())
                    lines.append(f"{lbl:<28} {val}")
                    det = str(it.get("details", "") or "").rstrip()
                    if det:
                        lines.append(det)
            else:
                # Fallback: show only message type if available (kept minimal)
                msg_type = ""
                try:
                    mm = re.search(r"^TYPE:\s*([^\n]+)", (rx_text or "").strip(), flags=re.MULTILINE)
                    msg_type = mm.group(1).strip() if mm else ""
                except Exception:
                    msg_type = ""
                lines.append("•")
                if msg_type:
                    lines.append(f"(last message: {msg_type})")
    
            self.demo_summary.configure(state=tk.NORMAL)
            self.demo_summary.delete("1.0", tk.END)
    
            # Use a monospaced feel for alignment if available
            try:
                self.demo_summary.configure(font=("Consolas", 10))
            except Exception:
                pass
    
            self.demo_summary.insert(tk.END, header)
            self.demo_summary.insert(tk.END, "\n".join(lines) + "\n")
            self.demo_summary.configure(state=tk.DISABLED)
    
        
        def _demo_render_summary_combined(self) -> None:
            """Render Demo summary with two sections: Overall values + Waveform info (if available)."""
            if self.demo_summary is None:
                return
    
            overall_values = self.demo_last_overall_values or []
            overall_txt = self.demo_last_overall_rx_text or ""
            wave_txt = self.demo_last_wave_rx_text or ""
    
            total_block = None
            if wave_txt:
                m2 = re.search(r"\btotal_block:\s*(\d+)", wave_txt)
                if m2:
                    try:
                        total_block = int(m2.group(1))
                    except Exception:
                        total_block = None
    
            self.demo_summary.configure(state=tk.NORMAL)
            self.demo_summary.delete("1.0", tk.END)
    
            self.demo_summary.insert(tk.END, "Overall\n", ("h",))
            if overall_values:
                self.demo_summary.insert(tk.END, f"{len(overall_values)} values\n", ("v",))
                for item in overall_values:
                    try:
                        lbl = str(item.get("label", "")).strip()
                        val = str(item.get("value", "")).strip()
                    except Exception:
                        lbl, val = "", ""
                    if not lbl:
                        lbl = "Value"
                    if not val:
                        val = "•"
                    self.demo_summary.insert(tk.END, f"• {lbl}: ", ("k",))
                    self.demo_summary.insert(tk.END, f"{val}\n", ("v",))
            else:
                if overall_txt:
                    pairs = len(re.findall(r"\bdata_pair\s*\{", overall_txt))
                    self.demo_summary.insert(tk.END, f"{pairs} pairs\n", ("v",))
                else:
                    self.demo_summary.insert(tk.END, "•\n", ("v",))
    
            self.demo_summary.insert(tk.END, "\nWaveform\n", ("h",))
            if wave_txt:
                blocks = total_block if total_block is not None else "?"
                pts = (total_block * 64) if isinstance(total_block, int) else "?"
                self.demo_summary.insert(tk.END, "Blocks: ", ("k",))
                self.demo_summary.insert(tk.END, f"{blocks}\n", ("v",))
                self.demo_summary.insert(tk.END, "Points: ", ("k",))
                self.demo_summary.insert(tk.END, f"{pts} (int16)\n", ("v",))
            else:
                self.demo_summary.insert(tk.END, "•\n", ("v",))
    
            self.demo_summary.configure(state=tk.DISABLED)
    
        def _build_ui_expert(self) -> None:
    
            # Header (same layout as Demo)
            _card, self.start_button, self.stop_auto_button = self._ui_build_run_header_card(self.root)
            self._update_demo_run_controls()
    
            # Filters (keep only the essentials here; other runtime settings live in the Settings tab)
            filter_box = tk.Frame(self.root, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            filter_box.pack(fill=tk.X, padx=16, pady=(0, 8))
            filter_in = tk.Frame(filter_box, bg=self.colors["panel"])
            filter_in.pack(fill=tk.X, padx=14, pady=10)
    
            tk.Label(
                filter_in,
                text="Filters",
                bg=self.colors["panel"],
                fg=self.colors["muted"],
                font=("Segoe UI", 9, "bold"),
            ).pack(anchor="w")
    
            form = tk.Frame(filter_in, bg=self.colors["panel"])
            form.pack(fill=tk.X, pady=(6, 0))
    
            # Optional advertising filters (leave empty to disable)
            self._build_field(form, "Address prefix", self.address_prefix_var)
            self._build_field(form, "ADV name contains", self.adv_name_contains_var)
    
            manual = tk.Frame(self.root, bg=self.colors["bg"])
            manual.pack(fill=tk.X, padx=16, pady=(8, 0))
    
            tk.Label(
                manual,
                text="Manual commands:",
                bg=self.colors["bg"],
                fg=self.colors["muted"],
                font=("Segoe UI", 9, "bold"),
            ).pack(anchor="w", pady=(0, 6))
    
            manual_btns = tk.Frame(manual, bg=self.colors["bg"])
            manual_btns.pack(fill=tk.X)
    
            # Line 1: main manual actions (wrap responsive)
            buttons = []
            for text_, action_ in MANUAL_ACTIONS:
                buttons.append(ttk.Button(manual_btns, text=text_, command=lambda a=action_: self._start_manual_action(a)))
            self._wrap_buttons(manual_btns, buttons)
    
            # Line 2: utilities (separate row)
            util = tk.Frame(manual, bg=self.colors["bg"])
            util.pack(fill=tk.X, pady=(8, 0))
    
            util_btns = [
                ttk.Button(util, text="Clear logs", command=self._clear_tiles),
                ttk.Button(util, text="Plot Latest", command=self._plot_latest_waveform),
            ]
            self._wrap_buttons(util, util_btns, min_btn_px=160)
    
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
    
        def _wrap_buttons(self, container: tk.Frame, buttons: list, min_btn_px: int = 140) -> None:
            """Lay out a list of ttk.Button into a responsive grid that wraps with window width."""
            state = {"cols": 0}
    
            def _relayout(_evt=None) -> None:
                try:
                    w = int(container.winfo_width())
                except Exception:
                    w = 0
                cols = max(1, w // max(1, int(min_btn_px)))
                if cols == state["cols"]:
                    return
                state["cols"] = cols
    
                for child in container.winfo_children():
                    child.grid_forget()
    
                for i, btn in enumerate(buttons):
                    r = i // cols
                    c = i % cols
                    btn.grid(row=r, column=c, padx=(0, 8), pady=(0, 8), sticky="w")
    
                for c in range(cols):
                    try:
                        container.grid_columnconfigure(c, weight=1)
                    except Exception:
                        pass
    
            container.bind("<Configure>", _relayout)
            # First layout after Tk has computed sizes
            self.root.after(0, _relayout)
    
        def _build_field(self, parent: tk.Frame, label: str, variable: tk.StringVar, width: int = 16) -> None:
            parent_bg = parent.cget("bg") if hasattr(parent, "cget") else self.colors["bg"]
            row = tk.Frame(parent, bg=parent_bg)
            row.pack(side=tk.LEFT, padx=(0, 12))
            tk.Label(row, text=label, bg=parent_bg, fg=self.colors["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
            entry = ttk.Entry(row, textvariable=variable, width=width)
            entry.pack(anchor="w")
    
        def _on_mouse_wheel(self, event: tk.Event) -> None:
            if not self.canvas.winfo_exists():
                return
            if event.delta == 0:
                return
            direction = -1 if event.delta > 0 else 1
            self.canvas.yview_scroll(direction, "units")
    
        def _parse_int_var(self, var: tk.StringVar, default: int) -> int:
            try:
                return int(var.get())
            except ValueError:
                return default
    
        def _parse_float_var(self, var: tk.StringVar, default: float) -> float:
            try:
                return float(var.get())
            except ValueError:
                return default
    
        def _read_runtime_params(self) -> tuple:
            address_prefix = self.address_prefix_var.get().strip()
            mtu = self._parse_int_var(self.mtu_var, 247)
            scan_timeout = self._parse_float_var(self.scan_timeout_var, 6.0)
            rx_timeout = self._parse_float_var(self.rx_timeout_var, 5.0)
            record_sessions = bool(self.record_sessions_var.get())
            session_root = self.session_root_var.get().strip() or "sessions"
            name_contains = self.adv_name_contains_var.get().strip()
            service_uuid_contains = self.adv_service_uuid_contains_var.get().strip()
            mfg_id_hex = self.adv_mfg_id_hex_var.get().strip()
            mfg_data_hex_contains = self.adv_mfg_data_hex_contains_var.get().strip()
            return address_prefix, mtu, scan_timeout, rx_timeout, record_sessions, session_root, name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains
    
        def _safe_destroy(self, widget) -> None:
            if widget is None:
                return
            try:
                widget.destroy()
            except Exception:
                pass
    
        def _clear_tiles(self) -> None:
            self._stop_auto()
            for tile in list(self.tiles.values()):
                self._safe_destroy(tile.get("card"))
            self.tiles.clear()
            self.tile_export_info.clear()
            self.latest_export_info = None
            self.latest_overall_values = None
            self.tile_counter = 0
    
        def _reset_auto_state(self, increment_generation: bool = True) -> None:
            self.auto_run = False
            if increment_generation:
                self._auto_generation += 1
            self._auto_cycle_running = False
            self._auto_active_tile_id = None
    
    
        def _update_demo_run_controls(self) -> None:
            """
            Update Demo Start/Stop controls and explicit run indicators.
            Notes:
            - "Stop" stops auto-restart immediately, but the currently running BLE cycle
              is not forcibly cancelled (it will finish and then auto_run stays OFF).
            """
            auto = bool(getattr(self, "auto_run", False))
            running = bool(getattr(self, "_auto_cycle_running", False))
    
            if auto and running:
                cycle = "RUNNING"
            elif auto and (not running):
                cycle = "WAITING"
            elif (not auto) and running:
                cycle = "STOPPING"
            else:
                cycle = "IDLE"
    
            try:
                self.demo_auto_state_var.set("AUTO: ON" if auto else "AUTO: OFF")
                self.demo_cycle_state_var.set(f"CYCLE: {cycle}")
            except Exception:
                pass
    
            # Button enable/disable
            try:
                if hasattr(self, "demo_start_button") and self.demo_start_button is not None:
                    self.demo_start_button.configure(state=("disabled" if auto else "normal"))
            except Exception:
                pass
    
            try:
                if hasattr(self, "demo_stop_button") and self.demo_stop_button is not None:
                    # Allow stop while auto is ON, or while a cycle is still running (stopping)
                    enable_stop = auto or running
                    self.demo_stop_button.configure(state=("normal" if enable_stop else "disabled"))
                    # Clarify semantics when a cycle is active
                    if running:
                        self.demo_stop_button.configure(text="Stop (after cycle)")
                    else:
                        self.demo_stop_button.configure(text="Stop")
            except Exception:
                pass
        def _new_tile_for_run(self) -> int:
            self.tile_counter += 1
            tile_id = self.tile_counter
            self._create_tile(tile_id)
            return tile_id
    
        def _start_worker_cycle(self, tile_id: int, action: str = None) -> None:
            address_prefix, mtu, scan_timeout, rx_timeout, record_sessions, session_root, name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains = self._read_runtime_params()
            if action is None:
                self.worker.run_cycle(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, record_sessions, session_root, name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains)
            else:
                self.worker.run_manual_action(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, action, record_sessions, session_root, name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains)
    
        def _on_start(self) -> None:
            self._reset_auto_state()
            # Clear any previous hard-stop request
            try:
                self.worker.clear_cancel_all()
            except Exception:
                pass
            self.auto_run = True
            self._update_demo_run_controls()
            self._start_cycle(expected_generation=self._auto_generation)
    
        def _start_cycle(self, expected_generation: int = None) -> None:
            if not self.auto_run:
                return
            if expected_generation is not None and expected_generation != self._auto_generation:
                return
            if self._auto_cycle_running:
                return
            self._auto_cycle_running = True
            self._update_demo_run_controls()
            tile_id = self._new_tile_for_run()
            self._auto_active_tile_id = tile_id
            self._start_worker_cycle(tile_id)
    
        def _start_manual_action(self, action: str) -> None:
            self._reset_auto_state()
            self._update_demo_run_controls()
            tile_id = self._new_tile_for_run()
            self._start_worker_cycle(tile_id, action=action)
    
        def _stop_auto(self) -> None:
            self._reset_auto_state()
            # Hard-stop: cancel any in-flight scan/connect/download
            try:
                self.worker.request_cancel_all()
            except Exception:
                pass
            try:
                self.demo_status_var.set("Idle")
            except Exception:
                pass
            self._update_demo_run_controls()
    
        def _schedule_next_auto(self, generation: int) -> None:
            def _cb() -> None:
                self._start_cycle(expected_generation=generation)
            self.root.after(AUTO_RESTART_DELAY_MS, _cb)
    
        
        def _format_overalls_compact(self, overall_values: Optional[list], max_lines: int = 6) -> str:
            """Return a compact multi-line string for overall values (raw)."""
            if not overall_values:
                return "(no overalls)"
            rows = []
            try:
                for it in overall_values:
                    lbl = str((it or {}).get("label", "") or "Metric")
                    val = str((it or {}).get("value", "") or "•")
                    rows.append((lbl, val))
            except Exception:
                return "(overalls parse error)"
            # stable sort by label for readability
            rows.sort(key=lambda x: x[0].lower())
            if max_lines > 0 and len(rows) > max_lines:
                shown = rows[:max_lines]
                more = len(rows) - max_lines
            else:
                shown = rows
                more = 0
            w = max((len(a) for a, _b in shown), default=0)
            w = min(max(w, 10), 28)
            lines = [f"{a[:w]:<{w}}  {b}" for a, b in shown]
            if more:
                lines.append(f"(+{more} more)")
            return "\n".join(lines)
    
        def _format_export_compact(self, export_info: Optional[dict]) -> str:
            """Return a compact export summary for Expert tiles."""
            if not export_info:
                return "Export: •"
            raw = export_info.get("raw") if isinstance(export_info, dict) else None
            idx = export_info.get("index") if isinstance(export_info, dict) else None
            cnt = export_info.get("count") if isinstance(export_info, dict) else None
            parts = []
            if raw:
                parts.append(f"- raw: {raw}")
            if idx:
                parts.append(f"- index: {idx}")
            if cnt not in (None, ""):
                parts.append(f"- blocks: {cnt}")
            return "Export:\n" + ("\n".join(parts) if parts else "•")
    
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
    
            address_label = tk.Label(body, text="Address: •", bg=self.colors["panel"], fg=self.colors["muted"])
            address_label.pack(anchor="w")
    
            session_label = tk.Label(body, text="Session: •", bg=self.colors["panel"], fg=self.colors["muted"])
            session_label.pack(anchor="w")
    
            checklist_frame = tk.Frame(body, bg=self.colors["panel"])
            checklist_frame.pack(anchor="w", pady=(6, 2))
    
            checklist_items = CHECKLIST_ITEMS
            checklist_labels: Dict[str, tk.Label] = {}
            checklist_titles: Dict[str, str] = {}
            for key, title in checklist_items:
                label = tk.Label(checklist_frame, text=f"☐ {title}", bg=self.colors["panel"], fg=self.colors["muted"])
                label.pack(anchor="w")
                checklist_labels[key] = label
                checklist_titles[key] = title
    
    
            # Compact summary (similar to Demo)
            overall_label = tk.Label(body, text="Overalls: •", bg=self.colors["panel"], fg=self.colors["text"], justify="left", font=("Consolas", 9))
            overall_label.pack(anchor="w", pady=(6, 0))
    
            waveform_label = tk.Label(body, text="Waveform: •", bg=self.colors["panel"], fg=self.colors["muted"], justify="left")
            waveform_label.pack(anchor="w", pady=(4, 0))
    
            export_label = tk.Label(body, text="Export: •", bg=self.colors["panel"], fg=self.colors["muted"], justify="left", wraplength=720)
            export_label.pack(anchor="w", pady=(4, 0))
    
            plot_btn = ttk.Button(body, text="Plot export", command=lambda tid=tile_id: self._plot_tile_waveform(tid))
            plot_btn.pack(anchor="w", pady=(6, 0))
    
            self.tiles[tile_id] = {
                "card": card,
                "status": status_label,
                "address": address_label,
                "session": session_label,
                "overall": overall_label,
                "waveform": waveform_label,
                "export": export_label,
                "checklist": checklist_labels,
                "checklist_titles": checklist_titles,
                "plot_btn": plot_btn,
            }
    
    
        def _plot_export_info(self, export_info: Optional[dict], title: str, empty_msg: str) -> None:
            if not export_info:
                messagebox.showinfo("Waveform plot", empty_msg)
                return
            self._plot_waveform_from_export(export_info, title=title)
    
        def _plot_tile_waveform(self, tile_id: int) -> None:
            self._plot_export_info(
                self.tile_export_info.get(tile_id),
                title=f"Tile {tile_id}",
                empty_msg=f"No export available yet for tile {tile_id}.",
            )
    
        def _plot_latest_waveform(self) -> None:
            self._plot_export_info(
                self.latest_export_info,
                title="Latest waveform export",
                empty_msg="No waveform export available yet.",
            )
    
    
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
                    y, meta = WaveformExportTools.extract_true_waveform_samples(raw_path)
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
    
        def _handle_ui_event(self, event) -> None:
            kind = event[0]
            if kind == "tile_update":
                _, tile_id, payload = event
                self._apply_tile_update(tile_id, payload)
                return
            if kind == "cycle_done":
                _, done_tile_id = event
                if done_tile_id == self._auto_active_tile_id:
                    self._auto_cycle_running = False
                    self._auto_active_tile_id = None
                    self._update_demo_run_controls()
                    if self.auto_run:
                        self._schedule_next_auto(self._auto_generation)
    
        def _on_tab_changed(self, _evt=None):
            """Start/stop Devices autoscan based on selected tab."""
            try:
                sel = self.notebook.select()
                w = self.notebook.nametowidget(sel)
            except Exception:
                w = None
    
            if w is not None and w == getattr(self, "_devices_tab_widget", None):
                self._devices_autoscan_start()
            else:
                self._devices_autoscan_stop()
    
        def _devices_autoscan_start(self):
            if getattr(self, "_devices_autoscan_job", None) is not None:
                return
            # Kick one scan immediately, then every interval
            self._devices_scan()
            self._devices_autoscan_job = self.root.after(self._devices_autoscan_interval_ms, self._devices_autoscan_tick)
    
        def _devices_autoscan_stop(self):
            job = getattr(self, "_devices_autoscan_job", None)
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
            self._devices_autoscan_job = None
    
        def _devices_autoscan_tick(self):
            self._devices_autoscan_job = None
            # Only scan if we're still on Devices tab
            try:
                sel = self.notebook.select()
                w = self.notebook.nametowidget(sel)
                if w != getattr(self, "_devices_tab_widget", None):
                    return
            except Exception:
                return
            self._devices_scan()
            self._devices_autoscan_job = self.root.after(self._devices_autoscan_interval_ms, self._devices_autoscan_tick)
    
        def _poll_queue(self) -> None:
            try:
                while True:
                    event = self.ui_queue.get_nowait()
                    self._handle_ui_event(event)
                    self.ui_queue.task_done()
            except Empty:
                pass
            self.root.after(UI_POLL_INTERVAL_MS, self._poll_queue)
    
        
        def _apply_tile_update(self, tile_id: int, payload: Dict[str, str]) -> None:
    
            # Surface structured errors in Demo Debug
            try:
                err = payload.get("error")
            except Exception:
                err = None
            if err:
                self._log("ERR", f"tile{tile_id}: {err.get('where','?')} {err.get('type','')} {err.get('msg','')}")
            tile = self.tiles.get(tile_id)
            if not tile:
                return
    
            # --- Update structured state first (never derive logic from rx_text) ---
            st = self.tile_state.get(tile_id)
            if st is None:
                st = TileState(checklist={key: "pending" for key, _t in CHECKLIST_ITEMS})
                self.tile_state[tile_id] = st
    
            if "status" in payload:
                st.status = payload.get("status", "") or st.status
            if "phase" in payload:
                st.phase = payload.get("phase", st.phase) or st.phase
            if "address" in payload:
                st.address = payload.get("address", st.address) or st.address
            if "session_dir" in payload:
                st.session_dir = payload.get("session_dir", st.session_dir) or st.session_dir
            if "rx_text" in payload:
                st.rx_text = payload.get("rx_text", st.rx_text) or st.rx_text
            if "overall_values" in payload and payload.get("overall_values") is not None:
                st.overall_values = payload.get("overall_values")
                self.latest_overall_values = st.overall_values
            if "export_info" in payload and payload.get("export_info"):
                st.export_info = payload.get("export_info")
                self.tile_export_info[tile_id] = st.export_info
                self.latest_export_info = st.export_info
                try:
                    st.last_export_raw = (st.export_info or {}).get("raw") or st.last_export_raw
                except Exception:
                    pass
            if "checklist" in payload:
                try:
                    for k, v in (payload.get("checklist") or {}).items():
                        st.checklist[k] = v
                except Exception:
                    pass
    
            # --- Update Expert tile widgets ---
            if "status" in payload:
                tile["status"].configure(text=payload["status"])
            if "address" in payload:
                tile["address"].configure(text=f"Address: {payload['address']}")
            if "session_dir" in payload:
                tile["session"].configure(text=f"Session: {payload['session_dir']}")
    
            # Always refresh compact summary when new data arrives
            try:
                ov_txt = self._format_overalls_compact(st.overall_values, max_lines=8)
                tile["overall"].configure(text=ov_txt)
            except Exception:
                pass
            try:
                # waveform KPI: show whether export is present
                if st.export_info and (st.export_info.get("raw") or st.export_info.get("index")):
                    tile["waveform"].configure(text="Waveform: OK")
                else:
                    tile["waveform"].configure(text="Waveform: •")
            except Exception:
                pass
            try:
                tile["export"].configure(text=self._format_export_compact(st.export_info))
            except Exception:
                pass
    
            if "checklist" in payload:
                labels = tile.get("checklist", {})
                titles = tile.get("checklist_titles", {})
                for key, state in (payload.get("checklist") or {}).items():
                    label = labels.get(key)
                    title = titles.get(key, key)
                    if label:
                        symbol = CHECKLIST_STATE_MAP.get(state, "☐")
                        label.configure(text=f"{symbol} {title}")
    
    
            # --- Demo mirror: mirror ONE active tile (structured payload only) ---
            # We keep showing the last connected tile while the next scan runs.
            # Switch the Demo mirror to a new tile only when it starts connecting / becomes connected.
            active_demo_tile = getattr(self, "_demo_mirrored_tile_id", None)
            if active_demo_tile is None:
                active_demo_tile = tile_id
                self._demo_mirrored_tile_id = tile_id
    
            if tile_id != active_demo_tile:
                status_txt = (st.status or "").lower()
                checklist = st.checklist or {}
                is_connected = (checklist.get("connected") == "done") or (checklist.get("waiting_connection") == "done")
                phase = (st.phase or "").lower()
                is_connecting = (phase == "connecting") or ("connecting" in status_txt)
                if is_connected or is_connecting:
                    # Switch Demo to this new tile and reset panels at connection start.
                    self._demo_mirrored_tile_id = tile_id
                    active_demo_tile = tile_id
                    try:
                        self.demo_last_overall_values = None
                        self.demo_overall_var.set("•")
                        self.demo_waveform_var.set("•")
                        self.demo_export_var.set("")
                        self._demo_last_plotted_raw = None
                        if self.demo_plot_label is not None:
                            self.demo_plot_label.configure(text="(waiting for waveform...)")
                        if self.demo_plot_canvas is not None and self.demo_plot_fig is not None:
                            ax = self.demo_plot_fig.axes[0] if self.demo_plot_fig.axes else self.demo_plot_fig.add_subplot(111)
                            ax.clear()
                            ax.set_title("Waveform (latest)")
                            ax.set_xlabel("Sample")
                            ax.set_ylabel("Amplitude (int16)")
                            ax.grid(True, alpha=0.2)
                            self.demo_plot_canvas.draw()
                    except Exception:
                        pass
    
            # If this update is not for the active Demo tile, do not overwrite Demo UI.
            if tile_id != active_demo_tile:
                # Keep overall/waveform from the last connected tile, but reflect current activity
                # (Scanning/Connecting/Disconnected) so the Demo doesn't look "stuck".
                try:
                    self.demo_status_var.set(st.status or "")
                    name_txt = tile.get("name").cget("text") if tile.get("name") else ""
                    addr_txt = tile.get("address").cget("text") if tile.get("address") else ""
                    self.demo_device_var.set((name_txt + " " + addr_txt).strip())
                    if st.checklist:
                        self._demo_update_timeline(st.checklist)
                except Exception:
                    pass
                return
    
            try:
                self.demo_status_var.set(st.status or "")
                # device label uses the tile's rendered labels
                name_txt = tile.get("name").cget("text") if tile.get("name") else ""
                addr_txt = tile.get("address").cget("text") if tile.get("address") else ""
                self.demo_device_var.set((name_txt + " " + addr_txt).strip())
    
                # timeline
                if st.checklist:
                    self._demo_update_timeline(st.checklist)
    
                # KPIs driven by structured info + rx_text only for display
                self._demo_set_kpis_from_rx_text(st.rx_text or "", st.export_info if st.export_info else None)
    
                # Overalls: driven only by structured overall_values
                if st.overall_values is not None:
                    self.demo_last_overall_values = st.overall_values
                    try:
                        n = len(self.demo_last_overall_values) if self.demo_last_overall_values is not None else 0
                        self.demo_overall_var.set(f"{n} metrics" if n > 0 else "•")
                    except Exception:
                        self.demo_overall_var.set("•")
    
                # Waveform: plot from export_info (raw preferred), once per new raw file.
                if st.export_info and isinstance(st.export_info, dict):
                    raw_path = st.export_info.get("raw")
                    samples_path = st.export_info.get("samples")
                    if raw_path and raw_path != self._demo_last_plotted_raw:
                        self._demo_last_plotted_raw = raw_path
                        try:
                            self.demo_plot_label.config(text="Rendering waveform...")
                            self._demo_plot_waveform_from_raw_export(raw_path)
                            self.demo_waveform_var.set("Waveform received")
                        except Exception as e:
                            self.demo_plot_label.config(text=f"(plot error: {type(e).__name__})")
                            try:
                                self._log("ERROR", f"Waveform plot failed: {e}")
                            except Exception:
                                pass
                    elif (not raw_path) and samples_path:
                        # fallback
                        try:
                            self.demo_plot_label.config(text="Rendering waveform (samples)...")
                            self._demo_plot_waveform_from_samples(samples_path)
                            self.demo_waveform_var.set("Waveform received")
                        except Exception as e:
                            self.demo_plot_label.config(text=f"(plot error: {type(e).__name__})")
                            try:
                                self._log("ERROR", f"Waveform plot (samples) failed: {e}")
                            except Exception:
                                pass
    
                # Summary: show overall values + last RX text (human readable)
                self._demo_render_summary(st.rx_text or "", st.overall_values)
    
            except Exception as e:
                try:
                    self._log("ERROR", f"Demo mirror update failed: {type(e).__name__}: {e}")
                except Exception:
                    pass
    
        def _on_dump_adv(self) -> None:
            """Scan and display advertising data in a readable window."""
            # Disable button while scanning
            try:
                self.dump_adv_button.configure(state="disabled")
            except Exception:
                pass
    
            address_prefix, _mtu, scan_timeout, _rx_timeout, _record_sessions, _session_root, name_contains, svc_contains, mfg_id_hex, mfg_data_hex = self._read_runtime_params()
    
            # Normalize filters
            addr_prefix = (address_prefix or "").strip().upper()
            name_contains = (name_contains or "").strip()
            svc_contains = (svc_contains or "").strip().lower()
    
            mfg_id = None
            mfg_id_hex = (mfg_id_hex or "").strip().lower()
            if mfg_id_hex:
                mfg_id_hex = mfg_id_hex.replace("0x", "")
                try:
                    mfg_id = int(mfg_id_hex, 16)
                except ValueError:
                    mfg_id = None
    
            mfg_data_sub = b""
            mfg_data_hex = (mfg_data_hex or "").strip().lower().replace("0x", "")
            if mfg_data_hex:
                mfg_data_hex = "".join(ch for ch in mfg_data_hex if ch in "0123456789abcdef")
                try:
                    mfg_data_sub = bytes.fromhex(mfg_data_hex)
                except ValueError:
                    mfg_data_sub = b""
    
            # Create window immediately
            win = tk.Toplevel(self._tk_root)
            win.title("Advertising dump")
            win.geometry("980x700")
            win.configure(bg=self.colors["bg"])
    
            header = tk.Frame(win, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            header.pack(fill=tk.X, padx=12, pady=12)
    
            tk.Label(header, text="Advertising dump", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
            tk.Label(header, text="Scan running...").pack(anchor="w", padx=12, pady=(0, 10))
    
            body = tk.Frame(win, bg=self.colors["bg"])
            body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
    
            text = tk.Text(body, wrap="none", bg=self.colors["panel_alt"], fg=self.colors["text"], insertbackground=self.colors["text"])
            text.pack(fill=tk.BOTH, expand=True)
    
            btns = tk.Frame(win, bg=self.colors["bg"])
            btns.pack(fill=tk.X, padx=12, pady=(0, 12))
    
            def _copy():
                try:
                    data = text.get("1.0", tk.END)
                    self.root.clipboard_clear()
                    self.root.clipboard_append(data)
                except Exception:
                    pass
    
            ttk.Button(btns, text="Copy", command=_copy).pack(side=tk.LEFT)
    
            async def _scan_adv():
                from bleak import BleakScanner
                res = await BleakScanner.discover(timeout=scan_timeout, return_adv=True)
                pairs = []
                if isinstance(res, dict):
                    for _addr, val in res.items():
                        if isinstance(val, tuple) and len(val) == 2:
                            dev, adv = val
                        else:
                            dev, adv = val, None
                        pairs.append((dev, adv))
                elif isinstance(res, list):
                    for item in res:
                        if isinstance(item, tuple) and len(item) == 2:
                            dev, adv = item
                        else:
                            dev, adv = item, None
                        pairs.append((dev, adv))
                return pairs
    
            def _matches(dev, adv) -> bool:
                # Address prefix
                addr = ""
                if isinstance(dev, str):
                    addr = dev
                else:
                    addr = getattr(dev, "address", "") or ""
                addr_u = addr.upper()
                if addr_prefix and not addr_u.startswith(addr_prefix):
                    return False
    
                # Name contains
                if name_contains:
                    n1 = (getattr(dev, "name", "") or "") if not isinstance(dev, str) else ""
                    n2 = (getattr(adv, "local_name", "") or "") if adv is not None else ""
                    combo = (n1 + " " + n2).lower()
                    if name_contains.lower() not in combo:
                        return False
    
                # Service UUID contains
                if svc_contains:
                    uus = []
                    if adv is not None and getattr(adv, "service_uuids", None):
                        uus = list(getattr(adv, "service_uuids", []) or [])
                    joined = " ".join(u.lower() for u in uus)
                    if svc_contains not in joined:
                        return False
    
                # Manufacturer data filters
                if mfg_id is not None or mfg_data_sub:
                    md = getattr(adv, "manufacturer_data", None) if adv is not None else None
                    md = md or {}
                    if mfg_id is not None:
                        if mfg_id not in md:
                            return False
                        if mfg_data_sub:
                            payload = bytes(md.get(mfg_id, b"")) if md.get(mfg_id) is not None else b""
                            if mfg_data_sub not in payload:
                                return False
                    else:
                        # mfg id not specified: match any payload containing substring
                        if mfg_data_sub:
                            ok = False
                            for _k, _v in md.items():
                                payload = bytes(_v) if _v is not None else b""
                                if mfg_data_sub in payload:
                                    ok = True
                                    break
                            if not ok:
                                return False
    
                return True
    
            def _render(pairs):
                # Sort by RSSI when available
                def rssi_of(item):
                    _dev, _adv = item
                    r = getattr(_adv, "rssi", None) if _adv is not None else None
                    return r if isinstance(r, int) else -999
                pairs2 = [p for p in pairs if _matches(p[0], p[1])]
                pairs2.sort(key=rssi_of, reverse=True)
    
                lines = []
                lines.append(f"Filters: addr_prefix={addr_prefix or '-'} name_contains={name_contains or '-'} svc_contains={svc_contains or '-'} mfg_id={('0x%04X'%mfg_id) if mfg_id is not None else '-'} mfg_data_sub={(mfg_data_sub.hex() if mfg_data_sub else '-')}")
                lines.append("")
    
                for dev, adv in pairs2:
                    if isinstance(dev, str):
                        addr = dev
                        name = "<?>"
                    else:
                        addr = getattr(dev, "address", "") or ""
                        name = getattr(dev, "name", "") or "<?>"
    
                    local_name = getattr(adv, "local_name", None) if adv is not None else None
                    rssi = getattr(adv, "rssi", None) if adv is not None else None
                    tx = getattr(adv, "tx_power", None) if adv is not None else None
                    svcs = getattr(adv, "service_uuids", None) if adv is not None else None
                    svcs = svcs or []
                    md = getattr(adv, "manufacturer_data", None) if adv is not None else None
                    md = md or {}
                    sd = getattr(adv, "service_data", None) if adv is not None else None
                    sd = sd or {}
    
                    lines.append("=" * 72)
                    lines.append(f"Address: {addr}")
                    lines.append(f"Name   : {name}")
                    if local_name:
                        lines.append(f"Local  : {local_name}")
                    lines.append(f"RSSI   : {rssi}")
                    lines.append(f"TX Pwr : {tx}")
                    if svcs:
                        lines.append("Service UUIDs:")
                        for u in svcs:
                            lines.append(f"  - {u}")
                    if md:
                        lines.append("Manufacturer data:")
                        for k, v in md.items():
                            payload = bytes(v) if v is not None else b""
                            lines.append(f"  - 0x{k:04X}: {payload.hex()}")
                    if sd:
                        lines.append("Service data:")
                        for k, v in sd.items():
                            payload = bytes(v) if v is not None else b""
                            lines.append(f"  - {k}: {payload.hex()}")
                lines.append("=" * 72)
                lines.append(f"Matched devices: {len(pairs2)}")
    
                text.delete("1.0", tk.END)
                text.insert(tk.END, "\n".join(lines))
                text.see("1.0")
    
                try:
                    self.dump_adv_button.configure(state="normal")
                except Exception:
                    pass
    
            def thread_main():
                try:
                    pairs = asyncio.run(_scan_adv())
                except Exception as e:
                    pairs = []
                    self.root.after(0, lambda: text.insert(tk.END, f"Scan failed: {e}\n"))
                self.root.after(0, lambda: _render(pairs))
    
            threading.Thread(target=thread_main, daemon=True).start()
    
    
    
    

    return SimGwV2App
