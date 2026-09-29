# -*- coding: utf-8 -*-
"""Оформление: палитра Catppuccin Mocha (совпадает с темой VS Code у
пользователя), генератор QSS и тёмный тайтлбар для Windows."""

import sys

# Catppuccin Mocha (тёмная) и Latte (светлая) — совпадают с семейством тем
# Catppuccin в VS Code у пользователя.
PALETTE_DARK = {
    "bg": "#181825",
    "surface": "#1e1e2e",
    "surface2": "#11111b",
    "border": "#313244",
    "text": "#cdd6f4",
    "subtext": "#a6adc8",
    "accent": "#cba6f7",
    "accent_text": "#11111b",
    "accent_hover": "#d9bbff",
    "success": "#a6e3a1",
    "warn": "#f9e2af",
    "error": "#f38ba8",
    "track": "#45475a",
    "input_bg": "#313244",
    "input_text": "#cdd6f4",
}
PALETTE_LIGHT = {
    "bg": "#e6e9ef",
    "surface": "#eff1f5",
    "surface2": "#dce0e8",
    "border": "#bcc0cc",
    "text": "#4c4f69",
    "subtext": "#6c6f85",
    "accent": "#8839ef",
    "accent_text": "#eff1f5",
    "accent_hover": "#9d5cf5",
    "success": "#40a02b",
    "warn": "#df8e1d",
    "error": "#d20f39",
    "track": "#ccd0da",
    "input_bg": "#ffffff",
    "input_text": "#4c4f69",
}
PALETTES = {"dark": PALETTE_DARK, "light": PALETTE_LIGHT}
PALETTE = PALETTE_DARK  # тема по умолчанию / обратная совместимость

# Наборы палитр — те же, что в окне настроек cpp-docs-panel (Настройки → Палитра):
# фон, панели, текст, акцент, свечение и цвета статусов. Картинка — пейзаж для
# баннера и превью (assets/palettes/<ключ>.jpg). В светлой теме набор меняет
# только акцент: фон остаётся светлым Latte, акцент затемняется под контраст.
PALETTE_SETS: dict[str, dict] = {
    "mocha": {"name": "Catppuccin", "bg": "#181825", "panel": "#1e1e2e", "code": "#11111b",
              "fg": "#cdd6f4", "muted": "#a6adc8", "ac": "#cba6f7", "glow": "#89b4fa",
              "ok": "#a6e3a1", "bad": "#f38ba8", "warn": "#f9e2af"},
    "tokyo": {"name": "Tokyo Night", "bg": "#1a1b26", "panel": "#1f2335", "code": "#16161e",
              "fg": "#c0caf5", "muted": "#a9b1d6", "ac": "#7aa2f7", "glow": "#bb9af7",
              "ok": "#9ece6a", "bad": "#f7768e", "warn": "#e0af68"},
    "dracula": {"name": "Dracula", "bg": "#21222c", "panel": "#282a36", "code": "#191a21",
                "fg": "#f8f8f2", "muted": "#bfc3d9", "ac": "#bd93f9", "glow": "#ff79c6",
                "ok": "#50fa7b", "bad": "#ff5555", "warn": "#f1fa8c"},
    "nord": {"name": "Nord", "bg": "#2e3440", "panel": "#353c4a", "code": "#272c36",
             "fg": "#eceff4", "muted": "#d8dee9", "ac": "#88c0d0", "glow": "#81a1c1",
             "ok": "#a3be8c", "bad": "#bf616a", "warn": "#ebcb8b"},
    "gruvbox": {"name": "Gruvbox", "bg": "#1d2021", "panel": "#282828", "code": "#171a1b",
                "fg": "#ebdbb2", "muted": "#d5c4a1", "ac": "#fe8019", "glow": "#fabd2f",
                "ok": "#b8bb26", "bad": "#fb4934", "warn": "#fabd2f"},
    "rosepine": {"name": "Rosé Pine", "bg": "#191724", "panel": "#1f1d2e", "code": "#14121e",
                 "fg": "#e0def4", "muted": "#aaa6c8", "ac": "#ebbcba", "glow": "#c4a7e7",
                 "ok": "#9ccfd8", "bad": "#eb6f92", "warn": "#f6c177"},
    "onedark": {"name": "One Dark", "bg": "#21252b", "panel": "#282c34", "code": "#1b1f24",
                "fg": "#d7dae0", "muted": "#abb2bf", "ac": "#61afef", "glow": "#c678dd",
                "ok": "#98c379", "bad": "#e06c75", "warn": "#e5c07b"},
    "forest": {"name": "Лес", "name_en": "Forest", "bg": "#141d18", "panel": "#1a2620",
               "code": "#0f1612", "fg": "#dde9e0", "muted": "#a9c2b1", "ac": "#7fd4a0",
               "glow": "#d8c97a", "ok": "#9fdc8c", "bad": "#e8828a", "warn": "#e6d27f"},
    "sunset": {"name": "Закат", "name_en": "Sunset", "bg": "#1f1520", "panel": "#281b29",
               "code": "#170f18", "fg": "#f3e3e6", "muted": "#cfb3bb", "ac": "#ff9e7a",
               "glow": "#e879b9", "ok": "#b5dd8c", "bad": "#ff6f91", "warn": "#ffd479"},
}
DEFAULT_PALETTE = "mocha"


