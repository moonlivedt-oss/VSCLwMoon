# -*- coding: utf-8 -*-
"""Самопроверки и автопочинка: здоровье проекта, запуск VS Code, отчёт поддержки."""

import json
import logging
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from launcher import cpp_project as cp
from launcher import support, vscode

GXX = r"D:\msys64\ucrt64\bin\g++.exe"


def _vscode(folder, **files):
    vs = folder / ".vscode"
    vs.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (vs / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


def _keys(folder):
    return {p["key"] for p in cp.project_problems(str(folder))}


def test_no_problems_without_vscode_folder(tmp_path):
    assert cp.project_problems(str(tmp_path)) == []


def test_gdb_in_cyrillic_folder_is_a_problem(tmp_path):
    folder = tmp_path / "Дмитрий"
    folder.mkdir()
    _vscode(folder, launch={"configurations": [{"type": "cppdbg", "MIMode": "gdb"}]})
    assert "gdb_unicode" in _keys(folder)
    _vscode(folder, launch={"configurations": [{"type": "lldb"}]})
    assert "gdb_unicode" not in _keys(folder)


def test_missing_compiler_debugger_and_task_are_found(tmp_path):
    _vscode(
        tmp_path,
        launch={
            "configurations": [
                {"type": "cppdbg", "miDebuggerPath": "Z:/nope/gdb.exe", "preLaunchTask": "сборка"}
            ]
        },
        tasks={"tasks": [{"label": "другое", "type": "process", "command": "Z:\\nope\\g++.exe"}]},
        c_cpp_properties={"configurations": [{"compilerPath": "Z:/nope/gcc.exe"}]},
    )
    assert _keys(tmp_path) >= {"missing_debugger", "missing_task", "missing_compiler"}


def test_fix_project_recreates_files_and_keeps_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "which", lambda name: None)
    exe = tmp_path / "g++.exe"
    exe.write_bytes(b"")
    (tmp_path / "gdb.exe").write_bytes(b"")
    proj = tmp_path / "proj"
    proj.mkdir()
    _vscode(
        proj,
        launch={"configurations": [{"type": "cppdbg", "miDebuggerPath": "Z:/nope/gdb.exe"}]},
        tasks={"tasks": [{"label": "x", "type": "process", "command": "Z:\\nope\\g++.exe"}]},
    )
    assert cp.project_problems(str(proj))
    o = cp.ProjectOptions(compiler_path=str(exe), has_cpptools=True)
    report = cp.fix_project(str(proj), o)
    assert any("перезаписан" in line for line in report)
    assert cp.project_problems(str(proj)) == []
    assert list((proj / ".vscode").glob("launch.json.bak-*"))


def test_generated_project_has_no_problems(tmp_path):
    exe = tmp_path / "g++.exe"
    exe.write_bytes(b"")
    (tmp_path / "gdb.exe").write_bytes(b"")
    proj = tmp_path / "p"
    proj.mkdir()
    o = cp.ProjectOptions(compiler_path=str(exe), has_cpptools=True)
    cp.apply_plan(str(proj), cp.plan_files(str(proj), o))
    assert cp.project_problems(str(proj)) == []


def test_launch_refuses_command_line_longer_than_windows_allows(monkeypatch):
    monkeypatch.setattr(vscode, "code_gui_exe", lambda cli: None)
    monkeypatch.setattr(vscode.subprocess, "Popen", lambda *a, **k: pytest.fail("не запускать"))
    args = ["--disable-extension", "publisher.some-long-extension-name"] * 900
    with pytest.raises(OSError):
        vscode.launch_detached("code.cmd", args)


def test_launched_vscode_gets_registry_path(monkeypatch):
    monkeypatch.setattr(vscode.env_path, "registry_path", lambda: r"C:\fresh")
    monkeypatch.setenv("PATH", r"C:\stale")
    assert vscode.clean_launch_env()["PATH"] == r"C:\fresh"
    monkeypatch.setattr(vscode.env_path, "registry_path", lambda: "")
    assert vscode.clean_launch_env()["PATH"] == r"C:\stale"


def test_support_report_survives_a_broken_section(monkeypatch, tmp_path):
    from launcher import cpp, path_doctor

    monkeypatch.setattr(cpp, "cpp_report", lambda **k: (_ for _ in ()).throw(RuntimeError("бум")))
    monkeypatch.setattr(path_doctor, "analyze", lambda **k: path_doctor.Report("", "", [], [], {}))
    text = support.build_report("code.cmd", {"presets": {"web": []}}, ["python"])
    assert "раздел не собран: RuntimeError" in text
    assert "Выбранные стеки: python" in text and "=== Журнал" in text
    monkeypatch.setattr(support, "CONFIG_DIR", tmp_path)
    assert support.save_report(text).read_text(encoding="utf-8-sig") == text


def test_failed_config_save_does_not_break_the_action(monkeypatch):
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    from launcher import gui
    from launcher.categories import build_ext_index
    from launcher.config import migrate_config

    app = QApplication.instance() or QApplication([])
    cats = {
        "always_on": {"extensions": []},
        "categories": {"web": {"title": "Web", "extensions": ["a.b"]}},
    }
    monkeypatch.setattr(gui, "_save_config", lambda c: (_ for _ in ()).throw(OSError("read-only")))
    Launcher = gui._launcher_factory(
        cats,
        "",
        migrate_config({}),
        build_ext_index(cats),
        None,
        {},
        {},
        logging.getLogger("t"),
        {"fn": None},
    )
    w = Launcher(background=False)
    try:
        w._persist()  # раньше OSError вылетал из обработчика
        w.set_override("a.b", "disable")
        assert w.override_mode("a.b") == "disable"
    finally:
        w.deleteLater()
        app.processEvents()
