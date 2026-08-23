# -*- coding: utf-8 -*-
"""Оформление: палитры Catppuccin Mocha (тёмная) и Latte (светлая), генератор
QSS и свето/тёмный тайтлбар окна для Windows."""
import sys

# Catppuccin Mocha (тёмная) и Latte (светлая) — совпадают с семейством тем
# Catppuccin в VS Code у пользователя.
PALETTE_DARK = {
    "bg": "#181825", "surface": "#1e1e2e", "surface2": "#11111b",
    "border": "#313244", "text": "#cdd6f4", "subtext": "#a6adc8",
    "accent": "#cba6f7", "accent_text": "#11111b", "accent_hover": "#d9bbff",
    "success": "#a6e3a1", "warn": "#f9e2af", "error": "#f38ba8",
    "track": "#45475a", "input_bg": "#313244", "input_text": "#cdd6f4",
}
PALETTE_LIGHT = {
    "bg": "#e6e9ef", "surface": "#eff1f5", "surface2": "#dce0e8",
    "border": "#bcc0cc", "text": "#4c4f69", "subtext": "#6c6f85",
    "accent": "#8839ef", "accent_text": "#eff1f5", "accent_hover": "#9d5cf5",
    "success": "#40a02b", "warn": "#df8e1d", "error": "#d20f39",
    "track": "#ccd0da", "input_bg": "#ffffff", "input_text": "#4c4f69",
}
PALETTES = {"dark": PALETTE_DARK, "light": PALETTE_LIGHT}


def _mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    r, g, bl = (max(0, min(255, round(x + (y - x) * t))) for x, y in zip(a, b))
    return f"#{r:02x}{g:02x}{bl:02x}"


def _rgba(color, a):
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {a})"


