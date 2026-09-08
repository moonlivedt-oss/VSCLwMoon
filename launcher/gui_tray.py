# -*- coding: utf-8 -*-
"""Значок в трее: запуск пресета без открытия окна.

Смысл лаунчера — открыть редактор нужным набором и уйти. Но до сих пор для
этого приходилось каждый раз поднимать окно на 25 карточек, находить пресет,
нажать «Запустить». Значок в трее убирает этот круг: правый клик — пресет —
редактор стартует. Окно нужно только когда набор действительно меняют.

Отдельный модуль, потому что трей ничего не знает про устройство окна: ему
нужны конфиг, карта расширений и путь к CLI. Всё остальное — в quicklaunch.
"""
from __future__ import annotations

from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from .i18n import _
from .paths import ICON_FILE
from .presets import normalize_preset
from .quicklaunch import launch_preset


class LauncherTray(QSystemTrayIcon):
    """Значок с меню: показать окно, запустить пресет, выйти.

    Ссылки на QAction держим в self._actions: Qt владеет только меню, а
    собранные в цикле действия без ссылки собрал бы сборщик мусора, и пункты
    молча перестали бы работать."""

    def __init__(self, window, cfg, ext_index, get_code_cli, on_quit, parent=None):
        icon = QIcon(str(ICON_FILE)) if ICON_FILE.exists() else window.windowIcon()
        super().__init__(icon, parent)
        self._window = window
        self._cfg = cfg
        self._ext_index = ext_index
        self._get_code_cli = get_code_cli
        self._on_quit = on_quit
        self._actions: list[QAction] = []
        self.setToolTip("VS Code Launcher")
        self.activated.connect(self._on_activated)
        self.rebuild_menu()

    # --- меню --------------------------------------------------------------

    def rebuild_menu(self):
        """Пересобрать меню (после сохранения/удаления пресета)."""
        menu = QMenu()
        self._actions = []

        show = menu.addAction(_("Показать окно"))
        show.triggered.connect(self.show_window)
        self._actions.append(show)
        menu.addSeparator()

        presets = self._cfg.get("presets", {})
        if presets:
            head = menu.addAction(_("Запустить пресет:"))
            head.setEnabled(False)
            self._actions.append(head)
            for name in presets:
                act = menu.addAction(self._preset_label(name))
                act.triggered.connect(lambda _checked=False, n=name: self.launch(n))
                self._actions.append(act)
        else:
            empty = menu.addAction(_("Пресетов пока нет"))
            empty.setEnabled(False)
            self._actions.append(empty)

        menu.addSeparator()
        quit_act = menu.addAction(_("Выход"))
        quit_act.triggered.connect(self._on_quit)
        self._actions.append(quit_act)
        self.setContextMenu(menu)

    def _preset_label(self, name: str) -> str:
        """Имя пресета плюс сколько стеков он включает — чтобы не гадать,
        что именно откроется, не открывая окно."""
        p = normalize_preset(self._cfg.get("presets", {}).get(name))
        n = len(p["stacks"])
        if p["bare"]:
            return _("{name} — голый режим").format(name=name)
        return _("{name} — стеков: {n}").format(name=name, n=n)

    # --- действия ----------------------------------------------------------

    def attach(self, window):
        """Пересобранное при смене языка окно — новое; значок должен показывать
        его, а не удалённое старое (иначе пункт «Показать окно» перестал бы
        работать после первого же переключения RU/EN)."""
        self._window = window
        window._tray = self
        self.rebuild_menu()

    def show_window(self):
        w = self._window
        w.showNormal()
        w.raise_()
        w.activateWindow()

    def launch(self, name: str):
        ok, msg = launch_preset(self._get_code_cli(), self._cfg, self._ext_index, name)
        self.showMessage(
            "VS Code Launcher", msg,
            QSystemTrayIcon.MessageIcon.Information if ok
            else QSystemTrayIcon.MessageIcon.Warning,
            4000,
        )

    def _on_activated(self, reason):
        # Двойной клик по значку — самое ожидаемое действие: показать окно.
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,
                      QSystemTrayIcon.ActivationReason.Trigger):
            self.show_window()
