# -*- coding: utf-8 -*-
"""Третья партия: CLI-диагностика, трей, пресеты, перенос настроек, доктор."""

import json
import logging
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from launcher import categories, cli, config, cpp, quicklaunch
from launcher import cpp_project as cp

GXX = r"D:\msys64\ucrt64\bin\g++.exe"


# --- CLI ---------------------------------------------------------------------


def test_cli_cpp_check_reports_and_fix_repairs(tmp_path, monkeypatch, capsys):
    from launcher import cli_cpp

    exe = tmp_path / "g++.exe"
    exe.write_bytes(b"")
    (tmp_path / "gdb.exe").write_bytes(b"")
    proj = tmp_path / "proj"
    (proj / ".vscode").mkdir(parents=True)
    (proj / ".vscode" / "tasks.json").write_text(
        json.dumps({"tasks": [{"label": "x", "type": "process", "command": "Z:\\no\\g++.exe"}]})
    )
    monkeypatch.setattr(cli_cpp, "_installed_exts", lambda: [])
    monkeypatch.setattr(cp, "which", lambda n: None)
    assert cli.cli_main(["--cpp-check", str(proj)]) == 1
    assert "чинится" in capsys.readouterr().out
    monkeypatch.setattr(
        cp, "auto_options", lambda folder, exts=(): cp.ProjectOptions(compiler_path=str(exe))
    )
    assert cli.cli_main(["--cpp-fix", str(proj)]) == 0
    assert cli.cli_main(["--cpp-check", str(proj)]) == 0
    assert cli.cli_main(["--cpp-check", str(tmp_path / "нет")]) == 2


def test_cli_purge_plan_only_prints(monkeypatch, capsys):
    from launcher import toolchains as tc

    monkeypatch.setattr(tc, "package_installed", lambda pkg: pkg.winget_id == "GoLang.Go")
    monkeypatch.setattr(
        tc,
        "purge_plan",
        lambda pkg: {
            "ids": ["GoLang.Go"],
            "dirs": [r"C:\Go"],
            "user_path": [],
            "machine_path": [r"C:\Go\bin"],
            "needs_admin": True,
        },
    )
    monkeypatch.setattr(tc, "purge_package", lambda *a, **k: pytest.fail("удалять нельзя"))
    assert cli.cli_main(["--purge-plan"]) == 0
    out = capsys.readouterr().out
    assert r"C:\Go" in out and "Ничего не удалено" in out


# --- запуск ------------------------------------------------------------------


def test_launch_last_uses_saved_selection_and_options(monkeypatch, tmp_path):
    seen = {}

    def fake_plan(cli_path, cfg, idx, stacks, options):
        seen.update(stacks=list(stacks), options=options)
        return {"disabled": ["a.one"], "args": ["x"]}

    monkeypatch.setattr(quicklaunch, "plan_launch", fake_plan)
    monkeypatch.setattr(quicklaunch, "vscode_process_count", lambda c: 0)
    monkeypatch.setattr(quicklaunch, "launch_detached", lambda c, a: None)
    cfg = {
        "last_selected": ["python"],
        "recent_folders": [str(tmp_path)],
        "kill_first": False,
        "disable_gpu": True,
    }
    ok, msg = quicklaunch.launch_last("code", cfg, {})
    assert ok and seen["stacks"] == ["python"]
    assert seen["options"]["folder"] == str(tmp_path) and seen["options"]["gpu_off"] is True
    assert "последний выбор" in msg


# --- проект ------------------------------------------------------------------


def test_external_console_option_and_quiet_failure_settings():
    assert (
        cp.launch_json(cp.ProjectOptions(compiler_path=GXX, has_cpptools=True))["configurations"][
            0
        ]["externalConsole"]
        is False
    )
    on = cp.ProjectOptions(compiler_path=GXX, has_cpptools=True, external_console=True)
    assert cp.launch_json(on)["configurations"][0]["externalConsole"] is True
    s = cp.workspace_settings(cp.ProjectOptions(compiler_path=GXX))
    assert s["debug.onTaskErrors"] == "showErrors" and s["code-runner.runInTerminal"] is True
    run = next(
        t
        for t in cp.tasks_json(cp.ProjectOptions(compiler_path=GXX))["tasks"]
        if t["label"] == cp.RUN_PLAIN_TASK
    )
    assert run["presentation"]["focus"] is True


