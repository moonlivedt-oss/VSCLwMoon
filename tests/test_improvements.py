# -*- coding: utf-8 -*-
"""Тесты новых возможностей (топ-10 улучшений).

Покрывают чистую логику: миграцию конфига (#15), память стеков по папке (#1),
базлайн реальной экономии (#2), пресеты-профили (#4), генератор ярлыка (#5),
детект по рекомендациям воркспейса (#3), настраиваемый путь к CLI (#13) и
расширенный CLI-режим (#19/#20/#4/#14).
"""
import json

import pytest

from launcher import cli, core
from launcher.presets import (
    build_shortcut_cmd, normalize_preset, preset_has_options, preset_stacks,
)


def sample_cats():
    return {
        "always_on": {"extensions": ["anthropic.claude-code"]},
        "categories": {
            "python": {"title": "Python", "extensions": ["ms-python.python", "charliermarsh.ruff"]},
            "web": {"title": "Web", "extensions": ["dbaeumer.vscode-eslint"]},
            "java": {"title": "Java", "extensions": ["redhat.java"]},
        },
    }


# --- #15 миграция конфига --------------------------------------------------

def test_migrate_config_adds_defaults_and_version():
    cfg = core.migrate_config({})
    for k in ("presets", "recent_folders", "last_selected", "folder_stacks"):
        assert k in cfg
    assert cfg["kill_first"] is True
    assert cfg["config_version"] == core.CONFIG_VERSION


def test_migrate_config_preserves_user_values_and_is_idempotent():
    cfg = {"presets": {"web": ["web"]}, "kill_first": False, "theme": "light"}
    once = core.migrate_config(dict(cfg))
    twice = core.migrate_config(dict(once))
    assert once["presets"] == {"web": ["web"]}
    assert once["kill_first"] is False       # пользовательское значение не тронуто
    assert once["theme"] == "light"
    assert twice == once                      # идемпотентна


def test_migrate_config_handles_non_dict():
    assert core.migrate_config(None)["config_version"] == core.CONFIG_VERSION


# --- #1 память стеков по папке ---------------------------------------------

def test_remember_and_recall_folder_stacks_roundtrip():
    cfg = {}
    core.remember_folder_stacks(cfg, r"D:\Proj", {"python", "git"})
    assert core.recall_folder_stacks(cfg, r"D:\Proj") == ["git", "python"]


def test_recall_folder_stacks_normalizes_path():
    cfg = {}
    core.remember_folder_stacks(cfg, r"D:\Proj", {"python"})
    # разный регистр и слэши указывают на ту же запись
    assert core.recall_folder_stacks(cfg, "d:/proj/") == ["python"]


def test_recall_folder_stacks_missing_is_none():
    assert core.recall_folder_stacks({}, r"D:\nope") is None


def test_remember_folder_stacks_empty_selection_valid():
    cfg = {}
    core.remember_folder_stacks(cfg, r"D:\Proj", set())
    assert core.recall_folder_stacks(cfg, r"D:\Proj") == []   # осознанный «только ядро»


def test_remember_folder_stacks_ignores_blank_folder():
    cfg = {}
    core.remember_folder_stacks(cfg, "", {"python"})
    assert cfg.get("folder_stacks", {}) == {}


def test_remember_folder_stacks_caps_history():
    cfg = {}
    for i in range(50):
        core.remember_folder_stacks(cfg, f"D:\\p{i:02d}", {"python"}, cap=10)
    assert len(cfg["folder_stacks"]) == 10


# --- #2 базлайн и реальная экономия ----------------------------------------

def test_baseline_and_measured_savings():
    cfg = {}
    core.record_baseline(cfg, 2000, 10)
    core.record_footprint(cfg, "python", 1400, 6)
    assert core.lookup_baseline(cfg) == {"mb": 2000, "n": 10}
    assert core.measured_savings_mb(cfg, "python") == 600


def test_measured_savings_none_without_baseline():
    cfg = {}
    core.record_footprint(cfg, "python", 1400, 6)
    assert core.measured_savings_mb(cfg, "python") is None


def test_measured_savings_none_when_not_positive():
    cfg = {}
    core.record_baseline(cfg, 1400, 6)
    core.record_footprint(cfg, "python", 1500, 6)   # шум замера вверх
    assert core.measured_savings_mb(cfg, "python") is None


def test_record_baseline_ignores_zero():
    cfg = {}
    core.record_baseline(cfg, 0, 0)
    assert core.lookup_baseline(cfg) is None


