# -*- coding: utf-8 -*-
"""Тесты чистой логики из launcher/core.py (без GUI).

Запуск:  python -m pytest
"""
import json

import pytest

from launcher import core


# --- build_ext_index -------------------------------------------------------

def sample_cats():
    return {
        "always_on": {"extensions": ["Anthropic.Claude-Code", "pkief.material-icon-theme"]},
        "categories": {
            "python": {"extensions": ["ms-python.python", "charliermarsh.ruff"]},
            "web": {"extensions": ["dbaeumer.vscode-eslint"]},
            "java": {"extensions": ["redhat.java"]},
        },
    }


def test_build_ext_index_lowercases_and_maps():
    idx = core.build_ext_index(sample_cats())
    assert idx["ms-python.python"] == "python"
    assert idx["charliermarsh.ruff"] == "python"
    assert idx["dbaeumer.vscode-eslint"] == "web"
    # always_on распознаётся и приводится к нижнему регистру
    assert idx["anthropic.claude-code"] == "always_on"


def test_build_ext_index_empty():
    assert core.build_ext_index({}) == {}


# --- compute_disabled ------------------------------------------------------

def test_compute_disabled_turns_off_unselected():
    idx = core.build_ext_index(sample_cats())
    installed = ["ms-python.python", "dbaeumer.vscode-eslint", "redhat.java"]
    disabled = core.compute_disabled(installed, idx, {"python"})
    assert "ms-python.python" not in disabled          # выбранная категория — вкл
    assert "dbaeumer.vscode-eslint" in disabled        # web не выбран — выкл
    assert "redhat.java" in disabled                    # java не выбран — выкл


def test_compute_disabled_keeps_always_on_and_unknown():
    idx = core.build_ext_index(sample_cats())
    installed = ["anthropic.claude-code", "some.unknown-ext"]
    disabled = core.compute_disabled(installed, idx, set())
    assert disabled == []   # ядро и незамапленное остаются включёнными


# --- estimate_saved_mb -----------------------------------------------------

def test_estimate_saved_mb_counts_each_category_once():
    idx = core.build_ext_index(sample_cats())
    # два питоновых расширения выключены -> питон считается один раз (medium=150)
    disabled = ["ms-python.python", "charliermarsh.ruff"]
    assert core.estimate_saved_mb(disabled, idx) == core.WEIGHT_MB["medium"]


def test_estimate_saved_mb_sums_distinct_categories():
    idx = core.build_ext_index(sample_cats())
    disabled = ["ms-python.python", "redhat.java"]   # medium + heavy
    expected = core.WEIGHT_MB["medium"] + core.WEIGHT_MB["heavy"]
    assert core.estimate_saved_mb(disabled, idx) == expected


def test_estimate_saved_mb_empty():
    assert core.estimate_saved_mb([], {}) == 0


# --- code_image_name -------------------------------------------------------

def test_code_image_name_stable():
    assert core.code_image_name(r"C:\...\bin\code.cmd") == "Code.exe"


def test_code_image_name_insiders():
    assert core.code_image_name(r"C:\...\bin\code-insiders.cmd") == "Code - Insiders.exe"


def test_code_image_name_none():
    assert core.code_image_name(None) == "Code.exe"


# --- build_launch_command --------------------------------------------------

def test_build_launch_command_kill_first_prepends_taskkill():
    cmd = core.build_launch_command("code.cmd", ["a.b"], "", False, True)
    assert "taskkill /F /IM" in cmd
    assert "timeout /t 2" in cmd
    assert "--new-window" in cmd            # kill_first форсит новое окно
    assert cmd.count(" & ") >= 2            # taskkill & timeout & launch


def test_build_launch_command_disables_extensions():
    cmd = core.build_launch_command("code.cmd", ["ms-python.python"], "", True, False)
    assert "--disable-extension" in cmd
    assert "ms-python.python" in cmd
    assert "taskkill" not in cmd            # без kill_first


def test_build_launch_command_bare_ignores_list():
    cmd = core.build_launch_command("code.cmd", ["ms-python.python"], "", True, False, bare=True)
    assert "--disable-extensions" in cmd
    assert "--disable-extension ms-python.python" not in cmd


def test_build_launch_command_folder_and_profile_quoted():
    cmd = core.build_launch_command(
        "code.cmd", [], r"D:\my project", True, False,
        profile="Web", disable_gpu=True)
    assert '"D:\\my project"' in cmd
    assert '--profile "Web"' in cmd
    assert "--disable-gpu" in cmd


# --- read_installed_from_disk ---------------------------------------------

def test_read_installed_from_disk(tmp_path, monkeypatch):
    ext_dir = tmp_path / "extensions"
    ext_dir.mkdir()
    (ext_dir / "extensions.json").write_text(json.dumps([
        {"identifier": {"id": "MS-Python.Python"}},
        {"identifier": {"id": "redhat.java"}},
    ]), encoding="utf-8")
    monkeypatch.setenv("VSCODE_EXTENSIONS", str(ext_dir))
    ids = core.read_installed_from_disk("code.cmd")
    assert ids == ["ms-python.python", "redhat.java"]   # lower + sorted


def test_read_installed_from_disk_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("VSCODE_EXTENSIONS", str(tmp_path / "nope"))
    assert core.read_installed_from_disk("code.cmd") == []


