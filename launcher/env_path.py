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

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, _USER_ENV_SUBKEY, 0, winreg.KEY_READ | winreg.KEY_WRITE
    ) as key:
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
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Environment",
            SMTO_ABORTIFHUNG,
            5000,
            ctypes.byref(res),
        )
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


def path_health(path_str: str | None = None) -> dict:
    """Диагностика PATH (#8): дубликаты, несуществующие каталоги, длина.

    Берёт PATH процесса (или переданную строку). Дубликаты — записи, совпадающие
    после нормализации (регистр/слэши/%VAR%): они замедляют поиск и путают
    порядок. missing — каталоги, которых нет на диске (мёртвые записи). length —
    длина строки: у пользовательского PATH в реестре есть практические лимиты,
    и близость к ним стоит показать. Чистая функция — тестируется без реестра."""
    raw = os.environ.get("PATH", "") if path_str is None else path_str
    entries = path_entries(raw)
    seen: set[str] = set()
    duplicates: list[str] = []
    missing: list[str] = []
    for e in entries:
        norm = _norm(e)
        if norm in seen:
            duplicates.append(e)
        else:
            seen.add(norm)
        try:
            if not Path(os.path.expandvars(e)).is_dir():
                missing.append(e)
        except Exception:
            missing.append(e)
    return {"count": len(entries), "duplicates": duplicates, "missing": missing, "length": len(raw)}


def refresh_process_path_from_registry() -> bool:
    """Подтянуть в PATH текущего процесса каталоги, которые появились в реестре
    (machine + user), но которых ещё нет у нас (#1).

    Пакеты, которые winget прописывает в PATH сам (Python, Node, Go, JDK…),
    кладут его в реестр, но у уже запущенного лаунчера `os.environ["PATH"]` не
    меняется — и наш probe (`which`) не видит только что установленный инструмент
    до перезапуска. Здесь мы, как новый терминал, дописываем недостающие
    реестровые каталоги в PATH процесса. ТОЛЬКО добавляем — ничего из текущего
    PATH не удаляем (там могут быть пути от родителя/venv). %VAR% раскрываем,
    иначе `which` их не поймёт. Возвращает True, если что-то добавили; на
    не-Windows реестр пуст — no-op."""
    current = os.environ.get("PATH", "")
    added = False
    for raw in path_entries(read_machine_path()) + path_entries(read_user_path()):
        try:
            directory = os.path.expandvars(raw)
        except Exception:
            directory = raw
        if directory and not contains_dir(current, directory):
            current = compute_appended(current, directory)
            added = True
    if added:
        os.environ["PATH"] = current
    return added


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


# --- чтение/запись произвольных пользовательских переменных окружения -------


def read_user_env_var(name: str) -> str:
    """Значение пользовательской переменной окружения из HKCU\\Environment (или
    пустая строка). Нужно для JAVA_HOME и подобных, которые тулчейн настраивает
    отдельно от PATH."""
    if not name:
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _USER_ENV_SUBKEY) as key:
            try:
                value, _typ = winreg.QueryValueEx(key, name)
                return value or ""
            except FileNotFoundError:
                return ""
    except OSError:
        return ""


def set_user_env_var(name: str, value: str) -> tuple[bool, str]:
    """Записать пользовательскую переменную окружения (REG_SZ) в HKCU\\Environment
    и в текущий процесс, разослать WM_SETTINGCHANGE. Без прав администратора —
    только ветка пользователя. Возвращает (изменили_ли, сообщение)."""
    if not name:
        return False, "Пустое имя переменной."
    if read_user_env_var(name) == value and os.environ.get(name) == value:
        return False, f"{name} уже равно {value}"
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _USER_ENV_SUBKEY, 0, winreg.KEY_READ | winreg.KEY_WRITE
        ) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        _broadcast_env_change()
    except Exception as e:
        return False, f"Не удалось записать {name} в реестр: {e}"
    os.environ[name] = value
    return True, f"{name} = {value}"


# --- чистка PATH: дубликаты и мёртвые записи (#8 → действие) ----------------
# Диагностика (path_health) только ПОКАЗЫВАЛА дубли и несуществующие каталоги;
# здесь их можно убрать. Работаем ТОЛЬКО с пользовательским PATH (HKCU) —
# машинный не наш и требует прав администратора. Из мёртвых записей исключаем
# «резервные» каталоги тулчейнов, которых пока нет на диске, но они законны и
# создадутся при первой установке инструмента (GOBIN, dotnet tools, npm-global).


def _dir_exists(entry: str) -> bool:
    """Существует ли каталог записи PATH (с раскрытием %VAR%). Ошибку трактуем
    как «не существует» — такую запись всё равно стоит показать как мёртвую."""
    try:
        return Path(os.path.expandvars(entry.strip())).is_dir()
    except Exception:
        return False