# --- #4 пресеты-профили ----------------------------------------------------

def test_normalize_preset_from_list():
    p = normalize_preset(["python", "web"])
    assert p["stacks"] == ["python", "web"]
    assert p["kill"] is False and p["new_window"] is True and p["folder"] == ""


def test_normalize_preset_from_dict():
    p = normalize_preset({"stacks": ["python"], "kill": True, "folder": "D:\\x",
                          "gpu_off": True, "profile": "Web"})
    assert p["stacks"] == ["python"]
    assert p["kill"] is True and p["gpu_off"] is True
    assert p["folder"] == "D:\\x" and p["profile"] == "Web"


def test_normalize_preset_garbage_is_safe():
    p = normalize_preset({"stacks": "notalist", "bogus": 1})
    assert p["stacks"] == []          # строка не считается списком стеков
    assert "bogus" not in p


def test_preset_stacks_both_forms():
    assert preset_stacks(["a", "b"]) == ["a", "b"]
    assert preset_stacks({"stacks": ["a"]}) == ["a"]


def test_preset_has_options():
    assert preset_has_options({"stacks": ["a"], "kill": True})
    assert not preset_has_options(["a", "b"])
    assert not preset_has_options({"stacks": ["a"]})   # только дефолты


# --- #5 генератор ярлыка ---------------------------------------------------

def test_build_shortcut_cmd_contains_preset_and_run():
    body = build_shortcut_cmd(["python", "vscode_launcher.py"], "web")
    assert "--run" in body and '--preset "web"' in body and "--quiet" in body
    assert '"python"' in body and '"vscode_launcher.py"' in body


def test_build_shortcut_cmd_strips_quotes_from_name():
    body = build_shortcut_cmd(["app.exe"], 'ev"il')
    # кавычка из имени убрана — строку .cmd не разорвать
    assert '--preset "evil"' in body


# --- #3 детект по рекомендациям воркспейса ---------------------------------

def _write_recs(tmp_path, text):
    vs = tmp_path / ".vscode"
    vs.mkdir()
    (vs / "extensions.json").write_text(text, encoding="utf-8")


def test_detect_recommended_maps_ids_to_stacks(tmp_path):
    idx = core.build_ext_index(sample_cats())
    _write_recs(tmp_path, json.dumps(
        {"recommendations": ["ms-python.python", "redhat.java", "anthropic.claude-code"]}))
    found = core.detect_recommended_stacks(tmp_path, idx)
    assert found == {"python", "java"}   # always_on отброшен


def test_detect_recommended_tolerates_jsonc(tmp_path):
    idx = core.build_ext_index(sample_cats())
    _write_recs(tmp_path, '{\n  // рекомендации\n  "recommendations": ["redhat.java",]\n}')
    assert core.detect_recommended_stacks(tmp_path, idx) == {"java"}


def test_detect_recommended_missing_file(tmp_path):
    idx = core.build_ext_index(sample_cats())
    assert core.detect_recommended_stacks(tmp_path, idx) == set()


def test_detect_recommended_unknown_ids_ignored(tmp_path):
    idx = core.build_ext_index(sample_cats())
    _write_recs(tmp_path, json.dumps({"recommendations": ["who.knows"]}))
    assert core.detect_recommended_stacks(tmp_path, idx) == set()


# --- #13 настраиваемый путь к CLI ------------------------------------------

def test_resolve_code_cli_prefers_existing_manual_path(tmp_path):
    exe = tmp_path / "code.cmd"
    exe.write_text("", encoding="utf-8")
    assert core.resolve_code_cli({"code_cli": str(exe)}) == str(exe)


def test_resolve_code_cli_ignores_missing_manual_path(monkeypatch):
    monkeypatch.setattr(core.vscode, "find_code_cli", lambda: "AUTO")
    assert core.resolve_code_cli({"code_cli": r"Z:\nope\code.cmd"}) == "AUTO"


def test_resolve_code_cli_no_config(monkeypatch):
    monkeypatch.setattr(core.vscode, "find_code_cli", lambda: "AUTO")
    assert core.resolve_code_cli(None) == "AUTO"


# --- расширенный CLI (#4 merge, #19 json, #20 list, #14 exit codes) --------

