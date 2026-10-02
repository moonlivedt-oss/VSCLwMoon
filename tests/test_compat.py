# -*- coding: utf-8 -*-
"""Проверка совместимости расширений (compat.py) и исправления аудита 2026-10-01:
кавычки в командах, ярлык пресета, .obsolete, конфиг, CLI."""

import json

import pytest

from launcher import cli, compat, config, launch, presets, quicklaunch, vscode


# --- engines.vscode ---------------------------------------------------------


@pytest.mark.parametrize(
    "engine,ok",
    [
        ("^1.80.0", True),
        ("^1.121.0", True),
        ("^1.130.0", False),
        (">=1.50.0", True),
        ("*", True),
        ("^0.10.0", True),  # «ниже 1.0.0 совместимо с 1.x»
        ("1.121.0", True),  # точное совпадение
        ("1.120.0", False),  # точная версия, другая
        ("^2.0.0", False),
        ("^1.x.x", True),
        ("^1.95.0-insider", True),
    ],
)
def test_engine_satisfied(engine, ok):
    assert compat.engine_satisfied(engine, "1.121.0") is ok


@pytest.mark.parametrize("engine", ["", "latest", "~1.2", "1.2"])
def test_engine_unparsable_is_none(engine):
    assert compat.engine_satisfied(engine, "1.121.0") is None


def test_platform_mismatch():
    assert compat.platform_mismatch("linux-x64")
    assert compat.platform_mismatch("darwin-arm64")
    assert not compat.platform_mismatch("win32-x64")
    assert not compat.platform_mismatch("universal")
    assert not compat.platform_mismatch("")


# --- сама проверка -----------------------------------------------------------

RULES = {
    "conflicts": [
        {"ids": ["a.vim", "b.neovim"], "keep": "", "reason": "клавиши"},
        {"ids": ["new.lang", "old.lang"], "keep": "new.lang", "reason": "дубли"},
    ],
    "deprecated": [
        {"id": "old.colorizer", "replaced_by": "", "reason": "встроено"},
        {"id": "x.tslint", "replaced_by": "x.eslint", "reason": "заменён"},
    ],
}


def _kinds(issues):
    return sorted((i["kind"], i["ext"]) for i in issues)


def test_engine_issue_and_fix():
    man = {"p.new": {"engine": "^1.200.0"}}
    issues = compat.check(["p.new"], man, "1.121.0", rules=RULES)
    assert _kinds(issues) == [("engine", "p.new")]
    assert issues[0]["disable"] == ["p.new"] and issues[0]["severity"] == "error"


def test_missing_dependency_but_builtin_and_vscode_ok():
    man = {"p.a": {"depends": ["p.lib", "github.copilot-chat", "vscode.git"]}}
    issues = compat.check(["p.a"], man, "1.121.0", rules=RULES, builtin={"github.copilot-chat"})
    assert [(i["kind"], i["others"]) for i in issues] == [("missing_dep", ["p.lib"])]


def test_dependency_installed_but_off():
    man = {"p.a": {"depends": ["p.lib"]}}
    issues = compat.check(["p.a"], man, installed=["p.a", "p.lib"], rules=RULES)
    assert _kinds(issues) == [("dep_off", "p.a")]


def test_conflict_with_and_without_keep():
    issues = compat.check(["a.vim", "b.neovim", "new.lang", "old.lang"], {}, rules=RULES)
    by = {tuple(sorted([i["ext"], *i["others"]])): i for i in issues}
    assert by[("a.vim", "b.neovim")]["disable"] == []  # выбирает человек
    assert by[("new.lang", "old.lang")]["disable"] == ["old.lang"]


def test_deprecated_info_vs_warning():
    issues = compat.check(["old.colorizer", "x.tslint", "x.eslint"], {}, rules=RULES)
    sev = {i["ext"]: i["severity"] for i in issues}
    assert sev == {"old.colorizer": "info", "x.tslint": "warning"}
    assert [i["ext"] for i in compat.actionable(issues)] == ["x.tslint"]


def test_ignored_keys_are_hidden():
    issues = compat.check(["a.vim", "b.neovim"], {}, rules=RULES)
    assert compat.actionable(issues, [issues[0]["key"]]) == []


