# -*- coding: utf-8 -*-
"""Сборка в папке с русскими буквами (C:\\Users\\Дмитрий\\…).

На втором ПК задача сборки падала: «ld.exe: cannot open output file C:\\Users\\:
Illegal byte sequence» — новые сборки MSYS2 не принимают такие аргументы.
"""

import json
import os
import sys

from launcher import cpp
from launcher import cpp_project as cp

GXX = r"C:\msys64\ucrt64\bin\g++.exe"


def test_build_task_passes_relative_paths():
    tasks = cp.tasks_json(cp.ProjectOptions(compiler_path=GXX, olympiad=True))["tasks"]
    build = tasks[0]
    assert "${fileBasename}" in build["args"] and "${file}" not in build["args"]
    assert not any("${fileDirname}" in a for a in build["args"])
    assert build["options"]["cwd"] == "${fileDirname}"
    assert build["problemMatcher"]["fileLocation"] == ["autoDetect", "${fileDirname}"]
    for t in tasks[1:]:
        assert "${fileDirname}" not in t["command"] and "${file}" not in t["command"]


def test_old_absolute_build_task_in_cyrillic_folder_is_fixable(tmp_path):
    folder = tmp_path / "Дмитрий"
    (folder / ".vscode").mkdir(parents=True)
    old = {
        "tasks": [
            {
                "label": "x",
                "type": "process",
                "command": "g++",
                "args": ["${file}", "-o", "${fileDirname}\\a.exe"],
            }
        ]
    }
    (folder / ".vscode" / "tasks.json").write_text(json.dumps(old), encoding="utf-8")
    keys = {p["key"] for p in cp.project_problems(str(folder))}
    assert "abs_args" in keys and "abs_args" in cp.FIXABLE
    ascii_dir = tmp_path / "proj"
    (ascii_dir / ".vscode").mkdir(parents=True)
    (ascii_dir / ".vscode" / "tasks.json").write_text(json.dumps(old), encoding="utf-8")
    if str(ascii_dir.resolve()).isascii():
        assert "abs_args" not in {p["key"] for p in cp.project_problems(str(ascii_dir))}


def test_compile_run_extension_is_flagged_in_cyrillic_folder(tmp_path):
    folder = tmp_path / "Дмитрий"
    (folder / ".vscode").mkdir(parents=True)
    keys = {p["key"] for p in cp.project_problems(str(folder), ["danielpinto8zz6.c-cpp-compile-run"])}
    assert keys == {"abs_runner"} and "abs_runner" not in cp.FIXABLE


def test_frozen_exe_folder_is_removed_from_child_path(monkeypatch, tmp_path):
    meipass = str(tmp_path / "_MEI123")
    seen = {}
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", meipass, raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join([meipass, r"C:\keep", meipass + r"\PyQt6"]))
    monkeypatch.setattr(cpp.subprocess, "run", lambda args, **kw: seen.update(kw))
    try:
        cpp._run(["x"])
    finally:
        try:
            import ctypes

            ctypes.windll.kernel32.SetDllDirectoryW(None)
        except Exception:
            pass
    path = next(v for k, v in seen["env"].items() if k.upper() == "PATH")
    assert path == r"C:\keep"


def test_unicode_check_reports_failing_compiler(monkeypatch):
    class Proc:
        returncode = 1
        stdout = ""
        stderr = "ld.exe: cannot open output file C:\\Users\\: Illegal byte sequence"

    monkeypatch.setattr(cpp, "_run", lambda *a, **k: Proc())
    c = cpp.Compiler(path=GXX, kind="gcc", version="16.1.0")
    issue = cpp.unicode_path_issue(c)
    assert issue and issue["key"] == "unicode_args" and "Illegal byte sequence" in issue["text"]
    assert cpp.unicode_path_issue(cpp.Compiler(path="cl.exe", kind="msvc")) is None
