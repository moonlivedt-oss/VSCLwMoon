# -*- coding: utf-8 -*-
r"""Управление пользовательским PATH в Windows — без прав администратора.

Зачем отдельный модуль. Установка языкового тулчейна бесполезна, если его
`bin` не виден из терминала VS Code. Большинство пакетов winget прописывают
PATH сами, но не все (архивные сборки вроде WinLibs просто распаковываются).
Тогда нужно дописать каталог в PATH — и сделать это правильно.

Почему НЕ `setx`. Классический `setx PATH ...` обрезает значение до 1024
символов: на машине с длинным PATH это тихо уничтожает часть путей. Поэтому
пишем напрямую в реестр `HKCU\Environment` (пользовательский PATH, админ не
нужен) значением типа REG_EXPAND_SZ, сохраняя `%VAR%`-подстановки, и рассылаем
WM_SETTINGCHANGE, чтобы Explorer и новые оболочки подхватили изменение без
перезагрузки. Плюс дописываем PATH текущего процесса — чтобы наш же probe
сразу нашёл только что установленный инструмент.

Чистая логика (`path_entries`, `contains_dir`, `compute_appended`) отделена от
реестрового I/O и тестируется без Windows.
"""
from __future__ import annotations

import os
from pathlib import Path

_USER_ENV_SUBKEY = "Environment"
_MACHINE_ENV_SUBKEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"


# --- чистая логика (тестируется на любой ОС) -------------------------------

def path_entries(path_str: str) -> list[str]:
    """Разбить строку PATH на непустые записи (по `;`), без обрезки пробелов
    внутри путей — только отбрасываем пустые сегменты от лишних `;`."""
    if not path_str:
        return []
    return [p for p in path_str.split(os.pathsep) if p.strip()]


def _norm(p: str) -> str:
    """Нормализовать путь для сравнения: регистр и слэши, снятый хвостовой слэш.
    Раскрываем %VAR% — записи в реестре могут быть в виде %USERPROFILE%\\..."""
    try:
        return os.path.normcase(os.path.normpath(os.path.expandvars(p.strip())))
    except Exception:
        return p.strip().lower()


def contains_dir(path_str: str, directory: str) -> bool:
    """Есть ли `directory` среди записей PATH (с учётом регистра/слэшей/%VAR%)."""
    target = _norm(directory)
    return any(_norm(e) == target for e in path_entries(path_str))


def compute_appended(path_str: str, directory: str) -> str:
    """Новое значение PATH с дописанным в конец `directory`. Если он уже есть —
    вернуть исходную строку без изменений (идемпотентность). Дубли не плодим."""
    if contains_dir(path_str, directory):
        return path_str
    directory = directory.rstrip("\\/")
    if not path_str:
        return directory
    sep = "" if path_str.endswith(os.pathsep) else os.pathsep
    return f"{path_str}{sep}{directory}"


def compute_removed(path_str: str, directory: str) -> str:
    """Новое значение PATH без записей, совпадающих с `directory` (с учётом
    регистра/слэшей/%VAR%). Для отката установки/чистки. Порядок остальных
    записей сохраняется."""
    target = _norm(directory)
    kept = [e for e in path_entries(path_str) if _norm(e) != target]
    return os.pathsep.join(kept)


# --- реестровый I/O (только Windows) ---------------------------------------

def read_user_path() -> str:
    """Прочитать пользовательский PATH из HKCU\\Environment. Пустая строка, если
    значения нет или мы не на Windows."""
    try:
        import winreg
    except ImportError:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _USER_ENV_SUBKEY) as key:
            try:
                value, _typ = winreg.QueryValueEx(key, "Path")
                return value or ""
            except FileNotFoundError:
                return ""
    except OSError:
        return ""


def read_machine_path() -> str:
    """Прочитать системный PATH (HKLM, только чтение). Нужен, чтобы не дублировать
    в пользовательский PATH каталог, который машинная установка уже прописала.
    Пустая строка, если нет доступа/значения/не Windows."""
    try:
        import winreg
    except ImportError:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _MACHINE_ENV_SUBKEY) as key:
            try:
                value, _typ = winreg.QueryValueEx(key, "Path")
                return value or ""
            except FileNotFoundError:
                return ""
    except OSError:
        return ""