def palette_name(key: str, lang: str = "ru") -> str:
    s = PALETTE_SETS.get(key, PALETTE_SETS[DEFAULT_PALETTE])
    return s.get("name_en", s["name"]) if lang == "en" else s["name"]


def make_palette(theme: str = "dark", palette: str = DEFAULT_PALETTE) -> dict:
    """Палитра для build_qss из темы (dark/light) и набора (PALETTE_SETS).

    Тёмная — все цвета набора; светлая — Latte с акцентом набора, затемнённым
    так, чтобы белый текст на кнопке оставался читаемым."""
    ps = PALETTE_SETS.get(palette) or PALETTE_SETS[DEFAULT_PALETTE]
    if theme == "light":
        p = dict(PALETTE_LIGHT)
        ac = _mix(ps["ac"], "#000000", 0.28)
        p.update(accent=ac, accent_hover=_mix(ac, "#ffffff", 0.14), glow=ps["glow"])
        p["key"] = palette
        p["theme"] = "light"
        return p
    return {
        "bg": ps["bg"],
        "surface": ps["panel"],
        "surface2": ps["code"],
        "border": _mix(ps["panel"], ps["fg"], 0.13),
        "text": ps["fg"],
        "subtext": ps["muted"],
        "accent": ps["ac"],
        "accent_text": ps["code"],
        "accent_hover": _mix(ps["ac"], "#ffffff", 0.16),
        "success": ps["ok"],
        "warn": ps["warn"],
        "error": ps["bad"],
        "track": _mix(ps["panel"], ps["fg"], 0.2),
        "input_bg": _mix(ps["panel"], ps["fg"], 0.07),
        "input_text": ps["fg"],
        "glow": ps["glow"],
        "key": palette,
        "theme": "dark",
    }


def _mix(c1, c2, t):
    a = [int(c1[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i : i + 2], 16) for i in (1, 3, 5)]
    r, g, bl = (max(0, min(255, round(x + (y - x) * t))) for x, y in zip(a, b, strict=True))
    return f"#{r:02x}{g:02x}{bl:02x}"


def _rgba(color, a):
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {a})"


def build_qss(p: dict) -> str:
    hov = _mix(p["surface"], p["text"], 0.08)
    return _base_qss(p, hov) + _shell_qss(p)


