"""
UI Application module for simGW - Main Tkinter GUI components.

This module contains the SimGwV2App class with a 4-tab interface:
- Demo Tab: User-friendly KPI display with timeline and waveform plot
- Expert Tab: Advanced tile-based monitoring with detailed hex dumps
- Devices Tab: BLE device scanner with advertising details
- Settings Tab: Configuration parameters

Architecture:
- Uses factory pattern (create_app_class) for dependency injection
- Integrates with BleCycleWorker for async BLE operations
- Centralized configuration in config.py (colors, phases, constants)
- Modular data handling via data_exporters and protobuf_formatters

Performance optimizations:
- Thread leak prevention in device scanning
- Fixed 5-second scan timeout
- Monotonic phase progression per tile
"""
import asyncio
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

from config import (
    AUTO_RESTART_DELAY_MS, UI_POLL_INTERVAL_MS, CHECKLIST_ITEMS, 
    CHECKLIST_STATE_MAP, MANUAL_ACTIONS, UI_COLORS,
    MEASUREMENT_TYPE_ACCELERATION_TWF, MEASUREMENT_TYPE_VELOCITY_TWF, 
    MEASUREMENT_TYPE_ENVELOPER3_TWF
)
from ble_filters import adv_matches as ble_adv_matches, format_adv_details as ble_format_adv_details
from data_exporters import WaveformParser
WaveformExportTools = WaveformParser


