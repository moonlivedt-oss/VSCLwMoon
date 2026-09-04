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
