# -*- coding: utf-8 -*-
"""Автоопределение стеков по содержимому папки проекта.

Чистая логика без GUI и без обращения к VS Code. Берём путь к проекту,
бегло сканируем файлы (с обрезкой тяжёлых каталогов и потолком по числу
записей, чтобы не подвесить окно на гигантском репозитории) и возвращаем
ключи стеков, которые в этом проекте, скорее всего, нужны.

Дальше GUI пересекает результат с реально установленными расширениями —
поэтому здесь можно детектировать щедро: стек без установленных плагинов
всё равно не будет предложен.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Точное имя файла в корне/подпапке -> ключ стека.
FILENAME_MARKERS: dict[str, str] = {
    "requirements.txt": "python",
    "pyproject.toml": "python",
    "pipfile": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "poetry.lock": "python",
    "environment.yml": "python",
    "package.json": "web",
    "tsconfig.json": "web",
    "jsconfig.json": "web",
    "go.mod": "go",
    "go.sum": "go",
    "cargo.toml": "rust",
    "cargo.lock": "rust",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "java",
    "settings.gradle": "java",
    "dockerfile": "docker",
    "docker-compose.yml": "docker",
    "docker-compose.yaml": "docker",
    "compose.yml": "docker",
    "compose.yaml": "docker",
    ".dockerignore": "docker",
    "composer.json": "php",
    "gemfile": "ruby",
    "gemfile.lock": "ruby",
    "pubspec.yaml": "dart",
    "pubspec.yml": "dart",
    "package.swift": "swift",
    "cmakelists.txt": "cpp_cmake",
    "cmakepresets.json": "cpp_cmake",
    "meson.build": "cpp_cmake",
    "vcpkg.json": "cpp",
    "conanfile.txt": "cpp",
    "conanfile.py": "cpp",
    ".clangd": "cpp_clangd",
    "svelte.config.js": "svelte_astro",
    "azure-pipelines.yml": "azure",
    "azure-pipelines.yaml": "azure",
}

# Расширение файла (в нижнем регистре, с точкой) -> ключ стека.
SUFFIX_MARKERS: dict[str, str] = {
    ".py": "python",
    ".ts": "web",
    ".tsx": "web",
    ".jsx": "web",
    ".vue": "web",
    ".cs": "dotnet",
    ".csproj": "dotnet",
    ".sln": "dotnet",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "java",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".c": "cpp",
    ".h": "cpp",
    ".ixx": "cpp",
    ".cppm": "cpp",
    ".asm": "cpp_extras",
    ".nasm": "cpp_extras",
    ".php": "php",
    ".rb": "ruby",
    ".lua": "lua",
    ".sql": "sql",
    ".db": "sqlite",
    ".sqlite": "sqlite",
    ".sqlite3": "sqlite",
    ".csv": "sqlite",
    ".dart": "dart",
    ".jl": "julia",
    ".swift": "swift",
    ".md": "markdown",
    ".markdown": "markdown",
    ".ps1": "powershell",
    ".psm1": "powershell",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".tf": "terraform",
    ".tfvars": "terraform",
    ".ipynb": "data",
    ".svelte": "svelte_astro",
    ".astro": "svelte_astro",
}

# Имя файла начинается с... -> ключ стека (для config-файлов с суффиксом версии).
PREFIX_MARKERS: tuple[tuple[str, str], ...] = (
    ("astro.config.", "svelte_astro"),
    ("vite.config.", "web"),
    ("webpack.config.", "web"),
    ("next.config.", "web"),
)

# Makefile сам по себе не говорит о C++ (им собирают и Go, и документацию):
# стек Makefile Tools предлагаем, только если в проекте есть C/C++ и нет CMake.
MAKEFILE_NAMES: frozenset[str] = frozenset({"makefile", "gnumakefile"})

# Стеки, которые означают C/C++-проект сами по себе.
CPP_IMPLYING: frozenset[str] = frozenset({"cpp_cmake", "cpp_clangd"})

C_SOURCE_SUFFIXES: frozenset[str] = frozenset(
    {".cpp", ".cxx", ".cc", ".c", ".h", ".hpp", ".hh", ".ixx", ".cppm"}
)

# Библиотека по #include -> ключ (для подсказок pacman/vcpkg и стека extras).
INCLUDE_LIBS: tuple[tuple[str, str], ...] = (
    ("SFML/", "sfml"),
    ("SDL3/", "sdl3"),
    ("SDL2/", "sdl2"),
    ("SDL.h", "sdl2"),
    ("boost/", "boost"),
    ("GLFW/", "glfw"),
    ("fmt/", "fmt"),
    ("gtest/", "gtest"),
    ("catch2/", "catch2"),
    ("doctest", "catch2"),
    ("Q", "qt6"),  # <QApplication>, <QtWidgets/...> — проверяется отдельно
    ("opencv2/", "opencv"),
    ("raylib.h", "raylib"),
)

# Библиотеки, при которых полезен стек «C++: дополнительно» (SFML-сниппеты,
# панель тестов для GoogleTest/Catch2).
EXTRAS_LIBS: frozenset[str] = frozenset({"sfml", "gtest", "catch2"})

# Каталоги, которые не открывают ничего нового, но раздувают обход.
PRUNE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        "dist",
        "build",
        "out",
        "target",
        ".next",
        ".nuxt",
        "vendor",
        "bin",
        "obj",
        ".idea",
        ".vscode",
        "coverage",
        ".mypy_cache",
        ".pytest_cache",
        ".gradle",
        ".tox",
        "site-packages",
        ".terraform",
    }
)


def detect_stacks(folder, available: set[str] | None = None, max_entries: int = 4000) -> set[str]:
    """Ключи стеков, подходящих проекту в `folder`.

    Обход прунит тяжёлые каталоги и останавливается после `max_entries`
    просмотренных записей — на большом репозитории детект остаётся быстрым
    и не блокирует окно. `available`, если задан, ограничивает результат
    существующими в карте ключами (чужой categories.json может не иметь
    какого-то стека). Несуществующий путь -> пустое множество."""
    try:
        root = Path(folder)
    except Exception:
        return set()
    if not folder or not root.exists() or not root.is_dir():
        return set()

    found: set[str] = set()
    seen = 0
    has_makefile = False
    c_sources: list[Path] = []
    for _dirpath, dirnames, filenames in os.walk(root):
        # `.git` в списке каталогов — верный признак git-проекта; отмечаем
        # до того, как выкинем его из обхода.
        if ".git" in dirnames:
            found.add("git")
        dirnames[:] = [d for d in dirnames if d.lower() not in PRUNE_DIRS]
        for name in filenames:
            seen += 1
            low = name.lower()
            if low in MAKEFILE_NAMES:
                has_makefile = True
            suffix = os.path.splitext(low)[1]
            if suffix in C_SOURCE_SUFFIXES and len(c_sources) < 40:
                c_sources.append(Path(_dirpath) / name)
            key = FILENAME_MARKERS.get(low)
            if key:
                found.add(key)
            else:
                suf = os.path.splitext(low)[1]
                key = SUFFIX_MARKERS.get(suf)
                if key:
                    found.add(key)
                else:
                    for pref, pkey in PREFIX_MARKERS:
                        if low.startswith(pref):
                            found.add(pkey)
                            break
        if seen >= max_entries:
            break

    # Документация — это тексты: вместе с Markdown предлагаем орфографию.
    if "markdown" in found:
        found.add("spell")

    _cpp_rules(found, has_makefile, c_sources)

    if available is not None:
        found &= available
    return found


def _cpp_rules(found: set[str], has_makefile: bool, c_sources: list[Path]) -> None:
    """C/C++: из маркеров вывести нужные части стека.

    CMake/.clangd означают C++ сам по себе; движок подсказок — clangd, если в
    проекте есть .clangd, иначе cpptools; Makefile Tools — только для проекта на
    Makefile без CMake; «дополнительно» — при SFML/тестовых фреймворках."""
    if found & CPP_IMPLYING:
        found.add("cpp")
    if "cpp" not in found:
        return
    if "cpp_clangd" not in found:
        found.add("cpp_cpptools")
    if has_makefile and "cpp_cmake" not in found:
        found.add("cpp_make")
    if scan_includes(c_sources) & EXTRAS_LIBS:
        found.add("cpp_extras")


_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.M)


def scan_includes(files: list[Path], max_bytes: int = 16384) -> set[str]:
    """Ключи библиотек по строкам #include в первых КБ исходников."""
    libs: set[str] = set()
    for f in files:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                text = fh.read(max_bytes)
        except OSError:
            continue
        for inc in _INCLUDE_RE.findall(text):
            for pref, lib in INCLUDE_LIBS:
                if lib == "qt6":
                    if re.match(r"^Qt[A-Z]\w*/|^Q[A-Z]\w+$", inc):
                        libs.add("qt6")
                elif inc.startswith(pref) or inc == pref:
                    libs.add(lib)
    return libs


