"""
UI Helpers - Reusable Tkinter utilities for styling and widget creation.

Contains:
- Windows-specific customization (dark mode, borders)
- TTK theme configuration
- Widget factory helpers
"""

import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, Optional, Tuple


ColorPalette = Dict[str, str]

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_BORDER_COLOR = 34
_DWMWA_CAPTION_COLOR = 35

_DWMWCP_ROUND = 2
_TITLE_COLORREF = 0x00211A17
_BORDER_COLORREF = 0x003A2F2A

_DEFAULT_CARD_PACK = {"fill": tk.X, "padx": 16, "pady": (16, 12)}
_DEFAULT_TEXT_PACK = {"fill": tk.BOTH, "expand": True}
_DEFAULT_TEXT_FONT = ("Consolas", 10)


def _dwm_set_window_attribute(ctypes_module, hwnd: int, attribute: int, value: int) -> None:
    """Set one DWM window attribute (Windows-only helper)."""
    ctypes_module.windll.dwmapi.DwmSetWindowAttribute(
        hwnd,
        attribute,
        ctypes_module.byref(ctypes_module.c_int(value)),
        ctypes_module.sizeof(ctypes_module.c_int),
    )


def _configure_combobox_popup_colors(root: tk.Tk, colors: ColorPalette) -> None:
    """Apply dark popup Listbox colors used by readonly comboboxes."""
    root.option_add("*TCombobox*Listbox*Background", colors["panel"])
    root.option_add("*TCombobox*Listbox*Foreground", colors["text"])
    root.option_add("*TCombobox*Listbox*selectBackground", colors["accent"])
    root.option_add("*TCombobox*Listbox*selectForeground", colors["text"])


def apply_windows_dark_mode(root: tk.Tk) -> None:
    """
    Apply Windows-specific window customization (dark mode, borders, rounded corners).
    
    Works on Windows 10 1809+ for dark title bar.
    Additional features (caption color, borders, rounded corners) require Windows 11 22000+.
    
    Args:
        root: The Tk root window to customize
    """
    try:
        import ctypes

        # Force window update to ensure it's rendered
        root.update_idletasks()

        # Get window handle - try both methods
        try:
            hwnd = int(root.wm_frame(), 16)  # Try frame method first (more reliable)
        except Exception:
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id())

        _dwm_set_window_attribute(ctypes, hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, 1)

        # Windows 11 22000+ specific enhancements
        try:
            _dwm_set_window_attribute(ctypes, hwnd, _DWMWA_CAPTION_COLOR, _TITLE_COLORREF)
            _dwm_set_window_attribute(ctypes, hwnd, _DWMWA_BORDER_COLOR, _BORDER_COLORREF)
            _dwm_set_window_attribute(ctypes, hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_ROUND)
        except Exception:
            pass  # Windows 11 APIs not available (Windows 10)

    except Exception:
        pass  # Not on Windows or API not available


def apply_dark_theme(root: tk.Tk, colors: ColorPalette) -> None:
    """
    Apply dark theme styling to TTK widgets.
    
    Configures styles for: Frame, Label, Entry, Button, Combobox, 
    Scrollbar, Notebook, Treeview.
    
    Args:
        root: The Tk root window
        colors: Color palette dict with keys: bg, panel, panel_alt, text, 
                muted, accent, accent_alt, border
    """
    style = ttk.Style(root)
    style.theme_use("clam")
    
    # Basic widgets
    style.configure("TFrame", background=colors["bg"])
    style.configure("TLabel", 
        background=colors["bg"], 
        foreground=colors["text"], 
        font=("Segoe UI", 10))
    style.configure("Header.TLabel", 
        background=colors["panel"], 
        foreground=colors["text"], 
        font=("Segoe UI", 14, "bold"))
    style.configure("Subtle.TLabel", 
        background=colors["bg"], 
        foreground=colors["muted"])
    style.configure("TEntry", 
        fieldbackground=colors["panel_alt"], 
        foreground=colors["text"], 
        insertcolor=colors["text"])
    
    # Buttons
    style.configure("TButton", 
        background=colors["panel"], 
        foreground=colors["text"], 
        padding=(10, 6))
    style.configure("Accent.TButton", 
        background=colors["accent"], 
        foreground="#0b0f14", 
        padding=(10, 6))
    style.map("Accent.TButton", 
        background=[("active", colors["accent_alt"])])
    
    # Combobox dark theme
    style.configure("TCombobox", 
        fieldbackground=colors["panel_alt"],
        background=colors["panel"],
        foreground=colors["text"],
        arrowcolor=colors["text"],
        borderwidth=0)
    style.map("TCombobox",
        fieldbackground=[("readonly", colors["panel_alt"])],
        selectbackground=[("readonly", colors["accent"])],
        selectforeground=[("readonly", colors["text"])])
    
    # Scrollbar dark theme
    style.configure("Vertical.TScrollbar",
        background=colors["panel"],
        troughcolor=colors["bg"],
        borderwidth=0,
        arrowcolor=colors["text"])
    style.map("Vertical.TScrollbar",
        background=[("active", colors["panel_alt"])])

    _configure_combobox_popup_colors(root, colors)

    # Notebook (tabs) styling - modern dark theme with equal width tabs
    style.configure("TNotebook", 
        background=colors["bg"],
        borderwidth=0,
        tabmargins=0)
    
    style.configure("TNotebook.Tab",
        background=colors["panel_alt"],
        foreground=colors["muted"],
        padding=(50, 12),
        borderwidth=0,
        focuscolor="none",
        font=("Segoe UI", 10, "bold"))
    
    style.map("TNotebook.Tab",
        background=[("selected", colors["panel"]), ("active", colors["panel_alt"])],
        foreground=[("selected", colors["accent"]), ("active", colors["text"])],
        padding=[("selected", (50, 12))])  # Expand selected tab slightly

    # Treeview dark theme
    style.configure("Treeview",
        background=colors["panel"],
        foreground=colors["text"],
        fieldbackground=colors["panel"],
        borderwidth=0)
    style.configure("Treeview.Heading",
        background=colors["panel_alt"],
        foreground=colors["text"],
        borderwidth=1,
        relief="flat")
    style.map("Treeview",
        background=[("selected", colors["accent"])],
        foreground=[("selected", "#ffffff")])
    style.map("Treeview.Heading",
        background=[("active", colors["border"])])