# --- load_categories (устойчивость) ---------------------------------------

def test_load_categories_ok(tmp_path, monkeypatch):
    f = tmp_path / "categories.json"
    f.write_text(json.dumps(sample_cats()), encoding="utf-8")
    monkeypatch.setattr(core, "CATEGORIES_FILE", f)
    data, err = core.load_categories()
    assert err == ""
    assert "python" in data["categories"]


def test_load_categories_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "CATEGORIES_FILE", tmp_path / "nope.json")
    data, err = core.load_categories()
    assert err
    assert data == {"always_on": {"extensions": []}, "categories": {}}


def test_load_categories_broken(tmp_path, monkeypatch):
    f = tmp_path / "bad.json"
    f.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr(core, "CATEGORIES_FILE", f)
    data, err = core.load_categories()
    assert err
    assert data["categories"] == {}


def test_load_categories_wrong_type(tmp_path, monkeypatch):
    f = tmp_path / "list.json"
    f.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setattr(core, "CATEGORIES_FILE", f)
    data, err = core.load_categories()
    assert err
    assert data["categories"] == {}


# --- valid_ext_id (безопасность) ------------------------------------------

@pytest.mark.parametrize("eid", [
    "ms-python.python", "redhat.java", "13xforever.language-x86-64-assembly",
    "ms-ceintl.vscode-language-pack-ru", "moonlivedt.diagnostics-ru",
])
def test_valid_ext_id_accepts_real_ids(eid):
    assert core.valid_ext_id(eid)


@pytest.mark.parametrize("bad", [
    "", "nodot", "a.b & calc.exe", "pub.name; rm -rf", 'pub.name"', "pub name.x",
    "pub.name`x`", "pub.name|x", "../evil",
])
def test_valid_ext_id_rejects_injection(bad):
    assert not core.valid_ext_id(bad)


def test_build_launch_command_drops_invalid_ids():
    cmd = core.build_launch_command(
        "code.cmd", ["ms-python.python", "evil & calc.exe"], "", True, False)
    assert "ms-python.python" in cmd
    assert "calc.exe" not in cmd          # инъекция отфильтрована


def test_install_rejects_bad_id():
    ok, msg = core.install_extension("code.cmd", "evil & calc")
    assert not ok and "Недопустимый" in msg


def test_shell_safe_strips_breakout_chars():
    assert core.shell_safe('C:\\a" & calc') == 'C:\\a & calc'   # кавычка убрана
    assert core.shell_safe("%APPDATA%\\x") == "APPDATA\\x"       # % убран
    assert core.shell_safe("C:\\Rock & Roll") == "C:\\Rock & Roll"  # & сам по себе ок


def test_build_launch_command_sanitizes_folder():
    cmd = core.build_launch_command("code.cmd", [], 'C:\\a" & calc.exe', True, False)
    # кавычки-вырыва нет: путь целиком внутри одной пары кавычек
    assert '" & calc.exe"' not in cmd
    assert cmd.count('"') % 2 == 0


# --- build_launch_args (запуск без оболочки) -------------------------------

def test_build_launch_args_list_form():
    args = core.build_launch_args(
        ["ms-python.python", "bad id&"], "D:\\proj", True, False,
        profile="Web", disable_gpu=True)
    assert args[0] == "--new-window"
    # каждый id — отдельным аргументом, невалидный отброшен
    assert "--disable-extension" in args
    assert "ms-python.python" in args
    assert "bad id&" not in args
    assert "--profile" in args and "Web" in args
    assert "--disable-gpu" in args
    assert args[-1] == "D:\\proj"          # папка — последним аргументом


def test_build_launch_args_bare():
    args = core.build_launch_args(["ms-python.python"], "", True, False, bare=True)
    assert "--disable-extensions" in args
    assert "--disable-extension" not in args


def test_build_launch_args_sanitizes():
    args = core.build_launch_args([], 'C:\\a"x', True, False, profile='p"%')
    assert 'C:\\ax' in args          # кавычка убрана из пути
    assert "p" in args               # профиль очищен от " и %


# --- apply_settings (автонастройка) ---------------------------------------

def test_apply_settings_adds_missing_and_keeps_existing(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"editor.fontSize": 14}', encoding="utf-8")
    ok, msg = core.apply_settings(p, {"editor.fontSize": 20, "git.autofetch": True})
    assert ok
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["editor.fontSize"] == 14      # существующее не тронуто
    assert data["git.autofetch"] is True      # недостающее добавлено
    assert list(tmp_path.glob("settings.backup-*.json"))  # есть бэкап


def test_apply_settings_refuses_jsonc(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{\n  // комментарий\n  "a": 1\n}', encoding="utf-8")
    ok, msg = core.apply_settings(p, {"b": 2})
    assert not ok and "JSONC" in msg
    assert "// комментарий" in p.read_text(encoding="utf-8")   # файл не изменён


def test_apply_settings_creates_when_missing(tmp_path):
    p = tmp_path / "settings.json"   # файла нет
    ok, msg = core.apply_settings(p, {"a": 1})
    assert ok and p.exists()
    assert json.loads(p.read_text(encoding="utf-8"))["a"] == 1
