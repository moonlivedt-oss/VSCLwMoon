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
    # Константа живёт в launcher.categories (см. фасад core.py);
    # ставим её через подмодуль, чтобы load_categories её увидел.
    monkeypatch.setattr(core.categories, "CATEGORIES_FILE", f)
    data, err = core.load_categories()
    assert err == ""
    assert "python" in data["categories"]


def test_load_categories_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(core.categories, "CATEGORIES_FILE", tmp_path / "nope.json")
    data, err = core.load_categories()
    assert err
    assert data == {"always_on": {"extensions": []}, "categories": {}}


def test_load_categories_broken(tmp_path, monkeypatch):
    f = tmp_path / "bad.json"
    f.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr(core.categories, "CATEGORIES_FILE", f)
    data, err = core.load_categories()
    assert err
    assert data["categories"] == {}


def test_load_categories_wrong_type(tmp_path, monkeypatch):
    f = tmp_path / "list.json"
    f.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setattr(core.categories, "CATEGORIES_FILE", f)
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


# --- safe_arg / argument injection ----------------------------------------

def test_safe_arg_strips_leading_dashes():
    # значение-подделка под флаг обезврежено, внутренние дефисы сохранены
    assert core.safe_arg("--disable-workspace-trust") == "disable-workspace-trust"
    assert core.safe_arg("  --extensions-dir=C:\\evil") == "extensions-dir=C:\\evil"
    assert core.safe_arg("D:\\my-project") == "D:\\my-project"
    assert core.safe_arg("") == ""


def test_build_launch_args_blocks_flag_injection_via_folder():
    # папка вида '--disable-workspace-trust' не должна стать флагом Code.exe
    args = core.build_launch_args([], "--disable-workspace-trust", True, False)
    assert "--disable-workspace-trust" not in args
    assert args[-1] == "disable-workspace-trust"


def test_build_launch_command_blocks_flag_injection_via_folder():
    cmd = core.build_launch_command("code.cmd", [], "--extensions-dir=C:\\evil", True, False)
    assert '"--extensions-dir=C:\\evil"' not in cmd
    assert "extensions-dir=C:\\evil" in cmd


def test_build_launch_args_blocks_flag_injection_via_profile():
    args = core.build_launch_args([], "", True, False, profile="--foo")
    assert "--foo" not in args
    assert "foo" in args


# --- kill_vscode (мягко / жёстко) -----------------------------------------

def test_kill_vscode_force_uses_slash_f(monkeypatch):
    seen = {}
    monkeypatch.setattr(core.subprocess, "run",
                        lambda a, **k: seen.setdefault("args", a))
    core.kill_vscode("code.cmd")                      # по умолчанию — жёстко
    assert "/F" in seen["args"]
    assert seen["args"][-1] == "Code.exe"


def test_kill_vscode_graceful_omits_slash_f(monkeypatch):
    seen = {}
    monkeypatch.setattr(core.subprocess, "run",
                        lambda a, **k: seen.setdefault("args", a))
    core.kill_vscode("code.cmd", graceful=True)       # мягко — без /F
    assert "/F" not in seen["args"]
    assert "/IM" in seen["args"] and seen["args"][-1] == "Code.exe"


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


# --- save_config (атомарная запись) ---------------------------------------

def test_save_config_atomic_roundtrip(tmp_path, monkeypatch):
    cf = tmp_path / "launcher_config.json"
    # save_config живёт в launcher.config; патчим константу через него.
    monkeypatch.setattr(core.config, "CONFIG_FILE", cf)
    core.save_config({"presets": {"web": ["web"]}, "kill_first": True})
    data = json.loads(cf.read_text(encoding="utf-8"))
    assert data["presets"]["web"] == ["web"]
    assert list(tmp_path.glob("*.tmp")) == []   # временный файл не остаётся