def _write_user_path(value: str) -> None:
    """Записать пользовательский PATH типом REG_EXPAND_SZ (чтобы %VAR% внутри
    продолжали раскрываться). Создаёт значение, если его не было."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _USER_ENV_SUBKEY, 0,
                        winreg.KEY_READ | winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, value)


def _broadcast_env_change() -> None:
    """Разослать WM_SETTINGCHANGE("Environment"), чтобы уже запущенные Explorer и
    новые процессы (в т.ч. новые терминалы VS Code) увидели изменённый PATH без
    перезагрузки. Тихо игнорируем любую ошибку — обновление PATH уже записано,
    рассылка лишь ускоряет его подхват."""
    try:
        import ctypes
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        res = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
            SMTO_ABORTIFHUNG, 5000, ctypes.byref(res))
    except Exception:
        pass


def is_on_path(directory: str) -> bool:
    """Виден ли `directory` в PATH — в процессе, в пользовательском ИЛИ машинном
    реестре. Достаточно любого: наличие в процессе значит, что инструмент уже
    работает сейчас; наличие в реестре (user или machine) — что он переживёт
    перезапуск. Машинный PATH учитываем, чтобы не дублировать запись, которую
    установка в machine-scope уже сделала."""
    if not directory:
        return False
    if contains_dir(os.environ.get("PATH", ""), directory):
        return True
    if contains_dir(read_user_path(), directory):
        return True
    return contains_dir(read_machine_path(), directory)


def add_to_user_path(directory: str) -> tuple[bool, str]:
    """Дописать `directory` в постоянный пользовательский PATH (реестр) и в PATH
    текущего процесса. Возвращает (изменили_ли, сообщение).

    Никаких прав администратора: правим только ветку пользователя. Если каталог
    уже в PATH — ничего не делаем и честно сообщаем об этом. Несуществующий
    каталог не добавляем: мусор в PATH бесполезен и лишь замедляет поиск."""
    directory = (directory or "").strip().rstrip("\\/")
    if not directory:
        return False, "Пустой путь."
    if not Path(directory).is_dir():
        return False, f"Каталог не существует: {directory}"

    already_reg = contains_dir(read_user_path(), directory)
    already_proc = contains_dir(os.environ.get("PATH", ""), directory)
    if already_reg and already_proc:
        return False, f"Уже в PATH: {directory}"

    # Постоянно — в реестр (если ещё не там).
    if not already_reg:
        try:
            current = read_user_path()
            _write_user_path(compute_appended(current, directory))
            _broadcast_env_change()
        except Exception as e:
            return False, f"Не удалось записать PATH в реестр: {e}"

    # Немедленно — в текущий процесс, чтобы probe нашёл инструмент сразу.
    if not already_proc:
        os.environ["PATH"] = compute_appended(os.environ.get("PATH", ""), directory)

    return True, f"Добавлено в PATH: {directory}"


def remove_from_user_path(directory: str) -> tuple[bool, str]:
    """Убрать `directory` из постоянного пользовательского PATH (реестр) и из
    PATH текущего процесса. Возвращает (изменили_ли, сообщение). Для отката
    установки/чистки. Машинный PATH не трогаем — на него у пользователя нет прав
    и это не наша запись."""
    directory = (directory or "").strip().rstrip("\\/")
    if not directory:
        return False, "Пустой путь."
    current = read_user_path()
    if not contains_dir(current, directory):
        # Возможно, в PATH процесса всё же есть — почистим и его.
        if contains_dir(os.environ.get("PATH", ""), directory):
            os.environ["PATH"] = compute_removed(os.environ.get("PATH", ""), directory)
            return True, f"Убрано из PATH процесса: {directory}"
        return False, f"Нет в пользовательском PATH: {directory}"
    try:
        _write_user_path(compute_removed(current, directory))
        _broadcast_env_change()
    except Exception as e:
        return False, f"Не удалось записать PATH в реестр: {e}"
    os.environ["PATH"] = compute_removed(os.environ.get("PATH", ""), directory)
    return True, f"Убрано из PATH: {directory}"
