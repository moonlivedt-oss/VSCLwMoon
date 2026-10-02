# -*- coding: utf-8 -*-
"""Уборка: что VS Code накопил на диске и что можно безопасно убрать.

VS Code ничего из этого не чистит сам (или чистит редко):
- CachedExtensionVSIXs — копии установщиков каждой версии каждого расширения;
- workspaceStorage     — данные проектов, папок которых давно нет на диске;
- CachedData           — скомпилированный JS прошлых версий редактора;
- Cache, Code Cache, GPUCache, Dawn*Cache — кэши движка Chromium;
- logs                 — логи прошлых сеансов;
- старые версии расширений, оставшиеся рядом с установленной новой;
- кэш IntelliSense C/C++ (ipch) — бывает на гигабайты;
- отчёты о падениях (Crashpad), хвосты обновлятора и Edge DevTools в TEMP;
- старые версии самого VS Code в папке установки.

Отдельно — то, что ценнее кэша, и потому по умолчанию НЕ отмечено (SAFE_KINDS):
данные удалённых расширений, давно не открытые проекты и локальная история
файлов, которых больше нет.

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
ENGINE_CACHES = (
    "Cache", "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache",
    "Service Worker/CacheStorage", "Service Worker/ScriptCache",
)
OLD_DAYS = 90  # «давно не открытый проект»

KIND_TITLES = {
    "cpptools": "Кэш IntelliSense C/C++ (ipch, базы обзора кода)",
    "vsix": "Копии установщиков расширений (CachedExtensionVSIXs)",
    "workspace": "Данные удалённых проектов (workspaceStorage)",
    "cacheddata": "Кэш прошлых версий VS Code (CachedData)",
    "engine": "Кэши движка (Cache, GPUCache…)",
    "logs": "Логи прошлых сеансов",
    "old_ext": "Старые версии расширений",
    "crash": "Отчёты о падениях (Crashpad)",
    "temp": "Временные файлы VS Code в TEMP",
    "old_vscode": "Старые версии самого VS Code",
    "orphan_data": "Данные удалённых расширений",
    "workspace_old": "Давно не открытые проекты",
    "history": "Локальная история удалённых файлов",
}

# Отмечены по умолчанию: всё это пересоздаётся само, потерять нечего.
SAFE_KINDS = frozenset({
    "cpptools", "vsix", "workspace", "cacheddata", "engine", "logs", "old_ext",
    "crash", "temp", "old_vscode",
})

KIND_HELP = {
    "cpptools": "Предкомпилированные заголовки и базы обзора кода расширения C/C++. "
    "Пересоздаются при открытии проекта (первые минуты подсказки медленнее).",
    "vsix": "Скачанные установщики прошлых версий расширений. Не нужны.",
    "workspace": "Состояние проектов, папок которых больше нет на диске.",
    "cacheddata": "Скомпилированный код прошлых версий VS Code.",
    "engine": "Кэши Chromium внутри VS Code — создаются заново.",
    "logs": "Логи прошлых сеансов (последний оставлен).",
    "old_ext": "Папки прошлых версий расширений и помеченные VS Code на удаление.",
    "crash": "Отчёты о падениях VS Code, которые никуда не отправлены.",
    "temp": "Журналы и загрузки обновлятора VS Code, профиль браузера Edge DevTools.",
    "old_vscode": "Папки прошлых версий VS Code после обновления. Текущая не трогается.",
    "orphan_data": "Настройки и кэши расширений, которых больше нет. При повторной "
    "установке расширение начнёт с чистого листа.",
    "workspace_old": "Состояние проектов, которые не открывались больше 90 дней: открытые "
    "вкладки, история поиска, кэши расширений. Сам проект не трогается.",
    "history": "Сохранённые VS Code версии файлов, которых больше нет. Это единственная "
    "копия удалённого файла — убирайте, только если он точно не нужен.",
}


def _size(path: Path) -> int:
    try:
        if path.is_file():
            return path.stat().st_size
        return _dir_size(path, max_entries=200_000)
    except OSError:
        return 0


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _item(kind: str, path: Path, note: str = "") -> dict:
    return {
        "kind": kind, "path": str(path), "bytes": _size(path), "note": note,
        "mtime": _mtime(path), "safe": kind in SAFE_KINDS,
    }


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


def _obsolete_names(ext_dir: Path) -> set[str]:
    try:
        data = json.loads((ext_dir / ".obsolete").read_text(encoding="utf-8-sig"))
    except Exception:
        return set()
    return {str(k).lower() for k, v in data.items() if v} if isinstance(data, dict) else set()


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
    # Помеченные VS Code на удаление (.obsolete) — он сам уберёт их при
    # следующем старте, но если редактор давно не перезапускали, они лежат.
    obsolete = _obsolete_names(ext_dir) - set(registered.values())
    for d in dirs:
        if d.name.lower() in obsolete:
            out.append(d)
            continue
        ext_id = folder_to_ext_id(d.name)
        if not ext_id or ext_id not in registered:
            continue
        if d.name.lower() == registered[ext_id]:
            continue
        if (d / "package.json").is_file():
            out.append(d)
    return out


def _version_dirs(install_dir: Path) -> list[tuple[tuple[int, ...], Path]]:
    """Папки версий VS Code в папке установки: [(версия, папка)], свежие первыми.
    Корневая resources/app тоже считается (старая раскладка)."""
    out: list[tuple[tuple[int, ...], Path]] = []
    cands = [install_dir]
    try:
        cands += [d for d in install_dir.iterdir() if d.is_dir()]
    except OSError:
        pass
    for d in cands:
        try:
            data = json.loads((d / "resources" / "app" / "package.json").read_text(encoding="utf-8-sig"))
            ver = tuple(int(x) for x in str(data.get("version", "")).split("-")[0].split("."))
        except Exception:
            continue
        out.append((ver, d))
    out.sort(key=lambda t: t[0], reverse=True)
    return out


def old_vscode_versions(code_exe: Path | None) -> list[Path]:
    """Папки прошлых версий VS Code (<install>/<hash>) после обновления.
    Самую новую не трогаем никогда; корень установки — тоже. Нечего сравнить
    (одна версия) — пусто."""
    if not code_exe:
        return []
    install = code_exe.parent
    vers = _version_dirs(install)
    if len(vers) < 2:
        return []
    return [d for _v, d in vers[1:] if d != install and len(d.name) == 10]


def current_commit(code_exe: Path | None) -> str:
    """Хэш коммита установленного VS Code (из product.json) — чтобы не трогать
    CachedData текущей версии. Пусто — не нашли, тогда CachedData не чистим."""
    if not code_exe:
        return ""
    # Самая новая версия: после обновления рядом лежит и прошлая, и раньше
    # бралась первая попавшаяся — кэш ТЕКУЩЕЙ версии мог уйти в уборку.
    candidates = [d / "resources" / "app" / "product.json" for _v, d in _version_dirs(code_exe.parent)]
    for f in candidates:
        try:
            commit = json.loads(f.read_text(encoding="utf-8")).get("commit", "")
        except Exception:
            continue
        if commit:
            return str(commit)
    return ""


_HEX32 = frozenset("0123456789abcdef")


def cpptools_cache(local_appdata: Path | None, custom: str = "") -> list[Path]:
    """Кэш расширения C/C++: ipch (предкомпилированные заголовки, гигабайты) и
    базы обзора кода в папках-хэшах. custom — C_Cpp.intelliSenseCachePath."""
    out: list[Path] = []
    if custom:
        p = Path(custom) / "ipch"
        if p.is_dir():
            out.append(p)
    if local_appdata is None:
        return out
    base = local_appdata / "Microsoft" / "vscode-cpptools"
    if (base / "ipch").is_dir() and base / "ipch" not in out:
        out.append(base / "ipch")
    try:
        for d in base.iterdir():
            name = d.name.lower()
            if d.is_dir() and len(name) == 32 and set(name) <= _HEX32:
                out.append(d)
    except OSError:
        pass
    return out


def crash_reports(user_data: Path) -> list[Path]:
    return [p for p in (user_data / "Crashpad" / "reports", user_data / "Crashpad" / "attachments")
            if p.is_dir()]


def temp_leftovers(temp: Path | None) -> list[Path]:
    """Хвосты VS Code во временной папке: журналы и загрузки обновлятора,
    профиль браузера расширения Edge DevTools."""
    if temp is None:
        return []
    out: list[Path] = []
    try:
        entries = list(temp.iterdir())
    except OSError:
        return out
    for e in entries:
        n = e.name.lower()
        if (n.startswith("vscode-inno-updater-") and n.endswith(".log")) or (
            e.is_dir() and (n.startswith(("vscode-stable-", "vscode-insider-"))
                            or n.startswith("vscode-edge-devtools-userdatadir"))):
            out.append(e)
    return out


def orphan_extension_data(user_data: Path, installed, builtin) -> list[Path]:
    """Папки данных расширений, которых больше нет (globalStorage/<id> и
    workspaceStorage/*/<id>). Без списка установленных или встроенных — ничего:
    иначе данные встроенных (vscode.git) сошли бы за мусор."""
    from .safety import valid_ext_id

    have = {str(e).lower() for e in installed or ()}
    built = {str(e).lower() for e in builtin or ()}
    if not have or not built:
        return []
    keep = have | built

    def orphan(d: Path) -> bool:
        n = d.name.lower()
        return (d.is_dir() and "." in n and valid_ext_id(n) and n not in keep
                and not n.startswith("vscode."))

    out: list[Path] = []
    gs = user_data / "User" / "globalStorage"
    try:
        out += [d for d in gs.iterdir() if orphan(d)]
    except OSError:
        pass
    ws = user_data / "User" / "workspaceStorage"
    try:
        for w in ws.iterdir():
            if w.is_dir():
                out += [d for d in w.iterdir() if orphan(d)]
    except OSError:
        pass
    return out


def old_workspaces(storage: Path, days: int, now: float, skip=()) -> list[tuple[Path, str, float]]:
    """Проекты, которые есть на диске, но не открывались дольше days дней:
    [(папка workspaceStorage, путь проекта, время последнего открытия)]."""
    out: list[tuple[Path, str, float]] = []
    skip = {str(p) for p in skip}
    try:
        entries = [d for d in storage.iterdir() if d.is_dir() and str(d) not in skip]
    except OSError:
        return out
    for d in entries:
        try:
            data = json.loads((d / "workspace.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        uri = data.get("folder") or data.get("workspace") if isinstance(data, dict) else None
        local = uri_to_local_path(uri) if isinstance(uri, str) else None
        if local is None or not local.exists():
            continue
        last = max(_mtime(d / "state.vscdb"), _mtime(d))
        if last and now - last > days * 86400:
            out.append((d, str(local), last))
    return out


def stale_history(user_data: Path) -> list[tuple[Path, str]]:
    """Локальная история (User/History) файлов, которых больше нет. Файл на
    отключённом диске не считается удалённым."""
    out: list[tuple[Path, str]] = []
    hist = user_data / "User" / "History"
    try:
        entries = [d for d in hist.iterdir() if d.is_dir()]
    except OSError:
        return out
    for d in entries:
        try:
            data = json.loads((d / "entries.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        res = data.get("resource") if isinstance(data, dict) else None
        local = uri_to_local_path(res) if isinstance(res, str) else None
        if local is None or not local.anchor or not Path(local.anchor).exists():
            continue
        if not local.exists():
            out.append((d, str(local)))
    return out


def scan(user_data: Path, ext_dir: Path, code_exe: Path | None = None, *,
         installed=None, builtin=None, local_appdata: Path | None = None,
         temp_dir: Path | None = None, cpp_cache_path: str = "",
         old_days: int = OLD_DAYS, now: float | None = None) -> list[dict]:
    """Найти всё, что можно убрать. Каждый элемент — {kind, path, bytes, note,
    mtime, safe}. Ничего не удаляет. Необязательные параметры включают
    дополнительные места (см. scan_vscode — он подставляет их сам)."""
    import time

    now = time.time() if now is None else now
    items: list[dict] = []
    for p in cpptools_cache(local_appdata, cpp_cache_path):
        items.append(_item("cpptools", p))
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
    for p in crash_reports(user_data):
        items.append(_item("crash", p))
    for p in temp_leftovers(temp_dir):
        items.append(_item("temp", p))
    for d in old_vscode_versions(code_exe):
        items.append(_item("old_vscode", d))
    for d in orphan_extension_data(user_data, installed, builtin):
        parent = d.parent.name if d.parent.name != "globalStorage" else ""
        items.append(_item("orphan_data", d, d.name + (f"  ({parent})" if parent else "")))
    stale = {i["path"] for i in items if i["kind"] == "workspace"}
    for d, proj, _last in old_workspaces(user_data / "User" / "workspaceStorage", old_days, now, stale):
        items.append(_item("workspace_old", d, proj))
    for hd, fname in stale_history(user_data):
        items.append(_item("history", hd, fname))
    return [i for i in items if i["bytes"] > 0]


def scan_vscode(code_cli: str | None) -> list[dict]:
    """scan() со всеми местами для этой установки VS Code: данные пользователя,
    расширения, кэш C/C++, TEMP, список установленных и встроенных."""
    import os

    from . import compat
    from .vscode import (code_gui_exe, extensions_dir, read_installed_from_disk,
                         vscode_user_settings_path)

    settings = vscode_user_settings_path(code_cli)
    if settings is None:
        raise OSError("Не найдена папка данных VS Code (%APPDATA%).")
    custom = ""
    try:
        from .detect import _loads_jsonc

        data = _loads_jsonc(settings.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict) and isinstance(data.get("C_Cpp.intelliSenseCachePath"), str):
            custom = os.path.expandvars(data["C_Cpp.intelliSenseCachePath"])
    except Exception:
        pass
    local = os.environ.get("LOCALAPPDATA")
    temp = os.environ.get("TEMP") or os.environ.get("TMP")
    return scan(
        settings.parent.parent, extensions_dir(code_cli), code_gui_exe(code_cli),
        installed=read_installed_from_disk(code_cli),
        builtin=compat.builtin_extensions(code_cli),
        local_appdata=Path(local) if local else None,
        temp_dir=Path(temp) if temp else None,
        cpp_cache_path=custom,
    )


def summarize(items: list[dict]) -> list[tuple[str, int, int]]:
    """[(kind, байты, число), ...]: сначала безопасное, внутри — по убыванию размера."""
    agg: dict[str, list[int]] = {}
    for i in items:
        a = agg.setdefault(i["kind"], [0, 0])
        a[0] += i["bytes"]
        a[1] += 1
    return sorted(((k, v[0], v[1]) for k, v in agg.items()),
                  key=lambda t: (t[0] not in SAFE_KINDS, -t[1]))


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
