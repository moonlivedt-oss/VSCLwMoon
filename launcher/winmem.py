# -*- coding: utf-8 -*-
"""Нативный замер памяти процессов Windows через ctypes.

Зачем отдельный модуль. Раньше лаунчер спрашивал память двумя способами:
`tasklist` (полный working set — завышает, общие страницы движка считаются у
каждого процесса Code заново) и PowerShell с CIM-счётчиком WorkingSetPrivate
(честнее, но старт powershell.exe стоит 0.7-2 с и он есть не везде). На каждое
открытие окна и после каждого запуска редактора это заметная пауза.

Здесь то же самое делается напрямую через Win32: снимок процессов
(CreateToolhelp32Snapshot) плюс GetProcessMemoryInfo на каждый подходящий pid.
Это единицы миллисекунд, без порождения процессов и без зависимости от
PowerShell.

Метрика — PrivateUsage (private commit, «Байты в выделенной памяти» в
диспетчере задач): память, которую процесс занял только для себя и которая
освободится при его закрытии. Именно это отвечает на вопрос «сколько я
сэкономлю, если не грузить этот стек». Общие страницы (движок, DLL) в неё не
попадают, поэтому число не раздувается от того, что процессов Code десяток.

Всё Windows-специфично: на других ОС функции возвращают пустой результат, а
вызывающий откатывается на прежний путь (tasklist).
"""
from __future__ import annotations

import ctypes
import sys

# ctypes.wintypes существует только на Windows — на других ОС сам импорт
# падает. Модуль обязан импортироваться везде (его тянет vscode.py, который
# импортируют и линтеры, и тесты чистой логики), поэтому импорт условный,
# а все функции на не-Windows возвращают пустой результат.
IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    from ctypes import wintypes
else:  # pragma: no cover — заглушки, чтобы объявления структур ниже собрались
    class wintypes:            # type: ignore[no-redef]
        DWORD = ctypes.c_uint32
        HANDLE = ctypes.c_void_p

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MAX_PATH = 260


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * MAX_PATH),
    ]


class _PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


# Загруженная библиотека переживает вызовы: WinDLL на каждое обращение — это
# LoadLibraryW на каждый процесс в замере (десятки на ровном месте).
# Аннотация не вычисляется в рантайме (from __future__ import annotations),
# поэтому ctypes.WinDLL в ней безопасен и на не-Windows.
_K32: ctypes.WinDLL | None = None


def _kernel32():
    global _K32
    if _K32 is None:
        _K32 = ctypes.WinDLL("kernel32", use_last_error=True)
    return _K32


def iter_processes() -> list[tuple[int, str]]:
    """Снимок процессов: [(pid, имя_exe), ...]. Пусто — не Windows или снимок
    не удался (это не ошибка приложения: вызывающий откатится на tasklist)."""
    if not IS_WINDOWS:
        return []
    k32 = _kernel32()
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    # INVALID_HANDLE_VALUE == -1: снимок не дался (например, нет прав).
    if not snap or snap == ctypes.c_void_p(-1).value:
        return []
    out: list[tuple[int, str]] = []
    try:
        entry = _PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
        ok = k32.Process32First(snap, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile.decode("mbcs", "replace")
            out.append((int(entry.th32ProcessID), name))
            ok = k32.Process32Next(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return out


def process_memory(pid: int) -> tuple[int, int]:
    """(private_bytes, working_set_bytes) процесса. (0, 0) — процесс уже исчез,
    защищён или нет прав: пропускаем его, а не роняем весь замер.

    GetProcessMemoryInfo живёт в psapi.dll, но начиная с Windows 7 доступен и
    как K32GetProcessMemoryInfo в kernel32 — берём то, что есть."""
    if not IS_WINDOWS:
        return 0, 0
    k32 = _kernel32()
    k32.OpenProcess.restype = wintypes.HANDLE
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return 0, 0
    try:
        counters = _PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS_EX)
        fn = getattr(k32, "K32GetProcessMemoryInfo", None)
        if fn is None:
            fn = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
        if not fn(handle, ctypes.byref(counters), counters.cb):
            return 0, 0
        return int(counters.PrivateUsage), int(counters.WorkingSetSize)
    except Exception:
        return 0, 0
    finally:
        k32.CloseHandle(handle)


def image_memory(image_name: str) -> tuple[int, int, int]:
    """Суммарная память всех процессов с этим именем образа.

    Возвращает (private_МБ, working_set_МБ, число_процессов). (0, 0, 0) —
    процессов нет ИЛИ замер невозможен (не Windows, снимок не дался): по
    третьему элементу вызывающий отличает «закрыт» от «не сумели»
    только вместе с available()."""
    target = (image_name or "").lower()
    if not target or not IS_WINDOWS:
        return 0, 0, 0
    private = ws = n = 0
    for pid, name in iter_processes():
        if name.lower() != target:
            continue
        p, w = process_memory(pid)
        if p or w:
            private += p
            ws += w
            n += 1
    mb = 1024 * 1024
    return round(private / mb), round(ws / mb), n


def available() -> bool:
    """Работает ли нативный путь здесь. False — вызывающий идёт через tasklist."""
    if not IS_WINDOWS:
        return False
    try:
        return bool(iter_processes())
    except Exception:
        return False
