# -*- coding: utf-8 -*-
"""Пути к ресурсам, конфигу и логу.

Один источник правды по путям: другие модули импортируют константы отсюда
и не занимаются определением, где живёт data/ или где писать конфиг.

Учитывает PyInstaller: в собранном exe ресурсы (data/, assets/) распакованы
в _MEIPASS, а личный конфиг и лог пишем рядом с exe, чтобы они переживали
перезапуск (в .gitignore тоже _MEIPASS исчезает при новом запуске).
"""
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    CONFIG_DIR = Path(sys.executable).parent
else:
    ROOT = Path(__file__).resolve().parent.parent
    CONFIG_DIR = ROOT

DATA_DIR = ROOT / "data"
ASSETS_DIR = ROOT / "assets"

CATEGORIES_FILE = DATA_DIR / "categories.json"
DESCRIPTIONS_FILE = DATA_DIR / "plugin_descriptions.json"
RECOMMENDED_FILE = DATA_DIR / "recommended_settings.json"

ICON_FILE = ASSETS_DIR / "app.ico"
LOGO_FILE = ASSETS_DIR / "logo.png"   # необязательный логотип в шапке

CONFIG_FILE = CONFIG_DIR / "launcher_config.json"
LOG_FILE = CONFIG_DIR / "launcher.log"
