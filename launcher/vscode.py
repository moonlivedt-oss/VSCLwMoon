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
import re
import subprocess
from pathlib import Path

from . import winmem
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
    """Честный footprint (#2): приватная память VS Code вместе с языковыми
    серверами расширений.

    tasklist в code_memory_mb суммирует полный working set каждого процесса —
    а десяток процессов Code делят общие страницы (движок, DLL), которые так
    считаются многократно, и «сэкономлено X МБ» завышается. Приватная память —
    только неразделяемая, реально освобождаемая при закрытии.

    Считаем по дереву процессов (proctree.py): кроме Code.exe сюда входят
    потомки, принадлежащие расширениям (cpptools.exe, java.exe SonarLint/Java,
    сервис MSSQL) — именно в них живёт основной вес тяжёлых стеков. Оболочки
    терминала и то, что в них запущено, не считаются. Если дерево собрать не
    удалось — прежний замер только Code.exe.

    Возвращает (МБ, число процессов). (0, 0) — VS Code не запущен ИЛИ замер не
    удался: вызывающий откатывается на code_memory_mb."""
    image = code_image_name(code_cli)
    try:
        from . import proctree
        tree = proctree.measure(image, str(extensions_dir(code_cli)), {})
        if tree and tree["n"]:
            return tree["total_mb"], tree["n"]
    except Exception:
        pass
    try:
        private_mb, _ws_mb, n = winmem.image_memory(image)
    except Exception:
        return 0, 0
    return (private_mb, n) if n else (0, 0)


# --- честная стоимость расширений: code --status ---------------------------

_STATUS_ROW_RE = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\S.*?)\s*$")


def parse_code_status(text: str) -> dict:
    """Разобрать вывод `code --status` в сводку по процессам редактора.

    Что там есть, чего нет больше нигде: VS Code сам подписывает свои процессы —
    'window', 'gpu-process', 'extensionHost', 'ptyHost', 'fileWatcher'. Это
    позволяет отделить память САМОГО редактора от памяти РАСШИРЕНИЙ: расширения
    живут в extensionHost и в порождённых им языковых серверах (они выводятся
    с отступом под ним). Ответ «сколько едят расширения» перестаёт быть
    догадкой по таблице весов.

    Возвращает {"total_mb", "extension_mb", "editor_mb", "processes", "extensions"}.
    Чистая функция без IO — тестируется на фикстуре; ничего не распарсилось —
    нули и пустой список.

    Вложенность считаем по КОЛОНКЕ, с которой начинается имя процесса: числовые
    колонки выровнены по правому краю, поэтому у детей имя сдвинуто правее
    родителя ровно на отступ."""
    rows: list[dict] = []
    in_table = False
    for raw in (text or "").splitlines():
        low = raw.strip().lower()
        if not in_table:
            if low.startswith("cpu %") and "mem mb" in low and "process" in low:
                in_table = True
            continue
        if not raw.strip():
            if rows:
                break          # таблица кончилась пустой строкой
            continue
        m = _STATUS_ROW_RE.match(raw)
        if not m:
            break
        # Отступ дочернего процесса VS Code кладёт В САМО поле имени, а поля
        # разделяет табами. Берём отступ из последнего поля — тогда pid другой
        # ширины (семизначные бывают) не сдвинет вложенность. Старый формат с
        # выравниванием пробелами всё ещё читается по колонке имени.
        if raw.count("\t") >= 3:
            field = raw.split("\t")[3]
            col = len(field) - len(field.lstrip(" "))
        else:
            col = m.start(4)
        rows.append({
            "cpu": int(m.group(1)),
            "mb": int(m.group(2)),
            "pid": int(m.group(3)),
            "name": m.group(4),
            "col": col,
        })

    if rows:  # колонка верхнего уровня = самая левая из встреченных
        base = min(r["col"] for r in rows)
        for r in rows:
            r["depth"] = r["col"] - base
            del r["col"]

    ext_mb = 0
    ext_depth = -1
    for r in rows:
        # Имя процесса VS Code менял: раньше 'extensionHost', в нынешних версиях
        # 'extension-host'. Сравниваем без дефисов, иначе на свежем редакторе
        # хост расширений не находится и вся память уходит в графу «редактор».
        if r["name"].lower().replace("-", "").startswith("extensionhost"):
            ext_depth = r["depth"]
            ext_mb += r["mb"]
        elif ext_depth >= 0:
            if r["depth"] > ext_depth:
                ext_mb += r["mb"]      # языковой сервер, порождённый расширением
            else:
                ext_depth = -1

    total = sum(r["mb"] for r in rows)
    n_ext = None
    m = re.search(r"^\s*Extensions\s*:?\s*(\d+)", text or "", re.M | re.I)
    if m:
        n_ext = int(m.group(1))
    return {
        "total_mb": total,
        "extension_mb": ext_mb,
        "editor_mb": max(0, total - ext_mb),
        "processes": rows,
        "extensions": n_ext,
    }


def code_status(code_cli: str | None, timeout: float = 30.0) -> dict | None:
    """Спросить у самого VS Code, сколько сейчас едят его процессы.

    Дорогая операция (поднимает node, ~1-3 с) и требует запущенного редактора,
    поэтому зовётся только по явному действию пользователя и всегда в фоне.
    None — CLI нет, редактор закрыт или вывод не разобрался."""
    if not code_cli:
        return None
    try:
        out = subprocess.run(
            [os.environ.get("COMSPEC", "cmd.exe"), "/c", code_cli, "--status"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=_NO_WINDOW,
        )
    except Exception:
        return None
    data = parse_code_status(out.stdout or "")
    return data if data["processes"] else None


def code_footprint_mb(code_cli: str | None) -> tuple[int, int]:
    """Память VS Code для показа пользователю: сначала приватная память по
    нативному замеру (#2), при неудаче — полный working set через tasklist
    (запасной путь, всегда работает). Единая точка для GUI/selftest/CLI, чтобы
    базлайн и текущий замер считались одной метрикой (иначе «экономия» —
    разница несравнимых чисел)."""
    mb, n = code_private_ws_mb(code_cli)
    if n > 0:
        return mb, n
    try:
        if winmem.available():
            return 0, 0   # нативный путь работает и говорит: редактор закрыт
    except Exception:
        pass
    return code_memory_mb(code_cli)


def vscode_process_count(code_cli: str | None) -> int:
    """Сколько процессов VS Code сейчас запущено (0 — закрыт).
    Для ожидания завершения при мягком закрытии. Нативный путь (миллисекунды)
    важен вдвойне: при мягком закрытии счётчик опрашивается раз в 750 мс, и
    старый tasklist успевал не уложиться в интервал."""
    try:
        if winmem.available():
            return winmem.image_memory(code_image_name(code_cli))[2]
    except Exception:
        pass
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
