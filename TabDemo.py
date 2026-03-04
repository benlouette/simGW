"""Demo tab UI and rendering helpers.

Public API consumed by `ui_application.py`:
- build_ui_demo
- demo_style_plot_axes
- demo_plot_waveform_from_raw_export
- demo_update_timeline
- demo_set_kpis_from_rx_text
- demo_render_summary
"""

import os
import re
import time
import tkinter as tk
from typing import Dict, Optional

from data_exporters import WaveformParser
from ui_config import CHECKLIST_ITEMS

_MSG_TYPE_RE = re.compile(r"^TYPE:\s*([^\n]+)", flags=re.MULTILINE)
_WAITING_WAVEFORM_TEXT = "(waiting for waveform...)"

try:
    from matplotlib.figure import Figure
    try:
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    except Exception:
        FigureCanvasTkAgg = None
except Exception:
    Figure = None
    FigureCanvasTkAgg = None


def _build_kpi_card(app, parent: tk.Frame, title: str, variable: tk.StringVar) -> None:
    card = tk.Frame(parent, bg=app.colors["panel"], highlightbackground=app.colors["border"], highlightthickness=1)
    card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

    body = tk.Frame(card, bg=app.colors["panel"])
    body.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

    tk.Label(body, text=title, bg=app.colors["panel"], fg=app.colors["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
    tk.Label(body, textvariable=variable, bg=app.colors["panel"], fg=app.colors["text"], font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(2, 0))


def _extract_formatted_rx_text(rx_text: str) -> str:
    lines_raw = rx_text.split("\n")
    filtered_lines = []
    skip_next_blank = False
    for line in lines_raw:
        if line.startswith("TYPE:") or line.startswith("HEX:"):
            skip_next_blank = True
            continue
        if skip_next_blank and line.strip() == "":
            skip_next_blank = False
            continue
        filtered_lines.append(line)
    return "\n".join(filtered_lines).strip()


def _sampling_rate_label(meta: dict) -> str:
    fs_hz = meta.get("fs_hz")
    try:
        fs_value = float(fs_hz) if fs_hz is not None else 0.0
    except Exception:
        fs_value = 0.0
    return f"{int(fs_value)} Hz" if fs_value > 0.0 else "n/a"

def build_ui_demo(app, parent: tk.Frame) -> None:
    """Demo-friendly UI: no hex dumps, just KPIs + a timeline + a short summary."""
    panel = tk.Frame(parent, bg=app.colors["bg"])
    panel.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

    _card, app.demo_start_button, app.demo_stop_button = app._ui_build_run_header_card(panel)
    app._update_demo_run_controls()

    kpi = tk.Frame(panel, bg=app.colors["bg"])
    kpi.pack(fill=tk.X, pady=(0, 12))

    _build_kpi_card(app, kpi, "Status", app.demo_status_var)
    _build_kpi_card(app, kpi, "Device", app.demo_device_var)
    _build_kpi_card(app, kpi, "Overall", app.demo_overall_var)
    _build_kpi_card(app, kpi, "Waveform", app.demo_waveform_var)

    tl_box = tk.Frame(panel, bg=app.colors["panel"], highlightbackground=app.colors["border"], highlightthickness=1)
    tl_box.pack(fill=tk.X, pady=(0, 12))
    tl_in = tk.Frame(tl_box, bg=app.colors["panel"])
    tl_in.pack(fill=tk.X, padx=14, pady=10)

    tk.Label(tl_in, text="Timeline", bg=app.colors["panel"], fg=app.colors["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")

    tl_row = tk.Frame(tl_in, bg=app.colors["panel"])
    tl_row.pack(fill=tk.X, pady=(6, 0))

    app.demo_timeline_labels = {}
    for key, title in CHECKLIST_ITEMS:
        item = tk.Frame(tl_row, bg=app.colors["panel"])
        item.pack(side=tk.LEFT, padx=(0, 14))

        dot = tk.Label(item, text="●", bg=app.colors["panel"], fg=app.colors["muted"], font=("Segoe UI", 12, "bold"))
        dot.pack(side=tk.LEFT)
        txt = tk.Label(item, text=title, bg=app.colors["panel"], fg=app.colors["muted"], font=("Segoe UI", 10))
        txt.pack(side=tk.LEFT, padx=(6, 0))

        app.demo_timeline_labels[key] = (dot, txt)

    panes = tk.PanedWindow(panel, orient=tk.VERTICAL, bg=app.colors["bg"], sashrelief=tk.RAISED, bd=0)
    panes.pack(fill=tk.BOTH, expand=True)

    sum_box = tk.Frame(panes, bg=app.colors["panel"], highlightbackground=app.colors["border"], highlightthickness=1)
    sum_in = tk.Frame(sum_box, bg=app.colors["panel"])
    sum_in.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)

    tk.Label(sum_in, text="Overalls", bg=app.colors["panel"], fg=app.colors["text"], font=("Segoe UI", 11, "bold")).pack(anchor="w")

    app.demo_summary = tk.Text(sum_in, height=13, wrap=tk.WORD, bg=app.colors["panel"], fg=app.colors["text"], bd=0)
    app.demo_summary.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
    app.demo_summary.configure(state=tk.DISABLED)

    plot_box = tk.Frame(panes, bg=app.colors["panel"], highlightbackground=app.colors["border"], highlightthickness=1)
    plot_in = tk.Frame(plot_box, bg=app.colors["panel"])
    plot_in.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)

    header_row = tk.Frame(plot_in, bg=app.colors["panel"])
    header_row.pack(fill=tk.X)

    tk.Label(header_row, text="Waveform", bg=app.colors["panel"], fg=app.colors["text"], font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT)

    app.demo_plot_label = tk.Label(header_row, text=_WAITING_WAVEFORM_TEXT, bg=app.colors["panel"], fg=app.colors["muted"], font=("Segoe UI", 10))
    app.demo_plot_label.pack(side=tk.LEFT, padx=(10, 0))

    plot_area = tk.Frame(plot_in, bg=app.colors["panel"])
    plot_area.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

    if Figure is None or FigureCanvasTkAgg is None:
        tk.Label(
            plot_area,
            text="Matplotlib/TkAgg not available. Install matplotlib and ensure Tk support to view the waveform plot here.",
            bg=app.colors["panel"],
            fg=app.colors["muted"],
            justify=tk.LEFT,
            wraplength=900,
            font=("Segoe UI", 10),
        ).pack(anchor="w")
        app.demo_plot_fig = None
        app.demo_plot_canvas = None
        app.demo_plot_widget = None
    else:
        app.demo_plot_fig = Figure(figsize=(7.5, 2.3), dpi=100)
        app.demo_plot_fig.subplots_adjust(bottom=0.15, top=0.95)
        ax = app.demo_plot_fig.add_subplot(111)
        ax.set_xlabel("Sample")
        ax.set_ylabel("Value")
        ax.grid(True, alpha=0.2)
        demo_style_plot_axes(app, ax)

        app.demo_plot_canvas = FigureCanvasTkAgg(app.demo_plot_fig, master=plot_area)
        app.demo_plot_widget = app.demo_plot_canvas.get_tk_widget()
        try:
            app.demo_plot_widget.configure(bg=app.colors.get("panel", "#171a21"))
        except Exception:
            pass
        app.demo_plot_widget.pack(fill=tk.BOTH, expand=True)

    panes.add(sum_box, stretch="always")
    panes.add(plot_box, stretch="always")

def demo_style_plot_axes(app, ax) -> None:
    """Apply dark-theme styling to the embedded matplotlib axes."""
    try:
        fc = app.colors.get("panel", "#171a21")
        tc = app.colors.get("text", "#e6e6e6")
        mc = app.colors.get("muted", "#8b93a1")
        bc = app.colors.get("border", "#2a2f3a")

        if getattr(app, "demo_plot_fig", None) is not None:
            app.demo_plot_fig.patch.set_facecolor(fc)
        ax.set_facecolor(fc)

        ax.title.set_color(tc)
        ax.xaxis.label.set_color(mc)
        ax.yaxis.label.set_color(mc)
        ax.tick_params(colors=mc)

        for sp in ax.spines.values():
            sp.set_color(bc)
        try:
            ax.grid(True, alpha=0.25, color=bc)
        except Exception:
            ax.grid(True, alpha=0.25)
    except Exception:
        pass

    app.demo_summary.tag_configure("k", foreground=app.colors["muted"], font=("Segoe UI", 10, "bold"))
    app.demo_summary.tag_configure("v", foreground=app.colors["text"], font=("Segoe UI", 10, "normal"))
    app.demo_summary.tag_configure("h", foreground=app.colors["text"], font=("Segoe UI", 10, "bold"))

    demo_update_timeline(app, {})


def demo_plot_waveform_from_raw_export(app, raw_path: str) -> None:
    """Render waveform in the embedded Demo matplotlib canvas from a raw export .bin file."""
    if not raw_path:
        return
    if app.demo_plot_canvas is None or app.demo_plot_fig is None:
        return
    if not os.path.isfile(raw_path):
        raise FileNotFoundError(raw_path)

    y, meta = WaveformParser.extract_true_waveform_samples(raw_path)

    try:
        n = int(meta.get("samples") or len(y))
    except Exception:
        n = len(y)

    twf_type = meta.get("twf_type", "Unknown")
    data_type = meta.get("data_type", "S16")

    info_parts = [f"{n} samples"]
    info_parts.append(f"Sampling rate: {_sampling_rate_label(meta)}")
    info_parts.append(data_type)
    info_parts.append(twf_type)
    info_parts.append(os.path.basename(raw_path))

    if app.demo_plot_label is not None:
        app.demo_plot_label.configure(text=" • ".join(info_parts))

    ax = app.demo_plot_fig.axes[0] if app.demo_plot_fig.axes else app.demo_plot_fig.add_subplot(111)
    ax.clear()
    ax.plot(y)
    ax.set_xlabel("Sample")
    ax.set_ylabel("Amplitude (int16)")
    ax.grid(True, alpha=0.2)
    demo_style_plot_axes(app, ax)
    app.demo_plot_canvas.draw()


def demo_update_timeline(app, checklist_update: Dict[str, str]) -> None:
    """Update the Demo timeline dots based on the merged checklist state."""
    if checklist_update:
        for k, v in checklist_update.items():
            if k in app.demo_checklist_state:
                app.demo_checklist_state[k] = v

    for key, _title in CHECKLIST_ITEMS:
        state = app.demo_checklist_state.get(key, "pending")
        dot, txt = app.demo_timeline_labels.get(key, (None, None))
        if dot is None or txt is None:
            continue

        if state == "done":
            fg = app.colors.get("ok", app.colors["accent_alt"])
            tfg = app.colors["text"]
        elif state == "in_progress":
            fg = app.colors["accent_alt"]
            tfg = app.colors["text"]
        else:
            fg = app.colors["muted"]
            tfg = app.colors["muted"]

        dot.configure(fg=fg)
        txt.configure(fg=tfg)


def demo_set_kpis_from_rx_text(app, rx_text: str, export_info: Optional[dict]) -> None:
    """Update Demo KPIs (Overall/Waveform) based on the latest received message text."""
    if not rx_text:
        return

    if export_info:
        if export_info.get("samples") or export_info.get("raw") or export_info.get("index"):
            try:
                count = int(export_info.get("count") or 0)
            except Exception:
                count = 0
            pts = count * 64 if count else 4096
            app.demo_waveform_var.set(f"OK ({pts} points)")
            path = export_info.get("samples") or export_info.get("index") or export_info.get("raw") or ""
            app.demo_export_var.set(path)


def demo_render_summary(app, rx_text: str, overall_values: Optional[list] = None) -> None:
    """Render the Demo 'Overalls' panel."""
    if app.demo_summary is None:
        return

    if rx_text and ("=== OVERALL MEASUREMENTS ===" in rx_text or "=== SESSION ACCEPTED ===" in rx_text):
        display_text = _extract_formatted_rx_text(rx_text)

        now_s = time.strftime("%H:%M:%S")
        header = f"Last update: {now_s}\n\n"

        app.demo_summary.configure(state=tk.NORMAL)
        app.demo_summary.delete("1.0", tk.END)

        try:
            app.demo_summary.configure(font=("Consolas", 10))
        except Exception:
            pass

        app.demo_summary.insert(tk.END, header + display_text + "\n")
        app.demo_summary.configure(state=tk.DISABLED)
        return

    items = overall_values or []

    now_s = time.strftime("%H:%M:%S")
    header = f"Last update: {now_s}   •   Metrics: {len(items) if items else 0}\n\n"

    lines = []
    if items:
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
            val = " ".join(val.split())
            lines.append(f"{lbl:<28} {val}")
            det = str(it.get("details", "") or "").rstrip()
            if det:
                lines.append(det)
    else:
        msg_type = ""
        try:
            mm = _MSG_TYPE_RE.search((rx_text or "").strip())
            msg_type = mm.group(1).strip() if mm else ""
        except Exception:
            msg_type = ""
        lines.append("•")
        if msg_type:
            lines.append(f"(last message: {msg_type})")

    app.demo_summary.configure(state=tk.NORMAL)
    app.demo_summary.delete("1.0", tk.END)

    try:
        app.demo_summary.configure(font=("Consolas", 10))
    except Exception:
        pass

    app.demo_summary.insert(tk.END, header)
    app.demo_summary.insert(tk.END, "\n".join(lines) + "\n")
    app.demo_summary.configure(state=tk.DISABLED)
