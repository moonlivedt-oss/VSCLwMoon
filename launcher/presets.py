# -*- coding: utf-8 -*-
"""Пресеты как полноценные лаунч-профили (#4) и генератор ярлыка (#5).

Исторически пресет — это просто список ключей стеков. Теперь значение пресета
может быть и словарём с опциями запуска (папка, закрыть VS Code, без GPU,
голый режим, новое окно, профиль). Обе формы валидны; normalize_preset
разбирает любую и всегда возвращает единый словарь, чтобы остальной код не
разбирался в вариантах.

build_shortcut_cmd собирает содержимое .cmd-файла, который открывает VS Code с
нужным пресетом одним двойным кликом — через тихий CLI-режим (launcher/cli.py),
без GUI.
"""
from __future__ import annotations

# Ключи опций запуска в словарной форме пресета и их дефолты.
_OPTION_DEFAULTS: dict[str, object] = {
    "folder": "",
    "kill": False,
    "gpu_off": False,
    "bare": False,
    "new_window": True,
    "profile": "",
}


def normalize_preset(value) -> dict:
    """Привести значение пресета (список ключей ИЛИ словарь) к единой форме:
    {"stacks": [...], "folder": str, "kill": bool, "gpu_off": bool,
     "bare": bool, "new_window": bool, "profile": str}.

    Неизвестные ключи из словаря игнорируются, недостающие берут дефолт —
    так чужой/старый пресет не роняет разбор."""
    out: dict = {"stacks": []}
    out.update(_OPTION_DEFAULTS)
    if isinstance(value, list):
        out["stacks"] = [str(x) for x in value]
        return out
    if isinstance(value, dict):
        raw = value.get("stacks", [])
        out["stacks"] = [str(x) for x in raw] if isinstance(raw, list) else []
        for k, default in _OPTION_DEFAULTS.items():
            if k in value:
                out[k] = type(default)(value[k]) if isinstance(default, bool) else value[k]
        out["folder"] = str(out["folder"] or "")
        out["profile"] = str(out["profile"] or "")
    return out


def preset_stacks(value) -> list[str]:
    """Список ключей стеков из пресета любой формы."""
    return normalize_preset(value)["stacks"]


def preset_has_options(value) -> bool:
    """True, если пресет несёт опции запуска (словарная форма с непустыми/
    неумолчальными значениями) — для пометки таких пресетов в UI."""
    if not isinstance(value, dict):
        return False
    p = normalize_preset(value)
    return (bool(p["folder"]) or p["kill"] or p["gpu_off"] or p["bare"]
            or not p["new_window"] or bool(p["profile"]))


def build_shortcut_cmd(invocation: list[str], preset: str) -> str:
    """Содержимое .cmd-файла, открывающего VS Code с пресетом `preset` через
    тихий CLI-режим. `invocation` — как вызвать лаунчер (например,
    [python, vscode_launcher.py] или [dist/VSCodeLauncher.exe]).

    Каждый токен берётся в кавычки — путь с пробелом не разорвётся. Аргументы
    фиксированы (--run --preset ИМЯ), пользовательский ввод — только имя
    пресета, которое подставляется в кавычках; кавычки из имени убираются,
    чтобы не разорвать строку."""
    safe_name = str(preset).replace('"', "")
    parts = " ".join(f'"{tok}"' for tok in invocation)
    return (
        "@echo off\r\n"
        "chcp 65001>nul\r\n"   # UTF-8: корректный путь с кириллицей внутри .cmd
        "rem Ярлык VS Code Launcher — открывает редактор с пресетом стеков.\r\n"
        "rem Сгенерирован автоматически; можно править и копировать.\r\n"
        f'{parts} --run --preset "{safe_name}" --quiet\r\n'
    )