def test_resolve_auto_cascades_dependents():
    # bad.base не запустится (версия), а dep.user от него зависит — в auto
    # выключаются оба, проверка становится чистой.
    man = {"bad.base": {"engine": "^1.300.0"}, "dep.user": {"depends": ["bad.base"]}}
    issues, off = compat.resolve(
        ["bad.base", "dep.user", "ok.one"],
        man,
        "1.121.0",
        ["bad.base", "dep.user", "ok.one"],
        "auto",
        rules=RULES,
    )
    assert off == {"bad.base", "dep.user"} and issues == []


def test_resolve_warn_does_not_disable_and_off_is_silent():
    man = {"bad.base": {"engine": "^1.300.0"}}
    issues, off = compat.resolve(["bad.base"], man, "1.121.0", [], "warn", rules=RULES)
    assert off == set() and len(issues) == 1
    assert compat.resolve(["bad.base"], man, "1.121.0", [], "off", rules=RULES) == ([], set())


def test_bundled_rules_file_is_valid():
    rules = compat.load_rules()
    assert rules["conflicts"] and rules["deprecated"]
    for c in rules["conflicts"]:
        assert len(c["ids"]) >= 2 and (not c["keep"] or c["keep"] in c["ids"])


def test_mode_of_falls_back():
    assert compat.mode_of({}) == "warn"
    assert compat.mode_of({"compat_check": "auto"}) == "auto"
    assert compat.mode_of({"compat_check": "кривое"}) == "warn"


# --- версия и встроенные расширения VS Code -----------------------------------


