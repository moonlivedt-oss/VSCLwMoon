# -*- coding: utf-8 -*-
"""Взаимодействие с самим VS Code.

Всё, что дёргает бинарь редактора: где он лежит, какие у него расширения
установлены, как их поставить/удалить, сколько он ест памяти, как его
закрыть и запустить.
"""
import csv
import io
import json
import os
import subprocess
from pathlib import Path

from .safety import valid_ext_id

# GUI запускается через pythonw/exe без консоли, поэтому любой консольный
# подпроцесс (code.cmd через cmd, tasklist, taskkill) Windows сопровождает
# вспышкой чёрного окна cmd. CREATE_NO_WINDOW гасит её. На не-Windows флага
# нет — там getattr вернёт 0 и ничего не изменит.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# --- обнаружение CLI и папки расширений -----------------------------------

def find_code_cli() -> str | None:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = [
        local / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd",
        Path("C:/Program Files/Microsoft VS Code/bin/code.cmd"),
        local / "Programs" / "Microsoft VS Code Insiders" / "bin" / "code-insiders.cmd",
        Path("C:/Program Files/Microsoft VS Code Insiders/bin/code-insiders.cmd"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    from shutil import which
    return which("code") or which("code-insiders")


def resolve_code_cli(cfg: dict | None = None) -> str | None:
    """Путь к CLI VS Code с учётом ручной настройки (#13).

    Порядок: явно заданный в конфиге `code_cli` (если файл существует) →
    автообнаружение find_code_cli(). Позволяет работать с портативной или
    нестандартно установленной сборкой: пользователь один раз указывает путь к
    code.cmd/Code.exe, и лаунчер его запоминает. Несуществующий заданный путь
    молча игнорируется — падать на устаревшей записи хуже, чем поискать заново."""
    if cfg:
        manual = cfg.get("code_cli")
        if isinstance(manual, str) and manual.strip() and Path(manual).exists():
            return manual.strip()
    return find_code_cli()


def list_code_installs() -> list[tuple[str, str]]:
    """Обнаруженные установки VS Code для выбора в UI (#18): [(метка, путь), …].

    Стабильная и Insiders в стандартных местах плюс то, что нашлось в PATH.
    Только реально существующие пути, без дублей. Пусто — ничего не найдено,
    тогда пользователь укажет путь вручную («Обзор…»)."""
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    cands = [
        ("VS Code (стабильная)",
         local / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd"),
        ("VS Code (Program Files)",
         Path("C:/Program Files/Microsoft VS Code/bin/code.cmd")),
        ("VS Code Insiders",
         local / "Programs" / "Microsoft VS Code Insiders" / "bin" / "code-insiders.cmd"),
        ("VS Code Insiders (Program Files)",
         Path("C:/Program Files/Microsoft VS Code Insiders/bin/code-insiders.cmd")),
    ]
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, p in cands:
        key = str(p).lower()
        if p.exists() and key not in seen:
            seen.add(key); out.append((label, str(p)))
    from shutil import which
    for w in (which("code"), which("code-insiders")):
        if w and w.lower() not in seen:
            seen.add(w.lower()); out.append((f"PATH: {w}", w))
    return out


def extensions_dir(code_cli: str | None) -> Path:
    """Папка установленных расширений. Учитывает VSCODE_EXTENSIONS и Insiders."""
    env = os.environ.get("VSCODE_EXTENSIONS")
    if env:
        return Path(env)
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    if code_cli and "insiders" in code_cli.lower():
        return home / ".vscode-insiders" / "extensions"
    return home / ".vscode" / "extensions"


def vscode_user_settings_path(code_cli: str | None) -> Path | None:
    """Путь к settings.json пользователя (Code или Code - Insiders)."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    folder = "Code - Insiders" if code_cli and "insiders" in code_cli.lower() else "Code"
    return Path(appdata) / folder / "User" / "settings.json"


# --- чтение списка расширений ---------------------------------------------

def read_installed_from_disk(code_cli: str | None) -> list[str]:
    """Быстрое чтение id из extensions.json (~3 мс). Пусто — файла нет/битый."""
    f = extensions_dir(code_cli) / "extensions.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        ids = {(e.get("identifier") or {}).get("id", "").lower()
               for e in data if isinstance(e, dict)}
        ids.discard("")
        return sorted(ids)
    except Exception:
        return []


def list_installed_extensions(code_cli: str) -> list[str]:
    """Надёжный фолбэк: спрашиваем сам VS Code (~0.5 с, спавнит Node)."""
    try:
        out = subprocess.run(
            [os.environ.get("COMSPEC", "cmd.exe"), "/c", code_cli, "--list-extensions"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            creationflags=_NO_WINDOW,
        )
        return [ln.strip().lower() for ln in out.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


def load_installed(code_cli: str | None) -> tuple[list[str], str]:
    """Единая точка: сначала чтение с диска, затем фолбэк на CLI.
    Возвращает (ids, источник)."""
    ids = read_installed_from_disk(code_cli)
    if ids:
        return ids, "extensions.json"
    if code_cli:
        return list_installed_extensions(code_cli), "code --list-extensions"
    return [], "нет источника"


# --- установка / удаление --------------------------------------------------

def install_extension(code_cli: str, ext_id: str) -> tuple[bool, str]:
    """Установить расширение из маркетплейса. Возвращает (успех, вывод)."""
    if not valid_ext_id(ext_id):
        return False, f"Недопустимый id расширения: {ext_id!r}"
    try:
        out = subprocess.run(
            [os.environ.get("COMSPEC", "cmd.exe"), "/c", code_cli,
             "--install-extension", ext_id, "--force"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
            creationflags=_NO_WINDOW,
        )
        text = ((out.stdout or "") + "\n" + (out.stderr or "")).strip()
        return out.returncode == 0, text
    except Exception as e:
        return False, str(e)


def uninstall_extension(code_cli: str, ext_id: str) -> tuple[bool, str]:
    """Удалить расширение. Возвращает (успех, вывод)."""
    if not valid_ext_id(ext_id):
        return False, f"Недопустимый id расширения: {ext_id!r}"
    try:
        out = subprocess.run(
            [os.environ.get("COMSPEC", "cmd.exe"), "/c", code_cli,
             "--uninstall-extension", ext_id],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
            creationflags=_NO_WINDOW,
        )
        text = ((out.stdout or "") + "\n" + (out.stderr or "")).strip()
        return out.returncode == 0, text
    except Exception as e:
        return False, str(e)


# --- процессы: имя, память, закрытие, запуск ------------------------------

def marketplace_url(ext_id: str) -> str | None:
    """Страница расширения в маркетплейсе VS Code — чтобы прочитать, что это,
    ПЕРЕД установкой. None для невалидного id (в URL пускаем только проверенный
    publisher.name, без подстановки произвольного текста)."""
    if not valid_ext_id(ext_id):
        return None
    from urllib.parse import quote
    return f"https://marketplace.visualstudio.com/items?itemName={quote(ext_id)}"


def code_image_name(code_cli: str | None) -> str:
    """Имя процесса для taskkill: 'Code.exe' или 'Code - Insiders.exe'."""
    return "Code - Insiders.exe" if "insiders" in (code_cli or "").lower() else "Code.exe"


def code_gui_exe(code_cli: str | None) -> Path | None:
    """GUI-исполняемый файл (Code.exe) рядом с bin/code.cmd — чтобы запускать
    напрямую через CreateProcess, минуя cmd.exe. None, если не удалось найти."""
    if not code_cli:
        return None
    exe = Path(code_cli).resolve().parent.parent / code_image_name(code_cli)
    return exe if exe.exists() else None


def code_memory_mb(code_cli: str | None) -> tuple[int, int]:
    """Фактический расход памяти запущенного VS Code: (МБ, число процессов)."""
    image = code_image_name(code_cli)
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            creationflags=_NO_WINDOW,
        )
    except Exception:
        return 0, 0
    total_kb, n = 0, 0
    for row in csv.reader(io.StringIO(out.stdout)):
        if len(row) < 5:
            continue
        digits = "".join(ch for ch in row[4] if ch.isdigit())
        if digits:
            total_kb += int(digits); n += 1
    return round(total_kb / 1024), n


def code_private_ws_mb(code_cli: str | None) -> tuple[int, int]:
    """Честный footprint (#2): сумма PRIVATE working set всех процессов VS Code.

    tasklist в code_memory_mb суммирует полный working set каждого процесса —
    а десяток процессов Code делят общие страницы (движок, DLL), которые так
    считаются многократно, и «сэкономлено X МБ» завышается. Private working set
    (perf-счётчик WorkingSetPrivate) — только неразделяемая, реально
    освобождаемая при закрытии память. Считаем её через PowerShell/CIM.

    Возвращает (МБ, число процессов). (0, 0) — VS Code не запущен ИЛИ замер не
    удался (нет PowerShell, счётчик недоступен): вызывающий откатывается на
    code_memory_mb. Имена процессов в perf-классе — базовое имя без .exe, у
    нескольких инстансов вид 'Code', 'Code#1'; фильтром берём оба."""
    base = code_image_name(code_cli)[:-4]      # 'Code.exe' -> 'Code'
    base = base.replace("'", "''")             # экранируем для WQL-фильтра
    wql = f"Name='{base}' OR Name LIKE '{base}#%'"
    ps = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$r=Get-CimInstance Win32_PerfFormattedData_PerfProc_Process "
        f"-Filter \"{wql}\";"
        "'{0} {1}' -f (($r|Measure-Object WorkingSetPrivate -Sum).Sum),"
        "($r|Measure-Object).Count"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15, creationflags=_NO_WINDOW,
        )
        parts = (out.stdout or "").split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            total_bytes, n = int(parts[0]), int(parts[1])
            if n > 0:
                return round(total_bytes / (1024 * 1024)), n
    except Exception:
        pass
    return 0, 0


def code_footprint_mb(code_cli: str | None) -> tuple[int, int]:
    """Память VS Code для показа пользователю: сначала честный private working
    set (#2), при неудаче — полный working set через tasklist (запасной путь,
    всегда работает). Единая точка для GUI/selftest/CLI, чтобы базлайн и
    текущий замер считались одной метрикой (иначе «экономия» = разница
    несравнимых чисел)."""
    mb, n = code_private_ws_mb(code_cli)
    if n > 0:
        return mb, n
    return code_memory_mb(code_cli)


def vscode_process_count(code_cli: str | None) -> int:
    """Сколько процессов VS Code сейчас запущено (0 — закрыт).
    Для ожидания завершения при мягком закрытии."""
    return code_memory_mb(code_cli)[1]


def kill_vscode(code_cli: str | None, graceful: bool = False) -> None:
    """Закрыть все окна VS Code (без оболочки). Аргументы фиксированные.
    graceful=True — послать WM_CLOSE (taskkill без /F): VS Code успеет
    спросить про несохранённые файлы и закроется сам. graceful=False —
    принудительно (/F): память освобождается гарантированно, но
    несохранённое теряется."""
    args = ["taskkill", "/IM", code_image_name(code_cli)]
    if not graceful:
        args.insert(1, "/F")
    try:
        subprocess.run(args, capture_output=True, timeout=15, creationflags=_NO_WINDOW)
    except Exception:
        pass


def launch_detached(code_cli: str, args: list[str]) -> bool:
    """Запуск без оболочки: напрямую Code.exe (argv, без разбора метасимволов).
    Если Code.exe не найден (портативная сборка) — запасной путь через cmd /c,
    но уже списком аргументов, а не единой строкой.

    Возвращает True при успешном старте процесса. Ошибку Popen (нет прав,
    исчез бинарь, кривой путь) НЕ глотает — пробрасывает наружу, чтобы
    вызывающий показал её, а не думал, что редактор запустился (#14)."""
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    exe = code_gui_exe(code_cli)
    if exe is not None:
        subprocess.Popen([str(exe), *args], creationflags=flags, close_fds=True)
    else:
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        subprocess.Popen([comspec, "/c", code_cli, *args],
                         creationflags=flags, close_fds=True)
    return True