def test_save_config_keeps_old_on_write_error(tmp_path, monkeypatch):
    cf = tmp_path / "launcher_config.json"
    cf.write_text('{"presets": {"old": []}}', encoding="utf-8")
    monkeypatch.setattr(core.config, "CONFIG_FILE", cf)

    def boom(*a, **k):
        raise OSError("disk full")
    # os — singleton-модуль, патч core.os.replace виден и в config.py.
    monkeypatch.setattr(core.os, "replace", boom)
    with pytest.raises(OSError):
        core.save_config({"presets": {"new": []}})
    # прежний конфиг цел, мусора не осталось
    assert json.loads(cf.read_text(encoding="utf-8"))["presets"] == {"old": []}
    assert list(tmp_path.glob("*.tmp")) == []


# --- find_duplicate_extensions --------------------------------------------

def test_find_duplicates_empty_for_clean_map():
    assert core.find_duplicate_extensions(sample_cats()) == {}


def test_find_duplicates_detects_cross_category_and_always_on():
    cats = {
        "always_on": {"extensions": ["core.ext", "shared.tool"]},
        "categories": {
            # дубль с always_on
            "python": {"extensions": ["ms-python.python", "shared.tool"]},
            # дубль с python
            "web": {"extensions": ["dbaeumer.vscode-eslint", "ms-python.python"]},
            "java": {"extensions": ["redhat.java"]},
        },
    }
    dups = core.find_duplicate_extensions(cats)
    assert set(dups) == {"shared.tool", "ms-python.python"}
    # Порядок ключей — как встречали (для наглядного сообщения пользователю).
    assert dups["shared.tool"] == ["always_on", "python"]
    assert dups["ms-python.python"] == ["python", "web"]


def test_find_duplicates_case_insensitive():
    cats = {
        "always_on": {"extensions": []},
        "categories": {
            "a": {"extensions": ["Pub.Ext"]},
            "b": {"extensions": ["pub.ext"]},   # тот же id в другом регистре
        },
    }
    dups = core.find_duplicate_extensions(cats)
    assert list(dups) == ["pub.ext"]


def test_build_ext_index_last_wins_on_duplicate():
    # Документируем текущее поведение build_ext_index: при дубле побеждает
    # последний, поэтому find_duplicate_extensions и нужен для предупреждения.
    cats = {
        "always_on": {"extensions": []},
        "categories": {
            "first": {"extensions": ["shared.ext"]},
            "second": {"extensions": ["shared.ext"]},
        },
    }
    assert core.build_ext_index(cats)["shared.ext"] == "second"


# --- _rotate_settings_backups ---------------------------------------------

def test_rotate_backups_keeps_last_n(tmp_path):
    # Имена сортируются лексикографически по timestamps, поэтому берём фиксированные.
    for ts in ["20250101-000000", "20250102-000000", "20250103-000000",
               "20250104-000000", "20250105-000000", "20250106-000000",
               "20250107-000000"]:
        (tmp_path / f"settings.backup-{ts}.json").write_text("{}", encoding="utf-8")
    removed = core._rotate_settings_backups(tmp_path, keep=3)
    assert removed == 4
    kept = sorted(p.name for p in tmp_path.glob("settings.backup-*.json"))
    assert kept == [
        "settings.backup-20250105-000000.json",
        "settings.backup-20250106-000000.json",
        "settings.backup-20250107-000000.json",
    ]


def test_rotate_backups_noop_when_within_limit(tmp_path):
    for ts in ["20250101-000000", "20250102-000000"]:
        (tmp_path / f"settings.backup-{ts}.json").write_text("{}", encoding="utf-8")
    assert core._rotate_settings_backups(tmp_path, keep=5) == 0
    assert len(list(tmp_path.glob("settings.backup-*.json"))) == 2


