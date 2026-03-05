"""Settings tab UI builder.

Public API consumed by `ui_application.py`:
- build_ui_settings

This tab groups runtime configuration fields used by worker cycles.
"""

import tkinter as tk
from tkinter import ttk

_ROW_PAD_Y = (10, 0)


def _build_header(app, parent: tk.Frame) -> None:
    header = tk.Frame(parent, bg=app.colors["panel"], highlightbackground=app.colors["border"], highlightthickness=1)
    header.pack(fill=tk.X, padx=16, pady=(16, 10))

    left = tk.Frame(header, bg=app.colors["panel"])
    left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=12, pady=12)
    tk.Label(left, text="Settings", bg=app.colors["panel"], fg=app.colors["text"], font=("Segoe UI", 14, "bold")).pack(anchor="w")
    tk.Label(left, text="Configuration and defaults", bg=app.colors["panel"], fg=app.colors["muted"]).pack(anchor="w", pady=(2, 0))

def build_ui_settings(app, parent: tk.Frame) -> None:
    """Build the Settings tab controls used by scan/cycle runtime."""
    _build_header(app, parent)

    body = tk.Frame(parent, bg=app.colors["bg"])
    body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))

    box = tk.Frame(body, bg=app.colors["panel"], highlightbackground=app.colors["border"], highlightthickness=1)
    box.pack(fill=tk.X)
    inner = tk.Frame(box, bg=app.colors["panel"])
    inner.pack(fill=tk.X, padx=12, pady=12)

    ttk.Checkbutton(inner, text="Record sessions", variable=app.record_sessions_var).grid(row=0, column=0, sticky="w", padx=(0, 12))
    tk.Label(inner, text="Session dir", bg=app.colors["panel"], fg=app.colors["muted"]).grid(row=0, column=1, sticky="e", padx=(12, 6))
    ttk.Entry(inner, textvariable=app.session_root_var, width=24).grid(row=0, column=2, sticky="w")

    tk.Label(inner, text="Scan timeout (s)", bg=app.colors["panel"], fg=app.colors["muted"]).grid(row=1, column=0, sticky="w", pady=_ROW_PAD_Y)
    ttk.Entry(inner, textvariable=app.scan_timeout_var, width=10).grid(row=1, column=1, sticky="w", pady=_ROW_PAD_Y)

    tk.Label(inner, text="RX timeout (s)", bg=app.colors["panel"], fg=app.colors["muted"]).grid(row=1, column=2, sticky="w", padx=(12, 0), pady=_ROW_PAD_Y)
    ttk.Entry(inner, textvariable=app.rx_timeout_var, width=10).grid(row=1, column=3, sticky="w", pady=_ROW_PAD_Y)

    tk.Label(inner, text="MTU", bg=app.colors["panel"], fg=app.colors["muted"]).grid(row=2, column=0, sticky="w", pady=_ROW_PAD_Y)
    ttk.Entry(inner, textvariable=app.mtu_var, width=10).grid(row=2, column=1, sticky="w", pady=_ROW_PAD_Y)

    util = tk.Frame(body, bg=app.colors["bg"])
    util.pack(fill=tk.X, pady=(12, 0))
    ttk.Button(util, text="Clear Logs", command=app._clear_tiles).pack(side=tk.LEFT)
    ttk.Button(util, text="Stop Auto", command=app._stop_auto).pack(side=tk.LEFT, padx=(8, 0))