def _fake_install(root, version, builtin=()):
    app = root / "f6cfa2ea24" / "resources" / "app"
    (app / "extensions").mkdir(parents=True)
    (app / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    for pub, name in builtin:
        d = app / "extensions" / name
        d.mkdir()
        (d / "package.json").write_text(
            json.dumps({"publisher": pub, "name": name}), encoding="utf-8"
        )
    (root / "bin").mkdir()
    cli_path = root / "bin" / "code.cmd"
    cli_path.write_text("", encoding="utf-8")
    return str(cli_path)


def test_vscode_version_and_builtin_from_hash_folder(tmp_path):
    code = _fake_install(tmp_path, "1.121.0", [("GitHub", "copilot-chat")])
    assert compat.vscode_version(code) == "1.121.0"
    assert "github.copilot-chat" in compat.builtin_extensions(code)
    assert compat.vscode_version(None) == ""


# --- общий путь запуска: auto выключает, warn сообщает ---------------------------


def test_plan_launch_auto_disables_incompatible(monkeypatch):
    man = {"bad.one": {"engine": "^1.999.0"}, "good.one": {}}
    monkeypatch.setattr(compat, "vscode_version", lambda cli: "1.121.0")
    monkeypatch.setattr(compat, "builtin_extensions", lambda cli: frozenset())
    cfg = {"compat_check": "auto"}
    plan = quicklaunch.plan_launch(
        "code", cfg, {}, [], {}, installed=["bad.one", "good.one"], dep_map={}, manifests=man
    )
    assert plan["compat_disabled"] == ["bad.one"]
    assert "bad.one" in plan["disabled"] and "good.one" not in plan["disabled"]
    assert "bad.one" in plan["args"]

    cfg = {"compat_check": "warn"}
    plan = quicklaunch.plan_launch(
        "code", cfg, {}, [], {}, installed=["bad.one", "good.one"], dep_map={}, manifests=man
    )
    assert plan["compat_disabled"] == [] and len(plan["compat_issues"]) == 1
    assert "компат" not in quicklaunch.compat_summary({}).lower()
    assert "1" in quicklaunch.compat_summary(plan)

    plan = quicklaunch.plan_launch(
        "code",
        cfg,
        {},
        [],
        {},
        installed=["bad.one"],
        dep_map={},
        manifests=man,
        extra_disable={"bad.one"},
        compat_mode="off",
    )
    assert plan["disabled"] == ["bad.one"] and plan["compat_issues"] == []


# --- аудит: исправленные баги ------------------------------------------------------


def test_obsolete_extensions_not_listed(tmp_path, monkeypatch):
    monkeypatch.setenv("VSCODE_EXTENSIONS", str(tmp_path))
    (tmp_path / "extensions.json").write_text(
        json.dumps(
            [
                {"identifier": {"id": "A.Keep"}, "relativeLocation": "a.keep-1.0.0"},
                {"identifier": {"id": "b.gone"}, "relativeLocation": "b.gone-2.0.0"},
                {"identifier": None},
                "мусор",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / ".obsolete").write_text(json.dumps({"b.gone-2.0.0": True}), encoding="utf-8")
    assert vscode.read_installed_from_disk(None) == ["a.keep"]


def test_shortcut_name_cannot_inject_commands():
    body = presets.build_shortcut_cmd(["C:\\app.exe"], 'x"\r\ncalc & 100%')
    last = body.strip().splitlines()[-1]
    assert "calc" in last and "\ncalc" not in body
    assert "100%%" in last and '"x' in last


def test_preset_string_bools():
    p = presets.normalize_preset({"stacks": [], "kill": "false", "bare": "true"})
    assert p["kill"] is False and p["bare"] is True


def test_launch_command_trailing_backslash():
    cmd = launch.build_launch_command("code", [], "D:\\", False, False)
    assert cmd.endswith('"D:\\\\"')


def test_validate_config_cleans_lists_and_choices():
    cfg = {"recent_folders": ["D:\\a", 5, None], "compat_check": "всегда", "theme": "pink"}
    fixed = config.validate_config(cfg)
    assert cfg["recent_folders"] == ["D:\\a"]
    assert cfg["compat_check"] == "warn" and cfg["theme"] == "dark"
    assert {"recent_folders", "compat_check", "theme"} <= set(fixed)


def test_save_config_keeps_good_backup(tmp_path):
    cf = config.CONFIG_FILE
    bak = config.backup_config_path()
    bak.write_text('{"presets": {"good": []}}', encoding="utf-8")
    cf.write_text("{битый", encoding="utf-8")
    config.save_config({"presets": {}})
    assert json.loads(bak.read_text(encoding="utf-8")) == {"presets": {"good": []}}
    assert json.loads(cf.read_text(encoding="utf-8")) == {"presets": {}}


def test_cmd_fallback_quotes_and_rejects(monkeypatch):
    calls = []
    monkeypatch.setattr(vscode, "code_gui_exe", lambda cli: None)
    monkeypatch.setattr(vscode, "clean_launch_env", lambda: {})
    monkeypatch.setattr(vscode.subprocess, "Popen", lambda cmd, **kw: calls.append(cmd))
    vscode.launch_detached("C:\\VS\\code.cmd", ["--new-window", "D:\\a&b\\"])
    assert calls and '"D:\\a&b\\\\"' in calls[0]
    with pytest.raises(OSError):
        vscode.launch_detached("C:\\VS\\code.cmd", ["D:\\100%path%"])


def test_code_gui_exe_accepts_exe(tmp_path):
    exe = tmp_path / "Code.exe"
    exe.write_bytes(b"")
    assert vscode.code_gui_exe(str(exe)) == exe


def test_cli_run_with_unknown_preset_fails(monkeypatch):
    monkeypatch.setattr(cli, "load_installed", lambda c: (["a.one"], "тест"))
    started = []
    monkeypatch.setattr(cli, "launch_detached", lambda c, a: started.append(a))
    rc = cli.cli_main(["--preset", "нет-такого", "--run", "--quiet", "--code-cli", __file__])
    assert rc == 2 and not started


def test_path_overwrite_guard(tmp_path):
    from launcher import env_path

    live = str(tmp_path)
    old = f"{live};C:\nonexistent-dir-xyz"
    # Сбой чтения реестра: «дописать каталог» дало бы PATH из одной записи.
    assert env_path.check_path_overwrite(old, "D:\new\bin")
    # Обычные правки: запись сохранена / убраны только мёртвые / PATH был пуст.
    assert env_path.check_path_overwrite(old, f"{live};D:\new\bin") == ""
    assert env_path.check_path_overwrite("C:\nonexistent-dir-xyz", "") == ""
    assert env_path.check_path_overwrite("", "D:\new\bin") == ""
