# -*- coding: utf-8 -*-
"""Автопочинка перед запуском: без вопросов, но с отчётом о сделанном."""

import json
import logging
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from launcher import categories, config, quicklaunch

RUNNER = "danielpinto8zz6.c-cpp-compile-run"


def _plan(cfg, folder, installed):
    return quicklaunch.plan_launch(
        "code", cfg, {}, [], {"folder": folder}, installed=installed, dep_map={}
    )


def test_compile_run_is_turned_off_for_cyrillic_folder(tmp_path):
    folder = tmp_path / "Дмитрий"
    folder.mkdir()
    plan = _plan({}, str(folder), [RUNNER, "a.b"])
    assert plan["auto_disabled"] == [RUNNER] and RUNNER in plan["disabled"]


def test_not_turned_off_when_auto_fix_is_off_or_user_keeps_it(tmp_path):
    folder = tmp_path / "Дмитрий"
    folder.mkdir()
    assert _plan({"auto_fix": False}, str(folder), [RUNNER])["auto_disabled"] == []
    keep = {"overrides": {"enable": [RUNNER]}}
    assert _plan(keep, str(folder), [RUNNER])["auto_disabled"] == []


def test_ascii_folder_keeps_compile_run(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    if str(folder.resolve()).isascii():
        assert _plan({}, str(folder), [RUNNER])["auto_disabled"] == []


@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


CATS = {
    "always_on": {"extensions": []},
    "categories": {
        "cpp": {"title": "C++", "extensions": ["xaver.clang-format"]},
        "cpp_cpptools": {"title": "cpptools", "extensions": ["ms-vscode.cpptools"]},
    },
}


def _window(app, cfg):
    from launcher import gui

    cfg.setdefault("installed_cache", {"ids": ["xaver.clang-format", "ms-vscode.cpptools"]})
    Launcher = gui._launcher_factory(
        CATS,
        "",
        cfg,
        categories.build_ext_index(CATS),
        None,
        {},
        {},
        logging.getLogger("t"),
        {"fn": None},
    )
    w = Launcher(background=False)
    w.show()
    app.processEvents()
    return w


def test_needed_stack_is_enabled_without_a_question(app, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    vs = tmp_path / ".vscode"
    vs.mkdir()
    (vs / "launch.json").write_text(json.dumps({"configurations": [{"type": "cppdbg"}]}))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: pytest.fail("не спрашивать"))
    w = _window(app, config.migrate_config({}))
    try:
        w._set_all(False)
        w.cat_checks["cpp"].setChecked(True)
        w._auto_notes = []
        assert w._confirm_project_needs(str(tmp_path)) is True
        assert w.cat_checks["cpp_cpptools"].isChecked()
        assert w._auto_notes and "cppdbg" in w._auto_notes[0]
        assert "Автоматически" in w.log.toPlainText()
    finally:
        w.deleteLater()


def test_with_auto_fix_off_the_launcher_asks(app, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    vs = tmp_path / ".vscode"
    vs.mkdir()
    (vs / "launch.json").write_text(json.dumps({"configurations": [{"type": "cppdbg"}]}))
    asked = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: asked.append(1) or 0)
    w = _window(app, config.migrate_config({"auto_fix": False}))
    try:
        w._set_all(False)
        w.cat_checks["cpp"].setChecked(True)
        w._confirm_project_needs(str(tmp_path))
        assert asked
    finally:
        w.deleteLater()
