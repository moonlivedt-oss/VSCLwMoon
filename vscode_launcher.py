# -*- coding: utf-8 -*-
"""VS Code Launcher — открывает редактор только с нужными стеками расширений,
остальные тяжёлые языковые серверы не грузятся (экономия ОЗУ). Ничего в базе
VS Code не меняется: запуск с флагами --disable-extension, всё обратимо.

Запуск:   pythonw vscode_launcher.py     (или через Запустить.bat)
Selftest: python  vscode_launcher.py --selftest python,web

Код разложен по пакету launcher/: core (логика), theme (оформление), gui (окно).
"""
import sys

from launcher.core import selftest
from launcher.gui import run_gui

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2] if len(sys.argv) > 2 else "")
    else:
        run_gui()
