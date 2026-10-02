# -*- coding: utf-8 -*-
"""Отчёт для поддержки: всё, что нужно для разбора проблемы, одним текстом.

Собирается из того, что лаунчер и так умеет: версия, выбор стеков, починка PATH,
доктор C++ (с пробной сборкой) и хвост журнала. Ничего не меняет на машине.
Каждый раздел изолирован: сбой одного не лишает отчёта остальных.
"""

from __future__ import annotations

import os
import platform
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .paths import CONFIG_DIR, CONFIG_FILE, LOG_FILE


def _section(lines: list[str], title: str, fn) -> None:
    lines += ["", f"=== {title} ==="]
    try:
        lines += [str(x) for x in fn()]
    except Exception as e:  # noqa: BLE001 — отчёт важнее одного раздела
        lines.append(f"(раздел не собран: {type(e).__name__}: {e})")


def build_report(code_cli: str | None, cfg: dict, selected=()) -> str:
    lines = [f"VS Code Launcher {__version__} — отчёт {datetime.now():%Y-%m-%d %H:%M:%S}"]

    def system():
        return [
            f"Windows: {platform.platform()}",
            f"Python: {sys.version.split()[0]}  собранный exe: {bool(getattr(sys, 'frozen', False))}",
            f"Профиль: {os.environ.get('USERPROFILE', '')}",
            f"VS Code CLI: {code_cli or 'не найден'}",
            f"Конфиг: {CONFIG_FILE}",
        ]

    def choice():
        ov = cfg.get("overrides", {}) if isinstance(cfg.get("overrides"), dict) else {}
        return [
            f"Выбранные стеки: {', '.join(selected) or '(только ядро)'}",
            f"Папка: {(cfg.get('recent_folders') or [''])[0]}",
            f"Закрывать VS Code: {cfg.get('kill_first')}  мягко: {cfg.get('soft_close')}",
            f"Исключения: всегда вкл {len(ov.get('enable', []))}, всегда выкл {len(ov.get('disable', []))}",
            f"Расширений в кэше: {len((cfg.get('installed_cache') or {}).get('ids', []))}",
            f"Пресеты: {', '.join(cfg.get('presets', {})) or 'нет'}",
        ]

    def path_report():
        from . import path_doctor as pd

        rep = pd.analyze(probe_versions=False)
        out = [f"[{i.level}] {i.title} — {i.detail}" for i in rep.issues] or ["проблем нет"]
        out += ["", "Системный PATH:"] + ["  " + e for e in pd.split_raw(rep.machine_raw)]
        out += ["Пользовательский PATH:"] + ["  " + e for e in pd.split_raw(rep.user_raw)]
        return out

    def cpp_report():
        from . import cpp

        return cpp.format_report(cpp.cpp_report(smoke=True))

    def project():
        from . import cpp_project as cp

        folder = (cfg.get("recent_folders") or [""])[0]
        if not folder or not Path(folder).is_dir():
            return ["папка проекта не задана"]
        out = [f"Папка: {folder}"]
        out += [f"[проблема] {p['text']}" for p in cp.project_problems(folder)] or ["проблем не найдено"]
        vs = Path(folder) / ".vscode"
        for name in ("tasks.json", "launch.json", "settings.json", "c_cpp_properties.json"):
            f = vs / name
            if f.is_file():
                out += ["", f"--- .vscode/{name} ---", f.read_text(encoding="utf-8-sig", errors="replace")[:6000]]
        return out

    def log_tail():
        if not LOG_FILE.is_file():
            return ["журнала нет"]
        return LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]

    _section(lines, "Система", system)
    _section(lines, "Выбор в лаунчере", choice)
    _section(lines, "PATH", path_report)
    _section(lines, "C++", cpp_report)
    _section(lines, "Проект", project)
    _section(lines, "Журнал (последние строки)", log_tail)
    return "\n".join(lines) + "\n"


def save_report(text: str) -> Path:
    path = CONFIG_DIR / f"support_report_{datetime.now():%Y%m%d_%H%M%S}.txt"
    path.write_text(text, encoding="utf-8-sig")
    return path