def create_card(parent: tk.Widget, colors: ColorPalette, **pack_kwargs) -> Tuple[tk.Frame, tk.Frame]:
    """
    Create a styled card container (Frame with border).
    
    Args:
        parent: Parent widget
        colors: Color palette dict
        **pack_kwargs: Additional pack() options (padx, pady, etc.)
        
    Returns:
        Tuple of (card_frame, inner_frame) - populate inner_frame with content
    """
    card = tk.Frame(
        parent, 
        bg=colors["panel"], 
        highlightbackground=colors["border"], 
        highlightthickness=1
    )
    
    pack_options = dict(_DEFAULT_CARD_PACK)
    pack_options.update(pack_kwargs)
    card.pack(**pack_options)
    
    inner = tk.Frame(card, bg=colors["panel"])
    inner.pack(fill=tk.X, padx=14, pady=12)
    
    return card, inner


def create_labeled_entry(
    parent: tk.Widget, 
    label_text: str,
    colors: ColorPalette,
    default_value: str = "",
    width: int = 20
) -> Tuple[tk.Frame, tk.Label, ttk.Entry, tk.StringVar]:
    """
    Create a labeled entry widget in a horizontal layout.
    
    Args:
        parent: Parent widget
        label_text: Label text to display
        colors: Color palette dict
        default_value: Initial value for entry
        width: Entry widget width in characters
        
    Returns:
        Tuple of (frame, label, entry, textvariable)
    """
    frame = tk.Frame(parent, bg=colors["bg"])
    
    label = tk.Label(
        frame,
        text=label_text,
        bg=colors["bg"],
        fg=colors["text"],
        font=("Segoe UI", 10)
    )
    label.pack(side=tk.LEFT, padx=(0, 8))
    
    var = tk.StringVar(value=default_value)
    entry = ttk.Entry(frame, textvariable=var, width=width)
    entry.pack(side=tk.LEFT)
    
    return frame, label, entry, var


def create_text_widget(
    parent: tk.Widget,
    colors: ColorPalette,
    wrap: str = tk.WORD,
    font: Optional[Tuple[Any, ...]] = None,
    **pack_kwargs
) -> tk.Text:
    """
    Create a styled Text widget with dark theme.
    
    Args:
        parent: Parent widget
        colors: Color palette dict
        wrap: Text wrapping mode (tk.WORD, tk.CHAR, tk.NONE)
        font: Font tuple (family, size, style) or None for default
        **pack_kwargs: Additional pack() options
        
    Returns:
        Configured Text widget
    """
    if font is None:
        font = _DEFAULT_TEXT_FONT
    
    text_widget = tk.Text(
        parent,
        wrap=wrap,
        bg=colors["panel"],
        fg=colors["text"],
        insertbackground=colors["text"],
        selectbackground=colors["accent"],
        selectforeground=colors["text"],
        font=font,
        borderwidth=0,
        highlightthickness=0,
        padx=10,
        pady=10
    )
    
    pack_options = dict(_DEFAULT_TEXT_PACK)
    pack_options.update(pack_kwargs)
    text_widget.pack(**pack_options)
    
    return text_widget


__all__ = [
    "apply_windows_dark_mode",
    "apply_dark_theme",
    "create_card",
    "create_labeled_entry",
    "create_text_widget",
]
