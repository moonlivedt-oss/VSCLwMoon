# -*- coding: utf-8 -*-
r"""Установка языковых тулчейнов (компиляторы, SDK, runtime) через winget.

VS Code — это редактор; чтобы собрать C++ или запустить Java, нужен сам
тулчейн: g++/gcc, JDK, Go, Rust и т.д. Расширения без него бесполезны
(«java не найдена», «cannot find compiler»). Этот модуль ставит недостающие
инструменты и следит, чтобы они попали в PATH.

Почему winget. Он предустановлен в современной Windows, сам качает пакеты из
доверенных источников, проверяет подписи и в большинстве случаев прописывает
PATH. Мы не изобретаем свой загрузчик и не тащим бинари в репозиторий.

Ключи каталога совпадают с ключами стеков (`detect.py`, `categories.json`):
`python`, `cpp`, `java`, `go`, `rust`, `dotnet`, `web`, `ruby`, `git`. Это
позволяет связать «в проекте обнаружен стек X» с «поставить его тулчейн».

Безопасность (в духе `safety.py`): в командную строку winget уходит только
id из НАШЕГО каталога, дополнительно пропущенный через `valid_winget_id`.
Пользовательский ввод в аргументы winget не попадает. Подпроцессы — списком
аргументов и с CREATE_NO_WINDOW (GUI без консоли не должен мигать окном cmd).
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from shutil import which

from . import env_path

log = logging.getLogger("launcher")

# GUI под pythonw/exe без консоли: гасим вспышку окна cmd у подпроцессов.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# id пакета winget: буквы/цифры и разделители . _ + -. Строго, без пробелов,
# кавычек и метасимволов — чтобы ничто из каталога не могло протащить инъекцию
# в командную строку, даже если файл каталога кто-то подменит.
_WINGET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]*$")


def valid_winget_id(pkg_id: str) -> bool:
    return bool(pkg_id) and bool(_WINGET_ID_RE.match(pkg_id))


@dataclass(frozen=True)
class Package:
    """Один устанавливаемый пакет.

    winget_id — id для `winget install --id`; probe — исполняемые файлы,
    которые должны появиться в PATH после установки (по ним и определяем,
    стоит ли инструмент); path_hints — типовые каталоги `bin`, куда дописать
    PATH, если winget этого не сделал (архивные сборки). optional — пакет-
    дополнение (например, CMake рядом с компилятором), не входит в набор
    «поставить всё» по умолчанию, но доступен явной кнопкой.
    """
    winget_id: str
    title: str
    probe: tuple[str, ...]
    note: str = ""
    optional: bool = False
    path_hints: tuple[str, ...] = ()
    version_arg: str = "--version"
    # Полный набор инструментов, который приносит пакет (для показа в UI): у
    # MinGW это не только g++, но и gcc, gdb, mingw32-make, gfortran. probe —
    # подмножество для детекта; provides — что реально становится доступно.
    provides: tuple[str, ...] = ()

    def tools(self) -> tuple[str, ...]:
        """Все инструменты пакета: provides, если задан, иначе probe."""
        return self.provides or self.probe


@dataclass(frozen=True)
class Toolchain:
    key: str            # совпадает с ключом стека
    title: str
    note: str
    packages: tuple[Package, ...] = field(default_factory=tuple)


# --- каталог ---------------------------------------------------------------
# id проверены в реестре winget (community). Версии в id намеренно
# «крупные» (мажорные) — winget сам поставит свежайшую в пределах мажора.

TOOLCHAINS: dict[str, Toolchain] = {
    "python": Toolchain(
        "python", "Python", "Интерпретатор Python и pip.",
        (Package("Python.Python.3.12", "Python 3.12", ("python", "pip"),
                 note="Сам прописывает PATH при установке."),)),
    "cpp": Toolchain(
        "cpp", "C / C++", "Компилятор GCC (MinGW-w64), отладчик GDB и make; опционально CMake, Ninja, Clang.",
        (Package("BrechtSanders.WinLibs.POSIX.UCRT", "MinGW-w64 (GCC/G++/GDB/make)",
                 ("g++", "gcc", "gdb"),
                 note="Архивная сборка WinLibs — PATH пропишет сам лаунчер. "
                      "Даёт компилятор, отладчик и mingw32-make.",
                 provides=("gcc", "g++", "gdb", "mingw32-make", "gfortran")),
         Package("Kitware.CMake", "CMake", ("cmake",), optional=True,
                 note="Система сборки для крупных C/C++ проектов."),
         Package("Ninja-build.Ninja", "Ninja", ("ninja",), optional=True,
                 note="Быстрый генератор сборки — часто в паре с CMake."),
         Package("LLVM.LLVM", "LLVM / Clang", ("clang", "clang++"), optional=True,
                 note="Альтернативный компилятор Clang.",
                 provides=("clang", "clang++", "clang-format", "lldb")))),
    "java": Toolchain(
        "java", "Java (JDK)", "OpenJDK (Eclipse Temurin): java и javac.",
        (Package("EclipseAdoptium.Temurin.21.JDK", "Temurin JDK 21",
                 ("java", "javac"),
                 note="LTS-сборка OpenJDK. Прописывает JAVA_HOME и PATH."),)),
    "go": Toolchain(
        "go", "Go", "Компилятор и тулчейн Go.",
        (Package("GoLang.Go", "Go", ("go",),
                 note="Сам прописывает PATH при установке."),)),
    "rust": Toolchain(
        "rust", "Rust", "Rustup ставит компилятор rustc и пакетный менеджер cargo.",
        (Package("Rustlang.Rustup", "Rustup (rustc + cargo)", ("cargo", "rustc"),
                 note="Через rustup обновляется и переключается вся цепочка Rust."),)),
    "dotnet": Toolchain(
        "dotnet", ".NET", "SDK для C#/F#: команда dotnet.",
        (Package("Microsoft.DotNet.SDK.8", ".NET SDK 8", ("dotnet",),
                 note="Сам прописывает PATH при установке."),)),
    "web": Toolchain(
        "web", "Node.js", "Node.js и npm — для веб- и JS/TS-проектов.",
        (Package("OpenJS.NodeJS", "Node.js LTS", ("node", "npm"),
                 note="Сам прописывает PATH при установке."),)),
    "ruby": Toolchain(
        "ruby", "Ruby", "Интерпретатор Ruby и gem.",
        (Package("RubyInstallerTeam.Ruby.3.3", "Ruby 3.3", ("ruby", "gem"),
                 note="Сам прописывает PATH при установке."),)),
    "git": Toolchain(
        "git", "Git", "Система контроля версий — нужна и самой VS Code.",
        (Package("Git.Git", "Git for Windows", ("git",),
                 note="Сам прописывает PATH при установке."),)),
}


def toolchain_keys() -> list[str]:
    return list(TOOLCHAINS)


def get_toolchain(key: str) -> Toolchain | None:
    return TOOLCHAINS.get(key)


# --- наличие winget --------------------------------------------------------

_winget_cache: dict = {}


def winget_path() -> str | None:
    """Путь к winget.exe или None. winget — App Execution Alias, `which` его находит.
    Результат кэшируется: путь в пределах сессии не меняется, а `which` не бесплатен
    (его зовут на каждый статус)."""
    if "path" not in _winget_cache:
        _winget_cache["path"] = which("winget")
    return _winget_cache["path"]


def winget_available() -> bool:
    return winget_path() is not None


def winget_version() -> str | None:
    """Строка версии winget (например, 'v1.29.290') или None. Кэшируется."""
    if "version" in _winget_cache:
        return _winget_cache["version"]
    ver = None
    wg = winget_path()
    if wg:
        try:
            out = subprocess.run([wg, "--version"], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=15,
                                 creationflags=_NO_WINDOW)
            ver = (out.stdout or "").strip() or None
        except Exception:
            ver = None
    _winget_cache["version"] = ver
    return ver


# --- определение, что уже стоит --------------------------------------------

def probe_version(exe: str) -> str | None:
    """Короткая строка версии инструмента `exe` или None, если его нет в PATH.

    Сначала проверяем наличие в PATH (which) — дёшево и без запуска процесса;
    затем спрашиваем версию. Любой сбой запуска трактуем как «нет»."""
    if not exe or which(exe) is None:
        return None
    for arg in ("--version", "version"):
        try:
            out = subprocess.run(
                [exe, arg], capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=15, creationflags=_NO_WINDOW)
        except Exception:
            continue
        text = ((out.stdout or "") + " " + (out.stderr or "")).strip()
        if text:
            return text.splitlines()[0].strip()[:120]
    return "установлен"   # в PATH есть, но версию не отдал — этого достаточно


def package_installed(pkg: Package) -> bool:
    """Пакет считаем установленным, если ЛЮБОЙ его probe-бинарь виден в PATH."""
    return any(which(exe) is not None for exe in pkg.probe)


def package_status(pkg: Package) -> dict:
    """{'installed': bool, 'version': str|None} — для строки в UI/CLI."""
    ver = None
    for exe in pkg.probe:
        ver = probe_version(exe)
        if ver:
            break
    return {"installed": ver is not None, "version": ver}


def verify_package(pkg: Package) -> tuple[bool, str]:
    """Проверить, что пакет реально работает: запустить probe и вернуть версию.
    (успех, текст). Используется после установки и кнопкой «Проверить» — чтобы
    подтвердить, что инструмент не просто на PATH, а действительно запускается."""
    for exe in pkg.probe:
        ver = probe_version(exe)
        if ver:
            return True, f"{exe}: {ver}"
    return False, f"{pkg.title}: ни один из {', '.join(pkg.probe)} не отвечает в PATH."


# Относительные шаблоны типовых мест установки C/C++-тулчейнов ВНЕ winget
# (MSYS2, ручной MinGW, Chocolatey, LLVM, CMake). Разворачиваются по каждому
# существующему диску — MSYS2 нередко стоит не на C:. Нужны, чтобы предложить
# «у вас уже есть компилятор, просто он не в PATH», не качая второй раз.
_DISK_SCAN_RELATIVE: tuple[str, ...] = (
    r"msys64\ucrt64\bin", r"msys64\mingw64\bin", r"msys64\mingw32\bin",
    r"mingw64\bin", r"mingw32\bin", r"MinGW\bin",
    r"ProgramData\mingw64\mingw64\bin",
    r"Program Files\LLVM\bin", r"Program Files\CMake\bin",
    r"Program Files\Git\bin",
)


def _disk_scan_roots() -> list[str]:
    """Развернуть относительные шаблоны по существующим дискам (C:..H:).
    Проверяем существование диска, а не каждого пути — дешевле, чем stat всего."""
    roots = []
    for letter in "CDEFGH":
        drive = f"{letter}:\\"
        if not os.path.isdir(drive):
            continue
        for rel in _DISK_SCAN_RELATIVE:
            roots.append(drive + rel)
    return roots


# Обратная совместимость: некоторые вызовы/тесты ждут кортеж корней на C:.
_DISK_SCAN_ROOTS: tuple[str, ...] = tuple(
    "C:\\" + rel for rel in _DISK_SCAN_RELATIVE)


def find_tool_on_disk(pkg: Package, extra_roots: tuple[str, ...] = ()) -> str | None:
    """Найти каталог с probe-бинарём пакета среди типовых мест установки (даже
    если ставили не через winget). Возвращает путь к `bin` или None.

    Порядок: сначала распакованные winget-пакеты (find_bin_dir_for), затем
    известные корни (_DISK_SCAN_ROOTS + extra_roots). Так покрывается и
    «поставили через winget, но PATH не прописался», и «стоит MSYS2/ручной
    MinGW мимо PATH»."""
    found = find_bin_dir_for(pkg)
    if found:
        return found
    wanted = {f"{e}.exe".lower() for e in pkg.probe}
    for root in (*_disk_scan_roots(), *extra_roots):
        try:
            d = Path(root)
            if d.is_dir() and any((d / w).exists() for w in wanted):
                return str(d)
        except OSError:
            continue
    return None


# Коды возврата winget → человеческое объяснение (частые случаи). Полный список
# — в документации APPINSTALLER_CLI_ERROR_*; здесь то, на что реально натыкаются.
_WINGET_CODE_HINTS: dict[int, str] = {
    -1978335215: "Пакет не найден в источнике winget.",
    -1978335212: "Не найден подходящий установщик (возможно, нужна другая "
                 "разрядность или область установки).",
    -1978335189: "Обновление не требуется — уже установлена актуальная версия.",
    -1978335162: "Установка отменена пользователем.",
    -1978334967: "Установщик требует прав администратора (machine-scope). "
                 "Согласитесь на запрос UAC или поставьте в user-scope.",
    -1978335135: "Уже установлено.",
}


def explain_winget_code(code: int, output: str = "") -> str:
    """Короткое человекочитаемое объяснение кода возврата winget. Если кода нет
    в таблице — вернуть последнюю осмысленную строку вывода (winget обычно сам
    пишет причину), иначе — сам код."""
    hint = _WINGET_CODE_HINTS.get(code)
    if hint:
        return hint
    for line in reversed((output or "").splitlines()):
        s = line.strip()
        if s:
            return s[:200]
    return f"winget вернул код {code}."


def toolchain_status(key: str) -> list[dict]:
    """Статус каждого пакета тулчейна: [{'package': Package, 'installed', 'version'}]."""
    tc = TOOLCHAINS.get(key)
    if not tc:
        return []
    rows = []
    for pkg in tc.packages:
        st = package_status(pkg)
        rows.append({"package": pkg, **st})
    return rows


def missing_required(key: str) -> list[Package]:
    """Обязательные (не optional) пакеты тулчейна, которых ещё нет."""
    tc = TOOLCHAINS.get(key)
    if not tc:
        return []
    return [p for p in tc.packages if not p.optional and not package_installed(p)]


# --- установка -------------------------------------------------------------

# «Успешные» коды возврата winget: 0 — установлено; специальные HRESULT ниже
# означают «уже установлено / нет применимого обновления» — для нас это тоже
# успех (инструмент на месте), а не ошибка.
_WINGET_OK_CODES = {
    0,
    -1978335189,   # 0x8A15002B APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE
    -1978335135,   # 0x8A150061 no applicable installer / already installed
}


def install_package(pkg: Package, scope: str | None = None) -> tuple[bool, str]:
    """Поставить пакет через winget и, если нужно, починить PATH.

    Возвращает (успех, вывод). После установки, если probe-бинарь всё ещё не
    виден, пробуем дописать в PATH подсказанные каталоги (`path_hints`) —
    так архивные сборки (WinLibs) тоже становятся доступны из терминала.

    scope=None (по умолчанию) — не навязывать область установки: winget сам
    выберет user/machine по тому, что предлагает пакет. Форсировать 'user'
    опасно — пакеты, доступные только машинно, дадут «no applicable installer»."""
    return _run_winget("install", pkg, scope=scope, repair=True)


def upgrade_package(pkg: Package, scope: str | None = None) -> tuple[bool, str]:
    """Обновить установленный пакет до свежей версии через `winget upgrade`.
    Если обновлять нечего — winget вернёт «update not applicable», и мы считаем
    это успехом (пакет уже актуален)."""
    return _run_winget("upgrade", pkg, scope=scope, repair=True)


def uninstall_package(pkg: Package) -> tuple[bool, str]:
    """Удалить пакет через winget и убрать из пользовательского PATH каталоги,
    которые лаунчер туда дописывал (архивные сборки). Машинный PATH не трогаем."""
    ok, text = _run_winget("uninstall", pkg, scope=None, repair=False)
    if ok:
        for hint in pkg.path_hints:
            removed, _m = env_path.remove_from_user_path(hint)
            if removed:
                text = (text + f"\nPATH очищен: {hint}").strip()
    return ok, text


def _run_winget(action: str, pkg: Package, scope: str | None,
                repair: bool) -> tuple[bool, str]:
    """Общий вызов winget для install/upgrade/uninstall.

    Возвращает (успех, вывод). Подпроцесс — списком аргументов и с
    CREATE_NO_WINDOW. При успехе install/upgrade и repair=True чиним PATH.
    Ошибку переводим в человеческую строку через explain_winget_code."""
    wg = winget_path()
    if wg is None:
        return False, ("winget не найден. Установите «App Installer» из Microsoft "
                       "Store — он входит в состав Windows 10/11.")
    if not valid_winget_id(pkg.winget_id):
        return False, f"Недопустимый id пакета: {pkg.winget_id!r}"

    args = [wg, action, "--id", pkg.winget_id, "--exact",
            "--accept-source-agreements", "--disable-interactivity",
            "--source", "winget"]
    if action in ("install", "upgrade"):
        args += ["--accept-package-agreements"]
    if action in ("install", "upgrade") and scope in ("user", "machine"):
        args += ["--scope", scope]
    log.info("winget %s %s (scope=%s)", action, pkg.winget_id, scope)
    try:
        out = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=1800, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        log.warning("winget %s %s: таймаут", action, pkg.winget_id)
        return False, "Операция не уложилась в 30 минут и была прервана."
    except Exception as e:
        log.warning("winget %s %s: %s", action, pkg.winget_id, e)
        return False, str(e)

    text = ((out.stdout or "") + "\n" + (out.stderr or "")).strip()
    ok = out.returncode in _WINGET_OK_CODES
    if ok:
        log.info("winget %s %s: успех (код %s)", action, pkg.winget_id, out.returncode)
        if repair:
            note = repair_path_for(pkg)
            if note:
                text = (text + "\n" + note).strip()
                log.info("%s", note)
    else:
        reason = explain_winget_code(out.returncode, text)
        log.warning("winget %s %s: код %s — %s", action, pkg.winget_id,
                    out.returncode, reason)
        text = (f"{reason}\n\n{text}").strip() if text else reason
    return ok, text


def _winget_package_roots() -> list[Path]:
    """Каталоги, куда winget распаковывает архивные пакеты (user и machine)."""
    roots = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "Microsoft" / "WinGet" / "Packages")
    pf = os.environ.get("ProgramFiles")
    if pf:
        roots.append(Path(pf) / "WinGet" / "Packages")
    return [r for r in roots if r.is_dir()]


def find_bin_dir_for(pkg: Package, max_entries: int = 40000) -> str | None:
    """Найти каталог с probe-бинарём пакета среди распакованных winget-пакетов.

    Нужно для архивных сборок (WinLibs и т.п.), которые сами PATH не прописывают:
    winget кладёт их под `…\\WinGet\\Packages\\<id>…\\…\\bin`, но точный путь
    заранее неизвестен. Ищем `<probe>.exe`, предпочитая ветки, чьё имя содержит
    id пакета. Обход ограничен `max_entries`, чтобы не сканировать вечно."""
    wanted = {f"{e}.exe".lower() for e in pkg.probe}
    if not wanted:
        return None
    id_hint = pkg.winget_id.split(".")[0].lower()
    seen = 0
    for root in _winget_package_roots():
        # Сначала подкаталоги, где в имени встречается id пакета — так мы почти
        # сразу попадаем в нужную ветку и не обходим соседние пакеты.
        subdirs = sorted(
            (p for p in root.iterdir() if p.is_dir()),
            key=lambda p: id_hint not in p.name.lower())
        for sub in subdirs:
            for dirpath, _dirs, filenames in os.walk(sub):
                low = {f.lower() for f in filenames}
                if wanted & low:
                    return dirpath
                seen += len(filenames)
                if seen >= max_entries:
                    return None
    return None


def repair_path_for(pkg: Package) -> str:
    """Если probe-бинарь пакета не виден в PATH, дописать его каталог.

    Порядок: сначала явные `path_hints`, затем автопоиск среди распакованных
    winget-пакетов (`find_bin_dir_for`) — так архивные сборки вроде WinLibs
    (g++/gcc/gdb) становятся видны из терминала. Возвращает пояснение для
    лога/UI (пустая строка — ничего не делали). Если winget уже прописал PATH,
    probe виден и мы сразу выходим."""
    if package_installed(pkg):
        return ""
    candidates = list(pkg.path_hints)
    found = find_bin_dir_for(pkg)
    if found and found not in candidates:
        candidates.append(found)
    added = []
    for hint in candidates:
        if env_path.is_on_path(hint):
            continue
        ok, _msg = env_path.add_to_user_path(hint)
        if ok:
            added.append(hint)
    if added:
        return "PATH дополнен: " + "; ".join(added)
    return ""


# --- связь тулчейна с настройками VS Code (чтобы C++ реально заработал) ------

def _compiler_path(exe: str) -> str | None:
    """Полный путь к компилятору `exe` (например g++) — в PATH или на диске.
    Нужен, чтобы прописать его в C_Cpp.default.compilerPath."""
    p = which(exe)
    if p:
        return p
    for root in _disk_scan_roots():
        cand = Path(root) / f"{exe}.exe"
        if cand.exists():
            return str(cand)
    return None


def settings_for_toolchain(key: str) -> dict:
    """Рекомендованные ключи VS Code для установленного тулчейна — чтобы
    расширение сразу знало, где компилятор, и IntelliSense/сборка заработали
    без ручной правки. Пусто, если инструмент не найден (нечего прописывать).

    Пока осмысленно для C/C++: C_Cpp.default.compilerPath + разумные стандарты.
    Для остальных языков расширения находят тулчейн по PATH сами."""
    if key == "cpp":
        gpp = _compiler_path("g++") or _compiler_path("clang++")
        if not gpp:
            return {}
        return {
            "C_Cpp.default.compilerPath": gpp,
            "C_Cpp.default.cStandard": "c17",
            "C_Cpp.default.cppStandard": "c++20",
            "C_Cpp.default.intelliSenseMode": "windows-gcc-x64",
        }
    return {}


def configure_vscode_for(key: str, code_cli: str | None) -> tuple[bool, str]:
    """Прописать settings_for_toolchain(key) в settings.json пользователя VS Code
    (только недостающие ключи, с бэкапом — через settings_apply.apply_settings).
    Возвращает (успех, сообщение). Так после установки компилятора C++
    расширение сразу видит его без ручной настройки."""
    settings = settings_for_toolchain(key)
    if not settings:
        return False, "Нечего настраивать: инструмент не найден в PATH/на диске."
    from .vscode import vscode_user_settings_path
    from .settings_apply import apply_settings
    path = vscode_user_settings_path(code_cli)
    if path is None:
        return False, "Не удалось определить путь к settings.json VS Code."
    ok, msg = apply_settings(path, settings)
    log.info("configure_vscode_for(%s): %s", key, msg.replace("\n", " "))
    return ok, msg


# --- связь с автоопределением стека по папке проекта ------------------------

def toolchain_for_stack(stack_key: str) -> Toolchain | None:
    """Тулчейн, соответствующий ключу стека (совпадает по ключу)."""
    return TOOLCHAINS.get(stack_key)


def missing_toolchains_for(folder: str) -> list[str]:
    """Ключи тулчейнов, которые нужны проекту в `folder`, но не установлены.

    Пересекаем автоопределённые стеки (detect.detect_stacks) с каталогом
    тулчейнов и оставляем те, где не хватает ОБЯЗАТЕЛЬНЫХ пакетов. Это связывает
    «в проекте C++» с «компилятор не стоит — предложить поставить». Пустой список,
    если всё на месте или папка ни на что не указывает."""
    if not folder:
        return []
    from .detect import detect_stacks
    stacks = detect_stacks(folder, available=set(TOOLCHAINS))
    return [k for k in stacks if missing_required(k)]


# --- сводка (для CLI/selftest/UI) ------------------------------------------

def toolchain_summary() -> dict:
    """Короткая сводка по всем тулчейнам: сколько всего, сколько с полностью
    установленными обязательными пакетами, список недостающих ключей."""
    total = len(TOOLCHAINS)
    missing = [k for k in TOOLCHAINS if missing_required(k)]
    return {"total": total, "ready": total - len(missing),
            "missing": missing, "winget": winget_available()}
