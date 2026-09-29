# -*- coding: utf-8 -*-
"""Smoke-тесты окна (offscreen, без pytest-qt).

GUI раньше был заперт в замыкании run_gui и не строился в тесте вовсе. Теперь
класс отдаёт фабрика _launcher_factory, а флаг background=False убирает фоновые
потоки и сеть — и окно можно собрать «на сухую». Тест ловит самый частый
регресс Qt-приложения: «падает при старте / кнопка ссылается в пустоту».
"""
import os

import pytest

# offscreen-платформа до создания QApplication — без дисплея (годится и для CI).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")

import logging

from PyQt6.QtWidgets import QApplication

from launcher import gui
from launcher.categories import build_ext_index
from launcher.config import migrate_config, set_folder_auto, remember_folder_stacks


CATS = {
    "always_on": {"extensions": ["anthropic.claude-code"]},
    "categories": {
        "python": {"title": "Python", "extensions": ["ms-python.python", "charliermarsh.ruff"]},
        "web": {"title": "Web", "extensions": ["dbaeumer.vscode-eslint"]},
        "java": {"title": "Java", "extensions": ["redhat.java"]},
    },
}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_window(app, cfg=None):
    cfg = cfg if cfg is not None else migrate_config({})
    ext_index = build_ext_index(CATS, cfg.get("extra_categories"))
    log = logging.getLogger("launcher-test")
    Launcher = gui._launcher_factory(
        CATS, "", cfg, ext_index, None, {}, {}, log, {"fn": None}
    )
    w = Launcher(background=False)
    w.show()  # offscreen: без show() дочерние виджеты считаются скрытыми
    return w


def test_window_builds_all_cards(app):
    w = make_window(app)
    try:
        assert set(w.cat_checks) == {"python", "web", "java"}
    finally:
        w.deleteLater()


def test_select_all_and_none(app):
    w = make_window(app)
    try:
        w._set_all(True)
        assert w._selected() == {"python", "web", "java"}
        w._set_all(False)
        assert w._selected() == set()
    finally:
        w.deleteLater()


def test_summary_and_disabled_list_do_not_raise(app):
    w = make_window(app)
    try:
        w._set_all(False)
        w.cat_checks["python"].setChecked(True)
        w._update_summary()                 # не должно падать
        assert isinstance(w._disabled_list(), list)
        assert w._bare() in (True, False)
    finally:
        w.deleteLater()


def test_filter_cards_runs(app):
    w = make_window(app)
    try:
        w._filter_cards("python")           # фильтр по тексту не падает
        w._filter_cards("")
    finally:
        w.deleteLater()


def test_folder_auto_applies_stacks_on_build(app):
    # #5-wiring: папка помечена авто + для неё запомнен набор → при сборке окна
    # стеки включаются сами, без строки-подсказки.
    cfg = migrate_config({})
    cfg["recent_folders"] = [r"D:\Proj"]        # подставится в поле папки при _restore
    remember_folder_stacks(cfg, r"D:\Proj", ["python", "web"])
    set_folder_auto(cfg, r"D:\Proj", True)
    w = make_window(app, cfg)
    try:
        assert not w.suggest_bar.isVisible()     # при старте — молча, без бара
        assert w._selected() >= {"python", "web"}
        assert w.auto_cb.isChecked()             # чекбокс отражает авто-режим
    finally:
        w.deleteLater()


# --- 1.4: состояние окна, доступность, реальный вес, исключения ------------


def test_ui_state_roundtrip_survives_rebuild(app):
    # Смена языка пересобирает окно. Раньше при этом терялись галочки, папка и
    # поиск — теперь снимок переносит их в новое окно.
    w = make_window(app)
    try:
        w._set_all(False)
        w.cat_checks["python"].setChecked(True)
        w.folder_edit.setText(r"D:\proj")
        w.search_edit.setText("py")
        w.gpu_cb.setChecked(True)
        state = w.ui_state()
    finally:
        w.deleteLater()

    w2 = make_window(app)
    try:
        w2.apply_ui_state(state)
        assert w2._selected() == {"python"}
        assert w2.folder_edit.text() == r"D:\proj"
        assert w2.search_edit.text() == "py"
        assert w2.gpu_cb.isChecked() is True
    finally:
        w2.deleteLater()


def test_apply_ui_state_ignores_empty(app):
    w = make_window(app)
    try:
        w.cat_checks["web"].setChecked(True)
        w.apply_ui_state({})          # не должно ничего сломать или сбросить
        assert w._selected() == {"web"}
    finally:
        w.deleteLater()


