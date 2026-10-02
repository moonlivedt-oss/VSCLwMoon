# -*- coding: utf-8 -*-
"""Диалог совместимости перед запуском (окно, offscreen)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from launcher import compat  # noqa: E402
from launcher.config import migrate_config  # noqa: E402

from test_gui_smoke import make_window  # noqa: E402

BAD = "ms-python.python"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app, monkeypatch):
    monkeypatch.setattr(compat, "vscode_version", lambda cli: "1.121.0")
    monkeypatch.setattr(compat, "builtin_extensions", lambda cli: frozenset())
    cfg = migrate_config({"installed_cache": {"ids": [BAD, "redhat.java"]}})
    w = make_window(app, cfg)
    w.cat_checks["python"].setChecked(True)
    w._dep_map = {}
    w._manifests = {BAD: {"engine": "^1.999.0"}}
    w._cfg_for_test = cfg
    yield w
    w.deleteLater()


def _answer(text: str, mute: bool = False):
    """Нажать кнопку с этим текстом в модальном окне, как только оно появится."""

    def go():
        box = QApplication.activeModalWidget()
        if not isinstance(box, QMessageBox):
            QTimer.singleShot(20, go)
            return
        if mute:
            box.checkBox().setChecked(True)
        for b in box.buttons():
            if b.text() == text:
                b.click()
                return

    QTimer.singleShot(0, go)


def test_warn_disable_and_launch(win):
    _answer("Выключить и запустить")
    assert win._confirm_compat() == {BAD}


def test_warn_cancel(win):
    _answer("Отмена")
    assert win._confirm_compat() is None


def test_warn_launch_as_is_and_mute(win):
    _answer("Запустить как есть", mute=True)
    assert win._confirm_compat() == set()
    cfg = win._cfg_for_test
    assert any(k.startswith("engine:" + BAD) for k in cfg["compat_ignored"])
    # скрытое больше не спрашивается
    assert win._confirm_compat() == set()


def test_auto_mode_disables_silently(win):
    win._cfg_for_test["compat_check"] = "auto"
    win._auto_notes = []
    assert win._confirm_compat() == {BAD}
    assert win._auto_notes


def test_off_and_bare_skip(win):
    win._cfg_for_test["compat_check"] = "off"
    assert win._confirm_compat() == set()
    win._cfg_for_test["compat_check"] = "warn"
    win.bare_cb.setChecked(True)
    assert win._confirm_compat() == set()
