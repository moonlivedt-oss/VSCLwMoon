# -*- coding: utf-8 -*-
"""Вторая партия улучшений: устойчивость к ошибкам ввода и окружения."""

import json
import logging
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from launcher import categories, config, quicklaunch, vscode
from launcher import cpp_project as cp
from launcher import env_path
from launcher import toolchains as tc

GXX = r"D:\msys64\ucrt64\bin\g++.exe"


# --- проект ------------------------------------------------------------------


def test_empty_folder_gets_a_sample_program(tmp_path):
    o = cp.ProjectOptions(compiler_path=GXX)
    paths = [i["path"] for i in cp.plan_files(str(tmp_path), o, starter=True)]
    assert paths[0] == "main.cpp" and ".gitignore" in paths
    assert "main.cpp" not in [i["path"] for i in cp.plan_files(str(tmp_path), o)]
    cmake = cp.ProjectOptions(compiler_path=GXX, build="cmake")
    paths = [i["path"] for i in cp.plan_files(str(tmp_path), cmake, starter=True)]
    assert paths[:2] == ["CMakeLists.txt", "src/main.cpp"]


def test_existing_sources_are_never_overwritten_by_default(tmp_path):
    (tmp_path / "main.cpp").write_text("мой код", encoding="utf-8")
    o = cp.ProjectOptions(compiler_path=GXX)
    cp.apply_plan(str(tmp_path), cp.plan_files(str(tmp_path), o, starter=True))
    assert (tmp_path / "main.cpp").read_text(encoding="utf-8") == "мой код"


def test_workspace_terminal_sees_the_chosen_compiler():
    s = cp.workspace_settings(cp.ProjectOptions(compiler_path=GXX))
    assert s["terminal.integrated.env.windows"]["PATH"].startswith(r"D:\msys64\ucrt64\bin;")
    msvc = cp.ProjectOptions(compiler_path=r"C:\VS\cl.exe", compiler_kind="msvc")
    assert "terminal.integrated.env.windows" not in cp.workspace_settings(msvc)


def test_missing_debugger_extension_is_reported_but_not_auto_fixable(tmp_path):
    vs = tmp_path / ".vscode"
    vs.mkdir()
    (vs / "launch.json").write_text(json.dumps({"configurations": [{"type": "lldb"}]}))
    assert cp.project_problems(str(tmp_path)) == []  # без списка расширений не судим
    keys = {p["key"] for p in cp.project_problems(str(tmp_path), ["ms-vscode.cpptools"])}
    assert keys == {"no_debug_ext"} and not (keys & cp.FIXABLE)
    assert cp.project_problems(str(tmp_path), ["vadimcn.vscode-lldb"]) == []


def test_clang_tidy_template_is_quiet_for_beginners():
    for check in ("-performance-avoid-endl", "-readability-braces-around-statements"):
        assert check in cp.CLANG_TIDY


# --- карта стеков и конфиг ---------------------------------------------------


def test_broken_categories_are_normalized_instead_of_crashing():
    data = {
        "always_on": "oops",
        "categories": {
            "ok": {"extensions": ["a.b"]},
            "no_list": {"title": "X", "extensions": "a.b"},
            "mixed": {"extensions": ["a.b", 5, None]},
            "junk": ["not", "a", "dict"],
        },
    }
    notes = categories.normalize_categories(data)
    assert notes and data["always_on"] == {"extensions": []}
    assert data["categories"]["no_list"]["extensions"] == []
    assert data["categories"]["mixed"]["extensions"] == ["a.b"]
    assert "junk" not in data["categories"]
    assert categories.normalize_categories(data) == []  # повторно править нечего


def test_config_falls_back_to_backup_when_main_file_is_corrupt():
    config.save_config({"presets": {"web": ["web"]}})
    config.save_config({"presets": {"web": ["web"], "py": ["python"]}})
    assert config.backup_config_path().is_file()
    config.CONFIG_FILE.write_text("{ обрыв", encoding="utf-8")
    cfg = config.load_config()
    assert set(cfg["presets"]) == {"web"}  # предыдущая удачная запись, без «py»


