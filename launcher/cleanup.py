# -*- coding: utf-8 -*-
"""Уборка: что VS Code накопил на диске и что можно безопасно убрать.

VS Code ничего из этого не чистит сам (или чистит редко):
- CachedExtensionVSIXs — копии установщиков каждой версии каждого расширения;
- workspaceStorage     — данные проектов, папок которых давно нет на диске;
- CachedData           — скомпилированный JS прошлых версий редактора;
- Cache, Code Cache, GPUCache, Dawn*Cache — кэши движка Chromium;
- logs                 — логи прошлых сеансов;
- старые версии расширений, оставшиеся рядом с установленной новой.

Всё это VS Code при необходимости создаст заново. Удаление идёт в Корзину
(можно вернуть) и только при закрытом редакторе: кэши занятого процесса
либо не удалятся, либо удалятся наполовину.

Поиск (scan) — без побочных эффектов, его и показываем как предпросмотр.
Удаление (send_to_trash) — отдельный явный шаг.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from .weights import _dir_size, folder_to_ext_id

# Кэши движка: пересоздаются при следующем старте, ничего пользовательского.
ENGINE_CACHES = ("Cache", "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache")

KIND_TITLES = {
    "vsix": "Копии установщиков расширений (CachedExtensionVSIXs)",
    "workspace": "Данные удалённых проектов (workspaceStorage)",
    "cacheddata": "Кэш прошлых версий VS Code (CachedData)",
    "engine": "Кэши движка (Cache, GPUCache…)",
    "logs": "Логи прошлых сеансов",
    "old_ext": "Старые версии расширений",
}


def _size(path: Path) -> int:
    try:
        if path.is_file():
            return path.stat().st_size
        return _dir_size(path, max_entries=200_000)
    except OSError:
        return 0


def _item(kind: str, path: Path, note: str = "") -> dict:
    return {"kind": kind, "path": str(path), "bytes": _size(path), "note": note}


def uri_to_local_path(uri: str) -> Path | None:
    """file:///d%3A/proj -> Path('d:/proj'). Не file-URI (remote, wsl) -> None:
    о существовании удалённой папки отсюда судить нельзя."""
    try:
        u = urlparse(uri)
    except Exception:
        return None
    if u.scheme != "file" or (u.netloc and u.netloc.lower() != "localhost"):
        return None
    p = unquote(u.path)
    if len(p) >= 3 and p[0] == "/" and p[2] == ":":  # /d:/proj -> d:/proj
        p = p[1:]
    return Path(p) if p else None


def stale_workspaces(storage: Path) -> list[Path]:
    """Папки workspaceStorage, чей проект (папка или .code-workspace) больше
    не существует. Записи без workspace.json и удалённые проекты не трогаем.
    Проект на отключённом диске (флешка, сетевой диск, VeraCrypt) тоже не
    трогаем: его папки нет сейчас, но она вернётся вместе с диском."""
    out: list[Path] = []
    try:
        entries = [d for d in storage.iterdir() if d.is_dir()]
    except OSError:
        return out
    for d in entries:
        meta = d / "workspace.json"
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except Exception:
            continue
        uri = data.get("folder") or data.get("workspace") if isinstance(data, dict) else None
        if not isinstance(uri, str):
            continue
        local = uri_to_local_path(uri)
        if local is None or not local.anchor or not Path(local.anchor).exists():
            continue
        if not local.exists():
            out.append(d)
    return out


def old_extension_folders(ext_dir: Path) -> list[Path]:
    """Папки расширений, которые VS Code больше не использует: у того же id
    зарегистрирована другая папка (новая версия). Папки без package.json и
    расширения без зарегистрированной версии не трогаем — это могут быть
    данные расширений или сборки, которые пользователь ставит руками."""
    try:
        reg = json.loads((ext_dir / "extensions.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    registered: dict[str, str] = {}
    for e in reg if isinstance(reg, list) else []:
        if not isinstance(e, dict):
            continue
        ext_id = str((e.get("identifier") or {}).get("id", "")).lower()
        loc = e.get("relativeLocation")
        if ext_id and isinstance(loc, str):
            registered[ext_id] = loc.lower()
    out: list[Path] = []
    try:
        dirs = [d for d in ext_dir.iterdir() if d.is_dir()]
    except OSError:
        return out
    for d in dirs:
        ext_id = folder_to_ext_id(d.name)
        if not ext_id or ext_id not in registered:
            continue
        if d.name.lower() == registered[ext_id]:
            continue
        if (d / "package.json").is_file():
            out.append(d)
    return out


def current_commit(code_exe: Path | None) -> str:
    """Хэш коммита установленного VS Code (из product.json) — чтобы не трогать
    CachedData текущей версии. Пусто — не нашли, тогда CachedData не чистим."""
    if not code_exe:
        return ""
    base = code_exe.parent
    candidates = [base / "resources" / "app" / "product.json"]
    try:
        # Новые сборки кладут resources в подпапку с хэшем версии.
        candidates += [
            d / "resources" / "app" / "product.json"
            for d in base.iterdir()
            if d.is_dir() and len(d.name) == 10
        ]
    except OSError:
        pass
    for f in candidates:
        try:
            commit = json.loads(f.read_text(encoding="utf-8")).get("commit", "")
        except Exception:
            continue
        if commit:
            return str(commit)
    return ""


def scan(user_data: Path, ext_dir: Path, code_exe: Path | None = None) -> list[dict]:
    """Найти всё, что можно убрать. Каждый элемент — {kind, path, bytes, note}.
    Ничего не удаляет."""
    items: list[dict] = []
    vsix = user_data / "CachedExtensionVSIXs"
    if vsix.is_dir():
        try:
            for f in vsix.iterdir():
                items.append(_item("vsix", f))
        except OSError:
            pass
    for d in stale_workspaces(user_data / "User" / "workspaceStorage"):
        note = ""
        try:
            data = json.loads((d / "workspace.json").read_text(encoding="utf-8"))
            note = str(data.get("folder") or data.get("workspace") or "")
        except Exception:
            pass
        local = uri_to_local_path(note) if note else None
        items.append(_item("workspace", d, str(local) if local else note))
    commit = current_commit(code_exe)
    cached = user_data / "CachedData"
    if commit and cached.is_dir():
        try:
            for d in cached.iterdir():
                if d.is_dir() and d.name != commit:
                    items.append(_item("cacheddata", d))
        except OSError:
            pass
    for name in ENGINE_CACHES:
        p = user_data / name
        if p.is_dir():
            items.append(_item("engine", p))
    logs = user_data / "logs"
    if logs.is_dir():
        try:
            sessions = sorted((d for d in logs.iterdir() if d.is_dir()), key=lambda d: d.name)
        except OSError:
            sessions = []
        for d in sessions[:-1]:  # последний сеанс оставляем
            items.append(_item("logs", d))
    for d in old_extension_folders(ext_dir):
        items.append(_item("old_ext", d))
    return [i for i in items if i["bytes"] > 0]


def summarize(items: list[dict]) -> list[tuple[str, int, int]]:
    """[(kind, байты, число), ...] по убыванию размера — для сводки."""
    agg: dict[str, list[int]] = {}
    for i in items:
        a = agg.setdefault(i["kind"], [0, 0])
        a[0] += i["bytes"]
        a[1] += 1
    return sorted(((k, v[0], v[1]) for k, v in agg.items()), key=lambda t: -t[1])


def _shell_trash_one(path: str) -> int:
    """Одна операция SHFileOperationW (FO_DELETE + FOF_ALLOWUNDO) для одного
    пути. Возвращает код API (0 — успех)."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", ctypes.c_uint),
            ("pFrom", ctypes.c_void_p),
            ("pTo", ctypes.c_void_p),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    FO_DELETE = 3
    FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400
    # API требует список путей, оканчивающийся двойным нулём. Буфер создаём
    # явно: c_wchar_p из str не гарантирует, что второй ноль дойдёт до API.
    buf = ctypes.create_unicode_buffer(os.path.abspath(path) + "\0")
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = ctypes.cast(buf, ctypes.c_void_p)
    op.fFlags = FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI
    return int(ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)))


