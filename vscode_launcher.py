# -*- coding: utf-8 -*-
"""VS Code Launcher — открывает редактор только с нужными стеками расширений,
остальные тяжёлые языковые серверы не грузятся (экономия ОЗУ). Ничего в базе
VS Code не меняется: запуск с флагами --disable-extension, всё обратимо.

Запуск:   pythonw vscode_launcher.py     (или через Запустить.bat)
Selftest: python  vscode_launcher.py --selftest python,web

Код разложен по пакету launcher/: core (логика), theme (оформление), gui (окно).
"""
import sys

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        from launcher.core import selftest   # без PyQt6
        selftest(sys.argv[2] if len(sys.argv) > 2 else "")
    else:
        from launcher.gui import run_gui
        run_gui()
