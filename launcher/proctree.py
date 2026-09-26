# -*- coding: utf-8 -*-
"""Кто ест память: дерево процессов VS Code с раскладкой по стекам.

Зачем. Замер по имени образа (winmem.image_memory('Code.exe')) видит только
процессы самого редактора. Но самые тяжёлые части стеков живут в ОТДЕЛЬНЫХ
процессах: cpptools.exe у C++, java.exe у Java и SonarLint, сервис MSSQL,
PowerShell Editor Services. Их память в замер не попадала — и экономия от
выключения тяжёлого стека выглядела меньше, чем есть.

Здесь берём снимок процессов с родителями, находим всех потомков Code.exe и
для каждого определяем, чьё это расширение: по пути в командной строке или
образе (<папка расширений>\\<publisher.name-версия>\\...). Потомок процесса
расширения наследует его принадлежность (cpptools-srv.exe -> cpptools).

Что не отнесено ни к редактору, ни к расширению (оболочки терминала и всё,
что пользователь запустил в терминале), в footprint НЕ входит: это не цена
расширений, и сборка проекта в терминале не должна «съедать» экономию.

Логика разбора (attribute_tree) — чистая функция без WinAPI, её и тестируем.
Сбор данных (snapshot) — Windows-специфичный, на других ОС пустой.
"""

from __future__ import annotations

import ctypes
import sys

from . import winmem

IS_WINDOWS = sys.platform == "win32"

# Класс ProcessCommandLineInformation для NtQueryInformationProcess
# (Windows 8.1+): отдаёт командную строку без чтения чужой памяти, с правами
# PROCESS_QUERY_LIMITED_INFORMATION — тех же, что нужны для замера памяти.
_PROCESS_COMMAND_LINE_INFORMATION = 60

EDITOR = "editor"
UNMAPPED = "(не в карте)"


def _norm(path: str) -> str:
    return (path or "").lower().replace("/", "\\").rstrip("\\")


def ext_folder_in(text: str, ext_dir: str) -> str:
    """Имя папки расширения, если `text` (командная строка или путь образа)
    указывает внутрь папки расширений. Иначе пустая строка."""
    base = _norm(ext_dir)
    if not base:
        return ""
    low = _norm(text)
    i = low.find(base + "\\")
    if i < 0:
        return ""
    rest = low[i + len(base) + 1 :]
    end = len(rest)
    for stop in ("\\", '"', " "):
        j = rest.find(stop)
        if 0 <= j < end:
            end = j
    return rest[:end]


def attribute_tree(
    procs: list[dict], editor_image: str, ext_dir: str, ext_index: dict[str, str]
) -> dict:
    """Разложить память дерева процессов VS Code.

    procs — [{pid, ppid, name, cmd, image, private}] (private — байты).
    Возвращает:
      total_mb   — редактор + расширения (то, что уходит при закрытии VS Code
                   и зависит от набора стеков);
      editor_mb  — процессы редактора, не принадлежащие расширениям;
      ext        — {ext_id: МБ};
      stacks     — {ключ стека | 'always_on' | '(не в карте)': МБ};
      other      — [(имя, МБ)] потомки вне расширений (терминал и т.п.);
      n          — число процессов в дереве."""
    # Импорт здесь: weights тянет categories, а тот — пути данных; модуль
    # должен импортироваться и в тестах без лишних зависимостей по кругу.
    from .weights import folder_to_ext_id

    image = (editor_image or "").lower()
    by_pid = {p["pid"]: p for p in procs}
    children: dict[int, list[int]] = {}
    for p in procs:
        children.setdefault(p["ppid"], []).append(p["pid"])

    def is_editor(pid: int) -> bool:
        p = by_pid.get(pid)
        return bool(p) and p["name"].lower() == image

    roots = [p["pid"] for p in procs if p["name"].lower() == image and not is_editor(p["ppid"])]

    owner: dict[int, str] = {}  # pid -> ext_id ('' — не расширение)
    order: list[int] = []
    seen: set[int] = set()
    queue = [(r, "") for r in roots]
    while queue:
        pid, inherited = queue.pop()
        if pid in seen:
            continue
        seen.add(pid)
        p = by_pid[pid]
        folder = ext_folder_in(p.get("cmd", ""), ext_dir) or ext_folder_in(
            p.get("image", ""), ext_dir
        )
        own = folder_to_ext_id(folder) if folder else ""
        owner[pid] = own or inherited
        order.append(pid)
        for c in children.get(pid, ()):
            if c != pid:
                queue.append((c, owner[pid]))

    mb = 1024 * 1024
    ext_bytes: dict[str, int] = {}
    editor_bytes = 0
    other: dict[str, int] = {}
    for pid in order:
        p = by_pid[pid]
        size = int(p.get("private", 0))
        ext_id = owner[pid]
        if ext_id:
            ext_bytes[ext_id] = ext_bytes.get(ext_id, 0) + size
        elif p["name"].lower() == image:
            editor_bytes += size
        else:
            other[p["name"]] = other.get(p["name"], 0) + size

    stacks: dict[str, int] = {}
    for ext_id, size in ext_bytes.items():
        key = ext_index.get(ext_id) or UNMAPPED
        stacks[key] = stacks.get(key, 0) + size

    ext_total = sum(ext_bytes.values())
    return {
        "total_mb": round((editor_bytes + ext_total) / mb),
        "editor_mb": round(editor_bytes / mb),
        "ext_mb": round(ext_total / mb),
        "ext": {k: round(v / mb) for k, v in sorted(ext_bytes.items(), key=lambda kv: -kv[1])},
        "stacks": {k: round(v / mb) for k, v in sorted(stacks.items(), key=lambda kv: -kv[1])},
        "other": sorted(((k, round(v / mb)) for k, v in other.items()), key=lambda kv: -kv[1]),
        "n": len(order),
    }