def _shell_qss(p: dict) -> str:
    """Оболочка окна в духе панелей vscode-bg и cpp-docs-panel: навигация
    колонкой слева с иконками-стикерами, страницы с заголовком и подписью,
    секции-карточки, компактные кнопки шапки."""
    glow = p.get("glow", p["accent"])
    return f"""
QWidget#TopBar {{
    background: qradialgradient(cx:0, cy:0, radius:1.1, fx:0, fy:0,
        stop:0 {_rgba(p["accent"], 0.20)}, stop:0.55 {_rgba(glow, 0.05)}, stop:1 {p["bg"]});
    border-bottom: 1px solid {p["border"]};
}}
QLabel#AppTile {{
    background: {_rgba(p["accent"], 0.16)}; border: 1px solid {_rgba(p["accent"], 0.35)};
    border-radius: 12px;
}}
QLabel#AppTitle {{ font-size: 13pt; font-weight: 800; color: {p["text"]}; }}
QLabel#AppSub {{ font-size: 9pt; color: {p["subtext"]}; }}
QPushButton#HBtn {{
    background: {_rgba(p["text"], 0.05)}; color: {p["subtext"]};
    border: 1px solid {_rgba(p["text"], 0.10)}; border-radius: 9px;
    padding: 5px 11px; font-size: 9pt; font-weight: 600;
}}
QPushButton#HBtn:hover {{ color: {p["text"]}; background: {_rgba(p["accent"], 0.18)};
    border-color: {_rgba(p["accent"], 0.45)}; }}
QPushButton#HBtn:checked {{ color: {p["accent"]}; background: {_rgba(p["accent"], 0.18)};
    border-color: {_rgba(p["accent"], 0.5)}; }}
QPushButton#HBtn::menu-indicator {{ width: 0; image: none; }}

QWidget#Nav {{
    background: {_rgba(p["text"], 0.025)}; border-right: 1px solid {p["border"]};
}}
QPushButton#NavItem {{
    background: transparent; border: 1px solid transparent; border-radius: 11px;
    padding: 0; text-align: left;
}}
QPushButton#NavItem:hover {{ background: {_rgba(p["text"], 0.06)}; }}
QPushButton#NavItem:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {_rgba(p["accent"], 0.24)}, stop:1 {_rgba(p["accent"], 0.07)});
    border: 1px solid {_rgba(p["accent"], 0.45)};
}}
QPushButton#NavItem:focus {{ border: 1px solid {_rgba(p["accent"], 0.6)}; }}
QLabel#NavIcon {{ background: {_rgba(p["text"], 0.06)}; border-radius: 8px; }}
QLabel#NavIcon[on="true"] {{ background: {_rgba(p["accent"], 0.22)}; }}
QLabel#NavText {{ color: {p["subtext"]}; font-size: 10pt; font-weight: 600; }}
QLabel#NavText[on="true"] {{ color: {p["text"]}; }}
QLabel#NavBadge {{
    color: {p["accent"]}; background: {_rgba(p["accent"], 0.18)};
    border: 1px solid {_rgba(p["accent"], 0.45)}; border-radius: 8px;
    padding: 0 5px; font-size: 8pt; font-weight: bold;
    qproperty-alignment: AlignCenter;
}}
QFrame#NavBar {{ background: {p["accent"]}; border-radius: 2px; }}

QLabel#PageTitle {{ font-size: 15pt; font-weight: 800; color: {p["text"]}; }}
QLabel#PageSub {{ font-size: 9pt; color: {p["subtext"]}; }}

QFrame#Sec {{
    background: {_rgba(p["text"], 0.035)}; border: 1px solid {p["border"]};
    border-radius: 13px;
}}
QPushButton#SecHead {{
    background: transparent; border: none; text-align: left; padding: 10px 14px;
    font-size: 10pt; font-weight: 700; color: {p["text"]};
}}
QPushButton#SecHead:hover {{ color: {p["accent"]}; }}
QPushButton#SecHead:focus {{ border: none; color: {p["accent"]}; }}
QLabel#SecTitle {{ font-size: 10pt; font-weight: 700; color: {p["text"]}; }}

QFrame#Pill {{
    background: {_rgba(p["accent"], 0.12)}; border: 1px solid {_rgba(p["accent"], 0.30)};
    border-radius: 11px;
}}
QFrame#Pill[on="false"] {{ background: {_rgba(p["text"], 0.05)}; border-color: {p["border"]}; }}
QLabel#PillText {{ font-weight: 600; color: {p["text"]}; }}

QFrame#Tile {{
    background: {_rgba(p["text"], 0.035)}; border: 1px solid {p["border"]}; border-radius: 13px;
}}
QFrame#Tile:hover {{ border-color: {_rgba(p["accent"], 0.55)}; background: {_rgba(p["accent"], 0.07)}; }}
QLabel#TileNum {{ font-size: 16pt; font-weight: 800; color: {p["accent"]}; }}
QLabel#TileTitle {{ font-size: 10pt; font-weight: 700; color: {p["text"]}; }}

QFrame#PalCard {{ background: {p["surface"]}; border: 1px solid {p["border"]}; border-radius: 12px; }}
QFrame#PalCard:hover {{ border-color: {_rgba(p["accent"], 0.6)}; }}
QFrame#PalCard[on="true"] {{ border: 2px solid {p["accent"]}; }}

QPushButton#Round {{
    background: {_rgba(p["text"], 0.05)}; border: 1px solid {p["border"]}; border-radius: 14px;
    color: {p["text"]}; padding: 0 0 2px 0; font-weight: bold; font-size: 12pt;
    min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
}}
QPushButton#Round:hover {{ color: {p["accent"]}; border-color: {p["accent"]};
    background: {_rgba(p["accent"], 0.10)}; }}
QPushButton#Round::menu-indicator {{ width: 0; image: none; }}

QMenu {{
    background: {p["surface"]}; color: {p["text"]}; border: 1px solid {p["border"]};
    border-radius: 10px; padding: 5px;
}}
QMenu::item {{ padding: 7px 18px 7px 12px; border-radius: 7px; background: transparent; }}
QMenu::item:selected {{ background: {_rgba(p["accent"], 0.18)}; color: {p["text"]}; }}
QMenu::item:disabled {{ color: {p["subtext"]}; }}
QMenu::separator {{ height: 1px; background: {p["border"]}; margin: 4px 8px; }}

QLabel#Status {{ color: {p["subtext"]}; font-size: 9pt; }}
"""


