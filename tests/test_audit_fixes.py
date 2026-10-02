# -*- coding: utf-8 -*-
"""Регрессии из проверки окна: «кнопки живут своей жизнью», «галочки сами
прожимаются», запуск VS Code и настройка C++-проекта.

Каждый тест — один найденный дефект; имя теста говорит, что было сломано.
"""

import json
import logging
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from launcher import cpp_project as cp
from launcher import detect, gui, quicklaunch, vscode
from launcher.categories import build_ext_index, cpp_engine_problem
from launcher.config import migrate_config, remember_folder_stacks, set_folder_auto
from launcher.gui_widgets import ComboBox

CATS = {
    "always_on": {"extensions": ["anthropic.claude-code"]},
    "categories": {
        "python": {"title": "Python", "extensions": ["ms-python.python"]},
        "web": {"title": "Web", "extensions": ["dbaeumer.vscode-eslint"]},
        "cpp": {"title": "C++", "extensions": ["xaver.clang-format"]},
        "cpp_cpptools": {"title": "cpptools", "extensions": ["ms-vscode.cpptools"]},
        "cpp_clangd": {
            "title": "clangd",
            "extensions": ["llvm-vs-code-extensions.vscode-clangd"],
        },
        "cpp_lldb": {"title": "CodeLLDB", "extensions": ["vadimcn.vscode-lldb"]},
    },
}
INSTALLED = sorted(e for c in CATS["categories"].values() for e in c["extensions"]) + [
    "anthropic.claude-code"
]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_window(app, cfg=None):
    cfg = cfg if cfg is not None else migrate_config({})
    cfg.setdefault("installed_cache", {"ids": list(INSTALLED)})
    ext_index = build_ext_index(CATS, cfg.get("extra_categories"))
    Launcher = gui._launcher_factory(
        CATS, "", cfg, ext_index, None, {}, {}, logging.getLogger("launcher-test"), {"fn": None}
    )
    w = Launcher(background=False)
    w.show()
    app.processEvents()
    return w


# --- карточки стеков --------------------------------------------------------


def test_card_toggles_on_release_not_on_press(app):
    w = make_window(app)
    try:
        card = w.cat_checks["python"]
        inside = QPoint(card.width() // 2, 4)
        QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=inside)
        assert not card.isChecked()  # одно нажатие ничего не переключает
        QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=inside)
        assert card.isChecked()
    finally:
        w.deleteLater()


def test_card_press_then_release_outside_is_cancelled(app):
    w = make_window(app)
    try:
        card = w.cat_checks["python"]
        QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(20, 4))
        QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=QPoint(-40, -40))
        assert not card.isChecked()
    finally:
        w.deleteLater()


def test_combo_ignores_mouse_wheel(app):
    box = ComboBox()
    box.addItems(["по стеку", "всегда вкл", "всегда выкл"])
    ev = QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    box.wheelEvent(ev)
    assert box.currentIndex() == 0
    assert not ev.isAccepted()  # колесо уходит прокрутке страницы


def test_select_all_works_while_another_page_is_open(app):
    w = make_window(app)
    try:
        w._goto("settings")
        app.processEvents()
        w._set_all(True)
        assert w._selected() == set(CATS["categories"])
    finally:
        w.deleteLater()


def test_cards_layout_has_height_before_page_is_shown(app):
    w = make_window(app)
    try:
        w._goto("settings")
        app.processEvents()
        assert w._cards_flow.heightForWidth(900) > 50
    finally:
        w.deleteLater()


# --- клавиатура ---------------------------------------------------------------


def _count_runs(w):
    calls = []
    w._run = lambda: calls.append(1)
    w.b_run.setEnabled(True)
    return calls


def test_enter_in_text_field_does_not_launch(app):
    w = make_window(app)
    try:
        calls = _count_runs(w)
        w.activateWindow()
        for field in (w.search_edit, w.folder_edit):
            field.setFocus()
            app.processEvents()
            if QApplication.focusWidget() is not field:
                pytest.skip("платформа не даёт фокус окну")
            QTest.keyClick(field, Qt.Key.Key_Return)
        assert calls == []
    finally:
        w.deleteLater()


def test_escape_clears_search_before_closing(app):
    w = make_window(app)
    try:
        closed = []
        w.close = lambda: closed.append(1)
        w.activateWindow()
        w.search_edit.setFocus()
        app.processEvents()
        if QApplication.focusWidget() is not w.search_edit:
            pytest.skip("платформа не даёт фокус окну")
        w.search_edit.setText("py")
        QTest.keyClick(w.search_edit, Qt.Key.Key_Escape)
        assert w.search_edit.text() == "" and closed == []
    finally:
        w.deleteLater()


# --- папка и авто-набор -------------------------------------------------------


