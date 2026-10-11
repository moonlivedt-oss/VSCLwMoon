# -*- coding: utf-8 -*-
"""Замеры старта от Moon Core: чтение недоверенного файла, стоимость стеков,
CLI и карточка стека."""

import json

import pytest

from launcher import moonperf as mp


def _export(**over):
    ex = {
        "schema": "moon-core/perf@1",
        "generated": "2026-10-06T10:00:00.000Z",
        "vscode": "1.140.0",
        "window": {"samples": 9, "readyMedianMs": 1200, "extensionsMedianMs": 3000},
        "extensions": [
            {
                "id": "ms-python.python",
                "samples": 5,
                "avgMs": 1800,
                "maxMs": 2600,
                "lastMs": 1700,
                "activation": "star",
                "eager": True,
            },
            {
                "id": "ms-python.vscode-pylance",
                "samples": 5,
                "avgMs": 900,
                "maxMs": 1200,
                "lastMs": 800,
                "activation": "language",
                "eager": False,
            },
            {
                "id": "Redhat.Java",
                "samples": 2,
                "avgMs": 700,
                "maxMs": 900,
                "lastMs": 700,
                "activation": "startup",
                "eager": True,
            },
            {
                "id": "vscode.git",
                "samples": 9,
                "avgMs": 150,
                "maxMs": 200,
                "lastMs": 150,
                "activation": "star",
                "eager": True,
            },
        ],
    }
    ex.update(over)
    return {"v": 1, "starts": [], "ext": {}, "export": ex}


def _write(tmp_path, monkeypatch, data, folder="Code"):
    f = tmp_path / folder / "User" / "globalStorage" / mp.EXT_ID / mp.FILE_NAME
    f.parent.mkdir(parents=True)
    f.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("VSCODE_PORTABLE", raising=False)
    return f


def test_load_valid_file(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, _export())
    c = mp.load_startup_costs("code.cmd")
    assert c["vscode"] == "1.140.0" and c["samples"] == 9
    assert c["ext"]["ms-python.python"] == {
        "avg_ms": 1800,
        "max_ms": 2600,
        "samples": 5,
        "eager": True,
    }
    assert "redhat.java" in c["ext"], "id приводится к нижнему регистру, как в ext_index"


def test_insiders_reads_own_folder(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, _export(), folder="Code - Insiders")
    assert mp.load_startup_costs("code.cmd") == {}
    assert mp.load_startup_costs(r"C:\x\code-insiders.cmd")["ext"]


@pytest.mark.parametrize(
    "data",
    [
        "{не json",
        [1, 2],
        _export(schema="moon-core/perf@2"),
        _export(extensions="мусор"),
        _export(
            extensions=[
                {"id": "../evil", "samples": 1, "avgMs": 5},
                {"id": "a.b", "samples": 0, "avgMs": 5},
                {"id": "a.c", "samples": 1, "avgMs": -1},
                {"id": "a.d", "samples": 1, "avgMs": float("nan")},
                {"id": "a.e", "samples": True, "avgMs": 10},
                {"id": "a.f", "samples": 1, "avgMs": 10**9},
            ]
        ),
    ],
)
def test_untrusted_file_is_ignored(tmp_path, monkeypatch, data):
    """Файл пишет другая программа: чужая схема и мусор — просто «замеров нет»."""
    _write(tmp_path, monkeypatch, data if isinstance(data, str) else json.dumps(data))
    assert mp.load_startup_costs("code.cmd") == {}


def test_too_big_file_is_not_read(tmp_path, monkeypatch):
    f = _write(tmp_path, monkeypatch, _export())
    f.write_text(json.dumps(_export()) + " " * (mp.MAX_FILE_BYTES + 1), encoding="utf-8")
    assert mp.load_startup_costs("code.cmd") == {}


