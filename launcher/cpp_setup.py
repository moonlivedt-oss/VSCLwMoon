# -*- coding: utf-8 -*-
r"""Единая установка C++: компоненты по ролям -> план шагов -> выполнение.

Раньше C++ ставился россыпью: пять карточек тулчейнов, расширения — в другом
окне, путь к компилятору — третьей кнопкой. Здесь всё сведено в один список
компонентов, сгруппированных по тому, за что они отвечают: компилятор, сборка,
подсказки кода, отладка, анализ, библиотеки, настройка VS Code. Пользователь
отмечает нужное, модуль строит план шагов (winget, pacman, расширения, запись
настроек, порядок в PATH), учитывая уже установленное и зависимости
(clangd требует LLVM, библиотеки — MSYS2, vcpkg — git), и выполняет его.

Без GUI: окно (gui_cpp.py) только показывает список и гоняет `execute` в фоне.
Тексты компонентов даны на двух языках (title/what и *_en): это данные, а не
строки интерфейса, поэтому живут здесь, а не в таблице i18n.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from shutil import which

from . import cpp
from . import toolchains as tc

log = logging.getLogger("launcher")

EXT_CPPTOOLS = "ms-vscode.cpptools"
EXT_CLANGD = "llvm-vs-code-extensions.vscode-clangd"
EXT_CODELLDB = "vadimcn.vscode-lldb"
EXT_CMAKE = "ms-vscode.cmake-tools"


@dataclass(frozen=True)
class Group:
    key: str
    title: str
    title_en: str
    note: str
    note_en: str
    exclusive: bool = False  # один вариант из группы (радиокнопки)


@dataclass(frozen=True)
class Option:
    key: str
    group: str
    title: str
    title_en: str
    what: str
    what_en: str
    size_mb: int = 0
    admin: bool = False
    info_only: bool = False  # строка-статус без выбора (gdb входит в GCC)


GROUPS: tuple[Group, ...] = (
    Group(
        "compiler",
        "Компилятор",
        "Compiler",
        "Превращает код в программу. Нужен один: второй GCC в PATH только мешает.",
        "Turns code into a program. You need one: a second GCC on PATH only gets in the way.",
        exclusive=True,
    ),
    Group(
        "build",
        "Сборка",
        "Build",
        "Для проектов из многих файлов и библиотек. Одиночный файл собирается и без них.",
        "For multi-file projects and libraries. A single file builds without these.",
    ),
    Group(
        "intellisense",
        "Подсказки кода в VS Code",
        "Code intelligence in VS Code",
        "Автодополнение, переход к определению, ошибки прямо в редакторе. Выберите один движок.",
        "Completion, go-to-definition, errors right in the editor. Pick one engine.",
        exclusive=True,
    ),
    Group(
        "debug",
        "Отладка",
        "Debugging",
        "Точки останова и просмотр переменных в VS Code.",
        "Breakpoints and variable inspection in VS Code.",
    ),
    Group(
        "tools",
        "Анализ и пакеты",
        "Analysis and packages",
        "Необязательные помощники: поиск ошибок, ускорение сборки, менеджеры библиотек.",
        "Optional helpers: bug finding, faster builds, library managers.",
    ),
    Group(
        "libs",
        "Библиотеки (MSYS2)",
        "Libraries (MSYS2)",
        "Ставятся через pacman в MSYS2 и сразу видны компилятору. Доступно с компилятором MSYS2.",
        "Installed with pacman into MSYS2, visible to the compiler right away. Needs the MSYS2 compiler.",
    ),
    Group(
        "setup",
        "Настройка",
        "Setup",
        "Что сделать после установки, чтобы всё заработало без ручной правки.",
        "What to do after installing so that everything works without manual edits.",
    ),
)

OPTIONS: tuple[Option, ...] = (
    Option(
        "keep",
        "compiler",
        "Другой установленный",
        "Another installed one",
        "Ничего не качать, взять компилятор, который уже стоит, но не относится к "
        "вариантам ниже (LLVM Clang, Code::Blocks и т.п.).",
        "Download nothing, use a compiler you already have that is not one of the "
        "options below (LLVM Clang, Code::Blocks etc.).",
    ),
    Option(
        "mingw",
        "compiler",
        "MinGW-w64 (WinLibs)",
        "MinGW-w64 (WinLibs)",
        "GCC, GDB и make одним архивом. Самый простой вариант: учёба, олимпиады, "
        "небольшие проекты.",
        "GCC, GDB and make in one archive. The simplest choice: learning, contests, "
        "small projects.",
        size_mb=300,
    ),
    Option(
        "msys2",
        "compiler",
        "MSYS2 UCRT64",
        "MSYS2 UCRT64",
        "GCC с пакетным менеджером pacman: SFML, SDL, Boost и др. ставятся одной "
        "командой. Для проектов с библиотеками. Вместе с CMake, Ninja и GDB.",
        "GCC with the pacman package manager: SFML, SDL, Boost etc. in one command. "
        "For projects with libraries. Comes with CMake, Ninja and GDB.",
        size_mb=1200,
    ),
    Option(
        "msvc",
        "compiler",
        "MSVC Build Tools",
        "MSVC Build Tools",
        "Компилятор Microsoft (cl.exe) и Windows SDK. Нужен для vcpkg по умолчанию и "
        "библиотек под Visual Studio. Большой, ставится с правами администратора.",
        "Microsoft compiler (cl.exe) and Windows SDK. Default for vcpkg and "
        "Visual Studio libraries. Large, needs administrator rights.",
        size_mb=4500,
        admin=True,
    ),
    Option(
        "cmake",
        "build",
        "CMake + CMake Tools",
        "CMake + CMake Tools",
        "Стандартная система сборки C++ и расширение VS Code к ней: конфигурация, "
        "сборка и запуск целей кнопками. Нужна для vcpkg.",
        "The standard C++ build system and its VS Code extension: configure, build "
        "and run targets with buttons. Required for vcpkg.",
        size_mb=60,
    ),
    Option(
        "ninja",
        "build",
        "Ninja",
        "Ninja",
        "Быстрый сборщик: CMake собирает через него быстрее, чем через make.",
        "A fast build runner: CMake builds faster through it than through make.",
        size_mb=1,
    ),
    Option(
        "cpptools",
        "intellisense",
        "C/C++ от Microsoft (cpptools)",
        "Microsoft C/C++ (cpptools)",
        "Привычный вариант: подсказки и отладчик gdb/MSVC в одном расширении. "
        "Тяжелее: от 300 МБ до 2 ГБ памяти на больших проектах.",
        "The familiar choice: code intelligence plus the gdb/MSVC debugger in one "
        "extension. Heavier: 300 MB to 2 GB of memory on large projects.",
        size_mb=70,
    ),
    Option(
        "clangd",
        "intellisense",
        "clangd (LLVM)",
        "clangd (LLVM)",
        "Легче и точнее на современном C++, сразу показывает замечания clang-tidy. "
        "Ставит LLVM, если его нет или он устарел. Для отладки добавьте CodeLLDB.",
        "Lighter and more precise on modern C++, shows clang-tidy findings. Installs "
        "LLVM if it is missing or outdated. Add CodeLLDB for debugging.",
        size_mb=450,
    ),
    Option(
        "gdb",
        "debug",
        "GDB",
        "GDB",
        "Отладчик GCC. Входит в MinGW и MSYS2, отдельно не ставится. Работает через "
        "расширение cpptools.",
        "The GCC debugger. Comes with MinGW and MSYS2, not installed separately. "
        "Works through the cpptools extension.",
        info_only=True,
    ),
    Option(
        "codelldb",
        "debug",
        "CodeLLDB",
        "CodeLLDB",
        "Отладчик на LLDB: для Clang и режима clangd, не требует cpptools. Нужен также для Rust.",
        "LLDB-based debugger: for Clang and clangd mode, does not need cpptools. "
        "Also used for Rust.",
        size_mb=40,
    ),
    Option(
        "cppcheck",
        "tools",
        "Cppcheck",
        "Cppcheck",
        "Статический анализ: утечки, выход за границы массива, неинициализированные переменные.",
        "Static analysis: leaks, out-of-bounds access, uninitialized variables.",
        size_mb=30,
    ),
    Option(
        "ccache",
        "tools",
        "ccache",
        "ccache",
        "Кэш компиляции: повторная сборка большого проекта в разы быстрее.",
        "Compilation cache: rebuilding a large project is several times faster.",
        size_mb=5,
    ),
    Option(
        "doxygen",
        "tools",
        "Doxygen",
        "Doxygen",
        "Документация из комментариев /** */ в HTML.",
        "HTML documentation from /** */ comments.",
        size_mb=50,
    ),
    Option(
        "vcpkg",
        "tools",
        "vcpkg",
        "vcpkg",
        "Менеджер библиотек от Microsoft (fmt, SDL, Boost…) для CMake-проектов. "
        "Ставится в папку пользователя, нужен git (поставится сам).",
        "Microsoft's library manager (fmt, SDL, Boost…) for CMake projects. Goes "
        "into your user folder, needs git (installed automatically).",
        size_mb=400,
    ),
    Option(
        "conan",
        "tools",
        "Conan",
        "Conan",
        "Альтернативный менеджер пакетов C/C++.",
        "An alternative C/C++ package manager.",
        size_mb=50,
    ),
    Option(
        "configure",
        "setup",
        "Прописать компилятор в VS Code",
        "Point VS Code at the compiler",
        "Путь к компилятору, стандарт C++20 и путь к clangd в settings.json: подсказки "
        "сразу найдут заголовки. Прочие ваши настройки не трогаются, есть бэкап.",
        "Compiler path, C++20 standard and clangd path in settings.json: code "
        "intelligence finds headers right away. Other settings are untouched, a "
        "backup is made.",
    ),
    Option(
        "path",
        "setup",
        "Сделать выбранный компилятор основным в PATH",
        "Make the chosen compiler first on PATH",
        "В PATH несколько GCC: выбранный встанет первым, остальные уедут в конец. "
        "Ничего не удаляется, старый PATH сохраняется в файл.",
        "Several GCCs on PATH: the chosen one goes first, the others move to the end. "
        "Nothing is removed, the old PATH is saved to a file.",
    ),
)

# Библиотеки MSYS2 с пояснениями.
LIBS: tuple[tuple[str, str, str], ...] = (
    ("sfml", "SFML — 2D-графика, звук, окна", "SFML — 2D graphics, audio, windows"),
    ("sdl2", "SDL2 — окна, ввод, звук для игр", "SDL2 — windows, input, audio for games"),
    ("raylib", "raylib — простые игры и визуализация", "raylib — simple games and visuals"),
    ("glfw", "GLFW — окно и контекст OpenGL", "GLFW — window and OpenGL context"),
    ("fmt", "fmt — форматирование строк", "fmt — string formatting"),
    ("boost", "Boost — большой набор библиотек", "Boost — a large set of libraries"),
    ("gtest", "GoogleTest — модульные тесты", "GoogleTest — unit tests"),
    ("catch2", "Catch2 — модульные тесты", "Catch2 — unit tests"),
    ("qt6", "Qt 6 — оконные приложения", "Qt 6 — desktop GUI apps"),
    ("opencv", "OpenCV — компьютерное зрение", "OpenCV — computer vision"),
)

OPT_BY_KEY = {o.key: o for o in OPTIONS}

# Готовые наборы: ключи отмечаемых компонентов (компилятор задаётся отдельно).
PRESETS: dict[str, dict] = {
    "study": {
        "title": "Учёба и олимпиады",
        "title_en": "Learning and contests",
        "note": "MinGW, подсказки cpptools, отладка gdb. Минимум загрузки.",
        "note_en": "MinGW, cpptools hints, gdb debugging. Smallest download.",
        "compiler": "mingw",
        "intellisense": "cpptools",
        "checked": {"configure", "path"},
    },
    "projects": {
        "title": "Проекты на CMake",
        "title_en": "CMake projects",
        "note": "MSYS2 с библиотеками, CMake, Ninja, cpptools.",
        "note_en": "MSYS2 with libraries, CMake, Ninja, cpptools.",
        "compiler": "msys2",
        "intellisense": "cpptools",
        "checked": {"cmake", "ninja", "configure", "path"},
    },
    "pro": {
        "title": "Лёгкий и современный",
        "title_en": "Light and modern",
        "note": "MSYS2, CMake, Ninja, clangd вместо cpptools, CodeLLDB, cppcheck, ccache.",
        "note_en": "MSYS2, CMake, Ninja, clangd instead of cpptools, CodeLLDB, cppcheck, ccache.",
        "compiler": "msys2",
        "intellisense": "clangd",
        "checked": {"cmake", "ninja", "codelldb", "cppcheck", "ccache", "configure", "path"},
    },
}


def text(obj, attr: str, lang: str) -> str:
    """Текст компонента/группы/набора на языке интерфейса."""
    if isinstance(obj, dict):
        return str(obj.get(f"{attr}_en") if lang == "en" else obj.get(attr) or "")
    return getattr(obj, f"{attr}_en") if lang == "en" else getattr(obj, attr)


# --- состояние машины -------------------------------------------------------------


def scan_state(code_cli: str | None) -> dict:
    """Что уже стоит: компиляторы, инструменты, расширения VS Code, MSYS2, vcpkg.
    Медленно (запускает компиляторы), поэтому зовётся в фоне."""
    comps = cpp.find_compilers()
    exts: set[str] = set()
    if code_cli:
        try:
            from .vscode import load_installed

            exts = {e.lower() for e in load_installed(code_cli)[0]}
        except Exception:
            exts = set()
    clangd = which("clangd")
    clangd_ver = ()
    if clangd:
        clangd_ver = cpp.parse_version(cpp._out(cpp._run([clangd, "--version"], timeout=15)))
    msys = cpp.msys2_status()
    libs = {}
    if msys["bin"]:
        libs = {k: cpp._msys2_lib_present(msys["bin"], k) for k, *_ in LIBS}
    return {
        "compilers": [c.to_dict() for c in comps],
        "tools": cpp.tool_locations(),
        "gcc_dirs": cpp.gcc_dirs(),
        "exts": sorted(exts),
        "msys2": msys,
        "msys2_libs": libs,
        "vcpkg": cpp.vcpkg_root() or "",
        "clangd": clangd or "",
        "clangd_version": list(clangd_ver),
        "git": which("git") or "",
        "code_cli": code_cli or "",
    }


def primary_of(comps: list[dict]) -> dict | None:
    """Компилятор «по умолчанию» из списка: активный GCC, затем любой активный."""
    for want in ("gcc", None):
        for c in comps:
            if c.get("active") and (want is None or c["kind"] == want):
                return c
    return comps[0] if comps else None


def other_compilers(comps: list[dict]) -> list[dict]:
    """Установленные компиляторы, которые не покрыты вариантами MinGW/MSYS2/MSVC
    (LLVM Clang, Code::Blocks, Strawberry…) — для варианта «Другой установленный»."""
    return [c for c in comps if compiler_choice_of(c) == "keep"]


def compiler_choice_of(c: dict | None) -> str:
    """Какой вариант группы «Компилятор» соответствует найденному компилятору."""
    if not c:
        return "keep"
    if c["origin"] == "WinLibs":
        return "mingw"
    if c["origin"].startswith("MSYS2") and c["kind"] == "gcc":
        return "msys2"
    if c["kind"] == "msvc":
        return "msvc"
    return "keep"


def _has_ext(state: dict, ext_id: str) -> bool:
    return ext_id.lower() in set(state.get("exts", []))


def _clangd_ok(state: dict) -> bool:
    v = state.get("clangd_version") or []
    return bool(state.get("clangd")) and bool(v) and v[0] >= cpp.MIN_CLANG


def status(key: str, state: dict) -> tuple[bool, str]:
    """(установлено, короткая подпись) для строки компонента."""
    comps = state.get("compilers", [])
    tools = state.get("tools", {})
    if key == "keep":
        others = other_compilers(comps)
        return (True, str(len(others))) if others else (False, "")
    if key == "mingw":
        c = next((c for c in comps if c["origin"] == "WinLibs"), None)
        return (True, c["version"]) if c else (False, "")
    if key == "msys2":
        m = state.get("msys2", {})
        if m.get("has_gcc"):
            c = next((c for c in comps if c["origin"].startswith("MSYS2")), None)
            return True, c["version"] if c else ""
        return False, (cpp._t("MSYS2 есть, компилятора нет", "MSYS2 without a compiler") if m.get("root") else "")
    if key == "msvc":
        c = next((c for c in comps if c["kind"] == "msvc"), None)
        return (True, c["version"]) if c else (False, "")
    if key == "cmake":
        return bool(tools.get("cmake")) and _has_ext(state, EXT_CMAKE), ""
    if key == "ninja":
        return bool(tools.get("ninja")), ""
    if key == "cpptools":
        return _has_ext(state, EXT_CPPTOOLS), ""
    if key == "clangd":
        ok = _has_ext(state, EXT_CLANGD) and _clangd_ok(state)
        v = state.get("clangd_version") or []
        return ok, (".".join(map(str, v)) if v else "")
    if key == "gdb":
        return bool(tools.get("gdb")), ""
    if key == "codelldb":
        return _has_ext(state, EXT_CODELLDB), ""
    if key in ("cppcheck", "ccache", "doxygen", "conan"):
        return bool(tools.get(key) or which(key)), ""
    if key == "vcpkg":
        return bool(state.get("vcpkg")), state.get("vcpkg", "")
    if key.startswith("lib:"):
        return bool(state.get("msys2_libs", {}).get(key[4:])), ""
    return False, ""


def default_selection(state: dict) -> dict:
    """Разумный выбор по умолчанию: ничего лишнего поверх установленного."""
    comps = state.get("compilers", [])
    installed_engine = (
        "clangd"
        if _has_ext(state, EXT_CLANGD) and not _has_ext(state, EXT_CPPTOOLS)
        else "cpptools"
    )
    checked = {
        k
        for k in ("cmake", "ninja", "codelldb", "cppcheck", "ccache", "doxygen", "vcpkg", "conan")
        if status(k, state)[0]
    }
    checked.add("configure")
    if len(state.get("gcc_dirs", [])) > 1:
        checked.add("path")
    active = primary_of(comps)
    return {
        "compiler": compiler_choice_of(active) if comps else "mingw",
        "keep_path": (
            active["path"]
            if active and compiler_choice_of(active) == "keep"
            else (other_compilers(comps) or [{"path": ""}])[0]["path"]
        ),
        "intellisense": installed_engine,
        "checked": checked,
        "libs": set(),
    }


def apply_preset(sel: dict, preset_key: str, state: dict) -> dict:
    """Набор поверх текущего выбора; уже установленное из набора не качается."""
    p = PRESETS[preset_key]
    out = dict(sel)
    comp = p["compiler"]  # уже установлен — план просто ничего не будет качать
    out["compiler"] = comp
    out["intellisense"] = p["intellisense"]
    out["checked"] = set(p["checked"]) | {
        k for k in sel.get("checked", set()) if status(k, state)[0]
    }
    out["libs"] = set(sel.get("libs", set()))
    return out


def libs_available(sel: dict, state: dict) -> bool:
    """Библиотеки MSYS2 доступны, если выбран MSYS2 или активный компилятор из MSYS2."""
    if sel.get("compiler") == "msys2":
        return True
    if sel.get("compiler") == "keep":
        return "msys64" in (sel.get("keep_path") or "").lower() and bool(
            state.get("msys2", {}).get("root")
        )
    return False


# --- план --------------------------------------------------------------------------


@dataclass
class Step:
    kind: str  # winget | winget_upgrade | pacman | vcpkg | ext | configure | path
    title: str
    title_en: str
    ref: str = ""  # toolchain/winget_id, ext id
    args: tuple = ()
    admin: bool = False
    size_mb: int = 0
    extra: dict = field(default_factory=dict)


def _pkg(toolchain: str, winget_id: str):
    chain = tc.get_toolchain(toolchain)
    if not chain:
        return None
    return next((p for p in chain.packages if p.winget_id == winget_id), None)


def _winget(toolchain, winget_id, title, title_en, size=0, admin=False, upgrade=False):
    return Step(
        "winget_upgrade" if upgrade else "winget",
        title,
        title_en,
        ref=f"{toolchain}/{winget_id}",
        admin=admin,
        size_mb=size,
    )


def _ext(ext_id: str, title: str, title_en: str, size=0) -> Step:
    return Step("ext", title, title_en, ref=ext_id, size_mb=size)


def build_plan(sel: dict, state: dict) -> list[Step]:
    """Шаги установки по выбору. Уже установленное пропускается; зависимости
    добавляются сами. Порядок: winget -> pacman -> vcpkg -> расширения ->
    настройка -> PATH."""
    steps: list[Step] = []
    ext_steps: list[Step] = []
    tools = state.get("tools", {})
    checked = set(sel.get("checked", set()))
    comp = sel.get("compiler", "keep")
    msys = state.get("msys2", {})

    # Компилятор.
    if comp == "mingw" and not status("mingw", state)[0]:
        steps.append(
            _winget(
                "cpp",
                "BrechtSanders.WinLibs.POSIX.UCRT",
                "MinGW-w64 (GCC, GDB, make)",
                "MinGW-w64 (GCC, GDB, make)",
                300,
            )
        )
    elif comp == "msys2" and not status("msys2", state)[0]:
        if msys.get("root"):
            steps.append(
                Step(
                    "pacman",
                    "MSYS2: GCC, CMake, Ninja, GDB (pacman)",
                    "MSYS2: GCC, CMake, Ninja, GDB (pacman)",
                    args=cpp.MSYS2_BASE,
                    size_mb=900,
                )
            )
        else:
            steps.append(
                _winget(
                    "cpp_msys2",
                    "MSYS2.MSYS2",
                    "MSYS2 + GCC, CMake, Ninja, GDB",
                    "MSYS2 + GCC, CMake, Ninja, GDB",
                    1200,
                )
            )
    elif comp == "msvc" and not status("msvc", state)[0]:
        steps.append(
            _winget(
                "cpp_msvc",
                "Microsoft.VisualStudio.BuildTools",
                "MSVC Build Tools (нужны права администратора)",
                "MSVC Build Tools (administrator rights needed)",
                4500,
                admin=True,
            )
        )
    msys_brings_build = comp == "msys2"

    # Сборка.
    if "cmake" in checked:
        if not tools.get("cmake") and not msys_brings_build:
            steps.append(_winget("cpp", "Kitware.CMake", "CMake", "CMake", 50))
        if not _has_ext(state, EXT_CMAKE):
            ext_steps.append(_ext(EXT_CMAKE, "Расширение CMake Tools", "CMake Tools extension", 10))
    if "ninja" in checked and not tools.get("ninja") and not msys_brings_build:
        steps.append(_winget("cpp", "Ninja-build.Ninja", "Ninja", "Ninja", 1))

    # Подсказки.
    engine = sel.get("intellisense", "cpptools")
    if engine == "cpptools" and not _has_ext(state, EXT_CPPTOOLS):
        ext_steps.append(
            _ext(EXT_CPPTOOLS, "Расширение C/C++ (cpptools)", "C/C++ extension (cpptools)", 70)
        )
    if engine == "clangd":
        if not _clangd_ok(state):
            steps.append(
                _winget(
                    "cpp_llvm",
                    "LLVM.LLVM",
                    "LLVM (clangd, clang-tidy, clang-format)",
                    "LLVM (clangd, clang-tidy, clang-format)",
                    450,
                    upgrade=bool(state.get("clangd")),
                )
            )
        if not _has_ext(state, EXT_CLANGD):
            ext_steps.append(_ext(EXT_CLANGD, "Расширение clangd", "clangd extension", 2))
    # Отладка.
    if "codelldb" in checked and not _has_ext(state, EXT_CODELLDB):
        ext_steps.append(_ext(EXT_CODELLDB, "Расширение CodeLLDB", "CodeLLDB extension", 40))

    # Инструменты.
    simple = {
        "cppcheck": ("Cppcheck.Cppcheck", "Cppcheck", 30),
        "ccache": ("Ccache.Ccache", "ccache", 5),
        "doxygen": ("DimitriVanHeesch.Doxygen", "Doxygen", 50),
        "conan": ("JFrog.Conan", "Conan", 50),
    }
    for key, (wid, title, size) in simple.items():
        if key in checked and not status(key, state)[0]:
            steps.append(_winget("cpp_tools", wid, title, title, size))
    if "vcpkg" in checked and not state.get("vcpkg"):
        if not state.get("git"):
            steps.append(
                _winget("git", "Git.Git", "Git (нужен vcpkg)", "Git (needed by vcpkg)", 300)
            )
        steps.append(Step("vcpkg", "vcpkg (клон и сборка)", "vcpkg (clone and build)", size_mb=400))

    # Библиотеки.
    libs = sorted(k for k in sel.get("libs", set()) if not state.get("msys2_libs", {}).get(k))
    if libs and libs_available(sel, state):
        steps.append(
            Step(
                "pacman",
                "Библиотеки MSYS2: " + ", ".join(libs),
                "MSYS2 libraries: " + ", ".join(libs),
                args=tuple(cpp.MSYS2_LIBS[k] for k in libs if k in cpp.MSYS2_LIBS),
                size_mb=80 * len(libs),
            )
        )

    steps += ext_steps
    if "configure" in checked:
        steps.append(
            Step(
                "configure",
                "Прописать компилятор в settings.json VS Code",
                "Write the compiler into VS Code settings.json",
                extra={"compiler": comp, "keep_path": sel.get("keep_path", ""), "engine": engine},
            )
        )
    if "path" in checked and comp != "msvc":
        steps.append(
            Step(
                "path",
                "Сделать компилятор основным в PATH",
                "Make the compiler first on PATH",
                extra={"compiler": comp, "keep_path": sel.get("keep_path", "")},
            )
        )
    return steps


def plan_summary(steps: list[Step]) -> dict:
    installs = [
        s for s in steps if s.kind in ("winget", "winget_upgrade", "pacman", "vcpkg", "ext")
    ]
    return {
        "count": len(installs),
        "size_mb": sum(s.size_mb for s in steps),
        "admin": any(s.admin for s in steps),
        "only_setup": not installs and bool(steps),
    }


# --- выполнение ---------------------------------------------------------------------


def resolve_compiler(compiler: str, keep_path: str) -> cpp.Compiler | None:
    """Компилятор, который выбран (после установки его путь уже известен)."""
    comps = cpp.find_compilers()
    if compiler == "keep":
        return next(
            (c for c in comps if keep_path and cpp._norm(c.path) == cpp._norm(keep_path)),
            cpp.active_compiler(comps),
        )
    if compiler == "mingw":
        return next((c for c in comps if c.origin == "WinLibs"), None)
    if compiler == "msys2":
        return next((c for c in comps if c.origin.startswith("MSYS2") and c.kind == "gcc"), None)
    if compiler == "msvc":
        return next((c for c in comps if c.kind == "msvc"), None)
    return None


_STR_KEY_TMPL = r'("{key}"\s*:\s*)"(?:[^"\\]|\\.)*"'


def _set_string_keys(path: Path, values: dict[str, str]) -> list[str]:
    """Заменить значения уже существующих строковых ключей в settings.json (с
    комментариями тоже: правка текстом). Возвращает изменённые ключи."""
    if not path.is_file():
        return []
    raw = path.read_text(encoding="utf-8-sig")
    changed = []
    for key, value in values.items():
        rx = re.compile(_STR_KEY_TMPL.format(key=re.escape(key)))
        rendered = json.dumps(value, ensure_ascii=False)
        new = rx.sub(lambda m, r=rendered: m.group(1) + r, raw, count=1)
        if new != raw:
            raw = new
            changed.append(key)
    if changed:
        path.write_text(raw, encoding="utf-8")
    return changed


def configure_vscode(compiler: str, keep_path: str, engine: str, code_cli) -> tuple[bool, str]:
    """Прописать выбранный компилятор (и clangd) в пользовательский settings.json.
    Недостающие ключи добавляются, путь к компилятору обновляется, даже если был
    задан: пользователь явно выбрал компилятор."""
    from .settings_apply import apply_settings
    from .vscode import vscode_user_settings_path

    c = resolve_compiler(compiler, keep_path)
    if c is None:
        return False, "Компилятор не найден после установки."
    path = vscode_user_settings_path(code_cli)
    if path is None:
        return False, "Не удалось определить путь к settings.json VS Code."
    mode = {"gcc": "windows-gcc-x64", "clang": "windows-clang-x64", "msvc": "windows-msvc-x64"}[
        c.kind
    ]
    values = {
        "C_Cpp.default.compilerPath": c.path,
        "C_Cpp.default.intelliSenseMode": mode,
        "C_Cpp.default.cppStandard": "c++20",
        "C_Cpp.default.cStandard": "c17",
    }
    if engine == "clangd":
        clangd = which("clangd")
        if clangd:
            values["clangd.path"] = clangd
    strings = {
        k: v
        for k, v in values.items()
        if k in ("C_Cpp.default.compilerPath", "C_Cpp.default.intelliSenseMode", "clangd.path")
    }
    try:
        changed = _set_string_keys(path, strings)
    except OSError as e:
        return False, str(e)
    ok, msg = apply_settings(path, values)
    if changed:
        msg = (msg + f"\nОбновлено: {', '.join(changed)}").strip()
        ok = True
    return ok, f"{c.kind} {c.version}: {c.path}\n{msg}"


def make_primary(compiler: str, keep_path: str) -> tuple[bool, str]:
    c = resolve_compiler(compiler, keep_path)
    if c is None or c.kind == "msvc":
        return False, "Нет GCC/Clang для PATH."
    plan = cpp.path_fix_plan(c.bin_dir, "demote")
    if not (plan["user_changed"] or plan["machine_changed"]):
        return True, "Уже первый в PATH."
    return cpp.apply_path_fix(plan)


def execute(step: Step, code_cli: str | None) -> tuple[bool, str]:
    """Выполнить один шаг плана. (успех, сообщение)."""
    try:
        if step.kind in ("winget", "winget_upgrade"):
            key, wid = step.ref.split("/", 1)
            pkg = _pkg(key, wid)
            if pkg is None:
                return False, f"Пакет {wid} не найден в каталоге."
            if step.kind == "winget_upgrade":
                return tc.upgrade_package(pkg)
            if step.admin:
                return tc.install_package_elevated(pkg, scope="machine")
            ok, msg = tc.install_package(pkg)
            if not ok and "прав администратора" in msg:  # пакет требует machine-scope
                return tc.install_package_elevated(pkg, scope="machine")
            return ok, msg
        if step.kind == "pacman":
            roots = cpp.msys2_roots()
            if not roots:
                return False, "MSYS2 не найден."
            return cpp.msys2_pacman(roots[0], "ucrt64", tuple(step.args))
        if step.kind == "vcpkg":
            return cpp.install_vcpkg()
        if step.kind == "ext":
            if not code_cli:
                return False, "Не найден CLI VS Code."
            from .vscode import install_extension

            return install_extension(code_cli, step.ref)
        if step.kind == "configure":
            e = step.extra
            return configure_vscode(e["compiler"], e["keep_path"], e["engine"], code_cli)
        if step.kind == "path":
            e = step.extra
            return make_primary(e["compiler"], e["keep_path"])
    except Exception as e:  # noqa: BLE001 — шаг не должен ронять весь план
        log.exception("Шаг C++ %s", step.title)
        return False, str(e)
    return False, f"Неизвестный шаг: {step.kind}"