def cpp_project_hints(folder, max_entries: int = 4000) -> dict:
    """Что за C/C++-проект в папке: система сборки, менеджер пакетов, есть ли
    настройки VS Code и под какие библиотеки. Для подсказок в окне и доктора.

    {'is_cpp', 'build': cmake|meson|make|none, 'vcpkg', 'conan',
     'has_vscode_cfg', 'has_clangd_cfg', 'has_compile_commands', 'libs', 'asm'}"""
    out = {
        "is_cpp": False,
        "build": "none",
        "vcpkg": False,
        "conan": False,
        "has_vscode_cfg": False,
        "has_clangd_cfg": False,
        "has_compile_commands": False,
        "libs": [],
        "asm": False,
    }
    try:
        root = Path(folder)
        if not folder or not root.is_dir():
            return out
    except Exception:
        return out
    vs = root / ".vscode"
    out["has_vscode_cfg"] = any(
        (vs / n).is_file() for n in ("tasks.json", "launch.json", "c_cpp_properties.json")
    )
    out["has_clangd_cfg"] = (root / ".clangd").is_file()
    out["has_compile_commands"] = (root / "compile_commands.json").is_file()
    names: set[str] = set()
    c_sources: list[Path] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in PRUNE_DIRS]
        for name in filenames:
            seen += 1
            low = name.lower()
            names.add(low)
            suf = os.path.splitext(low)[1]
            if suf in C_SOURCE_SUFFIXES and len(c_sources) < 40:
                c_sources.append(Path(dirpath) / name)
            if suf in (".asm", ".nasm", ".s"):
                out["asm"] = True
        if seen >= max_entries:
            break
    if "cmakelists.txt" in names:
        out["build"] = "cmake"
    elif "meson.build" in names:
        out["build"] = "meson"
    elif names & MAKEFILE_NAMES:
        out["build"] = "make"
    out["vcpkg"] = "vcpkg.json" in names
    out["conan"] = bool(names & {"conanfile.txt", "conanfile.py"})
    out["is_cpp"] = bool(c_sources) or out["build"] in ("cmake", "meson")
    out["libs"] = sorted(scan_includes(c_sources))
    return out