def _base_qss(p: dict, hov: str) -> str:
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
/* Видимая рамка фокуса: карточку теперь можно выбрать с клавиатуры (Tab),
   и должно быть понятно, на какой из двух десятков стеков сейчас фокус. */
QFrame#CatCard:focus {{
    border: 2px solid {p["accent"]}; background: {hov}; outline: none;
}}
QFrame#CatCard[on="true"] {{
    border: 1px solid {p["accent"]};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {_rgba(p["accent"], 0.18)}, stop:1 {_rgba(p["accent"], 0.07)});
}}
QFrame#CatCard[on="true"]:hover {{ border-color: {p["accent_hover"]}; }}
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

/* Hero-панель экономии: крупное число сэкономленных МБ + подписи-чипы. */
QFrame#SavingsCard {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {_mix(p["surface"], p["accent"], 0.20)}, stop:1 {p["surface"]});
    border: 1px solid {_rgba(p["accent"], 0.45)}; border-radius: 14px;
}}
QLabel#SavingsNumber {{ font-size: 30pt; font-weight: 800; color: {p["accent"]};
    letter-spacing: 0.5px; }}
QLabel#SavingsUnit {{ font-size: 12pt; font-weight: 700; color: {p["accent"]}; }}
QLabel#SavingsCaption {{ font-size: 9pt; color: {p["subtext"]};
    font-weight: bold; letter-spacing: 1px; }}