# --- доктор ------------------------------------------------------------------


def test_doctor_flags_stale_compiler_path_in_vscode_settings(tmp_path):
    real = tmp_path / "g++.exe"
    real.write_bytes(b"")
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "C_Cpp.default.compilerPath": "Z:/gone/g++.exe",
                "clangd.path": str(real),
                "C_Cpp_Runner.debuggerPath": "gdb",
            }
        ),
        encoding="utf-8",
    )
    issues = cpp.environment_issues(settings, temp_dir=str(tmp_path))
    texts = [i["text"] for i in issues if "C_Cpp" in i["text"] or "clangd" in i["text"]]
    assert len(texts) == 1 and "Z:/gone/g++.exe" in texts[0]


def test_doctor_flags_low_disk_space(tmp_path, monkeypatch):
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(cpp.shutil, "disk_usage", lambda p: usage(10**9, 10**9, 200 * 1024 * 1024))
    issues = cpp.environment_issues(tmp_path / "нет.json", temp_dir=str(tmp_path))
    assert any("200" in i["text"] for i in issues)


# --- окно --------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


CATS = {
    "always_on": {"extensions": []},
    "categories": {
        "web": {"title": "Web", "extensions": ["a.b"]},
        "python": {"title": "Python", "extensions": ["c.d"]},
    },
}


def _window(app, cfg):
    from launcher import gui

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


def test_selection_and_page_survive_closing_without_launch(app):
    cfg = config.migrate_config({})
    w = _window(app, cfg)
    w.cat_checks["python"].setChecked(True)
    w._goto("settings")
    w.close()
    w.deleteLater()
    assert cfg["last_selected"] == ["python"] and cfg["last_page"] == "settings"
    w2 = _window(app, cfg)
    try:
        assert w2._selected() == {"python"} and w2._page == "settings"
    finally:
        w2.deleteLater()


def test_update_preset_overwrites_with_current_selection(app):
    cfg = config.migrate_config({"presets": {"p": {"stacks": ["web"]}}})
    w = _window(app, cfg)
    try:
        w.cat_checks["python"].setChecked(True)
        w.preset_box.setCurrentIndex(w.preset_box.findData("p"))
        w._update_preset()
        assert cfg["presets"]["p"]["stacks"] == ["python"]
    finally:
        w.deleteLater()


def test_folder_field_marks_missing_path(app, tmp_path):
    w = _window(app, config.migrate_config({}))
    try:
        w.folder_edit.setText(str(tmp_path / "нет"))
        assert w.folder_edit.property("bad") is True
        w.folder_edit.setText(str(tmp_path))
        assert w.folder_edit.property("bad") is False
    finally:
        w.deleteLater()


def test_settings_export_skips_machine_keys_and_import_restores(app, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QFileDialog, QMessageBox

    cfg = config.migrate_config({"presets": {"p": ["web"]}})
    cfg["installed_cache"] = {"ids": ["a.b"]}
    w = _window(app, cfg)
    out = tmp_path / "s.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(out), ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    try:
        w._export_settings()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "installed_cache" not in data and "p" in data["presets"]
        cfg["presets"].clear()
        w._import_settings()
        assert "p" in cfg["presets"] and cfg["installed_cache"] == {"ids": ["a.b"]}
    finally:
        w.deleteLater()


def test_journal_lines_carry_time(app):
    import re

    w = _window(app, config.migrate_config({}))
    try:
        w.log.appendPlainText("проверка")
        assert re.search(r"\d\d:\d\d:\d\d  проверка", w.log.toPlainText())
    finally:
        w.deleteLater()