def reserve_dirs() -> tuple[str, ...]:
    """Каталоги, которые законно числятся в PATH, даже если их ещё нет на диске:
    они создаются при первой установке инструмента (например, `go install`
    создаёт GOBIN). Такие мёртвые записи чистка НЕ трогает."""
    home = os.environ.get("USERPROFILE", "")
    appdata = os.environ.get("APPDATA", "")
    out: list[str] = []
    if home:
        out += [home + r"\go\bin", home + r"\.dotnet\tools", home + r"\.cargo\bin"]
    if appdata:
        out += [appdata + r"\npm"]
    return tuple(out)


def compute_path_cleanup(
    path_str: str, remove_missing: bool = True, keep: tuple[str, ...] = ()
) -> dict:
    """Спланировать чистку PATH (чистая логика поверх ФС-проверки каталогов).

    Убираем повторные вхождения (первое сохраняем) и, если remove_missing,
    несуществующие каталоги — кроме тех, что перечислены в `keep` (резервные).
    Возвращает {'kept', 'removed_duplicates', 'removed_missing', 'new'} — порядок
    сохранённых записей не меняется."""
    keep_norm = {_norm(k) for k in keep}
    seen: set[str] = set()
    kept: list[str] = []
    removed_dupes: list[str] = []
    removed_missing: list[str] = []
    for e in path_entries(path_str):
        norm = _norm(e)
        if norm in seen:
            removed_dupes.append(e)
            continue
        seen.add(norm)
        if remove_missing and norm not in keep_norm and not _dir_exists(e):
            removed_missing.append(e)
            continue
        kept.append(e)
    return {
        "kept": kept,
        "removed_duplicates": removed_dupes,
        "removed_missing": removed_missing,
        "new": os.pathsep.join(kept),
    }


def _backup_path(value: str, scope: str) -> str | None:
    """Сохранить текущий PATH (scope: 'user'|'machine') в файл рядом с конфигом
    лаунчера перед изменением. Возвращает путь к бэкапу или None."""
    try:
        from datetime import datetime

        from .paths import CONFIG_DIR

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = "machine_path_backup" if scope == "machine" else "path_backup"
        dst = Path(CONFIG_DIR) / f"{prefix}_{stamp}.txt"
        dst.write_text(value, encoding="utf-8")
        return str(dst)
    except Exception:
        return None


def _backup_user_path(value: str) -> str | None:
    """Совместимость: бэкап пользовательского PATH."""
    return _backup_path(value, "user")


def clean_user_path(
    remove_missing: bool = True, dry_run: bool = False, keep: tuple[str, ...] = ()
) -> dict:
    """Убрать из пользовательского PATH дубликаты и (опц.) мёртвые записи.

    Только ветка пользователя (HKCU) — машинный PATH не трогаем. Резервные
    каталоги тулчейнов (reserve_dirs + `keep`) из мёртвых не удаляем. Перед
    записью делаем бэкап в файл. dry_run=True — только посчитать, ничего не
    менять (для предпросмотра в UI). Возвращает словарь с removed_*/new/applied/
    backup/message."""
    current = read_user_path()
    plan = compute_path_cleanup(
        current, remove_missing=remove_missing, keep=tuple(keep) + reserve_dirs()
    )
    removed = plan["removed_duplicates"] + plan["removed_missing"]
    result = {
        "removed_duplicates": plan["removed_duplicates"],
        "removed_missing": plan["removed_missing"],
        "removed": removed,
        "kept_count": len(plan["kept"]),
        "new": plan["new"],
        "changed": bool(removed),
        "applied": False,
        "backup": None,
    }
    if not removed:
        result["message"] = "PATH уже чист: дублей и мёртвых записей нет."
        return result
    if dry_run:
        result["message"] = (
            f"К удалению: дублей {len(plan['removed_duplicates'])}, "
            f"мёртвых {len(plan['removed_missing'])}."
        )
        return result
    backup = _backup_user_path(current)
    try:
        _write_user_path(plan["new"])
        _broadcast_env_change()
    except Exception as e:
        result["message"] = f"Не удалось записать PATH в реестр: {e}"
        result["backup"] = backup
        return result
    # Из PATH процесса удаляем ровно то, что убрали из реестра (не трогая записи,
    # доставшиеся от родителя/venv, которых в пользовательском PATH и не было).
    proc = os.environ.get("PATH", "")
    for entry in removed:
        proc = compute_removed(proc, entry)
    os.environ["PATH"] = proc
    result["applied"] = True
    result["backup"] = backup
    result["message"] = (
        f"Убрано записей: {len(removed)} "
        f"(дублей {len(plan['removed_duplicates'])}, "
        f"мёртвых {len(plan['removed_missing'])}). Бэкап: {backup or '—'}"
    )
    return result


# --- чистка системного (machine) PATH: нужны права администратора (#4) ------
# Системный PATH правит только администратор. Если лаунчер уже запущен с
# повышением — пишем в HKLM напрямую; иначе поднимаем короткий PowerShell через
# UAC (Start-Process -Verb RunAs), который применяет посчитанное значение из
# временного файла (так огромную строку PATH не нужно экранировать в команде).