# --- сбор данных (WinAPI) ---------------------------------------------------


def _open(pid: int):
    k32 = winmem._kernel32()
    k32.OpenProcess.restype = ctypes.c_void_p
    return k32.OpenProcess(winmem.PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))


def _image_path(handle) -> str:
    k32 = winmem._kernel32()
    buf = ctypes.create_unicode_buffer(1024)
    size = ctypes.c_uint32(len(buf))
    try:
        if k32.QueryFullProcessImageNameW(ctypes.c_void_p(handle), 0, buf, ctypes.byref(size)):
            return buf.value
    except Exception:
        pass
    return ""


def _command_line(handle) -> str:
    try:
        ntdll = ctypes.WinDLL("ntdll")
    except Exception:
        return ""
    need = ctypes.c_uint32(0)
    fn = ntdll.NtQueryInformationProcess
    fn.restype = ctypes.c_long
    fn(ctypes.c_void_p(handle), _PROCESS_COMMAND_LINE_INFORMATION, None, 0, ctypes.byref(need))
    if not need.value or need.value > 1 << 20:
        return ""
    buf = ctypes.create_string_buffer(need.value)
    status = fn(
        ctypes.c_void_p(handle),
        _PROCESS_COMMAND_LINE_INFORMATION,
        buf,
        need.value,
        ctypes.byref(need),
    )
    if status != 0:
        return ""

    # UNICODE_STRING { USHORT Length; USHORT MaximumLength; PWSTR Buffer; }
    class _US(ctypes.Structure):
        _fields_ = [
            ("Length", ctypes.c_ushort),
            ("MaximumLength", ctypes.c_ushort),
            ("Buffer", ctypes.c_void_p),
        ]

    us = _US.from_buffer(buf)
    if not us.Buffer or not us.Length:
        return ""
    return ctypes.wstring_at(us.Buffer, us.Length // 2)


def snapshot(editor_image: str) -> list[dict]:
    """Процессы редактора и всех его потомков с командной строкой, путём
    образа и приватной памятью. Пусто — не Windows или снимок не дался."""
    if not IS_WINDOWS:
        return []
    try:
        rows = winmem.iter_processes_ex()
    except Exception:
        return []
    image = (editor_image or "").lower()
    kids: dict[int, list[tuple[int, int, str]]] = {}
    for pid, ppid, name in rows:
        kids.setdefault(ppid, []).append((pid, ppid, name))
    names = {pid: name.lower() for pid, _pp, name in rows}
    tree: list[tuple[int, int, str]] = []
    stack = [r for r in rows if r[2].lower() == image and names.get(r[1]) != image]
    seen: set[int] = set()
    while stack:
        row = stack.pop()
        if row[0] in seen or row[0] == 0:
            continue
        seen.add(row[0])
        tree.append(row)
        stack.extend(kids.get(row[0], ()))

    k32 = winmem._kernel32()
    out: list[dict] = []
    for pid, ppid, name in tree:
        private, _ws = winmem.process_memory(pid)
        cmd = img = ""
        handle = _open(pid)
        if handle:
            try:
                img = _image_path(handle)
                cmd = _command_line(handle)
            finally:
                k32.CloseHandle(ctypes.c_void_p(handle))
        out.append(
            {"pid": pid, "ppid": ppid, "name": name, "cmd": cmd, "image": img, "private": private}
        )
    return out


def measure(editor_image: str, ext_dir: str, ext_index: dict[str, str]) -> dict | None:
    """Снимок + разбор. None — редактор не запущен или замер невозможен."""
    procs = snapshot(editor_image)
    if not procs:
        return None
    return attribute_tree(procs, editor_image, ext_dir, ext_index)
