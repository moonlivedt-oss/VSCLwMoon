# -*- coding: utf-8 -*-
r"""VS Code Launcher — открывает редактор только с нужными стеками расширений,
остальные тяжёлые языковые серверы не грузятся (экономия ОЗУ). Ничего в базе
VS Code не меняется: запуск с флагами --disable-extension, всё обратимо.

Запуск:   pythonw vscode_launcher.py     (или через Запустить.bat)
Selftest: python  vscode_launcher.py --selftest python,web
CLI:      python  vscode_launcher.py --run --stacks python,git --folder D:\proj

Код разложен по пакету launcher/: core (логика), theme (оформление), gui (окно).
"""
import sys

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        from launcher.core import selftest   # без PyQt6
        selftest(sys.argv[2] if len(sys.argv) > 2 else "")
    elif len(sys.argv) >= 2 and sys.argv[1].startswith("--"):
        # Любой другой флаг — тихий CLI-режим (без PyQt6): запуск/предпросмотр
        # из скриптов и ярлыков. См. launcher/cli.py.
        from launcher.cli import cli_main
        raise SystemExit(cli_main(sys.argv[1:]))
    else:
        from launcher.gui import run_gui
        run_gui()