def _loads_jsonc(text: str):
    """Разобрать JSON, терпя JSONC (// и /* */ комментарии, хвостовые запятые) —
    файлы VS Code часто с комментариями. Сначала честный json, при неудаче —
    чистка комментариев и повтор. None, если не разобралось.

    Чистка идёт посимвольно с учётом строк: «//» внутри значения (URL,
    `cscript //Nologo` в настройках Code Runner) — не комментарий."""
    import json

    try:
        return json.loads(text)
    except Exception:
        pass
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i : j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif ch in "}]":
            # Хвостовая запятая: убрать последнюю запятую, если после неё
            # были только пробелы (комментарии уже вырезаны).
            k = len(out) - 1
            while k >= 0 and out[k].isspace():
                k -= 1
            if k >= 0 and out[k] == ",":
                del out[k]
            out.append(ch)
            i += 1
        else:
            out.append(ch)
            i += 1
    try:
        return json.loads("".join(out))
    except Exception:
        return None


def detect_recommended_stacks(folder, ext_index: dict[str, str]) -> set[str]:
    """Стеки, на которые указывают РЕКОМЕНДАЦИИ воркспейса из
    `<folder>/.vscode/extensions.json` (#3).

    VS Code позволяет проекту перечислить рекомендованные расширения; их id
    точно называют нужные инструменты. Мапим каждый рекомендованный id на его
    стек через ext_index и возвращаем множество ключей стеков. always_on и id,
    которых нет в карте, отбрасываются. Файла нет/битый — пустое множество."""
    if not folder or not ext_index:
        return set()
    try:
        f = Path(folder) / ".vscode" / "extensions.json"
        if not f.is_file():
            return set()
        data = _loads_jsonc(f.read_text(encoding="utf-8-sig"))
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    recs = data.get("recommendations")
    if not isinstance(recs, list):
        return set()
    keys: set[str] = set()
    for rec in recs:
        if not isinstance(rec, str):
            continue
        cat = ext_index.get(rec.lower())
        if cat and cat != "always_on":
            keys.add(cat)
    return keys