def test_hide_after_launch_is_a_known_bool_setting():
    cfg = {"hide_after_launch": "да"}
    assert "hide_after_launch" in config.validate_config(cfg) and cfg["hide_after_launch"] is False


# --- запуск ------------------------------------------------------------------


def test_preset_with_deleted_folder_opens_without_it(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(quicklaunch, "load_installed", lambda cli: (["a.one"], "тест"))
    monkeypatch.setattr(quicklaunch, "read_extension_manifests", lambda cli: {})
    monkeypatch.setattr(quicklaunch, "vscode_process_count", lambda cli: 0)
    monkeypatch.setattr(quicklaunch, "launch_detached", lambda cli, a: seen.update(args=a))
    gone = str(tmp_path / "удалена")
    cfg = {"presets": {"p": {"stacks": [], "folder": gone}}}
    ok, msg = quicklaunch.launch_preset("code", cfg, {"a.one": "python"}, "p")
    assert ok and gone not in seen["args"] and gone in msg


@pytest.mark.parametrize(
    "text,word",
    [
        ("getaddrinfo ENOTFOUND marketplace.visualstudio.com", "интернет"),
        ("self signed certificate in certificate chain", "Сертификат"),
        ("EPERM: operation not permitted, rename", "заняты"),
        ("Extension 'x.y' not found.", "не нашёл"),
    ],
)
def test_extension_install_errors_are_explained(text, word):
    assert word in vscode.explain_cli_error(text)


def test_unknown_cli_error_is_left_as_is():
    assert vscode.explain_cli_error("something odd") == ""


# --- полное удаление: переменные окружения ---------------------------------------


def test_purge_drops_env_var_that_pointed_into_removed_folder(tmp_path, monkeypatch):
    root = tmp_path / "jdk-25"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "javac.exe").write_text("")
    pkg = tc.Package(winget_id="EclipseAdoptium.Temurin.25.JDK", title="JDK", probe=("javac",))
    deleted: list[str] = []
    monkeypatch.setattr(tc, "which", lambda n: None)
    monkeypatch.setattr(tc, "_run_winget", lambda *a, **k: (True, "ok"))
    monkeypatch.setattr(env_path, "remove_from_user_path", lambda d: (True, ""))
    monkeypatch.setattr(env_path, "read_machine_path", lambda: "")
    monkeypatch.setattr(env_path, "_broadcast_env_change", lambda: None)
    monkeypatch.setattr(
        env_path, "read_user_env_var", lambda n: str(root) if n == "JAVA_HOME" else r"C:\other"
    )
    monkeypatch.setattr(env_path, "delete_user_env_var", lambda n: (deleted.append(n) or True, ""))
    plan = {"ids": [pkg.winget_id], "dirs": [str(root)], "user_path": [], "machine_path": []}
    ok, report = tc.purge_package(pkg, plan)
    assert ok and deleted == ["JAVA_HOME"] and "JAVA_HOME" in report


# --- окно --------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _window(app, cfg):
    from launcher import gui

    cats = {
        "always_on": {"extensions": []},
        "categories": {"web": {"title": "Web", "extensions": ["a.b"]}},
    }
    Launcher = gui._launcher_factory(
        cats,
        "",
        cfg,
        categories.build_ext_index(cats),
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


def test_deleted_recent_folders_are_dropped_on_start(app, tmp_path):
    alive = str(tmp_path)
    cfg = config.migrate_config({"recent_folders": [str(tmp_path / "нет"), alive]})
    w = _window(app, cfg)
    try:
        assert cfg["recent_folders"] == [alive]
        assert w.folder_edit.text() == alive
    finally:
        w.deleteLater()


def test_ctrl_digit_switches_pages(app):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    w = _window(app, config.migrate_config({}))
    try:
        QTest.keyClick(w, Qt.Key.Key_6, Qt.KeyboardModifier.ControlModifier)
        assert w._page == "settings"
        QTest.keyClick(w, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
        assert w._page == "launch"
    finally:
        w.deleteLater()


def test_hide_after_launch_switch_saves_setting(app):
    cfg = config.migrate_config({})
    w = _window(app, cfg)
    try:
        w.hide_cb.setChecked(True)
        assert cfg["hide_after_launch"] is True
    finally:
        w.deleteLater()
