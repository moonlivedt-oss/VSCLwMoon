# -*- coding: utf-8 -*-
"""Сколько стек стоит по времени старта: замеры расширения Moon Core.

Лаунчер меряет память снаружи, а время старта отдельного расширения снаружи не
видно. Moon Core работает внутри VS Code и пишет, сколько стоила загрузка и
activate() каждого расширения при каждом запуске (метки самого VS Code), в
mooncore-perf.json в своей папке данных. Поле export этого файла — стабильная
схема "moon-core/perf@1" как раз для внешних программ:

    {"schema": "moon-core/perf@1", "generated": "...", "vscode": "1.140.0",
     "window": {"samples": 12, ...},
     "extensions": [{"id": "ms-python.python", "samples": 5, "avgMs": 1800,
                     "maxMs": 2600, "lastMs": 1700, "activation": "star",
                     "eager": true}, ...]}

Файл пишет другая программа, поэтому читается он как недоверенный: размер с
потолком, схема строго, id расширений и числа — по белому списку. Нет файла
или он чужой — пусто, и лаунчер работает как раньше.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .safety import valid_ext_id

SCHEMA = "moon-core/perf@1"
EXT_ID = "moonlivedt.moon-core"
FILE_NAME = "mooncore-perf.json"
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_MS = 600_000
MAX_EXTENSIONS = 400
# Меньше этого стек на старте ничего заметного не стоит — «старт 12 мс» на
# карточке был бы шумом.
SHOW_MIN_MS = 100


def perf_paths(code_cli: str | None) -> list[Path]:
    """Где может лежать файл замеров: папка данных стабильного VS Code или
    Insiders и портативная сборка (VSCODE_PORTABLE)."""
    out: list[Path] = []
    portable = os.environ.get("VSCODE_PORTABLE")
    if portable:
        out.append(Path(portable) / "user-data" / "User" / "globalStorage" / EXT_ID / FILE_NAME)
    appdata = os.environ.get("APPDATA")
    if appdata:
        folder = "Code - Insiders" if code_cli and "insiders" in code_cli.lower() else "Code"
        out.append(Path(appdata) / folder / "User" / "globalStorage" / EXT_ID / FILE_NAME)
    return out


def _ms(v: object) -> int | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if v != v or v < 0 or v > MAX_MS:  # NaN, отрицательное, невозможное
        return None
    return int(round(v))


def parse_export(data: object) -> dict:
    """Проверенный export: {"generated", "vscode", "samples", "ext": {id: {...}}}.
    Не та схема или мусор — {}."""
    if not isinstance(data, dict):
        return {}
    ex = data.get("export", data)  # сам файл Moon Core или уже вынутый export
    if not isinstance(ex, dict) or ex.get("schema") != SCHEMA:
        return {}
    ext: dict[str, dict] = {}
    items = ex.get("extensions")
    for e in (items if isinstance(items, list) else [])[:MAX_EXTENSIONS]:
        if not isinstance(e, dict):
            continue
        ext_id = str(e.get("id", "")).strip().lower()
        avg = _ms(e.get("avgMs"))
        n = e.get("samples")
        # bool — подкласс int: samples: true из чужого файла числом не считаем.
        if (
            not valid_ext_id(ext_id)
            or avg is None
            or isinstance(n, bool)
            or not isinstance(n, int)
            or n < 1
        ):
            continue
        ext[ext_id] = {
            "avg_ms": avg,
            "max_ms": _ms(e.get("maxMs")) or avg,
            "samples": min(n, 1_000_000),
            "eager": e.get("eager") is True,
        }
    raw_win = ex.get("window")
    win: dict = raw_win if isinstance(raw_win, dict) else {}
    raw_samples = win.get("samples")
    samples = raw_samples if isinstance(raw_samples, int) and not isinstance(raw_samples, bool) else 0
    return {
        "generated": str(ex.get("generated", ""))[:40],
        "vscode": str(ex.get("vscode", ""))[:40],
        "samples": max(0, min(samples, 1_000_000)),
        "ext": ext,
    }


def load_startup_costs(code_cli: str | None) -> dict:
    """Замеры Moon Core для этой установки VS Code или {} (нет Moon Core, ещё
    нет замеров, файл повреждён или слишком большой)."""
    for f in perf_paths(code_cli):
        try:
            if not f.is_file() or f.stat().st_size > MAX_FILE_BYTES:
                continue
            parsed = parse_export(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        if parsed.get("ext"):
            return parsed
    return {}


def stack_startup_ms(
    ext_index: dict[str, str], costs: dict, installed: list[str] | None = None
) -> dict[str, int]:
    """Ключ стека -> сколько мс в среднем стоит активация его расширений на
    каждом запуске. always_on не считаем: он включён всегда. Сумма — верхняя
    оценка: часть расширений VS Code активирует параллельно."""
    only = {e.lower() for e in installed} if installed is not None else None
    out: dict[str, int] = {}
    for ext_id, rec in (costs.get("ext") or {}).items():
        if only is not None and ext_id not in only:
            continue
        key = ext_index.get(ext_id)
        if not key or key == "always_on":
            continue
        out[key] = out.get(key, 0) + int(rec["avg_ms"])
    return out


def startup_saved_ms(disabled: list[str], costs: dict) -> int:
    """Сколько мс старта уйдёт, если выключить эти расширения (по средним
    замерам; расширения без замеров не считаются)."""
    ext = costs.get("ext") or {}
    ids = {d.lower() for d in disabled}
    return sum(int(ext[e]["avg_ms"]) for e in ids if e in ext)


def eager_costly(costs: dict, min_ms: int = 500) -> list[tuple[str, int]]:
    """Расширения, которые включаются при каждом старте (activationEvents "*"
    или onStartupFinished) и стоят от min_ms: [(id, мс)] по убыванию."""
    rows = [
        (i, r["avg_ms"])
        for i, r in (costs.get("ext") or {}).items()
        if r["eager"] and r["avg_ms"] >= min_ms
    ]
    return sorted(rows, key=lambda kv: (-kv[1], kv[0]))


def format_ms(ms: int, lang: str = "ru") -> str:
    """'450 мс' / '1,8 с' (по-английски '450 ms' / '1.8 s')."""
    en = lang == "en"
    if ms < 1000:
        return f"{int(ms)} {'ms' if en else 'мс'}"
    s = f"{ms / 1000:.1f}"
    return f"{s} s" if en else f"{s.replace('.', ',')} с"