def create_app_class(BleCycleWorker, TileState):
    """Factory function to create SimGwV2App class with injected dependencies."""
    
    class SimGwV2App:
        def __init__(self, root: tk.Tk) -> None:
            self.root = root
            self._tk_root = root
            self.root.title("SimGW ELO SKF")
            self.root.geometry("1000x800")
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
            self.twf_type_var = tk.StringVar(value="5")  # Default: Acceleration TWF

            self._apply_theme()
            self._build_ui()
            self._poll_queue()
            
            # Apply Windows customization after window is fully rendered
            self.root.after(100, self._apply_windows_customization)
    
        def _apply_windows_customization(self) -> None:
            """Apply Windows-specific window customization (dark mode, borders, etc.)."""
            try:
                import ctypes
                
                # Force window update to ensure it's rendered
                self.root.update_idletasks()
                
                # Get window handle - try both methods
                try:
                    hwnd = int(self.root.wm_frame(), 16)  # Try frame method first (more reliable)
                except Exception:
                    hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
                
                # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Windows 10 1809+)
                # Enable dark title bar
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 20, 
                    ctypes.byref(ctypes.c_int(1)), 
                    ctypes.sizeof(ctypes.c_int)
                )
                
                # Windows 11 22000+ specific enhancements
                try:
                    # DWMWA_CAPTION_COLOR = 35 - Set title bar color
                    # Convert hex color to COLORREF (0x00BBGGRR)
                    title_color = 0x00211a17  # Dark gray-blue matching panel
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, 35,
                        ctypes.byref(ctypes.c_int(title_color)),
                        ctypes.sizeof(ctypes.c_int)
                    )
                    
                    # DWMWA_BORDER_COLOR = 34 - Set border color
                    border_color = 0x003a2f2a  # Subtle dark border
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, 34,
                        ctypes.byref(ctypes.c_int(border_color)),
                        ctypes.sizeof(ctypes.c_int)
                    )
                    
                    # DWMWA_WINDOW_CORNER_PREFERENCE = 33
                    # DWMWCP_ROUND = 2 (rounded corners)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, 33,
                        ctypes.byref(ctypes.c_int(2)),
                        ctypes.sizeof(ctypes.c_int)
                    )
                except Exception:
                    pass  # Windows 11 APIs not available (Windows 10)
                    
            except Exception:
                pass  # Not on Windows or API not available

    
        def _apply_theme(self) -> None:
            # Use centralized color palette from config
            self.colors = UI_COLORS
    
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
            
            # Combobox dark theme
            style.configure("TCombobox", 
                fieldbackground=self.colors["panel_alt"],
                background=self.colors["panel"],
                foreground=self.colors["text"],
                arrowcolor=self.colors["text"],
                borderwidth=0)
            style.map("TCombobox",
                fieldbackground=[("readonly", self.colors["panel_alt"])],
                selectbackground=[("readonly", self.colors["accent"])],
                selectforeground=[("readonly", self.colors["text"])])
            
            # Scrollbar dark theme
            style.configure("Vertical.TScrollbar",
                background=self.colors["panel"],
                troughcolor=self.colors["bg"],
                borderwidth=0,
                arrowcolor=self.colors["text"])
            style.map("Vertical.TScrollbar",
                background=[("active", self.colors["panel_alt"])])

            # Configure popup listbox colors for Combobox
            self.root.option_add("*TCombobox*Listbox*Background", self.colors["panel"])
            self.root.option_add("*TCombobox*Listbox*Foreground", self.colors["text"])
            self.root.option_add("*TCombobox*Listbox*selectBackground", self.colors["accent"])
            self.root.option_add("*TCombobox*Listbox*selectForeground", self.colors["text"])



            # Notebook (tabs) styling - modern dark theme with equal width tabs
            style.configure("TNotebook", 
                background=self.colors["bg"],
                borderwidth=0,
                tabmargins=0)
            
            style.configure("TNotebook.Tab",
                background=self.colors["panel_alt"],
                foreground=self.colors["muted"],
                padding=(50, 12),
                borderwidth=0,
                focuscolor="none",
                font=("Segoe UI", 10, "bold"))
            
            style.map("TNotebook.Tab",
                background=[("selected", self.colors["panel"]), ("active", self.colors["panel_alt"])],
                foreground=[("selected", self.colors["accent"]), ("active", self.colors["text"])],
                padding=[("selected", (50, 12))])  # Expand selected tab slightly

            # Treeview dark theme
            style.configure("Treeview",
                           background=self.colors["panel"],
                           foreground=self.colors["text"],
                           fieldbackground=self.colors["panel"],
                           borderwidth=0)
            style.configure("Treeview.Heading",
                           background=self.colors["panel_alt"],
                           foreground=self.colors["text"],
                           borderwidth=1,
                           relief="flat")
            style.map("Treeview",
                     background=[("selected", self.colors["accent"])],
                     foreground=[("selected", "#ffffff")])
            style.map("Treeview.Heading",
                     background=[("active", self.colors["border"])])

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
            card.pack(fill=tk.X, padx=16, pady=(16, 12))
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
                height=13,
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
            plot_area.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
    
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
                self.demo_plot_fig = Figure(figsize=(7.5, 2.3), dpi=100)
                self.demo_plot_fig.subplots_adjust(bottom=0.15, top=0.95)
                ax = self.demo_plot_fig.add_subplot(111)
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
    
            # Update label with detailed info
            try:
                n = int(meta.get("samples") or len(y))
            except Exception:
                n = len(y)
            
            # Extract metadata
            fs_hz = meta.get("fs_hz", 0)
            twf_type = meta.get("twf_type", "Unknown")
            data_type = meta.get("data_type", "S16")
            
            # Build info string
            info_parts = [f"{n} samples"]
            if fs_hz:
                info_parts.append(f"{int(fs_hz)} Hz")
            info_parts.append(data_type)
            info_parts.append(twf_type)
            info_parts.append(os.path.basename(raw_path))
            
            if self.demo_plot_label is not None:
                self.demo_plot_label.configure(text=" • ".join(info_parts))
    
            ax = self.demo_plot_fig.axes[0] if self.demo_plot_fig.axes else self.demo_plot_fig.add_subplot(111)
            ax.clear()
            ax.plot(y)
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
            
            # Apply dark theme to treeview
            tree_style = ttk.Style()
            tree_style.configure("Treeview",
                               background=self.colors["panel"],
                               foreground=self.colors["text"],
                               fieldbackground=self.colors["panel"],
                               borderwidth=0)
            tree_style.configure("Treeview.Heading",
                               background=self.colors["panel_alt"],
                               foreground=self.colors["text"],
                               borderwidth=1,
                               relief="flat")
            tree_style.map("Treeview",
                         background=[("selected", self.colors["accent"])],
                         foreground=[("selected", "#ffffff")])
            
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

            # TWF Type selector
            tk.Label(inner, text="Waveform type", bg=self.colors["panel"], fg=self.colors["muted"]).grid(row=3, column=0, sticky="w", pady=(10, 0))
            twf_combo = ttk.Combobox(inner, textvariable=self.twf_type_var, width=24, state="readonly")
            twf_combo['values'] = (
                f"{MEASUREMENT_TYPE_ACCELERATION_TWF} - Acceleration TWF",
                f"{MEASUREMENT_TYPE_VELOCITY_TWF} - Velocity TWF",
                f"{MEASUREMENT_TYPE_ENVELOPER3_TWF} - Enveloper3 TWF"
            )
            twf_combo.current(0)  # Default to Acceleration
            twf_combo.grid(row=3, column=1, columnspan=2, sticky="w", pady=(10, 0))

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
            addr_prefix, _mtu, _scan_timeout, _rx_timeout, _rec, _sess, name_contains, svc_contains, mfg_id_hex, mfg_data_hex, _twf_type = self._read_runtime_params()
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
            addr_prefix, _mtu, _scan_timeout, _rx_timeout, _rec, _sess, name_contains, svc_contains, mfg_id_hex, mfg_data_hex, _twf_type = self._read_runtime_params()
    
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
    
                ok = ble_adv_matches(dev, adv, addr_prefix, name_contains, svc_contains, mfg_id_hex, mfg_data_hex)
                
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
            txt = ble_format_adv_details(dev, adv)
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

            # Add logo overlay in tab bar area (top-right corner)
            self._add_logo_to_tab_bar()
    
            self._build_ui_demo(demo_tab)
            self._build_ui_expert(expert_tab)
            self._build_ui_devices(devices_tab)
            self._build_ui_settings(settings_tab)
    
        def _add_logo_to_tab_bar(self) -> None:
            """Add SKF logo overlay in the tab bar area (top-right corner)."""
            try:
                from PIL import Image, ImageTk
                import os
                
                # Load logo image
                logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SKF_transparent_cream.png")
                if not os.path.exists(logo_path):
                    return  # No logo available
                
                img = Image.open(logo_path)
                
                # Crop transparent borders to get tight bounds around the logo
                # First convert to RGBA if needed
                if img.mode != 'RGBA':
                    img = img.convert('RGBA')
                
                # Get bounding box of non-transparent pixels
                bbox = img.getbbox()
                if bbox:
                    img = img.crop(bbox)
                
                # Resize to fit in tab bar (height ~24-28px, keep aspect ratio)
                target_height = 28
                aspect_ratio = img.width / img.height
                target_width = int(target_height * aspect_ratio)
                img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
                
                # Convert to PhotoImage
                photo = ImageTk.PhotoImage(img)
                
                # Create a frame that will be placed in top-right corner
                logo_frame = tk.Frame(self.root, bg=self.colors["bg"])
                logo_frame.place(relx=1.0, y=2, anchor="ne", x=-10)
                
                # Add logo label
                logo_label = tk.Label(logo_frame, image=photo, bg=self.colors["bg"])
                logo_label.image = photo  # Keep reference
                logo_label.pack()
                
            except Exception as e:
                # Silently fail if PIL not available or image loading fails
                print(f"Could not load logo: {e}")
    
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

            # Check if rx_text contains the new formatted view
            if rx_text and ("=== OVERALL MEASUREMENTS ===" in rx_text or "=== SESSION ACCEPTED ===" in rx_text):
                # Use the new formatted view directly
                # Remove TYPE and HEX headers
                lines_raw = rx_text.split('\n')
                filtered_lines = []
                skip_next = False
                for line in lines_raw:
                    if line.startswith('TYPE:') or line.startswith('HEX:'):
                        skip_next = True
                        continue
                    if skip_next and line.strip() == '':
                        skip_next = False
                        continue
                    filtered_lines.append(line)
                
                display_text = '\n'.join(filtered_lines).strip()
                
                # Add header with timestamp
                now_s = time.strftime("%H:%M:%S")
                header = f"Last update: {now_s}\n\n"
                
                self.demo_summary.configure(state=tk.NORMAL)
                self.demo_summary.delete("1.0", tk.END)
                
                # Use monospaced font
                try:
                    self.demo_summary.configure(font=("Consolas", 10))
                except Exception:
                    pass
                
                self.demo_summary.insert(tk.END, header + display_text + "\n")
                self.demo_summary.configure(state=tk.DISABLED)
                return
    
            # Legacy path: use overall_values
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
    
        def _build_ui_expert(self, parent: tk.Frame) -> None:
    
            # Header (same layout as Demo)
            _card, self.start_button, self.stop_auto_button = self._ui_build_run_header_card(parent)
            self._update_demo_run_controls()
    
            # Filters (keep only the essentials here; other runtime settings live in the Settings tab)
            filter_box = tk.Frame(parent, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            filter_box.pack(fill=tk.X, padx=16, pady=(0, 8))
            filter_in = tk.Frame(filter_box, bg=self.colors["panel"])
            filter_in.pack(fill=tk.X, padx=14, pady=10)
    
            # Filters title aligned with fields
            title_row = tk.Frame(filter_in, bg=self.colors["panel"])
            title_row.pack(fill=tk.X, pady=(0, 6))
            tk.Label(
                title_row,
                text="🔍 Filters",
                bg=self.colors["panel"],
                fg=self.colors["text"],
                font=("Segoe UI", 10, "bold"),
            ).pack(side=tk.LEFT)
    
            form = tk.Frame(filter_in, bg=self.colors["panel"])
            form.pack(fill=tk.X)
    
            # Optional advertising filters (leave empty to disable)
            self._build_field(form, "Address prefix", self.address_prefix_var)
            self._build_field(form, "ADV name contains", self.adv_name_contains_var)
    
            # Manual Commands with border
            manual_card = tk.Frame(parent, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            manual_card.pack(fill=tk.X, padx=16, pady=(0, 12))
            manual = tk.Frame(manual_card, bg=self.colors["panel"])
            manual.pack(fill=tk.X, padx=14, pady=10)
    
            # Title
            title_row = tk.Frame(manual, bg=self.colors["panel"])
            title_row.pack(fill=tk.X, pady=(0, 8))
            tk.Label(
                title_row,
                text="⚡ Manual Commands",
                bg=self.colors["panel"],
                fg=self.colors["text"],
                font=("Segoe UI", 10, "bold"),
            ).pack(side=tk.LEFT)
    
            # Main actions grid
            manual_btns = tk.Frame(manual, bg=self.colors["panel"])
            manual_btns.pack(fill=tk.X, pady=(0, 8))
    
            buttons = []
            for text_, action_ in MANUAL_ACTIONS:
                btn = ttk.Button(manual_btns, text=text_, width=20, command=lambda a=action_: self._start_manual_action(a))
                buttons.append(btn)
            self._wrap_buttons(manual_btns, buttons, min_btn_px=180)
    
            # Utilities separator
            sep = tk.Frame(manual, bg=self.colors["border"], height=1)
            sep.pack(fill=tk.X, pady=(0, 8))
    
            # Utilities row
            util = tk.Frame(manual, bg=self.colors["panel"])
            util.pack(fill=tk.X)
    
            util_btns = [
                ttk.Button(util, text="Clear logs", width=20, command=self._clear_tiles),
                ttk.Button(util, text="Plot Latest", width=20, command=self._plot_latest_waveform),
            ]
            self._wrap_buttons(util, util_btns, min_btn_px=180)
    
            tiles_frame = tk.Frame(parent, bg=self.colors["bg"])
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
            # Parse TWF type (extract first number from "5 - Acceleration TWF" format)
            twf_type_str = self.twf_type_var.get().strip()
            try:
                twf_type = int(twf_type_str.split()[0]) if twf_type_str else MEASUREMENT_TYPE_ACCELERATION_TWF
            except (ValueError, IndexError):
                twf_type = MEASUREMENT_TYPE_ACCELERATION_TWF
            return address_prefix, mtu, scan_timeout, rx_timeout, record_sessions, session_root, name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains, twf_type
    
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
            address_prefix, mtu, scan_timeout, rx_timeout, record_sessions, session_root, name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains, twf_type = self._read_runtime_params()
            if action is None:
                self.worker.run_cycle(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, record_sessions, session_root, name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains, twf_type)
            else:
                self.worker.run_manual_action(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, action, record_sessions, session_root, name_contains, service_uuid_contains, mfg_id_hex, mfg_data_hex_contains, twf_type)
    
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
    
            # Buttons row
            btn_row = tk.Frame(body, bg=self.colors["panel"])
            btn_row.pack(anchor="w", pady=(6, 0), fill=tk.X)
            
            plot_btn = ttk.Button(btn_row, text="Plot Waveform", width=18, command=lambda tid=tile_id: self._plot_tile_waveform(tid))
            plot_btn.pack(side=tk.LEFT, padx=(0, 6))
            
            details_btn = ttk.Button(btn_row, text="View Details", width=18, command=lambda tid=tile_id: self._view_session_details(tid))
            details_btn.pack(side=tk.LEFT)

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
                "details_btn": details_btn,
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

        def _view_session_details(self, tile_id: int) -> None:
            """Open a popup window showing formatted session details from events.txt."""
            # Get tile state to find session directory
            tile_state = self.tile_state.get(tile_id)
            if not tile_state or not tile_state.session_dir:
                messagebox.showinfo("Session Details", f"No session data available for tile {tile_id}.")
                return
            
            events_file = os.path.join(tile_state.session_dir, "events.txt")
            if not os.path.exists(events_file):
                messagebox.showinfo("Session Details", f"Session log file not found:\n{events_file}")
                return
            
            # Read the file contents
            try:
                with open(events_file, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to read session log:\n{e}")
                return
            
            # Create popup window
            popup = tk.Toplevel(self.root)
            popup.title(f"Session Details - Tile {tile_id}")
            popup.geometry("900x700")
            popup.configure(bg=self.colors["bg"])
            
            # Header with session info
            header = tk.Frame(popup, bg=self.colors["panel"], highlightbackground=self.colors["border"], highlightthickness=1)
            header.pack(fill=tk.X, padx=10, pady=10)
            header_in = tk.Frame(header, bg=self.colors["panel"])
            header_in.pack(fill=tk.X, padx=12, pady=10)
            
            tk.Label(
                header_in,
                text=f"📋 Session Details - Tile {tile_id}",
                bg=self.colors["panel"],
                fg=self.colors["text"],
                font=("Segoe UI", 12, "bold")
            ).pack(side=tk.LEFT)
            
            session_name = os.path.basename(tile_state.session_dir)
            tk.Label(
                header_in,
                text=f"Session: {session_name}",
                bg=self.colors["panel"],
                fg=self.colors["muted"],
                font=("Segoe UI", 9)
            ).pack(side=tk.LEFT, padx=(20, 0))
            
            # Text widget with scrollbar
            text_frame = tk.Frame(popup, bg=self.colors["bg"])
            text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
            
            scrollbar = tk.Scrollbar(text_frame)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            
            text_widget = tk.Text(
                text_frame,
                wrap=tk.NONE,
                bg=self.colors["panel"],
                fg=self.colors["text"],
                font=("Consolas", 9),
                yscrollcommand=scrollbar.set
            )
            text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.config(command=text_widget.yview)
            
            # Insert content
            text_widget.insert("1.0", content)
            text_widget.configure(state=tk.DISABLED)
            
            # Bottom buttons
            btn_frame = tk.Frame(popup, bg=self.colors["bg"])
            btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
            
            ttk.Button(
                btn_frame,
                text="Copy to Clipboard",
                command=lambda: self._copy_to_clipboard(content, popup)
            ).pack(side=tk.LEFT, padx=(0, 6))
            
            ttk.Button(
                btn_frame,
                text="Open in Notepad",
                command=lambda: os.startfile(events_file)
            ).pack(side=tk.LEFT, padx=(0, 6))
            
            ttk.Button(
                btn_frame,
                text="Close",
                command=popup.destroy
            ).pack(side=tk.RIGHT)
        
        def _copy_to_clipboard(self, text: str, parent_window: tk.Toplevel) -> None:
            """Copy text to clipboard and show confirmation."""
            try:
                parent_window.clipboard_clear()
                parent_window.clipboard_append(text)
                messagebox.showinfo("Copied", "Session details copied to clipboard!", parent=parent_window)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to copy to clipboard:\n{e}", parent=parent_window)
    
    
        def _plot_waveform_from_export(self, export_info: dict, title: str = "Waveform") -> None:
            """Plot waveform from export info (uses .bin file only)."""
            if plt is None:
                messagebox.showerror("Waveform plot", "matplotlib is not installed.\nInstall with: pip install matplotlib")
                return
            
            raw_path = export_info.get("raw") if isinstance(export_info, dict) else None
            
            try:
                if not raw_path or not os.path.exists(raw_path):
                    raise RuntimeError("Binary export file not found")
                
                # Extract true time waveform from raw protobuf payloads
                y, meta = WaveformExportTools.extract_true_waveform_samples(raw_path)
                
                if not y:
                    raise RuntimeError("No waveform samples found in export")
                
                # Extract metadata
                fs = float(meta.get("fs_hz", 0.0) or 0.0)
                n_samples = meta.get("samples", len(y))
                data_type = meta.get("data_type", "S16")
                twf_type = meta.get("twf_type", "Unknown")
                
                # Build informative title
                title_parts = [f"{n_samples} samples"]
                if fs > 0.0:
                    title_parts.append(f"{int(fs)} Hz")
                title_parts.append(data_type)
                title_parts.append(twf_type)
                plot_title = " • ".join(title_parts)
                
                # Build X axis data and label
                x = list(range(len(y)))
                xlabel = "Sample index"
                
                if fs > 0.0:
                    x = [i / fs for i in range(len(y))]
                    xlabel = f"Time (s) @ Fs={int(fs)} Hz"
                
                # Y axis label with TWF type
                ylabel = f"{twf_type.replace('Twf', '')} (raw {data_type})"
                
                plt.figure(figsize=(12, 6))
                plt.plot(x, y, linewidth=0.5)
                plt.title(plot_title)
                plt.xlabel(xlabel)
                plt.ylabel(ylabel)
                plt.grid(True, alpha=0.3)
                plt.tight_layout()
                plt.show()
                
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
                # If rx_text contains the new formatted view, use it directly
                if st.rx_text and ("=== OVERALL MEASUREMENTS ===" in st.rx_text or "=== SESSION ACCEPTED ===" in st.rx_text):
                    # Extract just the formatted section (without TYPE/HEX headers)
                    display_text = st.rx_text
                    # Remove TYPE and HEX lines if present
                    lines = display_text.split('\n')
                    filtered_lines = []
                    skip_next = False
                    for line in lines:
                        if line.startswith('TYPE:') or line.startswith('HEX:'):
                            skip_next = True
                            continue
                        if skip_next and line.strip() == '':
                            skip_next = False
                            continue
                        filtered_lines.append(line)
                    display_text = '\n'.join(filtered_lines).strip()
                    tile["overall"].configure(text=display_text)
                else:
                    # Use legacy formatted overall_values
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
    
                # Waveform: plot from export_info (raw .bin file), once per new raw file.
                if st.export_info and isinstance(st.export_info, dict):
                    raw_path = st.export_info.get("raw")
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
    
                # Summary: show overall values + last RX text (human readable)
                self._demo_render_summary(st.rx_text or "", st.overall_values)
    
            except Exception as e:
                try:
                    self._log("ERROR", f"Demo mirror update failed: {type(e).__name__}: {e}")
                except Exception:
                    pass


    return SimGwV2App    

