# -*- coding: utf-8 -*-
r"""Настройка C++-проекта под выбранный компилятор: .vscode, CMake, clangd.

Глобальный settings.json знает только путь к компилятору. Чтобы проект
собирался, отлаживался и подсказывал код с первого открытия, нужны файлы в
самой папке: tasks.json (сборка), launch.json (отладчик в паре с
компилятором), c_cpp_properties.json или .clangd (IntelliSense), для CMake —
CMakePresets.json с тем же компилятором. Модуль строит эти файлы (`plan_files`)
и аккуратно записывает (`apply_plan`): существующие не трогает без явного
разрешения, а перезаписываемые сохраняет в .bak.

Выбор движка подсказок — проектный, а не глобальный: `C_Cpp.intelliSenseEngine:
disabled` в .vscode/settings.json отключает тяжёлый IntelliSense cpptools только
здесь, и clangd с cpptools не дерутся. Расширение cpptools при этом может
остаться включённым ради отладчика cppdbg — без своего IntelliSense оно лёгкое.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from shutil import which

ENGINES = ("cpptools", "clangd")
DEBUGGERS = ("auto", "gdb", "lldb", "cppvsdbg")
BUILDS = ("single", "cmake")
STANDARDS = ("c++17", "c++20", "c++23")
TEMPLATES = ("single", "olympiad", "cmake", "cmake_vcpkg")

BUILD_TASK = "C++: собрать текущий файл"
RUN_TASK = "C++: собрать -O2 и запустить на input.txt"

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

# Разбор ошибок gcc/clang без зависимости от $gcc из cpptools: в режиме clangd
# расширение может быть выключено, и именованный matcher пропал бы.
GCC_MATCHER = {
    "owner": "cpp",
    "fileLocation": ["autoDetect", "${workspaceFolder}"],
    "pattern": {
        "regexp": r"^(.*?):(\d+):(\d*):?\s+(?:fatal\s+)?(warning|error):\s+(.*)$",
        "file": 1,
        "line": 2,
        "column": 3,
        "severity": 4,
        "message": 5,
    },
}


@dataclass
class ProjectOptions:
    compiler_path: str = ""
    compiler_kind: str = "gcc"  # gcc | clang | msvc
    vcvars: str = ""  # MSVC: vcvars64.bat
    engine: str = "cpptools"
    debugger: str = "auto"
    std: str = "c++20"
    build: str = "single"
    olympiad: bool = False
    clang_target: str = ""  # напр. x86_64-w64-mingw32 для Clang без MSVC
    vcpkg: bool = False
    lint_files: bool = True  # .clang-format и .clang-tidy
    name: str = "app"

    def resolved_debugger(self) -> str:
        if self.debugger != "auto":
            return self.debugger
        if self.compiler_kind == "msvc":
            return "cppvsdbg"
        if self.compiler_kind == "clang" or self.engine == "clangd":
            # cppdbg живёт в cpptools; в режиме clangd его может не быть —
            # CodeLLDB самодостаточен и читает DWARF от GCC тоже.
            return "lldb"
        return "gdb"


def _fwd(p: str) -> str:
    """Путь с прямыми слэшами — так он читается в JSON без экранирования."""
    return (p or "").replace("\\", "/")


def sibling(compiler_path: str, exe: str) -> str:
    """Инструмент рядом с компилятором (gdb рядом с g++), иначе из PATH."""
    if compiler_path:
        cand = Path(compiler_path).parent / f"{exe}.exe"
        if cand.is_file():
            return str(cand)
    return which(exe) or ""


def intellisense_mode(o: ProjectOptions) -> str:
    return {
        "gcc": "windows-gcc-x64",
        "clang": "windows-clang-x64",
        "msvc": "windows-msvc-x64",
    }.get(o.compiler_kind, "windows-gcc-x64")


def _flags(o: ProjectOptions, optimize: bool = False) -> list[str]:
    f = [f"-std={o.std}", "-Wall", "-Wextra"]
    f += ["-O2", "-DLOCAL"] if optimize else ["-g", "-O0"]
    if o.compiler_kind == "clang" and o.clang_target:
        f.append(f"--target={o.clang_target}")
    return f


def _msvc_std(std: str) -> str:
    return "/std:c++latest" if std == "c++23" else f"/std:{std}"


# --- содержимое файлов -------------------------------------------------------


def tasks_json(o: ProjectOptions) -> dict:
    exe = "${fileDirname}\\${fileBasenameNoExtension}.exe"
    tasks: list[dict] = []
    if o.build == "cmake":
        tasks += [
            {
                "label": "CMake: configure (debug)",
                "type": "shell",
                "command": "cmake --preset debug",
                "problemMatcher": [],
            },
            {
                "label": "CMake: build (debug)",
                "type": "shell",
                "command": "cmake --build --preset debug",
                "group": {"kind": "build", "isDefault": True},
                "problemMatcher": "$msCompile" if o.compiler_kind == "msvc" else GCC_MATCHER,
            },
        ]
        return {"version": "2.0.0", "tasks": tasks}
    if o.compiler_kind == "msvc":
        cmd = (
            f'call "{o.vcvars}" >nul && cl /nologo {_msvc_std(o.std)} /EHsc /Zi /W4 '
            f'"${{file}}" /Fe:"{exe}"'
        )
        tasks.append(
            {
                "label": BUILD_TASK,
                "type": "shell",
                "command": cmd,
                "options": {
                    "cwd": "${fileDirname}",
                    "shell": {"executable": "cmd.exe", "args": ["/d", "/c"]},
                },
                "group": {"kind": "build", "isDefault": True},
                "problemMatcher": "$msCompile",
            }
        )
        return {"version": "2.0.0", "tasks": tasks}
    tasks.append(
        {
            "label": BUILD_TASK,
            "type": "process",
            "command": o.compiler_path or ("clang++" if o.compiler_kind == "clang" else "g++"),
            "args": [*_flags(o), "${file}", "-o", exe],
            "options": {"cwd": "${fileDirname}"},
            "group": {"kind": "build", "isDefault": True},
            "problemMatcher": GCC_MATCHER,
        }
    )
    if o.olympiad:
        comp = o.compiler_path or "g++"
        flags = " ".join(_flags(o, optimize=True))
        tasks.append(
            {
                "label": RUN_TASK,
                "type": "shell",
                "command": (
                    f'call "{comp}" {flags} "${{file}}" -o "{exe}" && '
                    f'"{exe}" < "${{workspaceFolder}}\\input.txt"'
                ),
                "options": {
                    "cwd": "${fileDirname}",
                    "shell": {"executable": "cmd.exe", "args": ["/d", "/c"]},
                },
                "group": "test",
                "problemMatcher": GCC_MATCHER,
            }
        )
    return {"version": "2.0.0", "tasks": tasks}


def launch_json(o: ProjectOptions) -> dict:
    dbg = o.resolved_debugger()
    if o.build == "cmake":
        program = "${command:cmake.launchTargetPath}"
        pre = None
    else:
        program = "${fileDirname}\\${fileBasenameNoExtension}.exe"
        pre = BUILD_TASK
    cfg: dict
    if dbg == "gdb":
        cfg = {
            "name": "C++: отладка (gdb)",
            "type": "cppdbg",
            "request": "launch",
            "program": program,
            "args": [],
            "cwd": "${workspaceFolder}",
            "externalConsole": False,
            "MIMode": "gdb",
            "miDebuggerPath": _fwd(sibling(o.compiler_path, "gdb")) or "gdb",
            "setupCommands": [
                {
                    "description": "pretty-printing",
                    "text": "-enable-pretty-printing",
                    "ignoreFailures": True,
                }
            ],
        }
    elif dbg == "lldb":
        cfg = {
            "name": "C++: отладка (CodeLLDB)",
            "type": "lldb",
            "request": "launch",
            "program": program,
            "args": [],
            "cwd": "${workspaceFolder}",
        }
    else:
        cfg = {
            "name": "C++: отладка (MSVC)",
            "type": "cppvsdbg",
            "request": "launch",
            "program": program,
            "args": [],
            "cwd": "${workspaceFolder}",
            "console": "integratedTerminal",
        }
    if pre:
        cfg["preLaunchTask"] = pre
    return {"version": "0.2.0", "configurations": [cfg]}


def c_cpp_properties(o: ProjectOptions) -> dict:
    conf = {
        "name": "Win32",
        "includePath": ["${workspaceFolder}/**"],
        "defines": ["_DEBUG", "UNICODE", "_UNICODE"],
        "cppStandard": o.std,
        "cStandard": "c17",
        "intelliSenseMode": intellisense_mode(o),
    }
    if o.compiler_path:
        conf["compilerPath"] = _fwd(o.compiler_path)
    if o.compiler_kind == "clang" and o.clang_target:
        conf["compilerArgs"] = [f"--target={o.clang_target}"]
    if o.build == "cmake":
        conf["configurationProvider"] = "ms-vscode.cmake-tools"
    return {"configurations": [conf], "version": 4}


def clangd_config(o: ProjectOptions) -> str:
    """.clangd для одиночных файлов (у CMake-проекта флаги берутся из
    compile_commands.json, но стандарт и цель лишними не будут)."""
    add = [f"-std={o.std}", "-Wall", "-Wextra"]
    if o.compiler_kind == "clang" and o.clang_target:
        add.append(f"--target={o.clang_target}")
    lines = ["CompileFlags:", "  Add: [" + ", ".join(add) + "]"]
    if o.compiler_path and o.compiler_kind != "msvc":
        lines.append(f"  Compiler: {_fwd(o.compiler_path)}")
    lines += [
        "Diagnostics:",
        "  UnusedIncludes: Strict",
        "  ClangTidy:",
        "    FastCheckFilter: Loose",
        "InlayHints:",
        "  Enabled: Yes",
        "  ParameterNames: Yes",
        "  DeducedTypes: Yes",
        "",
    ]
    return "\n".join(lines)


def workspace_settings(o: ProjectOptions) -> dict:
    """Ключи .vscode/settings.json: выбор движка подсказок для этого проекта."""
    s: dict = {"files.associations": {"*.ipp": "cpp", "*.tpp": "cpp"}}
    if o.engine == "clangd":
        clangd = which("clangd") or sibling(o.compiler_path, "clangd")
        args = [
            "--background-index",
            "--clang-tidy",
            "--header-insertion=never",
            "--completion-style=detailed",
        ]
        if o.compiler_path and o.compiler_kind != "msvc":
            # Без --query-driver clangd не спросит у g++ системные include-пути и
            # не найдёт <iostream> из MinGW.
            args.append(f"--query-driver={_fwd(str(Path(o.compiler_path).parent))}/*")
        s.update(
            {
                "C_Cpp.intelliSenseEngine": "disabled",
                "C_Cpp.autocomplete": "disabled",
                "C_Cpp.errorSquiggles": "disabled",
                "clangd.arguments": args,
            }
        )
        if clangd:
            s["clangd.path"] = _fwd(clangd)
        if o.build == "cmake":
            s["cmake.copyCompileCommands"] = "${workspaceFolder}/compile_commands.json"
    else:
        s.update(
            {
                "C_Cpp.intelliSenseEngine": "default",
                "C_Cpp.intelliSense.maxCachedProcesses": 2,
                "C_Cpp.intelliSense.maxMemory": 2048,
            }
        )
    if o.build == "cmake":
        s["cmake.configureOnOpen"] = True
        s["cmake.useCMakePresets"] = "always"
    if o.lint_files:
        s["[cpp]"] = {"editor.defaultFormatter": _formatter_for(o)}
    return s


def _formatter_for(o: ProjectOptions) -> str:
    return "llvm-vs-code-extensions.vscode-clangd" if o.engine == "clangd" else "ms-vscode.cpptools"


def extensions_json(o: ProjectOptions) -> dict:
    recs = []
    recs.append(
        "llvm-vs-code-extensions.vscode-clangd" if o.engine == "clangd" else "ms-vscode.cpptools"
    )
    dbg = o.resolved_debugger()
    if dbg == "lldb":
        recs.append("vadimcn.vscode-lldb")
    elif "ms-vscode.cpptools" not in recs:
        recs.append("ms-vscode.cpptools")  # cppdbg/cppvsdbg живут в cpptools
    if o.build == "cmake":
        recs.append("ms-vscode.cmake-tools")
    return {"recommendations": recs}


def cmake_generator(o: ProjectOptions) -> str:
    if o.compiler_kind == "msvc":
        low = (o.vcvars or "").lower()
        return "Visual Studio 18 2026" if "\\18\\" in low else "Visual Studio 17 2022"
    if which("ninja") or sibling(o.compiler_path, "ninja"):
        return "Ninja"
    return "MinGW Makefiles"


def vcpkg_triplet(o: ProjectOptions) -> str:
    if o.compiler_kind == "msvc" or (o.compiler_kind == "clang" and not o.clang_target):
        return "x64-windows"
    # Статическая сборка для MinGW: иначе рядом с exe нужно носить DLL библиотек.
    return "x64-mingw-static"


def cmake_presets(o: ProjectOptions) -> dict:
    gen = cmake_generator(o)
    multi = gen.startswith("Visual Studio")
    cache: dict = {"CMAKE_EXPORT_COMPILE_COMMANDS": "ON"}
    if o.compiler_kind != "msvc" and o.compiler_path:
        cache["CMAKE_CXX_COMPILER"] = _fwd(o.compiler_path)
        if o.compiler_kind == "clang" and o.clang_target:
            cache["CMAKE_CXX_COMPILER_TARGET"] = o.clang_target
            cache["CMAKE_C_COMPILER_TARGET"] = o.clang_target
    if o.vcpkg:
        trip = vcpkg_triplet(o)
        cache["VCPKG_TARGET_TRIPLET"] = trip
        cache["VCPKG_HOST_TRIPLET"] = trip
    base: dict = {
        "name": "base",
        "hidden": True,
        "generator": gen,
        "binaryDir": "${sourceDir}/build/${presetName}",
        "cacheVariables": cache,
    }
    if o.vcpkg:
        base["toolchainFile"] = "$env{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"
    configure = [base]
    build = []
    for name, typ in (("debug", "Debug"), ("release", "Release")):
        p: dict = {"name": name, "displayName": typ, "inherits": "base"}
        if not multi:
            p["cacheVariables"] = {"CMAKE_BUILD_TYPE": typ}
        configure.append(p)
        b: dict = {"name": name, "configurePreset": name}
        if multi:
            b["configuration"] = typ
        build.append(b)
    return {
        "version": 6,
        "cmakeMinimumRequired": {"major": 3, "minor": 25, "patch": 0},
        "configurePresets": configure,
        "buildPresets": build,
    }


def cmakelists(o: ProjectOptions) -> str:
    n = o.name
    lines = [
        "cmake_minimum_required(VERSION 3.25)",
        f"project({n} LANGUAGES CXX)",
        "",
        f"set(CMAKE_CXX_STANDARD {o.std.removeprefix('c++')})",
        "set(CMAKE_CXX_STANDARD_REQUIRED ON)",
        "set(CMAKE_CXX_EXTENSIONS OFF)",
        "set(CMAKE_EXPORT_COMPILE_COMMANDS ON)",
        "",
    ]
    if o.vcpkg:
        lines += ["find_package(fmt CONFIG REQUIRED)", ""]
    lines += [
        f"add_executable({n} src/main.cpp)",
        "",
        "if(MSVC)",
        f"    target_compile_options({n} PRIVATE /W4 /permissive-)",
        "else()",
        f"    target_compile_options({n} PRIVATE -Wall -Wextra -Wpedantic)",
        "endif()",
    ]
    if o.vcpkg:
        lines.append(f"target_link_libraries({n} PRIVATE fmt::fmt)")
    return "\n".join(lines) + "\n"


def vcpkg_manifest(o: ProjectOptions) -> dict:
    name = re.sub(r"[^a-z0-9]+", "-", o.name.lower()).strip("-") or "app"
    return {"name": name, "version-string": "0.1.0", "dependencies": ["fmt"]}


CLANG_FORMAT = """BasedOnStyle: LLVM
IndentWidth: 4
ColumnLimit: 100
AllowShortFunctionsOnASingleLine: Empty
AllowShortIfStatementsOnASingleLine: Never
PointerAlignment: Left
"""

CLANG_TIDY = """Checks: >
  -*,
  bugprone-*,
  performance-*,
  modernize-*,
  readability-*,
  -modernize-use-trailing-return-type,
  -readability-magic-numbers,
  -readability-identifier-length
