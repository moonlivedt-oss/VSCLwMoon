# -*- coding: utf-8 -*-
"""Тесты того, что появилось в 1.4: нативный замер памяти, разбор code --status,
реальный вес стеков, надёжные пути конфига, быстрый запуск пресета.

Запуск:  python -m pytest tests/test_v14.py
"""

import json
import sys

import pytest

from launcher import config, paths, quicklaunch, vscode, weights, winmem

# --- paths: конфиг переживает папку только для чтения -----------------------


def test_dir_writable_true_for_tmp(tmp_path):
    assert paths.dir_writable(tmp_path) is True


def test_dir_writable_false_for_impossible_path(tmp_path):
    # Файл вместо папки: создать внутри ничего нельзя.
    f = tmp_path / "file.txt"
    f.write_text("x", encoding="utf-8")
    assert paths.dir_writable(f) is False


def test_dir_writable_leaves_no_probe_file(tmp_path):
    paths.dir_writable(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_resolve_config_dir_prefers_writable(tmp_path):
    got, fallback = paths.resolve_config_dir(tmp_path)
    assert got == tmp_path
    assert fallback is False


def test_resolve_config_dir_falls_back(tmp_path, monkeypatch):
    blocked = tmp_path / "blocked.txt"
    blocked.write_text("x", encoding="utf-8")
    fb = tmp_path / "fallback"
    monkeypatch.setattr(paths, "fallback_config_dir", lambda: fb)
    got, fallback = paths.resolve_config_dir(blocked)
    assert got == fb
    assert fallback is True


def test_migrate_config_file_copies_once(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / paths.CONFIG_NAME).write_text('{"presets": {"a": []}}', encoding="utf-8")
    assert paths.migrate_config_file(old, new) is True
    assert json.loads((new / paths.CONFIG_NAME).read_text(encoding="utf-8"))["presets"] == {"a": []}
    # Повторный вызов не затирает уже существующий конфиг в новом месте.
    (new / paths.CONFIG_NAME).write_text('{"presets": {"b": []}}', encoding="utf-8")
    assert paths.migrate_config_file(old, new) is False
    assert "b" in (new / paths.CONFIG_NAME).read_text(encoding="utf-8")


# --- config: битые значения не стирают весь конфиг --------------------------


def test_validate_config_resets_only_broken_key():
    cfg = {"presets": ["не словарь"], "recent_folders": [r"D:\p"], "kill_first": "да"}
    fixed = config.validate_config(cfg)
    assert set(fixed) == {"presets", "kill_first"}
    assert cfg["presets"] == {}
    assert cfg["kill_first"] is True
    assert cfg["recent_folders"] == [r"D:\p"]  # корректное значение не тронуто


def test_validate_config_accepts_json_zero_one_as_bool():
    cfg = {"kill_first": 0, "new_window": 1}
    config.validate_config(cfg)
    assert cfg["kill_first"] is False
    assert cfg["new_window"] is True


def test_validate_config_keeps_unknown_keys():
    cfg = {"from_future_version": {"x": 1}}
    config.validate_config(cfg)
    assert cfg["from_future_version"] == {"x": 1}


def test_migrate_marks_old_measurements_with_old_metric():
    cfg = {
        "config_version": 2,
        "footprint_history": {"python": {"mb": 900, "n": 6}},
        "baseline_full": {"mb": 1500, "n": 9},
    }
    config.migrate_config(cfg)
    assert cfg["footprint_history"]["python"]["metric"] == "ws-private-perf"
    assert cfg["baseline_full"]["metric"] == "ws-private-perf"
    # И такой замер не выдаётся как сравнимый с нынешним.
    assert config.lookup_footprint(cfg, "python") is None
    assert config.lookup_baseline(cfg) is None


def test_migrate_is_idempotent():
    cfg = config.migrate_config({})
    once = json.dumps(cfg, sort_keys=True)
    config.migrate_config(cfg)
    assert json.dumps(cfg, sort_keys=True) == once


def test_quarantine_config_keeps_copy(tmp_path, monkeypatch):
    broken = tmp_path / "launcher_config.json"
    broken.write_text("{ это не json", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_FILE", broken)
    saved = config.quarantine_config()
    assert saved is not None and saved.exists()
    assert "не json" in saved.read_text(encoding="utf-8")


def test_load_config_survives_broken_file(tmp_path, monkeypatch):
    broken = tmp_path / "launcher_config.json"
    broken.write_text("{{{", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_FILE", broken)
    cfg = config.load_config()
    assert cfg["presets"] == {}
    assert cfg["config_version"] == config.CONFIG_VERSION
    assert list(tmp_path.glob("launcher_config.corrupt-*.json"))  # копия рядом


# --- winmem: нативный замер вместо PowerShell -------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 API")
def test_iter_processes_finds_current_process():
    import os

    pids = {pid for pid, _name in winmem.iter_processes()}
    assert os.getpid() in pids


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 API")
def test_process_memory_of_self_is_positive():
    import os

    private, ws = winmem.process_memory(os.getpid())
    assert private > 0 and ws > 0


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 API")
def test_image_memory_unknown_image_is_zero():
    assert winmem.image_memory("этого-процесса-нет.exe") == (0, 0, 0)


def test_image_memory_empty_name():
    assert winmem.image_memory("") == (0, 0, 0)


# --- vscode: разбор code --status -------------------------------------------

STATUS_SAMPLE = """Version:          Code 1.98.0 (abcdef, 2026-01-01)
OS Version:       Windows_NT x64 10.0.26100
Memory (System):  31.85GB (12.34GB free)

CPU %   Mem MB     PID  Process
    0      145   12345  window [1] (main.py - proj)
    0       80   12346    gpu-process
    2      210    9347    extensionHost [1]
    0       45  123489      electron-nodejs (server.js)
    1       33   12350      electron-nodejs (pylance)
    0       30   12349    ptyHost

Workspace Stats:
|  Window (main.py - proj)
"""


def test_parse_code_status_splits_editor_and_extensions():
    r = vscode.parse_code_status(STATUS_SAMPLE)
    assert r["total_mb"] == 145 + 80 + 210 + 45 + 33 + 30
    # extensionHost и порождённые им языковые серверы — это цена расширений.
    assert r["extension_mb"] == 210 + 45 + 33
    assert r["editor_mb"] == 145 + 80 + 30
    assert len(r["processes"]) == 6


def test_parse_code_status_nesting_survives_wide_pids():
    # PID разной ширины не должен ломать определение вложенности: колонки
    # выровнены по правому краю, вложенность задаёт колонка имени.
    r = vscode.parse_code_status(STATUS_SAMPLE)
    by_name = {p["name"].split(" ")[0]: p["depth"] for p in r["processes"]}
    assert by_name["window"] == 0
    assert by_name["extensionHost"] == by_name["ptyHost"]
    assert by_name["electron-nodejs"] > by_name["extensionHost"]


def test_parse_code_status_garbage_is_empty():
    r = vscode.parse_code_status("тут нет никакой таблицы")
    assert r["processes"] == []
    assert r["total_mb"] == 0


# Реальный вывод code --status 1.121: хост расширений называется
# 'extension-host', а не 'extensionHost', как было в старых версиях. Фикстура
# снята с живого редактора — на выдуманной ошибка в имени не ловилась.
STATUS_SAMPLE_MODERN = """CPU %	Mem MB	   PID	Process
    0	   161	 11784	code
    0	   127	  3824	shared-process
    0	   382	  5816	window [1] (Visual Studio Code)
    0	   137	 20752	pty-host
    0	   193	 22072	   gpu-process
    0	   654	 24120	extension-host [1]
    0	   105	  1508	     electron-nodejs (jsonServerMain)
    0	   269	 14756	     java -jar sonarlint-ls.jar
"""


def test_parse_code_status_finds_modern_extension_host():
    r = vscode.parse_code_status(STATUS_SAMPLE_MODERN)
    assert r["extension_mb"] == 654 + 105 + 269
    assert r["editor_mb"] == 161 + 127 + 382 + 137 + 193
    assert r["extension_mb"] > 0


def test_parse_code_status_none_safe():
    assert vscode.parse_code_status("")["total_mb"] == 0


def test_code_status_without_cli_is_none():
    assert vscode.code_status(None) is None


# --- weights: реальный вес стеков -------------------------------------------


def test_folder_to_ext_id_strips_version_and_platform():
    assert weights.folder_to_ext_id("ms-python.python-2024.2.0-win32-x64") == "ms-python.python"
    assert weights.folder_to_ext_id("golang.go-0.41.4") == "golang.go"
    assert weights.folder_to_ext_id("redhat.java-1.2.3") == "redhat.java"


def test_folder_to_ext_id_rejects_service_entries():
    for name in (".obsolete", "not-an-extension", "", ".init-default-profile"):
        assert weights.folder_to_ext_id(name) == ""


def test_dir_size_counts_files(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x" * 1000)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_bytes(b"y" * 2000)
    assert weights._dir_size(tmp_path) == 3000


def test_dir_size_respects_entry_cap(tmp_path):
    for i in range(20):
        (tmp_path / f"f{i}.bin").write_bytes(b"z" * 100)
    capped = weights._dir_size(tmp_path, max_entries=5)
    assert 0 < capped < 2000


def test_extension_sizes_reads_folders(tmp_path, monkeypatch):
    (tmp_path / "ms-python.python-1.0.0").mkdir()
    (tmp_path / "ms-python.python-1.0.0" / "big.bin").write_bytes(b"0" * (3 * 1024 * 1024))
    (tmp_path / ".obsolete").mkdir()
    monkeypatch.setattr(weights, "extensions_dir", lambda cli: tmp_path, raising=False)
    monkeypatch.setattr("launcher.vscode.extensions_dir", lambda cli: tmp_path)
    sizes = weights.extension_sizes(None)
    assert sizes == {"ms-python.python": 3}


def test_stack_disk_mb_groups_by_stack():
    idx = {"a.one": "python", "b.two": "python", "c.three": "web", "d.core": "always_on"}
    sizes = {"a.one": 10, "b.two": 5, "c.three": 7, "d.core": 100}
    assert weights.stack_disk_mb(idx, sizes) == {"python": 15, "web": 7}


def test_stack_disk_mb_only_installed():
    idx = {"a.one": "python", "b.two": "python"}
    sizes = {"a.one": 10, "b.two": 5}
    assert weights.stack_disk_mb(idx, sizes, installed=["a.one"]) == {"python": 10}


def _hist(**pairs):
    return {
        "footprint_history": {
            sig: {"mb": mb, "n": 5, "metric": config.MEMORY_METRIC} for sig, mb in pairs.items()
        }
    }


def test_measured_stack_costs_from_single_stack_difference():
    # web=600, web+python=900 -> python стоит 300 МБ на этой машине.
    cfg = _hist(web=600, **{"python|web": 900})
    assert weights.measured_stack_costs(cfg)["python"] == 300


def test_measured_stack_costs_takes_median_of_noisy_measurements():
    cfg = _hist(
        **{
            "web": 600,
            "python|web": 900,
            "git|web": 650,
            "git|python|web": 1100,  # шумный замер: разница 450
        }
    )
    # Две разницы для python: 300 и 450 -> медиана 375.
    assert weights.measured_stack_costs(cfg)["python"] == 375


def test_measured_stack_costs_ignores_bare_and_old_metric():
    cfg = {
        "footprint_history": {
            "bare": {"mb": 200, "n": 3, "metric": config.MEMORY_METRIC},
            "web": {"mb": 600, "n": 5, "metric": "ws-private-perf"},
            "python|web": {"mb": 900, "n": 6, "metric": config.MEMORY_METRIC},
        }
    }
    assert weights.measured_stack_costs(cfg) == {}


def test_measured_stack_costs_skips_negative_noise():
    # Набор с python замерился МЕНЬШЕ, чем без него — это шум, а не экономия.
    cfg = _hist(web=900, **{"python|web": 600})
    assert weights.measured_stack_costs(cfg) == {}


def test_estimate_saved_uses_measurement_over_table():
    idx = {"a.one": "python"}
    cfg = _hist(web=600, **{"python|web": 900})
    mb, calibrated = weights.estimate_saved_mb(["a.one"], idx, cfg)
    assert (mb, calibrated) == (300, 1)  # 300 из замера, а не 150 из WEIGHT_MB


def test_estimate_saved_falls_back_to_table():
    idx = {"a.one": "java"}
    mb, calibrated = weights.estimate_saved_mb(["a.one"], idx, {})
    assert (mb, calibrated) == (500, 0)  # java = heavy = 500 МБ по таблице


def test_estimate_saved_counts_each_stack_once():
    idx = {"a.one": "java", "b.two": "java"}
    mb, _c = weights.estimate_saved_mb(["a.one", "b.two"], idx, {})
    assert mb == 500


def test_estimate_saved_ignores_always_on():
    idx = {"a.one": "always_on"}
    assert weights.estimate_saved_mb(["a.one"], idx, {}) == (0, 0)


# --- quicklaunch: один путь запуска для окна, CLI и трея --------------------


def test_plan_launch_builds_args(monkeypatch):
    monkeypatch.setattr(quicklaunch, "load_installed", lambda cli: (["a.one", "b.two"], "тест"))
    monkeypatch.setattr(quicklaunch, "read_extension_manifests", lambda cli: {})
    plan = quicklaunch.plan_launch(
        "code", {}, {"a.one": "python", "b.two": "java"}, ["python"], {"folder": r"D:\proj"}
    )
    assert plan["disabled"] == ["b.two"]
    assert "--disable-extension" in plan["args"] and "b.two" in plan["args"]
    assert plan["args"][-1] == r"D:\proj"
    assert plan["signature"] == "python"


def test_plan_launch_respects_overrides(monkeypatch):
    monkeypatch.setattr(quicklaunch, "load_installed", lambda cli: (["a.one", "b.two"], "тест"))
    monkeypatch.setattr(quicklaunch, "read_extension_manifests", lambda cli: {})
    cfg = {"overrides": {"enable": ["b.two"], "disable": ["a.one"]}}
    plan = quicklaunch.plan_launch("code", cfg, {"a.one": "python", "b.two": "java"}, ["python"])
    assert plan["disabled"] == ["a.one"]  # личное исключение сильнее стека


def test_resolve_overrides_survives_broken_config():
    assert quicklaunch.resolve_overrides({"overrides": "мусор"}) == (set(), set())
    assert quicklaunch.resolve_overrides({}) == (set(), set())


def test_launch_preset_reports_missing_preset():
    ok, msg = quicklaunch.launch_preset("code", {"presets": {}}, {}, "нет-такого")
    assert ok is False and "не найден" in msg.lower()


def test_launch_preset_without_cli():
    ok, msg = quicklaunch.launch_preset(None, {"presets": {"web": ["web"]}}, {}, "web")
    assert ok is False


def test_launch_preset_runs_and_kills(monkeypatch):
    calls = {"kill": 0, "args": None}
    monkeypatch.setattr(quicklaunch, "load_installed", lambda cli: (["a.one"], "тест"))
    monkeypatch.setattr(quicklaunch, "read_extension_manifests", lambda cli: {})
    monkeypatch.setattr(quicklaunch, "kill_vscode", lambda cli: calls.__setitem__("kill", 1))
    monkeypatch.setattr(
        quicklaunch, "launch_detached", lambda cli, args: calls.__setitem__("args", args)
    )
    cfg = {"presets": {"web": {"stacks": ["web"], "kill": True, "folder": r"D:\p"}}}
    ok, msg = quicklaunch.launch_preset("code", cfg, {"a.one": "python"}, "web")
    assert ok is True
    assert calls["kill"] == 1
    assert calls["args"][-1] == r"D:\p"
    assert "a.one" in calls["args"]  # стек python не выбран -> выключен