def test_rotate_backups_ignores_other_files(tmp_path):
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("keep me", encoding="utf-8")
    (tmp_path / "settings.backup-20250101-000000.json").write_text("{}", encoding="utf-8")
    core._rotate_settings_backups(tmp_path, keep=0)
    assert (tmp_path / "settings.json").exists()
    assert (tmp_path / "notes.txt").exists()
    assert list(tmp_path.glob("settings.backup-*.json")) == []


def test_apply_settings_rotates_backups(tmp_path):
    # 7 старых бэкапов + settings.json: после apply_settings их остаётся
    # SETTINGS_BACKUP_KEEP (5), включая только что созданный.
    p = tmp_path / "settings.json"
    p.write_text('{"editor.fontSize": 14}', encoding="utf-8")
    for i in range(1, 8):
        (tmp_path / f"settings.backup-2025010{i}-000000.json").write_text(
            "{}", encoding="utf-8")
    ok, _msg = core.apply_settings(p, {"git.autofetch": True})
    assert ok
    backups = sorted(tmp_path.glob("settings.backup-*.json"))
    assert len(backups) == core.SETTINGS_BACKUP_KEEP


def test_apply_settings_when_no_prior_file_no_backup(tmp_path):
    p = tmp_path / "settings.json"
    ok, msg = core.apply_settings(p, {"a": 1})
    assert ok
    assert "Бэкап" not in msg   # нечего было бэкапить
    assert list(tmp_path.glob("settings.backup-*.json")) == []


# --- detect_stacks (#1 автоопределение проекта) ---------------------------

def test_detect_stacks_by_marker_files(tmp_path):
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "go.mod").write_text("module x", encoding="utf-8")
    found = core.detect_stacks(tmp_path)
    assert {"python", "web", "go"} <= found


def test_detect_stacks_by_suffix(tmp_path):
    (tmp_path / "main.rs").write_text("", encoding="utf-8")
    (tmp_path / "app.cs").write_text("", encoding="utf-8")
    found = core.detect_stacks(tmp_path)
    assert "rust" in found and "dotnet" in found


def test_detect_stacks_prunes_and_detects_git(tmp_path):
    (tmp_path / ".git").mkdir()
    junk = tmp_path / "node_modules" / "pkg"
    junk.mkdir(parents=True)
    (junk / "index.ts").write_text("", encoding="utf-8")   # не должен дать web
    (tmp_path / "readme.md").write_text("", encoding="utf-8")
    found = core.detect_stacks(tmp_path)
    assert "git" in found          # .git-каталог замечен до прунинга
    assert "markdown" in found
    assert "web" not in found      # node_modules выкинут из обхода


def test_detect_stacks_respects_available(tmp_path):
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "main.rs").write_text("", encoding="utf-8")
    found = core.detect_stacks(tmp_path, available={"python"})
    assert found == {"python"}     # rust отфильтрован — его нет в карте


def test_detect_stacks_missing_path():
    assert core.detect_stacks("Z:\\nope\\missing") == set()
    assert core.detect_stacks("") == set()


# --- compute_disabled: оверрайды по расширению (#9) ------------------------

def test_compute_disabled_force_disable_within_enabled_stack():
    idx = core.build_ext_index(sample_cats())
    installed = ["ms-python.python", "charliermarsh.ruff"]
    # стек python включён, но ruff персонально принудительно выключаем
    disabled = core.compute_disabled(installed, idx, {"python"},
                                     force_disable={"charliermarsh.ruff"})
    assert "charliermarsh.ruff" in disabled
    assert "ms-python.python" not in disabled


def test_compute_disabled_force_enable_overrides_off_stack():
    idx = core.build_ext_index(sample_cats())
    installed = ["ms-python.python", "redhat.java"]
    # ни один стек не выбран, но python держим включённым персонально
    disabled = core.compute_disabled(installed, idx, set(),
                                     force_enable={"ms-python.python"})
    assert "ms-python.python" not in disabled
    assert "redhat.java" in disabled