def build_qss(p: dict) -> str:
    hov = _mix(p["surface"], p["text"], 0.08)
    return f"""
QWidget {{ background: {p["bg"]}; color: {p["text"]}; font-family: "Segoe UI"; font-size: 10pt; }}
QLabel {{ background: transparent; }}
QToolTip {{
    background: {p["surface2"]}; color: {p["text"]};
    border: 1px solid {p["accent"]}; border-radius: 6px; padding: 6px 8px;
}}

QFrame#Header {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {_mix(p["surface"], p["accent"], 0.16)}, stop:1 {p["surface"]});
    border: 1px solid {p["border"]}; border-radius: 16px;
}}
QLabel#Title {{ font-size: 19pt; font-weight: 800; color: {p["text"]}; letter-spacing: 0.3px; }}
QLabel#Subtitle {{ font-size: 10pt; color: {p["subtext"]}; }}

QFrame#Card {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {_mix(p["surface"], p["text"], 0.03)}, stop:1 {p["surface"]});
    border: 1px solid {p["border"]}; border-radius: 14px;
}}
QFrame#CatCard {{
    background: {p["surface"]}; border: 1px solid {p["border"]}; border-radius: 12px;
}}
QFrame#CatCard:hover {{ border-color: {_rgba(p["accent"], 0.55)}; background: {hov}; }}
QFrame#CatCard[on="true"] {{
    border: 1px solid {p["accent"]};
    background: {_rgba(p["accent"], 0.10)};
}}
QWidget#CatInner {{ background: transparent; }}
QFrame#Strip_heavy {{ background: {p["error"]};
    border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
QFrame#Strip_medium {{ background: {p["warn"]};
    border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
QFrame#Strip_light {{ background: {p["success"]};
    border-top-left-radius: 11px; border-bottom-left-radius: 11px; }}
QLabel#Section {{ color: {p["subtext"]}; font-size: 9pt; font-weight: bold; letter-spacing: 1px; }}
QLabel#CatTitle {{ font-size: 11pt; font-weight: bold; color: {p["text"]}; }}
QLabel#CatNote {{ color: {p["subtext"]}; font-size: 9pt; }}
QLabel#Warn {{
    color: {p["error"]}; background: {_rgba(p["error"], 0.12)};
    border: 1px solid {_rgba(p["error"], 0.35)}; border-radius: 10px;
    padding: 8px 12px; font-weight: bold;
}}
QLabel#Summary {{ font-size: 11pt; font-weight: bold; color: {p["text"]}; }}

QLabel#Count {{
    color: {p["accent"]}; background: {_rgba(p["accent"], 0.14)};
    border-radius: 9px; padding: 3px 10px; font-size: 9pt; font-weight: bold;
    min-width: 44px; qproperty-alignment: AlignCenter;
}}
QLabel#Wheavy {{ color: {p["error"]};  background: {_rgba(p["error"], 0.14)};
    border-radius: 9px; padding: 3px 10px; font-size: 8pt; font-weight: bold;
    min-width: 62px; qproperty-alignment: AlignCenter; }}
QLabel#Wmedium {{ color: {p["warn"]}; background: {_rgba(p["warn"], 0.14)};
    border-radius: 9px; padding: 3px 10px; font-size: 8pt; font-weight: bold;
    min-width: 62px; qproperty-alignment: AlignCenter; }}
QLabel#Wlight {{ color: {p["success"]}; background: {_rgba(p["success"], 0.12)};
    border-radius: 9px; padding: 3px 10px; font-size: 8pt; font-weight: bold;
    min-width: 62px; qproperty-alignment: AlignCenter; }}
QLabel#Woff {{ color: {p["subtext"]}; background: {_rgba(p["subtext"], 0.10)};
    border-radius: 9px; padding: 3px 10px; font-size: 8pt; font-weight: bold;
    min-width: 62px; qproperty-alignment: AlignCenter; }}

QPushButton {{
    background: {p["input_bg"]}; color: {p["text"]};
    border: 1px solid {p["border"]}; border-radius: 8px; padding: 7px 14px;
}}
QPushButton:hover {{ background: {hov}; border-color: {p["accent"]}; }}
QPushButton:pressed {{ background: {_mix(p["surface"], p["surface2"], 0.5)}; }}
QPushButton:disabled {{ color: {p["subtext"]}; background: {p["surface"]}; }}
QPushButton#Accent {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {p["accent_hover"]}, stop:1 {p["accent"]});
    color: {p["accent_text"]}; border: 1px solid {p["accent"]};
    border-radius: 11px; font-size: 11pt; font-weight: bold; padding: 12px 22px;
}}
QPushButton#Accent:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {_mix(p["accent_hover"], "#ffffff", 0.18)}, stop:1 {p["accent_hover"]});
}}
QPushButton#Accent:pressed {{ background: {p["accent"]}; }}
QPushButton#Ghost {{ background: transparent; border: 1px solid {p["border"]}; color: {p["subtext"]}; }}
QPushButton#Ghost:hover {{ color: {p["text"]}; border-color: {p["accent"]}; background: {_rgba(p["accent"], 0.10)}; }}
QPushButton#Danger {{ background: transparent; border: 1px solid {_rgba(p["error"], 0.40)}; color: {p["error"]}; }}
QPushButton#Danger:hover {{ border-color: {p["error"]}; background: {_rgba(p["error"], 0.14)}; }}
QPushButton#Danger:disabled {{ color: {p["subtext"]}; border-color: {p["border"]}; }}

QLineEdit, QPlainTextEdit {{
    background: {p["input_bg"]}; color: {p["input_text"]};
    border: 1px solid {p["border"]}; border-radius: 8px; padding: 7px 10px;
    selection-background-color: {p["accent"]}; selection-color: {p["accent_text"]};
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {p["accent"]}; }}
QPlainTextEdit#Log {{
    background: {p["surface2"]}; color: {p["subtext"]};
    font-family: "Consolas", monospace; font-size: 9pt; border-radius: 10px;
}}
QComboBox {{
    background: {p["input_bg"]}; color: {p["input_text"]};
    border: 1px solid {p["border"]}; border-radius: 8px; padding: 6px 10px; min-height: 18px;
}}
QComboBox:hover, QComboBox:focus {{ border-color: {p["accent"]}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {p["subtext"]}; margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {p["input_bg"]}; color: {p["input_text"]};
    border: 1px solid {p["border"]}; border-radius: 8px; padding: 4px; outline: none;
    selection-background-color: {p["accent"]}; selection-color: {p["accent_text"]};
}}

QCheckBox {{ background: transparent; spacing: 9px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border: 1px solid {p["border"]};
    background: {p["input_bg"]}; border-radius: 6px;
}}
QCheckBox::indicator:hover {{ border-color: {p["accent"]}; }}
QCheckBox::indicator:checked {{ background: {p["accent"]}; border-color: {p["accent"]}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p["track"]}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p["accent"]}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QFrame#HLine {{ background: {p["border"]}; border: none; max-height: 1px; }}
"""


def apply_titlebar(widget, dark: bool = True) -> None:
    """Тёмная/светлая рамка и заголовок окна на Windows 10/11. Другие ОС — no-op."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE: 20 новое, 19 старое
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass
