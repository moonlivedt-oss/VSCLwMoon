# -*- coding: utf-8 -*-
"""Проверка обновлений через GitHub Releases.

Без сторонних зависимостей (urllib из stdlib). Сетевая часть изолирована в
fetch_latest_release, а сравнение версий — чистые функции, которые легко
тестировать без сети. Всё падает мягко: нет сети/таймаут/мусор в ответе —
возвращаем None, лаунчер просто не показывает баннер.
"""
from __future__ import annotations

import json
import re
import urllib.request

REPO = "moonlivedt-oss/VSCLwMoon"
RELEASES_URL = f"https://github.com/{REPO}/releases"
_API = f"https://api.github.com/repos/{REPO}/releases/latest"

_NUM_RE = re.compile(r"\d+")


def parse_version(s: str) -> tuple[int, ...]:
    """'v1.2.0' / '1.2' / 'release-1.2.0-beta' -> кортеж чисел (1,2,0).
    Нечисловые хвосты (beta/rc) отбрасываются — для грубого сравнения
    «новее/нет» этого достаточно. Пустой/битый ввод -> (0,)."""
    if not s:
        return (0,)
    nums = _NUM_RE.findall(s)
    return tuple(int(n) for n in nums) if nums else (0,)


def is_newer(latest: str, current: str) -> bool:
    """True, если версия latest строго больше current (посегментно)."""
    a, b = parse_version(latest), parse_version(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


def fetch_latest_release(timeout: float = 6.0) -> str | None:
    """Тег последнего релиза ('v1.2.0') или None при любой проблеме.
    Изолирует сеть: всё внутри try, наружу — только строка или None."""
    try:
        req = urllib.request.Request(
            _API, headers={"Accept": "application/vnd.github+json",
                           "User-Agent": "VSCodeLauncher-update-check"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        tag = data.get("tag_name") or data.get("name")
        return tag.strip() if isinstance(tag, str) and tag.strip() else None
    except Exception:
        return None


def check_for_update(current: str, timeout: float = 6.0) -> str | None:
    """Вернуть тег новой версии, если она новее current, иначе None."""
    latest = fetch_latest_release(timeout=timeout)
    if latest and is_newer(latest, current):
        return latest
    return None