WarningsAsErrors: ''
HeaderFilterRegex: '.*'
"""

GITIGNORE = """build/
.cache/
compile_commands.json
*.exe
*.o
*.obj
*.pdb
*.ilk
"""

MAIN_SIMPLE = """#include <iostream>
#include <string>
#include <vector>

int main() {
    std::vector<std::string> words{"Hello", "C++"};
    for (const auto& w : words) {
        std::cout << w << ' ';
    }
    std::cout << '\\n';
    return 0;
}
"""

MAIN_FMT = """#include <fmt/core.h>

int main() {
    fmt::print("Hello, {}!\\n", "vcpkg");
    return 0;
}
"""

MAIN_OLYMPIAD = """#include <bits/stdc++.h>
using namespace std;

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    int n;
    if (!(cin >> n)) return 0;
    long long sum = 0;
    for (int i = 0; i < n; ++i) {
        long long x;
        cin >> x;
        sum += x;
    }
    cout << sum << '\\n';
    return 0;
}
"""


# --- план и запись ------------------------------------------------------------


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=4) + "\n"


def plan_files(folder: str, o: ProjectOptions) -> list[dict]:
    """Что будет записано: [{'path', 'content', 'exists', 'merge'}].

    merge=True — это .vscode/settings.json: в него дописываются только
    недостающие ключи (settings_apply), content здесь — словарь."""
    root = Path(folder)
    files: list[tuple[str, object]] = [
        (".vscode/tasks.json", _dump(tasks_json(o))),
        (".vscode/launch.json", _dump(launch_json(o))),
        (".vscode/extensions.json", _dump(extensions_json(o))),
    ]
    if o.engine == "clangd":
        files.append((".clangd", clangd_config(o)))
    else:
        files.append((".vscode/c_cpp_properties.json", _dump(c_cpp_properties(o))))
    if o.build == "cmake":
        files.append(("CMakePresets.json", _dump(cmake_presets(o))))
        if o.vcpkg:
            files.append(("vcpkg.json", _dump(vcpkg_manifest(o))))
    if o.lint_files:
        files.append((".clang-format", CLANG_FORMAT))
        files.append((".clang-tidy", CLANG_TIDY))
    out = [
        {"path": rel, "content": content, "exists": (root / rel).exists(), "merge": False}
        for rel, content in files
    ]
    settings = workspace_settings(o)
    from .settings_apply import missing_settings

    sp = root / ".vscode" / "settings.json"
    missing = missing_settings(sp, settings)
    out.append(
        {
            "path": ".vscode/settings.json",
            "content": missing,
            "exists": sp.exists(),
            "merge": True,
            "skipped_keys": sorted(set(settings) - set(missing)),
        }
    )
    return out


def _backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = path.with_name(f"{path.name}.bak-{stamp}")
    dst.write_bytes(path.read_bytes())
    return dst


def apply_plan(
    folder: str, plan: list[dict], overwrite: set[str] | None = None, skip: set[str] | None = None
) -> list[str]:
    """Записать план. Существующие файлы — только если их путь в `overwrite`
    (старая версия уходит в .bak-<время>). `skip` — пути, снятые пользователем.
    Возвращает строки-отчёт для показа."""
    overwrite = overwrite or set()
    skip = skip or set()
    root = Path(folder)
    report: list[str] = []
    for item in plan:
        rel = item["path"]
        if rel in skip:
            continue
        dst = root / rel
        if item["merge"]:
            if not item["content"]:
                report.append(f"{rel}: все ключи уже заданы")
                continue
            from .settings_apply import apply_settings

            ok, msg = apply_settings(dst, item["content"])
            report.append(f"{rel}: {msg.splitlines()[0] if msg else ('ok' if ok else 'ошибка')}")
            if item.get("skipped_keys"):
                report.append(f"    не тронуты (уже заданы): {', '.join(item['skipped_keys'])}")
            continue
        if dst.exists():
            if rel not in overwrite:
                report.append(f"{rel}: уже есть, пропущен")
                continue
            bak = _backup(dst)
            report.append(f"{rel}: перезаписан (старый — {bak.name})")
        else:
            report.append(f"{rel}: создан")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(item["content"], encoding="utf-8")
    return report


def valid_project_name(name: str) -> bool:
    return bool(name) and bool(_NAME_RE.match(name)) and len(name) <= 64


def new_project(parent: str, name: str, template: str, o: ProjectOptions) -> tuple[bool, str]:
    """Создать проект из шаблона и настроить его. (успех, путь или ошибка).

    Шаблоны: single (один файл), olympiad (один файл + input.txt + сборка -O2
    с запуском на входе), cmake, cmake_vcpkg (CMake + vcpkg-манифест с fmt)."""
    if template not in TEMPLATES:
        return False, f"Неизвестный шаблон: {template}"
    if not valid_project_name(name):
        return False, "Имя проекта: латиница, цифры, _ . - (без пробелов), до 64 символов."
    base = Path(parent)
    if not base.is_dir():
        return False, f"Папка не существует: {parent}"
    root = base / name
    if root.exists() and any(root.iterdir()):
        return False, f"Папка уже существует и не пуста: {root}"
    o.name = name
    o.build = "cmake" if template.startswith("cmake") else "single"
    o.vcpkg = template == "cmake_vcpkg"
    o.olympiad = template == "olympiad"
    root.mkdir(parents=True, exist_ok=True)
    if o.build == "cmake":
        (root / "src").mkdir(exist_ok=True)
        (root / "src" / "main.cpp").write_text(
            MAIN_FMT if o.vcpkg else MAIN_SIMPLE, encoding="utf-8"
        )
        (root / "CMakeLists.txt").write_text(cmakelists(o), encoding="utf-8")
    elif o.olympiad:
        (root / "main.cpp").write_text(MAIN_OLYMPIAD, encoding="utf-8")
        (root / "input.txt").write_text("3\n1 2 3\n", encoding="utf-8")
    else:
        (root / "main.cpp").write_text(MAIN_SIMPLE, encoding="utf-8")
    (root / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    apply_plan(str(root), plan_files(str(root), o))
    return True, str(root)


def options_from_compiler(c, engine: str = "cpptools", **kw) -> ProjectOptions:
    """ProjectOptions из найденного компилятора (cpp.Compiler или его dict)."""
    get = c.get if isinstance(c, dict) else (lambda k, d=None: getattr(c, k, d))
    o = ProjectOptions(
        compiler_path=get("path", "") or "",
        compiler_kind=get("kind", "gcc") or "gcc",
        vcvars=get("vcvars", "") or "",
        engine=engine,
    )
    target = get("target", "") or ""
    if o.compiler_kind == "clang" and "msvc" in target and not _msvc_present():
        o.clang_target = "x86_64-w64-mingw32"
    for k, v in kw.items():
        setattr(o, k, v)
    return o


def _msvc_present() -> bool:
    try:
        from .cpp import find_msvc

        return bool(find_msvc())
    except Exception:
        return False


# Что делает каждый файл — для подписи в окне настройки проекта.
FILE_WHAT = {
    ".vscode/tasks.json": "сборка текущего файла или CMake-цели (Ctrl+Shift+B)",
    ".vscode/launch.json": "запуск под отладчиком (F5) в паре с компилятором",
    ".vscode/extensions.json": "рекомендованные расширения для этого проекта",
    ".vscode/c_cpp_properties.json": "компилятор и стандарт для подсказок cpptools",
    ".clangd": "флаги и компилятор для подсказок clangd",
    "CMakePresets.json": "пресеты Debug/Release с выбранным компилятором",
    "vcpkg.json": "манифест библиотек vcpkg",
    ".clang-format": "стиль форматирования кода",
    ".clang-tidy": "набор проверок clang-tidy",
    ".vscode/settings.json": "движок подсказок и настройки проекта",
}
FILE_WHAT_EN = {
    ".vscode/tasks.json": "build the current file or CMake target (Ctrl+Shift+B)",
    ".vscode/launch.json": "run under the debugger (F5), matched to the compiler",
    ".vscode/extensions.json": "recommended extensions for this project",
    ".vscode/c_cpp_properties.json": "compiler and standard for cpptools hints",
    ".clangd": "flags and compiler for clangd hints",
    "CMakePresets.json": "Debug/Release presets with the chosen compiler",
    "vcpkg.json": "vcpkg library manifest",
    ".clang-format": "code formatting style",
    ".clang-tidy": "clang-tidy check set",
    ".vscode/settings.json": "code-intelligence engine and project settings",
}

TEMPLATE_INFO = (
    (
        "single",
        "Один файл",
        "Single file",
        "main.cpp, сборка и отладка одной кнопкой.",
        "main.cpp, build and debug with one key.",
    ),
    (
        "olympiad",
        "Олимпиадная задача",
        "Contest problem",
        "main.cpp с быстрым вводом, input.txt и задача «собрать -O2 и запустить на input.txt».",
        "main.cpp with fast I/O, input.txt and a 'build -O2 and run on input.txt' task.",
    ),
    (
        "cmake",
        "CMake-приложение",
        "CMake application",
        "CMakeLists.txt, src/main.cpp, пресеты Debug/Release.",
        "CMakeLists.txt, src/main.cpp, Debug/Release presets.",
    ),
    (
        "cmake_vcpkg",
        "CMake + vcpkg",
        "CMake + vcpkg",
        "Как CMake-приложение, плюс vcpkg.json с библиотекой fmt для примера.",
        "Like the CMake app, plus vcpkg.json with the fmt library as an example.",
    ),
)
