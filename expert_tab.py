import tkinter as tk
from tkinter import ttk
from ui_config import MANUAL_ACTIONS


def build_ui_expert(app, parent: tk.Frame) -> None:
    _card, app.start_button, app.stop_auto_button = app._ui_build_run_header_card(parent)
    app._update_demo_run_controls()

    filter_box = tk.Frame(parent, bg=app.colors["panel"], highlightbackground=app.colors["border"], highlightthickness=1)
    filter_box.pack(fill=tk.X, padx=16, pady=(0, 8))
    filter_in = tk.Frame(filter_box, bg=app.colors["panel"])
    filter_in.pack(fill=tk.X, padx=14, pady=10)

    title_row = tk.Frame(filter_in, bg=app.colors["panel"])
    title_row.pack(fill=tk.X, pady=(0, 6))
    tk.Label(
        title_row,
        text="🔍 Filters",
        bg=app.colors["panel"],
        fg=app.colors["text"],
        font=("Segoe UI", 10, "bold"),
    ).pack(side=tk.LEFT)

    form = tk.Frame(filter_in, bg=app.colors["panel"])
    form.pack(fill=tk.X)

    build_field(app, form, "Address prefix", app.address_prefix_var)
    build_field(app, form, "ADV name contains", app.adv_name_contains_var)

    manual_card = tk.Frame(parent, bg=app.colors["panel"], highlightbackground=app.colors["border"], highlightthickness=1)
    manual_card.pack(fill=tk.X, padx=16, pady=(0, 12))
    manual = tk.Frame(manual_card, bg=app.colors["panel"])
    manual.pack(fill=tk.X, padx=14, pady=10)

    title_row = tk.Frame(manual, bg=app.colors["panel"])
    title_row.pack(fill=tk.X, pady=(0, 8))
    tk.Label(
        title_row,
        text="⚡ Manual Commands",
        bg=app.colors["panel"],
        fg=app.colors["text"],
        font=("Segoe UI", 10, "bold"),
    ).pack(side=tk.LEFT)

    manual_btns = tk.Frame(manual, bg=app.colors["panel"])
    manual_btns.pack(fill=tk.X, pady=(0, 8))

    buttons = []
    for text_, action_ in MANUAL_ACTIONS:
        btn = ttk.Button(manual_btns, text=text_, width=20, command=lambda a=action_: app._start_manual_action(a))
        buttons.append(btn)
    wrap_buttons(app, manual_btns, buttons, min_btn_px=180)

    sep = tk.Frame(manual, bg=app.colors["border"], height=1)
    sep.pack(fill=tk.X, pady=(0, 8))

    util = tk.Frame(manual, bg=app.colors["panel"])
    util.pack(fill=tk.X)

    util_btns = [
        ttk.Button(util, text="Clear logs", width=20, command=app._clear_tiles),
        ttk.Button(util, text="Plot Latest", width=20, command=app._plot_latest_waveform),
    ]
    wrap_buttons(app, util, util_btns, min_btn_px=180)

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
    app.root.after(0, _relayout)


def build_field(app, parent: tk.Frame, label: str, variable: tk.StringVar, width: int = 16) -> None:
    parent_bg = parent.cget("bg") if hasattr(parent, "cget") else app.colors["bg"]
    row = tk.Frame(parent, bg=parent_bg)
    row.pack(side=tk.LEFT, padx=(0, 12))
    tk.Label(row, text=label, bg=parent_bg, fg=app.colors["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
    entry = ttk.Entry(row, textvariable=variable, width=width)
    entry.pack(anchor="w")


def on_mouse_wheel(app, event: tk.Event) -> None:
    if not app.canvas.winfo_exists():
        return
    if event.delta == 0:
        return
    direction = -1 if event.delta > 0 else 1
    app.canvas.yview_scroll(direction, "units")
