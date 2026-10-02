# -*- coding: utf-8 -*-
"""Быстрая сводка «здоровья» для старта окна: сколько можно освободить
уборкой и есть ли ошибки совместимости расширений.

Полные отчёты (уборка, совместимость) человек сам не открывает, пока что-то
не сломается. Эта сводка считается в фоне при каждом запуске окна (~1 с) и
выводится счётчиками на «Обслуживании» — проблемы видны заранее.
"""
from __future__ import annotations


def quick_health(code_cli: str | None) -> dict:
    """{"cleanup_safe_bytes", "cleanup_risky_bytes", "compat_errors",
    "compat_warnings"}. Любая часть, которая не посчиталась, — 0."""
    out = {"cleanup_safe_bytes": 0, "cleanup_risky_bytes": 0,
           "compat_errors": 0, "compat_warnings": 0}
    if not code_cli:
        return out
    try:
        from . import cleanup

        for item in cleanup.scan_vscode(code_cli):
            key = "cleanup_safe_bytes" if item["kind"] in cleanup.SAFE_KINDS else "cleanup_risky_bytes"
            out[key] += int(item["bytes"])
    except Exception:
        pass
    try:
        from . import compat
        from .manifests import read_extension_manifests
        from .vscode import read_installed_from_disk

        installed = read_installed_from_disk(code_cli)
        issues = compat.check(installed, read_extension_manifests(code_cli), installed=installed,
                              ctx=compat.context(code_cli))
        out["compat_errors"] = sum(1 for i in issues if i["severity"] == "error")
        out["compat_warnings"] = sum(1 for i in issues if i["severity"] == "warning")
    except Exception:
        pass
    return out


def size_label(n: int) -> str:
    """5.4 ГБ / 320 МБ — коротко для плитки."""
    from .i18n import get_language

    gb, mb = ("GB", "MB") if get_language() == "en" else ("ГБ", "МБ")
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f} {gb}"
    return f"{round(n / 1024 ** 2)} {mb}"