def test_no_appdata_no_crash(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("VSCODE_PORTABLE", raising=False)
    assert mp.load_startup_costs("code.cmd") == {}


def test_stack_costs_and_savings():
    costs = mp.parse_export(_export())
    index = {
        "ms-python.python": "python",
        "ms-python.vscode-pylance": "python",
        "redhat.java": "java",
        "vscode.git": "always_on",
    }
    assert mp.stack_startup_ms(index, costs) == {"python": 2700, "java": 700}
    assert mp.stack_startup_ms(index, costs, installed=["MS-Python.Python"]) == {"python": 1800}
    assert (
        mp.startup_saved_ms(["ms-python.python", "MS-PYTHON.PYTHON", "unknown.ext"], costs) == 1800
    )
    assert mp.eager_costly(costs) == [("ms-python.python", 1800), ("redhat.java", 700)]
    assert mp.stack_startup_ms(index, {}) == {}


def test_format_ms():
    assert mp.format_ms(450) == "450 мс"
    assert mp.format_ms(1840) == "1,8 с"
    assert mp.format_ms(1840, "en") == "1.8 s"


def test_cli_startup_costs(tmp_path, monkeypatch, capsys):
    from launcher import cli

    _write(tmp_path, monkeypatch, _export())
    monkeypatch.setattr(cli, "load_config", lambda: {})
    monkeypatch.setattr(cli, "resolve_code_cli", lambda cfg: "code.cmd")
    monkeypatch.setattr(
        cli, "load_installed", lambda c: (["ms-python.python", "redhat.java"], "disk")
    )
    monkeypatch.setattr(
        cli,
        "build_ext_index",
        lambda cats, extra=None: {"ms-python.python": "python", "redhat.java": "java"},
    )
    assert cli.cli_main(["--startup-costs", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [s["key"] for s in out["stacks"]] == ["python", "java"]
    assert out["eager"][0] == {"id": "ms-python.python", "avg_ms": 1800, "stack": "python"}
    assert cli.cli_main(["--startup-costs"]) == 0
    text = capsys.readouterr().out
    assert "1,8 с" in text and "Включаются при каждом старте" in text


def test_window_shows_startup_on_cards_and_summary(tmp_path, monkeypatch):
    """Окно: «старт 1,8 с» на карточке стека и «старт быстрее» в итоге запуска."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets")
    from test_gui_smoke import make_window
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    w = make_window(app)
    try:
        w.installed = ["ms-python.python", "redhat.java"]
        w._startup = mp.parse_export(_export())
        w._apply_startup()
        py = w.cat_checks["python"]
        assert py.startup_ms() == 1800
        assert "старт 1,8 с" in py.weight_lbl.text()
        assert "Moon Core" in py.weight_lbl.toolTip()
        assert w.cat_checks["web"].startup_ms() == 0
        assert "старт" not in w.cat_checks["web"].weight_lbl.text()
        w.cat_checks["python"].setChecked(False)
        w.cat_checks["java"].setChecked(False)
        w._update_summary()
        assert "старт быстрее на ~2,5 с" in w.stat_extra.text()
        w._startup = {}
        w._apply_startup()
        w._update_summary()
        assert "старт" not in w.stat_extra.text() and "старт" not in py.weight_lbl.text()
    finally:
        w.deleteLater()


def test_contract_with_moon_core_sample():
    """Контракт со схемой: tests/data/mooncore-perf.sample.json сгенерирован кодом
    самого Moon Core (lib/perf-model.js + lib/perf-advice.js exportData). Если
    Moon Core поменяет формат, этот образец перегенерируют — и тест покажет,
    понимает ли его лаунчер."""
    from pathlib import Path

    data = json.loads((Path(__file__).parent / "data" / "mooncore-perf.sample.json").read_text(encoding="utf-8"))
    c = mp.parse_export(data)
    assert c["vscode"] == "1.140.0" and c["samples"] == 1
    assert c["ext"]["ms-python.python"] == {"avg_ms": 1800, "max_ms": 1800, "samples": 2, "eager": True}
    assert c["ext"]["redhat.java"]["eager"] is True, "onStartupFinished — тоже «при каждом старте»"
    assert mp.eager_costly(c) == [("ms-python.python", 1800), ("redhat.java", 800)]