def test_compute_disabled_force_enable_beats_force_disable():
    idx = core.build_ext_index(sample_cats())
    installed = ["ms-python.python"]
    disabled = core.compute_disabled(installed, idx, {"python"},
                                     force_disable={"ms-python.python"},
                                     force_enable={"ms-python.python"})
    assert disabled == []          # force_enable в приоритете


def test_compute_disabled_no_overrides_unchanged():
    idx = core.build_ext_index(sample_cats())
    installed = ["ms-python.python", "dbaeumer.vscode-eslint"]
    assert core.compute_disabled(installed, idx, {"python"}) == \
        ["dbaeumer.vscode-eslint"]


# --- disabled_by_category (#5 предпросмотр) --------------------------------

def test_disabled_by_category_groups_and_sorts():
    idx = core.build_ext_index(sample_cats())
    disabled = ["redhat.java", "dbaeumer.vscode-eslint", "some.unknown"]
    groups = dict(core.disabled_by_category(disabled, idx))
    assert groups["web"] == ["dbaeumer.vscode-eslint"]
    assert groups["java"] == ["redhat.java"]
    assert groups["(не в карте)"] == ["some.unknown"]


# --- selection_signature (#6) ---------------------------------------------

def test_selection_signature_stable_and_order_independent():
    assert core.selection_signature({"web", "python"}) == \
        core.selection_signature({"python", "web"})
    assert core.selection_signature(set()) == "core-only"
    assert core.selection_signature({"web"}, bare=True) == "bare"


# --- footprint history (#6) -----------------------------------------------

def test_record_and_lookup_footprint():
    cfg = {}
    core.record_footprint(cfg, "python|web", 1200, 8)
    assert core.lookup_footprint(cfg, "python|web") == {"mb": 1200, "n": 8}
    assert core.lookup_footprint(cfg, "other") is None


def test_record_footprint_ignores_zero_measurement():
    cfg = {}
    core.record_footprint(cfg, "python", 0, 0)   # VS Code не запущен
    assert core.lookup_footprint(cfg, "python") is None


def test_record_footprint_caps_history():
    cfg = {}
    for i in range(50):
        core.record_footprint(cfg, f"sig{i:02d}", 100 + i, 1, cap=10)
    hist = cfg["footprint_history"]
    assert len(hist) == 10
    assert "sig49" in hist and "sig00" not in hist   # свежие пережили чистку


# --- updates: сравнение версий (#8) ---------------------------------------

@pytest.mark.parametrize("s,expected", [
    ("v1.2.0", (1, 2, 0)), ("1.2", (1, 2)), ("release-2.0.1-beta", (2, 0, 1)),
    ("", (0,)), ("no-numbers", (0,)),
])
def test_parse_version(s, expected):
    assert core.parse_version(s) == expected


@pytest.mark.parametrize("latest,current,newer", [
    ("v1.2.0", "1.1.0", True), ("1.2.0", "1.2.0", False),
    ("1.10.0", "1.9.0", True), ("1.2", "1.2.0", False), ("v2.0", "1.9.9", True),
])
def test_is_newer(latest, current, newer):
    assert core.is_newer(latest, current) is newer


# --- cli._resolve_selected (#10) ------------------------------------------

def test_cli_resolve_selected_from_preset_and_stacks():
    from launcher import cli
    cfg = {"presets": {"web": ["web", "git"]}}
    args = cli.build_parser().parse_args(["--preset", "web", "--stacks", "python,bogus"])
    selected, warns = cli._resolve_selected(args, cfg, {"web", "git", "python"})
    assert selected == {"web", "git", "python"}
    assert any("bogus" in w for w in warns)


def test_cli_resolve_selected_unknown_preset_warns():
    from launcher import cli
    args = cli.build_parser().parse_args(["--preset", "nope"])
    selected, warns = cli._resolve_selected(args, {"presets": {}}, {"web"})
    assert selected == set()
    assert any("nope" in w for w in warns)