def is_admin() -> bool:
    """Запущены ли мы с правами администратора (для чистки системного PATH)."""
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _write_machine_path_direct(value: str) -> None:
    """Записать системный PATH напрямую в HKLM (REG_EXPAND_SZ). Требует прав
    администратора — иначе winreg бросит PermissionError."""
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE, _MACHINE_ENV_SUBKEY, 0, winreg.KEY_READ | winreg.KEY_WRITE
    ) as key:
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, value)


def _write_machine_path_elevated(value: str) -> tuple[bool, str]:
    """Применить значение системного PATH через UAC: пишем значение и .ps1 во
    временные файлы и запускаем их elevated (Start-Process -Verb RunAs). Так не
    приходится экранировать длинную строку PATH в командной строке.
    Возвращает (успех, сообщение)."""
    import subprocess
    import tempfile

    tmpdir = tempfile.mkdtemp(prefix="vscl_path_")
    val_file = Path(tmpdir) / "path_value.txt"
    ps_file = Path(tmpdir) / "apply.ps1"
    try:
        val_file.write_text(value, encoding="utf-8")
        # Скрипт читает точное значение из файла (без хвостовых переводов строк)
        # и пишет его в реестр как ExpandString (REG_EXPAND_SZ).
        script = (
            "$ErrorActionPreference='Stop'\n"
            f"$v=[IO.File]::ReadAllText('{str(val_file)}')\n"
            "Set-ItemProperty -Path "
            "'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment' "
            "-Name Path -Value $v -Type ExpandString\n"
        )
        ps_file.write_text(script, encoding="utf-8")
        launcher = (
            "try { $p = Start-Process -FilePath 'powershell' -ArgumentList "
            "'-NoProfile','-ExecutionPolicy','Bypass','-File',"
            f"'{str(ps_file)}' -Verb RunAs -Wait -PassThru; exit $p.ExitCode }} "
            "catch { exit 1223 }"
        )
        _NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", launcher],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            creationflags=_NO_WINDOW,
        )
    except Exception as e:
        return False, f"Не удалось запустить elevated-процесс: {e}"
    finally:
        for f in (val_file, ps_file):
            try:
                f.unlink()
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass
    if out.returncode == 0:
        return True, "Системный PATH обновлён (с правами администратора)."
    if out.returncode == 1223:
        return False, "Запрос прав администратора (UAC) отклонён — изменения не внесены."
    return False, f"Elevated-процесс вернул код {out.returncode}."


def clean_machine_path(
    remove_missing: bool = True, dry_run: bool = False, keep: tuple[str, ...] = ()
) -> dict:
    """Убрать из системного (machine) PATH дубликаты и (опц.) мёртвые записи.

    Требует прав администратора: если лаунчер уже elevated — пишем HKLM напрямую,
    иначе поднимаем короткий elevated-процесс через UAC. Резервные каталоги
    (reserve_dirs + keep) из мёртвых не удаляем. Перед записью — бэкап в файл.
    dry_run=True — только предпросмотр. Возвращает словарь removed_*/new/applied/
    backup/needs_elevation/message."""
    current = read_machine_path()
    plan = compute_path_cleanup(
        current, remove_missing=remove_missing, keep=tuple(keep) + reserve_dirs()
    )
    removed = plan["removed_duplicates"] + plan["removed_missing"]
    result = {
        "removed_duplicates": plan["removed_duplicates"],
        "removed_missing": plan["removed_missing"],
        "removed": removed,
        "kept_count": len(plan["kept"]),
        "new": plan["new"],
        "changed": bool(removed),
        "applied": False,
        "backup": None,
        "needs_elevation": not is_admin(),
    }
    if not removed:
        result["message"] = "Системный PATH уже чист: дублей и мёртвых записей нет."
        return result
    if dry_run:
        result["message"] = (
            f"К удалению из системного PATH: дублей "
            f"{len(plan['removed_duplicates'])}, мёртвых {len(plan['removed_missing'])}."
        )
        return result
    backup = _backup_path(current, "machine")
    result["backup"] = backup
    if is_admin():
        try:
            _write_machine_path_direct(plan["new"])
            _broadcast_env_change()
        except Exception as e:
            result["message"] = f"Не удалось записать системный PATH: {e}"
            return result
    else:
        ok, msg = _write_machine_path_elevated(plan["new"])
        if not ok:
            result["message"] = msg
            return result
        _broadcast_env_change()
    # Обновим PATH процесса, чтобы наш же probe/поиск сразу увидел изменение.
    proc = os.environ.get("PATH", "")
    for entry in removed:
        proc = compute_removed(proc, entry)
    os.environ["PATH"] = proc
    result["applied"] = True
    result["message"] = (
        f"Убрано из системного PATH: {len(removed)} "
        f"(дублей {len(plan['removed_duplicates'])}, "
        f"мёртвых {len(plan['removed_missing'])}). Бэкап: {backup or '—'}"
    )
    return result


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