def test_cli_resolve_selected_from_dict_preset():
    cfg = {"presets": {"prof": {"stacks": ["web", "git"], "kill": True}}}
    args = cli.build_parser().parse_args(["--preset", "prof"])
    selected, warns = cli._resolve_selected(args, cfg, {"web", "git"})
    assert selected == {"web", "git"} and warns == []


def test_cli_merge_options_preset_and_flags():
    cfg = {"presets": {"prof": {"stacks": ["web"], "kill": True, "gpu_off": True,
                                "folder": "D:\\p", "profile": "Web"}}}
    args = cli.build_parser().parse_args(["--preset", "prof"])
    opts = cli._merge_options(args, cfg)
    assert opts["kill"] and opts["gpu_off"]
    assert opts["folder"] == "D:\\p" and opts["profile"] == "Web"


def test_cli_merge_options_cli_folder_overrides_preset():
    cfg = {"presets": {"prof": {"stacks": ["web"], "folder": "D:\\preset"}}}
    args = cli.build_parser().parse_args(["--preset", "prof", "--folder", "D:\\cli"])
    assert cli._merge_options(args, cfg)["folder"] == "D:\\cli"


def _patch_cli_env(monkeypatch, cfg, installed=("ms-python.python", "redhat.java")):
    monkeypatch.setattr(cli, "load_config", lambda: core.migrate_config(cfg))
    monkeypatch.setattr(cli, "load_categories", lambda: (sample_cats(), ""))
    monkeypatch.setattr(cli, "load_installed", lambda c: (list(installed), "test"))
    monkeypatch.setattr(cli, "resolve_code_cli", lambda c: "code.cmd")


def test_cli_json_dry_run(monkeypatch, capsys):
    _patch_cli_env(monkeypatch, {})
    rc = cli.cli_main(["--stacks", "python", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["selected"] == ["python"]
    assert "redhat.java" in out["disabled"]      # java не выбран — выключается
    assert out["will_run"] is False


def test_cli_list_stacks_json(monkeypatch, capsys):
    _patch_cli_env(monkeypatch, {})
    rc = cli.cli_main(["--list-stacks", "--json"])
    rows = json.loads(capsys.readouterr().out)
    assert rc == 0
    keys = {r["key"] for r in rows}
    assert {"python", "web", "java"} <= keys
    py = next(r for r in rows if r["key"] == "python")
    assert py["installed"] == 1 and py["extensions"] == 2


def test_cli_launch_error_returns_3(monkeypatch, capsys):
    _patch_cli_env(monkeypatch, {})

    def boom(*a, **k):
        raise OSError("cannot start")
    monkeypatch.setattr(cli, "launch_detached", boom)
    monkeypatch.setattr(cli, "kill_vscode", lambda *a, **k: None)
    rc = cli.cli_main(["--run", "--stacks", "python"])
    assert rc == 3
    assert "Ошибка запуска" in capsys.readouterr().out


def test_cli_make_shortcut_writes_file(monkeypatch, tmp_path, capsys):
    _patch_cli_env(monkeypatch, {"presets": {"web": ["web"]}})
    out = tmp_path / "web"
    rc = cli.cli_main(["--make-shortcut", str(out), "--preset", "web"])
    assert rc == 0
    assert out.with_suffix(".cmd").exists()
    assert "--preset" in out.with_suffix(".cmd").read_text(encoding="utf-8")


def test_cli_make_shortcut_unknown_preset_returns_2(monkeypatch, tmp_path):
    _patch_cli_env(monkeypatch, {"presets": {}})
    rc = cli.cli_main(["--make-shortcut", str(tmp_path / "x.cmd"), "--preset", "nope"])
    assert rc == 2


# --- маркетплейс-ссылка (понятность + безопасность) ------------------------

def test_marketplace_url_for_valid_id():
    url = core.marketplace_url("ms-python.python")
    assert url == ("https://marketplace.visualstudio.com/items?"
                   "itemName=ms-python.python")


@pytest.mark.parametrize("bad", ["", "nodot", "evil & calc.exe", "../x", 'a"b.c'])
def test_marketplace_url_rejects_bad_ids(bad):
    # В URL пускаем только валидный publisher.name — не открываем произвольный текст.
    assert core.marketplace_url(bad) is None


# --- WEIGHT_HELP (тултипы нагрузки) ----------------------------------------

def test_weight_help_covers_all_levels():
    from launcher.categories import WEIGHT_HELP
    assert set(WEIGHT_HELP) == {"heavy", "medium", "light"}
    assert all(WEIGHT_HELP.values())