def test_folder_focus_loss_does_not_recheck_auto_stacks(app, tmp_path):
    cfg = migrate_config({})
    folder = str(tmp_path)
    remember_folder_stacks(cfg, folder, ["python"])
    set_folder_auto(cfg, folder, True)
    cfg["recent_folders"] = [folder]
    w = make_window(app, cfg)
    try:
        assert w.cat_checks["python"].isChecked()  # авто-набор применён при старте
        w.cat_checks["python"].setChecked(False)  # человек снял галочку
        w._folder_edited()  # поле потеряло фокус, текст тот же
        assert not w.cat_checks["python"].isChecked()
        w.folder_edit.setText(folder + os.sep)  # текст изменился — считаем заново
        w._folder_edited()
        assert w.cat_checks["python"].isChecked()
    finally:
        w.deleteLater()


def test_auto_folder_sets_exactly_the_remembered_stacks(app, tmp_path):
    cfg = migrate_config({})
    folder = str(tmp_path)
    remember_folder_stacks(cfg, folder, ["python"])
    set_folder_auto(cfg, folder, True)
    cfg["recent_folders"] = [folder]
    cfg["last_selected"] = ["web", "cpp"]  # осталось от прошлого проекта
    w = make_window(app, cfg)
    try:
        assert w._selected() == {"python"}
    finally:
        w.deleteLater()


def test_ui_state_keeps_current_page(app):
    w = make_window(app)
    try:
        w._goto("settings")
        st = w.ui_state()
    finally:
        w.deleteLater()
    w2 = make_window(app)
    try:
        w2.apply_ui_state(st)
        assert w2._page == "settings"
    finally:
        w2.deleteLater()


# --- что нужно проекту --------------------------------------------------------


def _write_vscode(tmp_path, name, data):
    vs = tmp_path / ".vscode"
    vs.mkdir(exist_ok=True)
    (vs / name).write_text(json.dumps(data), encoding="utf-8")


def test_project_required_extensions_reads_debug_types(tmp_path):
    _write_vscode(
        tmp_path,
        "launch.json",
        {"configurations": [{"type": "cppdbg"}, {"type": "lldb", "program": "${command:cmake.x}"}]},
    )
    _write_vscode(tmp_path, "settings.json", {"C_Cpp.intelliSenseEngine": "disabled"})
    need = detect.project_required_extensions(str(tmp_path))
    assert set(need) == {
        "ms-vscode.cpptools",
        "vadimcn.vscode-lldb",
        "ms-vscode.cmake-tools",
        "llvm-vs-code-extensions.vscode-clangd",
    }
    assert detect.project_required_extensions(str(tmp_path / "нет")) == {}
    assert detect.project_required_extensions("") == {}


def test_window_reports_debugger_stack_that_would_be_disabled(app, tmp_path):
    _write_vscode(tmp_path, "launch.json", {"configurations": [{"type": "cppdbg"}]})
    w = make_window(app)
    try:
        w._set_all(False)
        w.cat_checks["cpp"].setChecked(True)
        w.cat_checks["cpp_clangd"].setChecked(True)
        wanted, text = w._missing_for_project(str(tmp_path))
        assert set(wanted) == {"cpp_cpptools"} and "cppdbg" in text
        w.cat_checks["cpp_cpptools"].setChecked(True)
        assert w._missing_for_project(str(tmp_path))[0] == {}
    finally:
        w.deleteLater()


def test_cpp_engine_problem():
    both = {"cpp_cpptools", "cpp_clangd"}
    assert cpp_engine_problem({"python"}, both) == ""
    assert cpp_engine_problem({"cpp"}, both) == "none"
    assert cpp_engine_problem({"cpp", "cpp_cpptools"}, both) == ""
    assert cpp_engine_problem({"cpp", "cpp_cpptools"}, both, cpptools_off=True) == "cpptools_off"
    assert cpp_engine_problem({"cpp", "cpp_clangd"}, both, cpptools_off=True) == ""
    assert cpp_engine_problem({"cpp"}, set()) == ""  # движки не установлены — не наше дело


# --- запуск VS Code -----------------------------------------------------------


def test_launch_env_drops_traces_of_another_vscode():
    env = vscode.clean_launch_env(
        {
            "PATH": "x",
            "ELECTRON_RUN_AS_NODE": "1",
            "VSCODE_IPC_HOOK_CLI": "pipe",
            "vscode_pid": "7",
            "VSCODE_EXTENSIONS": r"D:\ext",
        }
    )
    assert env == {"PATH": "x", "VSCODE_EXTENSIONS": r"D:\ext"}


def _patch_preset_launch(monkeypatch, running: int):
    seen = {"wait": 0, "args": None}
    monkeypatch.setattr(quicklaunch, "load_installed", lambda cli: (["a.one"], "тест"))
    monkeypatch.setattr(quicklaunch, "read_extension_manifests", lambda cli: {})
    monkeypatch.setattr(quicklaunch, "kill_vscode", lambda cli: None)
    monkeypatch.setattr(
        quicklaunch, "wait_vscode_closed", lambda cli: seen.__setitem__("wait", seen["wait"] + 1)
    )
    monkeypatch.setattr(quicklaunch, "vscode_process_count", lambda cli: running)
    monkeypatch.setattr(
        quicklaunch, "launch_detached", lambda cli, args: seen.__setitem__("args", args)
    )
    return seen


