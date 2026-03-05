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
- Centralized configuration in ble_config.py / ui_config.py / protocol_utils.py
- Modular data handling via data_exporters and protobuf_formatters

Performance optimizations:
- Thread leak prevention in device scanning
- Fixed 5-second scan timeout
- Monotonic phase progression per tile
"""
import os
import time
import tkinter as tk
from queue import Queue, Empty
from tkinter import ttk, messagebox
from typing import Any, Dict, Optional

try:
    import matplotlib.pyplot as plt
except Exception:
    plt = None

from protocol_utils import AUTO_RESTART_DELAY_MS
from ui_config import (
    UI_POLL_INTERVAL_MS, CHECKLIST_ITEMS, CHECKLIST_STATE_MAP, 
    UI_COLORS
)
from ble_config import (
    MEASUREMENT_TYPE_ACCELERATION_TWF,
    MEASUREMENT_TYPE_VELOCITY_TWF,
    MEASUREMENT_TYPE_ENVELOPER3_TWF,
)
from data_exporters import WaveformParser
from ui_helpers import apply_windows_dark_mode, apply_dark_theme
from TabDevices import (
    build_ui_devices,
    devices_scan,
)
from TabSettings import build_ui_settings
from TabDemo import (
    build_ui_demo,
    demo_plot_waveform_from_raw_export,
    demo_update_timeline,
    demo_set_kpis_from_rx_text,
    demo_render_summary,
)
from TabExpert import build_ui_expert
from ui_events import TileUpdatePayload, UiEvent

WaveformExportTools = WaveformParser
_CHECKLIST_PENDING_SYMBOL = "☐"
_WAVEFORM_KEY_BY_TYPE = {
    MEASUREMENT_TYPE_ACCELERATION_TWF: "acceleration_twf",
    MEASUREMENT_TYPE_VELOCITY_TWF: "velocity_twf",
    MEASUREMENT_TYPE_ENVELOPER3_TWF: "enveloper3_twf",
}
_WAVEFORM_LABEL_BY_KEY = {
    "acceleration_twf": "Acceleration TWF",
    "velocity_twf": "Velocity TWF",
    "enveloper3_twf": "Enveloper3 TWF",
}
_DEFAULT_WAVEFORM_KEY = "acceleration_twf"


def create_app_class(BleCycleWorker, TileState):
    """Factory function to create SimGwV2App class with injected dependencies."""
    
    class SimGwV2App:
        def __init__(self, root: tk.Tk) -> None:
            self.root = root
            self._tk_root = root
            self.root.title("SimGW ELO SKF")
            self.root.geometry("1000x800")
            self.root.configure(bg="#0f1115")
    
            self.ui_queue: Queue[UiEvent] = Queue()
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
            self.tile_state: Dict[int, Any] = {}
            self._demo_mirrored_tile_id: Optional[int] = None
    
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
            self.debug_mode = str(os.getenv("SIMGW_DEBUG", "0")).strip().lower() in {"1", "true", "yes", "on"}
            #  Demo timeline (mirrors the latest Expert tile checklist)
            self.demo_checklist_state = {key: "pending" for key, _title in CHECKLIST_ITEMS}
            self.demo_timeline_labels = {}  # key -> (dot_label, text_label)

            # Expert plotting options
            self.expert_plot_spectrum_var = tk.BooleanVar(value=True)
            self.expert_spectrum_button = None


            # Devices tab state
            self.devices_tree = None
            self.devices_detail = None
            self.devices_scan_status_var = tk.StringVar(value="Ready")
            self._devices_scan_in_progress = False  # Prevent concurrent scans

            self._devices_by_addr = {}  # addr -> {"dev":..., "adv":..., "last_seen_ms":...}
            self._devices_autoscan_job = None
            self._devices_autoscan_interval_ms = 3000
            self._devices_tab_widget = None  # set in _build_ui


            self.address_prefix_var = tk.StringVar(value="C4:BD:6A:01:02:03")
            # Optional advertising-content filter (applied in addition to address prefix when set)
            self.adv_name_contains_var = tk.StringVar(value="IMx-1_ELO")
            self.scan_timeout_var = tk.StringVar(value="60")
            self.rx_timeout_var = tk.StringVar(value="5")
            self.record_sessions_var = tk.BooleanVar(value=True)
            self.session_root_var = tk.StringVar(value="sessions")
            self.mtu_var = tk.StringVar(value="247")
            self.twf_type_var = tk.StringVar(value=f"{MEASUREMENT_TYPE_ACCELERATION_TWF} - Acceleration TWF")

            # Apply dark theme and Windows customization
            self.colors = UI_COLORS
            apply_dark_theme(self.root, self.colors)
            self._build_ui()
            self._poll_queue()
            
            # Apply Windows customization after window is fully rendered
            self.root.after(100, lambda: apply_windows_dark_mode(self.root))
    
        def _log(self, level: str, msg: str) -> None:
            """Emit debug logs to stdout only when SIMGW_DEBUG is enabled."""
            try:
                if not self.debug_mode:
                    return
                ts = time.strftime("%H:%M:%S")
                print(f"[{ts}] {level}: {msg}")
            except Exception:
                pass
    
        
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
    
        def _build_ui(self) -> None:
            """Build a 4-tab UI (Demo / Expert / Devices / Settings) without changing backend logic."""
            nb = ttk.Notebook(self.root)
            nb.pack(fill=tk.BOTH, expand=True)
            self.notebook = nb
    
            tab_demo_frame = tk.Frame(nb, bg=self.colors["bg"])
            tab_expert_frame = tk.Frame(nb, bg=self.colors["bg"])
            tab_devices_frame = tk.Frame(nb, bg=self.colors["bg"])
            tab_settings_frame = tk.Frame(nb, bg=self.colors["bg"])

            nb.add(tab_demo_frame, text="Demo")
            nb.add(tab_expert_frame, text="Expert")
            nb.add(tab_devices_frame, text="Devices")
            nb.add(tab_settings_frame, text="Settings")

            self._devices_tab_widget = tab_devices_frame
            nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

            # Add logo overlay in tab bar area (top-right corner)
            self._add_logo_to_tab_bar()
    
            build_ui_demo(self, tab_demo_frame)
            build_ui_expert(self, tab_expert_frame)
            build_ui_devices(self, tab_devices_frame)
            build_ui_settings(self, tab_settings_frame)
    
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
                self._log("WARN", f"Could not load logo: {e}")
    
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
            return address_prefix, mtu, scan_timeout, rx_timeout, record_sessions, session_root, name_contains
    
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
            address_prefix, mtu, scan_timeout, rx_timeout, record_sessions, session_root, name_contains = self._read_runtime_params()
            if action is None:
                self.worker.run_cycle(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, record_sessions, session_root, name_contains)
            else:
                self.worker.run_manual_action(tile_id, address_prefix, mtu, scan_timeout, rx_timeout, action, record_sessions, session_root, name_contains)
    
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
    
        def _format_export_compact(self, export_payload: Optional[dict]) -> str:
            """Return a compact export summary for Expert tiles."""
            if not export_payload:
                return "Export: •"

            if not isinstance(export_payload, dict):
                return "Export: •"

            if "raw" in export_payload or "txt" in export_payload or "count" in export_payload:
                raw = export_payload.get("raw")
                idx = export_payload.get("index")
                cnt = export_payload.get("count")
                parts = []
                if raw:
                    parts.append(f"- raw: {raw}")
                if idx:
                    parts.append(f"- index: {idx}")
                if cnt not in (None, ""):
                    parts.append(f"- blocks: {cnt}")
                return "Export:\n" + ("\n".join(parts) if parts else "•")

            lines = ["Export:"]
            for waveform_key in (_DEFAULT_WAVEFORM_KEY, "velocity_twf", "enveloper3_twf"):
                info = export_payload.get(waveform_key)
                if not isinstance(info, dict):
                    continue
                label = self._waveform_label_for_key(waveform_key)
                raw = info.get("raw")
                if raw:
                    lines.append(f"- {label}: {raw}")
                elif info.get("error"):
                    lines.append(f"- {label}: ERROR")
                else:
                    lines.append(f"- {label}: •")

            return "\n".join(lines) if len(lines) > 1 else "Export: •"
    
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
                label = tk.Label(checklist_frame, text=f"{_CHECKLIST_PENDING_SYMBOL} {title}", bg=self.colors["panel"], fg=self.colors["muted"])
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
            
            plot_btn = ttk.Button(btn_row, text="Plot Accel", width=14, command=lambda tid=tile_id: self._plot_tile_waveform(tid, "acceleration_twf"))
            plot_btn.pack(side=tk.LEFT, padx=(0, 6))

            plot_vel_btn = ttk.Button(btn_row, text="Plot Vel", width=12, command=lambda tid=tile_id: self._plot_tile_waveform(tid, "velocity_twf"))
            plot_vel_btn.pack(side=tk.LEFT, padx=(0, 6))

            plot_env_btn = ttk.Button(btn_row, text="Plot Env3", width=12, command=lambda tid=tile_id: self._plot_tile_waveform(tid, "enveloper3_twf"))
            plot_env_btn.pack(side=tk.LEFT, padx=(0, 6))
            
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
                "plot_vel_btn": plot_vel_btn,
                "plot_env_btn": plot_env_btn,
                "details_btn": details_btn,
            }
    
    
        def _plot_export_info(self, export_info: Optional[dict], title: str, empty_msg: str) -> None:
            if not export_info:
                messagebox.showinfo("Waveform plot", empty_msg)
                return
            self._plot_waveform_from_export(export_info, title=title)
    
        def _plot_tile_waveform(self, tile_id: int, waveform_key: str = _DEFAULT_WAVEFORM_KEY) -> None:
            export_infos = self.tile_export_info.get(tile_id)
            selected_export = None
            if isinstance(export_infos, dict):
                if waveform_key in export_infos and isinstance(export_infos.get(waveform_key), dict):
                    selected_export = export_infos.get(waveform_key)
                elif waveform_key == _DEFAULT_WAVEFORM_KEY and ("raw" in export_infos or "txt" in export_infos):
                    # Legacy single-export payload (pre multi-waveform map)
                    selected_export = export_infos

            self._plot_export_info(
                selected_export,
                title=f"Tile {tile_id} • {self._waveform_label_for_key(waveform_key)}",
                empty_msg=f"No export available yet for tile {tile_id}.",
            )
    
        def _plot_latest_waveform(self) -> None:
            selected_export = self._resolve_selected_export_info(self.latest_export_info)
            self._plot_export_info(
                selected_export,
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
                fs_label = f"{int(fs)} Hz" if fs > 0.0 else "n/a"
                
                # Build informative title
                title_parts = [f"{n_samples} samples"]
                title_parts.append(f"Sampling rate: {fs_label}")
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
                
                time_fig = plt.figure(figsize=(12, 6))
                time_ax = time_fig.add_subplot(111)
                time_ax.plot(x, y, linewidth=0.5)
                time_ax.set_title(plot_title)
                time_ax.set_xlabel(xlabel)
                time_ax.set_ylabel(ylabel)
                time_ax.grid(True, alpha=0.3)
                time_fig.tight_layout()

                show_spectrum = False
                try:
                    spectrum_var = getattr(self, "expert_plot_spectrum_var", None)
                    show_spectrum = bool(spectrum_var.get()) if spectrum_var is not None else False
                except Exception:
                    show_spectrum = False

                if show_spectrum:
                    try:
                        import numpy as np

                        samples = np.asarray(y, dtype=float)
                        if samples.size >= 2:
                            samples = samples - float(np.mean(samples))
                            window = np.hanning(samples.size)
                            windowed = samples * window

                            spectrum = np.fft.rfft(windowed)
                            magnitude = np.abs(spectrum)

                            if fs > 0.0:
                                freqs = np.fft.rfftfreq(samples.size, d=1.0 / fs)
                                spectrum_xlabel = "Frequency (Hz)"
                                nyquist_text = f"Nyquist: {fs/2:.1f} Hz"
                            else:
                                freqs = np.arange(magnitude.size)
                                spectrum_xlabel = "Frequency bin"
                                nyquist_text = "Nyquist: n/a"

                            spec_fig = plt.figure(figsize=(12, 6))
                            spec_ax = spec_fig.add_subplot(111)
                            spec_ax.plot(freqs, magnitude, linewidth=0.8)
                            spec_ax.set_title(f"Spectrum • {twf_type} • {nyquist_text}")
                            spec_ax.set_xlabel(spectrum_xlabel)
                            spec_ax.set_ylabel("Magnitude")
                            spec_ax.grid(True, alpha=0.3)
                            spec_fig.tight_layout()
                    except Exception as fft_exc:
                        self._log("WARN", f"Spectrum plot unavailable: {fft_exc}")
                plt.show()
                
            except Exception as e:
                messagebox.showerror("Waveform plot", f"Unable to plot waveform: {e}")
    
        def _handle_ui_event(self, event: UiEvent) -> None:
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

        def _selected_notebook_widget(self):
            try:
                selection = self.notebook.select()
                return self.notebook.nametowidget(selection)
            except Exception:
                return None

        def _is_devices_tab_selected(self) -> bool:
            widget = self._selected_notebook_widget()
            return widget is not None and widget == getattr(self, "_devices_tab_widget", None)

        def _selected_waveform_type(self) -> int:
            raw_value = str(self.twf_type_var.get() or "").strip()
            try:
                return int(raw_value.split()[0]) if raw_value else MEASUREMENT_TYPE_ACCELERATION_TWF
            except Exception:
                return MEASUREMENT_TYPE_ACCELERATION_TWF

        def _selected_waveform_key(self) -> str:
            return _WAVEFORM_KEY_BY_TYPE.get(self._selected_waveform_type(), _DEFAULT_WAVEFORM_KEY)

        def _refresh_expert_spectrum_button(self) -> None:
            """Refresh Expert FFT toggle button text/style."""
            btn = getattr(self, "expert_spectrum_button", None)
            if btn is None:
                return
            enabled = bool(self.expert_plot_spectrum_var.get())
            btn.configure(text=("FFT Spectrum: ON" if enabled else "FFT Spectrum: OFF"))
            btn.configure(style=("Accent.TButton" if enabled else "TButton"))

        def _toggle_expert_spectrum_plot(self) -> None:
            """Toggle optional FFT spectrum plot for Expert waveform plotting."""
            current = bool(self.expert_plot_spectrum_var.get())
            self.expert_plot_spectrum_var.set(not current)
            self._refresh_expert_spectrum_button()

        @staticmethod
        def _waveform_label_for_key(waveform_key: str) -> str:
            return _WAVEFORM_LABEL_BY_KEY.get(waveform_key, waveform_key)

        def _resolve_selected_export_info(self, export_infos: Any, fallback_export: Optional[dict] = None) -> Optional[dict]:
            selected_key = self._selected_waveform_key()

            if isinstance(export_infos, dict):
                if "raw" in export_infos or "txt" in export_infos or "count" in export_infos:
                    return export_infos

                selected = export_infos.get(selected_key)
                if isinstance(selected, dict):
                    return selected

                default_export = export_infos.get(_DEFAULT_WAVEFORM_KEY)
                if isinstance(default_export, dict):
                    return default_export

                for value in export_infos.values():
                    if isinstance(value, dict):
                        return value

            if isinstance(fallback_export, dict):
                return fallback_export
            return None

        def _plot_selected_demo_waveform(self, st: Any, force: bool = False) -> bool:
            export_info = self._resolve_selected_export_info(getattr(st, "export_infos", None), getattr(st, "export_info", None))
            if not export_info or not isinstance(export_info, dict):
                return False

            raw_path = export_info.get("raw")
            if not raw_path:
                return False
            if (not force) and raw_path == self._demo_last_plotted_raw:
                return True

            self._demo_last_plotted_raw = raw_path
            self.latest_export_info = export_info
            try:
                self.demo_plot_label.config(text="Rendering waveform...")
                demo_plot_waveform_from_raw_export(self, raw_path)
                selected_label = self._waveform_label_for_key(self._selected_waveform_key())
                self.demo_waveform_var.set(f"{selected_label} received")
                return True
            except Exception as e:
                self.demo_plot_label.config(text=f"(plot error: {type(e).__name__})")
                self._log("ERROR", f"Waveform plot failed: {e}")
                return False

        def _on_demo_waveform_selector_changed(self, _evt=None) -> None:
            """Re-render Demo waveform panel using currently selected waveform type."""
            tile_id = getattr(self, "_demo_mirrored_tile_id", None)
            if tile_id is None:
                self.demo_waveform_var.set("•")
                return
            st = self.tile_state.get(tile_id)
            if st is None:
                self.demo_waveform_var.set("•")
                return
            plotted = self._plot_selected_demo_waveform(st, force=True)
            if not plotted:
                selected_label = self._waveform_label_for_key(self._selected_waveform_key())
                self.demo_waveform_var.set("•")
                if self.demo_plot_label is not None:
                    self.demo_plot_label.configure(text=f"(waiting for {selected_label})")

        @staticmethod
        def _extract_overall_display_text(rx_text: str) -> Optional[str]:
            if not rx_text:
                return None
            if ("=== OVERALL MEASUREMENTS ===" not in rx_text) and ("=== SESSION ACCEPTED ===" not in rx_text):
                return None

            filtered_lines = []
            skip_blank_after_header = False
            for line in rx_text.split("\n"):
                if line.startswith("TYPE:") or line.startswith("HEX:"):
                    skip_blank_after_header = True
                    continue
                if skip_blank_after_header and line.strip() == "":
                    skip_blank_after_header = False
                    continue
                filtered_lines.append(line)

            display_text = "\n".join(filtered_lines).strip()
            return display_text or None

        def _update_demo_header_from_tile(self, tile: Dict[str, Any], st: Any) -> None:
            self.demo_status_var.set(st.status or "")
            name_txt = tile.get("name").cget("text") if tile.get("name") else ""
            addr_txt = tile.get("address").cget("text") if tile.get("address") else ""
            self.demo_device_var.set((name_txt + " " + addr_txt).strip())
            if st.checklist:
                demo_update_timeline(self, st.checklist)

        def _reset_demo_panels_for_new_tile(self) -> None:
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
    
        def _on_tab_changed(self, _evt=None):
            """Start/stop Devices autoscan based on selected tab."""
            if self._is_devices_tab_selected():
                self._devices_autoscan_start()
            else:
                self._devices_autoscan_stop()
    
        def _devices_autoscan_start(self):
            if getattr(self, "_devices_autoscan_job", None) is not None:
                return
            # Kick one scan immediately, then every interval
            devices_scan(self)
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
            if not self._is_devices_tab_selected():
                return
            devices_scan(self)
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
    
        
        def _apply_tile_update(self, tile_id: int, payload: TileUpdatePayload) -> None:
    
            # Surface structured errors through debug logger (stdout in debug mode)
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
            if "export_infos" in payload and payload.get("export_infos"):
                incoming_infos = payload.get("export_infos")
                if isinstance(incoming_infos, dict):
                    current_infos = getattr(st, "export_infos", None)
                    if not isinstance(current_infos, dict):
                        current_infos = {}
                    current_infos.update(incoming_infos)
                    st.export_infos = current_infos
                    self.tile_export_info[tile_id] = current_infos
                    selected_export = self._resolve_selected_export_info(current_infos, st.export_info)
                    if selected_export:
                        self.latest_export_info = selected_export
            if "export_info" in payload and payload.get("export_info"):
                st.export_info = payload.get("export_info")
                if isinstance(getattr(st, "export_infos", None), dict) and st.export_infos:
                    self.tile_export_info[tile_id] = st.export_infos
                else:
                    # Legacy single-export payload compatibility (no typed waveform map)
                    self.tile_export_info[tile_id] = st.export_info

                selected_export = self._resolve_selected_export_info(getattr(st, "export_infos", None), st.export_info)
                self.latest_export_info = selected_export or st.export_info
                try:
                    raw_candidate = (selected_export or st.export_info or {}).get("raw")
                    st.last_export_raw = raw_candidate or st.last_export_raw
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
                display_text = self._extract_overall_display_text(st.rx_text or "")
                if display_text:
                    tile["overall"].configure(text=display_text)
                else:
                    ov_txt = self._format_overalls_compact(st.overall_values, max_lines=8)
                    tile["overall"].configure(text=ov_txt)
            except Exception:
                pass
            try:
                export_infos = getattr(st, "export_infos", None)
                if isinstance(export_infos, dict) and export_infos:
                    done = 0
                    for value in export_infos.values():
                        if isinstance(value, dict) and (value.get("raw") or value.get("index")):
                            done += 1
                    tile["waveform"].configure(text=f"Waveform: {done}/3")
                elif st.export_info and (st.export_info.get("raw") or st.export_info.get("index")):
                    tile["waveform"].configure(text="Waveform: OK")
                else:
                    tile["waveform"].configure(text="Waveform: •")
            except Exception:
                pass
            try:
                tile["export"].configure(text=self._format_export_compact(getattr(st, "export_infos", None) or st.export_info))
            except Exception:
                pass
    
            if "checklist" in payload:
                labels = tile.get("checklist", {})
                titles = tile.get("checklist_titles", {})
                for key, state in (payload.get("checklist") or {}).items():
                    label = labels.get(key)
                    title = titles.get(key, key)
                    if label:
                        symbol = CHECKLIST_STATE_MAP.get(state, _CHECKLIST_PENDING_SYMBOL)
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
                        self._reset_demo_panels_for_new_tile()
                    except Exception:
                        pass
    
            # If this update is not for the active Demo tile, do not overwrite Demo UI.
            if tile_id != active_demo_tile:
                # Keep overall/waveform from the last connected tile, but reflect current activity
                # (Scanning/Connecting/Disconnected) so the Demo doesn't look "stuck".
                try:
                    self._update_demo_header_from_tile(tile, st)
                except Exception:
                    pass
                return
    
            try:
                self._update_demo_header_from_tile(tile, st)
    
                # KPIs driven by structured info + rx_text only for display
                selected_export = self._resolve_selected_export_info(getattr(st, "export_infos", None), st.export_info)
                demo_set_kpis_from_rx_text(self, st.rx_text or "", selected_export if selected_export else None)
    
                # Overalls: driven only by structured overall_values
                if st.overall_values is not None:
                    self.demo_last_overall_values = st.overall_values
                    try:
                        n = len(self.demo_last_overall_values) if self.demo_last_overall_values is not None else 0
                        self.demo_overall_var.set(f"{n} metrics" if n > 0 else "•")
                    except Exception:
                        self.demo_overall_var.set("•")
    
                # Waveform: render selected waveform type when a new export arrives.
                self._plot_selected_demo_waveform(st)
    
                # Summary: show overall values + last RX text (human readable)
                demo_render_summary(self, st.rx_text or "", st.overall_values)
    
            except Exception as e:
                try:
                    self._log("ERROR", f"Demo mirror update failed: {type(e).__name__}: {e}")
                except Exception:
                    pass


    return SimGwV2App    

