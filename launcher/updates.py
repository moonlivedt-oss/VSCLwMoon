# -*- coding: utf-8 -*-
"""Проверка обновлений через GitHub Releases.

Без сторонних зависимостей (urllib из stdlib). Сетевая часть изолирована в
fetch_latest_release, а сравнение версий — чистые функции, которые легко
тестировать без сети. Всё падает мягко: нет сети/таймаут/мусор в ответе —
возвращаем None, лаунчер просто не показывает баннер.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from pathlib import Path

REPO = "moonlivedt-oss/VSCLwMoon"
RELEASES_URL = f"https://github.com/{REPO}/releases"
_API = f"https://api.github.com/repos/{REPO}/releases/latest"

_NUM_RE = re.compile(r"\d+")
_HEX64_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")


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


# --- автоскачивание и применение обновления (#10) --------------------------

def fetch_latest_release_info(timeout: float = 6.0) -> dict | None:
    """Полная информация о последнем релизе для авто-обновления (#10):
    {tag, exe_url, sha256_url}. Ищем среди assets .exe и парный .sha256 по имени
    файла. None при любой проблеме или если нужных ассетов нет."""
    try:
        req = urllib.request.Request(
            _API, headers={"Accept": "application/vnd.github+json",
                           "User-Agent": "VSCodeLauncher-update-check"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None
    return parse_release_info(data)


def parse_release_info(data: dict) -> dict | None:
    """Разобрать JSON релиза GitHub в {tag, exe_url, sha256_url}. Чистая функция
    (без сети) — тестируется на фикстуре. None, если нет .exe-ассета."""
    if not isinstance(data, dict):
        return None
    tag = data.get("tag_name") or data.get("name")
    if not isinstance(tag, str) or not tag.strip():
        return None
    exe_url = sha_url = None
    for asset in data.get("assets") or ():
        if not isinstance(asset, dict):
            continue
        name = (asset.get("name") or "").lower()
        url = asset.get("browser_download_url")
        if not isinstance(url, str):
            continue
        if name.endswith(".sha256"):
            sha_url = url
        elif name.endswith(".exe"):
            exe_url = url
    if not exe_url:
        return None
    return {"tag": tag.strip(), "exe_url": exe_url, "sha256_url": sha_url}


def parse_sha256_text(text: str) -> str | None:
    """Извлечь 64-символьный SHA256 из текста файла .sha256 (там может быть
    'HASH' или 'HASH  имя_файла', регистр любой). None, если хэша нет."""
    m = _HEX64_RE.search(text or "")
    return m.group(0).lower() if m else None


def sha256_of(path) -> str:
    """SHA256 файла (hex, нижний регистр). Читаем блоками — файл может быть
    десятки МБ."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest, timeout: float = 60.0,
                  progress=None) -> None:
    """Скачать url в dest. progress(получено, всего) — опциональный колбэк для
    полоски (всего может быть 0, если сервер не прислал Content-Length)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "VSCodeLauncher-update-check"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)


def download_and_verify(info: dict, dest, timeout: float = 60.0,
                        progress=None) -> tuple[bool, str]:
    """Скачать exe из info и, если есть .sha256, сверить контрольную сумму.
    Возвращает (успех, сообщение). Несовпадение суммы -> файл удаляется и
    успех=False: не подсовываем пользователю неполную/битую сборку."""
    dest = Path(dest)
    try:
        download_file(info["exe_url"], dest, timeout=timeout, progress=progress)
    except Exception as e:
        return False, f"Не удалось скачать: {e}"
    sha_url = info.get("sha256_url")
    if sha_url:
        try:
            req = urllib.request.Request(
                sha_url, headers={"User-Agent": "VSCodeLauncher-update-check"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                expected = parse_sha256_text(resp.read().decode("utf-8", "replace"))
        except Exception:
            expected = None
        if expected:
            actual = sha256_of(dest)
            if actual != expected:
                try:
                    dest.unlink()
                except OSError:
                    pass
                return False, ("Контрольная сумма не совпала — файл повреждён "
                               "или подменён. Обновление отменено.")
            return True, "Скачано и проверено по SHA256."
        return True, "Скачано (файл .sha256 недоступен — без проверки суммы)."
    return True, "Скачано (в релизе нет .sha256 — без проверки суммы)."


def build_update_swap_bat(old_exe: str, new_exe: str, image_name: str) -> str:
    """Содержимое .bat, который заменяет запущенный exe (#10). Запущенный файл
    перезаписать нельзя, поэтому: ждём, пока процесс лаунчера закроется, меняем
    старый файл новым и снова запускаем — затем bat самоудаляется. Пути в
    кавычках; image_name — имя процесса для tasklist (VSCodeLauncher.exe)."""
    return (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        ":wait\r\n"
        "timeout /t 1 /nobreak >nul\r\n"
        f'tasklist /FI "IMAGENAME eq {image_name}" | find /I "{image_name}" >nul '
        "&& goto wait\r\n"
        f'move /Y "{new_exe}" "{old_exe}" >nul\r\n'
        f'start "" "{old_exe}"\r\n'
        'del "%~f0"\r\n'
    )