def test_preset_launch_waits_for_vscode_to_exit(monkeypatch):
    seen = _patch_preset_launch(monkeypatch, running=5)
    cfg = {"presets": {"web": {"stacks": ["web"], "kill": True}}}
    ok, _msg = quicklaunch.launch_preset("code", cfg, {"a.one": "python"}, "web")
    assert ok and seen["wait"] == 1 and seen["args"] is not None


def test_preset_launch_warns_when_vscode_already_open(monkeypatch):
    seen = _patch_preset_launch(monkeypatch, running=5)
    cfg = {"presets": {"web": {"stacks": ["web"], "kill": False}}}
    ok, msg = quicklaunch.launch_preset("code", cfg, {"a.one": "python"}, "web")
    assert ok and seen["wait"] == 0
    assert "уже был открыт" in msg
    _patch_preset_launch(monkeypatch, running=0)
    ok, msg = quicklaunch.launch_preset("code", cfg, {"a.one": "python"}, "web")
    assert "уже был открыт" not in msg


def test_tray_asks_window_for_current_cli(app, monkeypatch):
    from launcher import gui_tray

    got = {}
    monkeypatch.setattr(
        gui_tray,
        "launch_preset",
        lambda cli, cfg, idx, name: got.update(cli=cli, idx=idx) or (True, "ok"),
    )
    w = make_window(app)
    try:
        tray = gui_tray.LauncherTray(w, {"presets": {}}, {"old": "x"}, lambda: "old-cli", lambda: 0)
        w.current_code_cli = lambda: "new-cli"
        tray.launch("p")
        assert got["cli"] == "new-cli" and got["idx"] is w.current_ext_index()
    finally:
        w.deleteLater()


# --- C++-проект ---------------------------------------------------------------

GXX = r"D:\msys64\ucrt64\bin\g++.exe"
BIN_PATH = r"D:\msys64\ucrt64\bin;${env:PATH}"


def test_build_task_runs_with_compiler_folder_on_path():
    o = cp.ProjectOptions(compiler_path=GXX, olympiad=True)
    for task in cp.tasks_json(o)["tasks"]:
        assert task["options"]["env"] == {"PATH": BIN_PATH}
    o.build = "cmake"
    assert all(t["options"]["env"]["PATH"] == BIN_PATH for t in cp.tasks_json(o)["tasks"])


def test_debug_config_runs_with_compiler_folder_on_path():
    gdb = cp.launch_json(cp.ProjectOptions(compiler_path=GXX, has_cpptools=True))
    assert gdb["configurations"][0]["environment"] == [{"name": "PATH", "value": BIN_PATH}]
    lldb = cp.launch_json(cp.ProjectOptions(compiler_path=GXX, engine="clangd"))
    assert lldb["configurations"][0]["env"] == {"PATH": BIN_PATH}
    msvc = cp.ProjectOptions(compiler_path=r"C:\VS\cl.exe", compiler_kind="msvc", vcvars="v.bat")
    assert "environment" not in cp.launch_json(msvc)["configurations"][0]
    assert "env" not in cp.tasks_json(msvc)["tasks"][0]["options"]


def test_cyrillic_project_path_debugs_with_codelldb(tmp_path):
    # gdb под cppdbg не открывает программу по пути с русскими буквами.
    folder = tmp_path / "Дмитрий" / "c++"
    folder.mkdir(parents=True)
    o = cp.ProjectOptions(compiler_path=GXX, has_cpptools=True)
    plan = {i["path"]: i["content"] for i in cp.plan_files(str(folder), o)}
    conf = json.loads(plan[".vscode/launch.json"])["configurations"][0]
    assert conf["type"] == "lldb"
    assert "vadimcn.vscode-lldb" in plan[".vscode/extensions.json"]
    ascii_dir = tmp_path / "proj"
    ascii_dir.mkdir()
    if str(ascii_dir.resolve()).isascii():
        plan = {i["path"]: i["content"] for i in cp.plan_files(str(ascii_dir), o)}
        assert json.loads(plan[".vscode/launch.json"])["configurations"][0]["type"] == "cppdbg"


def test_run_without_debugger_task_exists():
    tasks = cp.tasks_json(cp.ProjectOptions(compiler_path=GXX))["tasks"]
    run = next(t for t in tasks if t["label"] == cp.RUN_PLAIN_TASK)
    assert run["dependsOn"] == cp.BUILD_TASK and ".exe" in run["command"]


def test_project_tab_keeps_chosen_build_system(app, tmp_path):
    from launcher.gui_cpp import CppCenter

    c = CppCenter(None, None, folder=str(tmp_path))
    try:
        c._refresh_project()  # новая папка без CMakeLists -> «одиночные файлы»
        assert c.pj_build.currentData() == "single"
        c.pj_build.setCurrentIndex(1)  # человек выбрал CMake
        c._refresh_project()  # поле потеряло фокус / нажали «Применить»
        assert c.pj_build.currentData() == "cmake"
    finally:
        c.deleteLater()
