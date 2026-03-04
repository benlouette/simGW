"""Expert tab UI builders and layout helpers.

Public API consumed by `ui_application.py`:
- build_ui_expert

Internal helpers:
- wrap_buttons
- build_field
- on_mouse_wheel
"""

import tkinter as tk
from tkinter import ttk

from ui_config import MANUAL_ACTIONS

_BUTTON_WIDTH = 20
_WRAP_MIN_BUTTON_PX = 180


def _build_card(parent: tk.Widget, colors: dict, pady: tuple[int, int]) -> tk.Frame:
    card = tk.Frame(parent, bg=colors["panel"], highlightbackground=colors["border"], highlightthickness=1)
    card.pack(fill=tk.X, padx=16, pady=pady)
    inner = tk.Frame(card, bg=colors["panel"])
    inner.pack(fill=tk.X, padx=14, pady=10)
    return inner


def _build_section_title(parent: tk.Widget, colors: dict, text: str) -> None:
    title_row = tk.Frame(parent, bg=colors["panel"])
    title_row.pack(fill=tk.X, pady=(0, 8))
    tk.Label(
        title_row,
        text=text,
        bg=colors["panel"],
        fg=colors["text"],
        font=("Segoe UI", 10, "bold"),
    ).pack(side=tk.LEFT)


def build_ui_expert(app, parent: tk.Frame) -> None:
    """Build the Expert tab (filters, manual actions, and scrollable tile list)."""
    _card, app.start_button, app.stop_auto_button = app._ui_build_run_header_card(parent)
    app._update_demo_run_controls()

    filter_in = _build_card(parent, app.colors, pady=(0, 8))
    _build_section_title(filter_in, app.colors, "🔍 Filters")

    form = tk.Frame(filter_in, bg=app.colors["panel"])
    form.pack(fill=tk.X)

    build_field(app, form, "Address prefix", app.address_prefix_var)
    build_field(app, form, "ADV name contains", app.adv_name_contains_var)

    manual = _build_card(parent, app.colors, pady=(0, 12))
    _build_section_title(manual, app.colors, "⚡ Manual Commands")

    manual_btns = tk.Frame(manual, bg=app.colors["panel"])
    manual_btns.pack(fill=tk.X, pady=(0, 8))

    buttons = []
    for label_text, action_name in MANUAL_ACTIONS:
        button = ttk.Button(manual_btns, text=label_text, width=_BUTTON_WIDTH, command=lambda a=action_name: app._start_manual_action(a))
        buttons.append(button)
    wrap_buttons(app, manual_btns, buttons, min_btn_px=_WRAP_MIN_BUTTON_PX)

    sep = tk.Frame(manual, bg=app.colors["border"], height=1)
    sep.pack(fill=tk.X, pady=(0, 8))

    util = tk.Frame(manual, bg=app.colors["panel"])
    util.pack(fill=tk.X)

    util_btns = [
        ttk.Button(util, text="Clear logs", width=_BUTTON_WIDTH, command=app._clear_tiles),
        ttk.Button(util, text="Plot Latest", width=_BUTTON_WIDTH, command=app._plot_latest_waveform),
    ]
    wrap_buttons(app, util, util_btns, min_btn_px=_WRAP_MIN_BUTTON_PX)

    tiles_frame = tk.Frame(parent, bg=app.colors["bg"])
    tiles_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(12, 16))

    app.canvas = tk.Canvas(tiles_frame, bg=app.colors["bg"], highlightthickness=0)
    scrollbar = ttk.Scrollbar(tiles_frame, orient="vertical", command=app.canvas.yview)
    app.tiles_container = tk.Frame(app.canvas, bg=app.colors["bg"])

    app.tiles_container.bind(
        "<Configure>",
        lambda event: app.canvas.configure(scrollregion=app.canvas.bbox("all")),
    )
    app.canvas.create_window((0, 0), window=app.tiles_container, anchor="nw")
    app.canvas.configure(yscrollcommand=scrollbar.set)

    app.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    app.canvas.bind_all("<MouseWheel>", lambda event: on_mouse_wheel(app, event))
    app.canvas.bind_all("<Shift-MouseWheel>", lambda event: on_mouse_wheel(app, event))


def wrap_buttons(app, container: tk.Frame, buttons: list, min_btn_px: int = 140) -> None:
    """Lay out buttons in a responsive wrapping grid based on container width."""
    state = {"cols": 0}

    def _relayout(_evt=None) -> None:
        try:
            container_width = int(container.winfo_width())
        except Exception:
            container_width = 0

        columns = max(1, container_width // max(1, int(min_btn_px)))
        if columns == state["cols"]:
            return

        state["cols"] = columns

        for child in container.winfo_children():
            child.grid_forget()

        for index, button in enumerate(buttons):
            row = index // columns
            column = index % columns
            button.grid(row=row, column=column, padx=(0, 8), pady=(0, 8), sticky="w")

        for column in range(columns):
            try:
                container.grid_columnconfigure(column, weight=1)
            except Exception:
                pass

    container.bind("<Configure>", _relayout)
    app.root.after(0, _relayout)


def build_field(app, parent: tk.Frame, label: str, variable: tk.StringVar, width: int = 16) -> None:
    """Build one label + entry filter field in Expert filter row."""
    parent_bg = parent.cget("bg") if hasattr(parent, "cget") else app.colors["bg"]
    row = tk.Frame(parent, bg=parent_bg)
    row.pack(side=tk.LEFT, padx=(0, 12))
    tk.Label(row, text=label, bg=parent_bg, fg=app.colors["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
    entry = ttk.Entry(row, textvariable=variable, width=width)
    entry.pack(anchor="w")


def on_mouse_wheel(app, event: tk.Event) -> None:
    """Scroll the Expert tiles canvas using mouse wheel."""
    if not app.canvas.winfo_exists():
        return
    if event.delta == 0:
        return
    direction = -1 if event.delta > 0 else 1
    app.canvas.yview_scroll(direction, "units")