def send_to_trash(paths: list[str]) -> tuple[bool, str]:
    """Переместить файлы и папки в Корзину. Возвращает (успех, текст ошибки).

    По одному пути за вызов: пакетный SHFileOperation отдаёт код ошибки на всю
    операцию, даже если не удался один элемент из сотни, а остальные уже в
    Корзине (так пользователь получал «0x7c», хотя всё было убрано). Итог
    проверяем по факту — существует ли путь после операции, — а не по коду."""
    paths = [p for p in paths if p and os.path.exists(p)]
    if not paths:
        return True, ""
    if sys.platform != "win32":
        return False, "Корзина поддерживается только в Windows"
    import logging

    log = logging.getLogger("launcher")
    left: list[str] = []
    for p in paths:
        try:
            rc = _shell_trash_one(p)
        except Exception as e:  # noqa: BLE001 — одна ошибка не должна рвать уборку
            rc = -1
            log.warning("Уборка: %s — %s", p, e)
        if os.path.exists(p):
            left.append(p)
            log.warning("Уборка: не удалось убрать %s (код %#x)", p, rc & 0xFFFFFFFF)
    log.info("Уборка: в Корзину %d из %d", len(paths) - len(left), len(paths))
    if not left:
        return True, ""
    shown = "\n".join(left[:5]) + ("\n…" if len(left) > 5 else "")
    return False, f"осталось {len(left)} из {len(paths)} (файлы заняты?):\n{shown}"