QLabel#Stat {{
    color: {p["text"]}; background: {_rgba(p["text"], 0.06)};
    border: 1px solid {p["border"]}; border-radius: 9px;
    padding: 4px 12px; font-size: 9pt; font-weight: bold;
}}
QLabel#StatAccent {{
    color: {p["accent"]}; background: {_rgba(p["accent"], 0.12)};
    border: 1px solid {_rgba(p["accent"], 0.35)}; border-radius: 9px;
    padding: 4px 12px; font-size: 9pt; font-weight: bold;
}}
/* Чип «выбрано N / M» в шапке секции стеков. */
QLabel#SelCount {{
    color: {p["subtext"]}; background: {_rgba(p["text"], 0.06)};
    border-radius: 9px; padding: 3px 12px; font-size: 9pt; font-weight: bold;
}}

/* Сегментированный фильтр: Все / Установленные / Не установленные. */
QFrame#Segmented {{
    background: {p["surface2"]}; border: 1px solid {p["border"]}; border-radius: 10px;
}}
QPushButton#SegBtn {{
    background: transparent; border: none; border-radius: 8px;
    padding: 6px 14px; color: {p["subtext"]}; font-size: 9pt; font-weight: bold;
}}
QPushButton#SegBtn:hover {{ color: {p["text"]}; background: {_rgba(p["text"], 0.06)}; }}
QPushButton#SegBtn:checked {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {p["accent_hover"]}, stop:1 {p["accent"]});
    color: {p["accent_text"]};
}}
QPushButton#SegBtn:checked:hover {{ background: {p["accent_hover"]}; color: {p["accent_text"]}; }}

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
/* Видимый фокус с клавиатуры — доступность (Tab-навигация). */
QPushButton:focus, QComboBox:focus {{ border: 2px solid {p["accent"]}; }}
QCheckBox:focus {{ outline: none; }}
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
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    border: none; width: 24px; background: transparent;
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

QRadioButton {{ background: transparent; spacing: 9px; }}
QRadioButton::indicator {{
    width: 16px; height: 16px; border: 1px solid {p["border"]};
    background: {p["input_bg"]}; border-radius: 9px;
}}
QRadioButton::indicator:hover {{ border-color: {p["accent"]}; }}
QRadioButton::indicator:checked {{
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {p["accent"]}, stop:0.45 {p["accent"]}, stop:0.55 {p["input_bg"]},
        stop:1 {p["input_bg"]});
    border-color: {p["accent"]};
}}
QRadioButton:disabled, QCheckBox:disabled {{ color: {p["subtext"]}; }}

/* Вкладки C++-центра. */
QTabWidget::pane {{ border: none; top: -1px; }}
QTabBar::tab {{
    background: transparent; color: {p["subtext"]}; padding: 8px 18px;
    border: none; border-bottom: 2px solid transparent; font-weight: bold;
}}
QTabBar::tab:hover {{ color: {p["text"]}; }}
QTabBar::tab:selected {{ color: {p["text"]}; border-bottom: 2px solid {p["accent"]}; }}

/* Строка-вариант в списке компонентов: подсветка выбранного. */
QFrame#OptRow {{ background: transparent; border: 1px solid transparent; border-radius: 9px; }}
QFrame#OptRow:hover {{ background: {_rgba(p["accent"], 0.06)}; }}
QFrame#OptRow[on="true"] {{ background: {_rgba(p["accent"], 0.10)};
    border: 1px solid {_rgba(p["accent"], 0.45)}; }}
QLabel#Hint {{
    color: {p["text"]}; background: {_rgba(p["accent"], 0.10)};
    border: 1px solid {_rgba(p["accent"], 0.35)}; border-radius: 10px; padding: 8px 12px;
}}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p["track"]}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p["accent"]}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QFrame#HLine {{ background: {p["border"]}; border: none; max-height: 1px; }}

QProgressBar#InstallBar {{
    background: {p["track"]}; border: none; border-radius: 4px;
}}
QProgressBar#InstallBar::chunk {{
    border-radius: 4px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {p["accent"]}, stop:1 {p["accent_hover"]});
}}
"""


def apply_titlebar(widget, dark: bool = True) -> None:
    """Тёмная/светлая рамка и заголовок окна на Windows 10/11. Другие ОС — no-op."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(widget.winId())
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE: 20 новое, 19 старое
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)
            )
    except Exception:
        pass