def test_cards_are_keyboard_reachable(app):
    from PyQt6.QtCore import Qt

    w = make_window(app)
    try:
        card = w.cat_checks["python"]
        assert card.focusPolicy() == Qt.FocusPolicy.StrongFocus
        assert card.accessibleName()          # скринридер получает имя стека
    finally:
        w.deleteLater()


def test_space_toggles_focused_card(app):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeyEvent

    w = make_window(app)
    try:
        card = w.cat_checks["python"]
        card.setChecked(False)
        card.keyPressEvent(
            QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        )
        assert card.isChecked() is True
    finally:
        w.deleteLater()


def test_disk_badge_shows_real_size(app):
    w = make_window(app)
    try:
        w.installed = ["ms-python.python"]
        w._apply_sizes({"ms-python.python": 42}, persist=False)
        assert w.cat_checks["python"].disk_mb() == 42
        assert "42" in w.cat_checks["python"].weight_lbl.text()
        # У стека без установленных расширений размер не дописывается.
        assert w.cat_checks["java"].disk_mb() == 0
        assert "МБ" not in w.cat_checks["java"].weight_lbl.text()
    finally:
        w.deleteLater()


def test_scan_root_uses_folder_of_workspace_file(app, tmp_path):
    ws = tmp_path / "proj.code-workspace"
    ws.write_text("{}", encoding="utf-8")
    w = make_window(app)
    try:
        assert w._scan_root(str(ws)) == str(tmp_path)
        assert w._scan_root(str(tmp_path)) == str(tmp_path)
        assert w._scan_root("") == ""
    finally:
        w.deleteLater()


def test_override_chip_hidden_without_overrides(app):
    w = make_window(app)
    try:
        assert w.overrides_btn.isHidden()  # кнопка на странице «Расширения»
        w.set_override("some.ext", "disable")
        assert not w.overrides_btn.isHidden()
        assert "1" in w.overrides_btn.text()
        w.set_override("some.ext", "default")
        assert w.overrides_btn.isHidden()  # кнопка на странице «Расширения»
    finally:
        w.deleteLater()


def test_savings_tooltip_explains_source(app):
    w = make_window(app)
    try:
        w._set_all(False)
        w.installed = ["ms-python.python"]
        w._update_summary()
        assert w.savings_num.toolTip()      # число всегда объяснено
    finally:
        w.deleteLater()


def test_tray_settings_persist(app):
    from launcher.config import migrate_config

    cfg = migrate_config({})
    w = make_window(app, cfg)
    try:
        w.tray_cb.setChecked(False)
        assert cfg["tray"] is False
        assert w.close_tray_cb.isEnabled() is False
    finally:
        w.deleteLater()


# --- 1.4: значок в трее ----------------------------------------------------


def _tray(app, cfg, window):
    from launcher.gui_tray import LauncherTray

    return LauncherTray(window, cfg, build_ext_index(CATS), lambda: None, lambda: None)


def test_tray_menu_lists_presets(app):
    cfg = migrate_config({})
    cfg["presets"] = {"веб": ["web"], "пусто": {"stacks": [], "bare": True}}
    w = make_window(app, cfg)
    try:
        tray = _tray(app, cfg, w)
        texts = [a.text() for a in tray.contextMenu().actions()]
        assert any("веб" in t for t in texts)
        assert any("голый" in t or "bare" in t for t in texts)
    finally:
        w.deleteLater()


def test_tray_menu_handles_no_presets(app):
    cfg = migrate_config({})
    w = make_window(app, cfg)
    try:
        tray = _tray(app, cfg, w)
        texts = [a.text() for a in tray.contextMenu().actions()]
        assert any("Пресетов" in t or "No presets" in t for t in texts)
    finally:
        w.deleteLater()


def test_tray_attach_follows_rebuilt_window(app):
    # Смена языка пересобирает окно: значок должен показывать новое, иначе
    # «Показать окно» указывало бы на удалённый виджет.
    cfg = migrate_config({})
    w1 = make_window(app, cfg)
    w2 = make_window(app, cfg)
    try:
        tray = _tray(app, cfg, w1)
        tray.attach(w2)
        assert tray._window is w2
        assert w2._tray is tray
    finally:
        w1.deleteLater()
        w2.deleteLater()


def test_tray_launch_reports_missing_cli(app):
    cfg = migrate_config({})
    cfg["presets"] = {"веб": ["web"]}
    w = make_window(app, cfg)
    try:
        tray = _tray(app, cfg, w)
        tray.launch("веб")   # CLI нет — должно не упасть, а показать сообщение
    finally:
        w.deleteLater()
