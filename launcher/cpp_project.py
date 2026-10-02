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
from dataclasses import dataclass, replace
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
RUN_PLAIN_TASK = "C++: собрать и запустить"

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
    has_cpptools: bool = False  # расширение стоит, даже если подсказки даёт clangd
    debugger: str = "auto"
    std: str = "c++20"
    build: str = "single"
    olympiad: bool = False
    clang_target: str = ""  # напр. x86_64-w64-mingw32 для Clang без MSVC
    vcpkg: bool = False
    lint_files: bool = True  # .clang-format и .clang-tidy
    name: str = "app"
    # В пути к проекту есть не-ASCII символы (C:\Users\Дмитрий\…). Выставляет
    # plan_files по папке.
    non_ascii_path: bool = False
    # Отлаживать во внешнем окне консоли: под gdb ввод (cin) в панели VS Code не
    # работает, программа «зависает» на чтении.
    external_console: bool = False

    def resolved_debugger(self) -> str:
        if self.debugger != "auto":
            return self.debugger
        if self.compiler_kind == "msvc":
            return "cppvsdbg"
        if self.compiler_kind == "clang":
            return "lldb"
        if self.non_ascii_path:
            # gdb под cppdbg получает путь к программе в UTF-8, а читает его в
            # кодировке Windows: на русских буквах в пути отвечает «No such file or
            # directory», и F5 не работает вовсе. CodeLLDB пути в Юникоде открывает.
            return "lldb"
        if self.engine == "clangd" and not self.has_cpptools:
            # cppdbg живёт в cpptools; если расширения нет, берём CodeLLDB — он
            # самодостаточен и читает DWARF от GCC тоже.
            return "lldb"
        # GCC отлаживаем родным gdb: cpptools установлен, а выключенный
        # IntelliSense отладчику не мешает.
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


def tool_path_env(o: ProjectOptions) -> str:
    """PATH для сборки и запуска: каталог выбранного компилятора впереди.

    g++ из MSYS2, вызванный по полному пути, не находит DLL своего же cc1plus
    (libgmp, libisl…), если каталог bin не в PATH, и молча завершается с кодом 1.
    А собранная программа при запуске берёт первую libstdc++-6.dll из PATH —
    чужую, если там раньше стоит другой GCC, — и падает с 0xC0000139. С этим
    PATH проект работает одинаково при любом порядке каталогов в системе.
    Для MSVC окружение поднимает vcvars, PATH не трогаем."""
    if not o.compiler_path or o.compiler_kind == "msvc":
        return ""
    return str(Path(o.compiler_path).parent) + ";${env:PATH}"


def _with_env(options: dict, o: ProjectOptions) -> dict:
    path = tool_path_env(o)
    if path:
        options["env"] = {"PATH": path}
    return options


def _msvc_std(std: str) -> str:
    return "/std:c++latest" if std == "c++23" else f"/std:{std}"


# --- содержимое файлов -------------------------------------------------------


def _matcher(base: str) -> dict:
    """Разбор ошибок gcc с путями относительно `base`."""
    m = json.loads(json.dumps(GCC_MATCHER))
    m["fileLocation"] = ["autoDetect", base]
    return m


def tasks_json(o: ProjectOptions) -> dict:
    exe = "${fileDirname}\\${fileBasenameNoExtension}.exe"
    # Компилятору и программе пути передаются ОТНОСИТЕЛЬНО папки файла (cwd).
    # Новые сборки MSYS2 (ld) не принимают аргументы с русскими буквами: при
    # проекте в C:\Users\Дмитрий\… сборка падала с «cannot open output file
    # C:\Users\: Illegal byte sequence». Имя файла при этом должно быть латиницей.
    rel_exe = "${fileBasenameNoExtension}.exe"
    tasks: list[dict] = []
    if o.build == "cmake":
        tasks += [
            {
                "label": "CMake: configure (debug)",
                "type": "shell",
                "command": "cmake --preset debug",
                "options": _with_env({}, o),
                "problemMatcher": [],
            },
            {
                "label": "CMake: build (debug)",
                "type": "shell",
                "command": "cmake --build --preset debug",
                "options": _with_env({}, o),
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
            "args": [*_flags(o), "${fileBasename}", "-o", rel_exe],
            "options": _with_env({"cwd": "${fileDirname}"}, o),
            "group": {"kind": "build", "isDefault": True},
            "problemMatcher": _matcher("${fileDirname}"),
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
                    f'call "{comp}" {flags} "${{fileBasename}}" -o "{rel_exe}" && '
                    f'".\\{rel_exe}" < "${{workspaceFolder}}\\input.txt"'
                ),
                "options": _with_env(
                    {
                        "cwd": "${fileDirname}",
                        "shell": {"executable": "cmd.exe", "args": ["/d", "/c"]},
                    },
                    o,
                ),
                "group": "test",
                "problemMatcher": _matcher("${fileDirname}"),
            }
        )
    # Запуск без отладчика: собрать и выполнить в терминале. Работает, даже когда
    # отладка не настроена или отладчик не справился с путём.
    tasks.append(
        {
            "label": RUN_PLAIN_TASK,
            "type": "shell",
            "command": f'call ".\\{rel_exe}"',
            "dependsOn": BUILD_TASK,
            "options": _with_env(
                {
                    "cwd": "${fileDirname}",
                    "shell": {"executable": "cmd.exe", "args": ["/d", "/c"]},
                },
                o,
            ),
            "group": "test",
            # Терминал получает фокус: программа сразу готова читать ввод.
            "presentation": {"reveal": "always", "focus": True, "clear": True, "panel": "shared"},
            "problemMatcher": [],
        }
    )
    return {"version": "2.0.0", "tasks": tasks}


def launch_json(o: ProjectOptions) -> dict:
    dbg = o.resolved_debugger()
    if o.build == "cmake":
        program = "${command:cmake.launchTargetPath}"
        pre = None
        cwd = "${workspaceFolder}"
    else:
        program = "${fileDirname}\\${fileBasenameNoExtension}.exe"
        pre = BUILD_TASK
        # Одиночный файл запускается из своей папки: рядом лежат input.txt и т.п.
        cwd = "${fileDirname}"
    cfg: dict
    if dbg == "gdb":
        cfg = {
            "name": "C++: отладка (gdb)",
            "type": "cppdbg",
            "request": "launch",
            "program": program,
            "args": [],
            "cwd": cwd,
            "externalConsole": bool(o.external_console),
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
            "cwd": cwd,
        }
    else:
        cfg = {
            "name": "C++: отладка (MSVC)",
            "type": "cppvsdbg",
            "request": "launch",
            "program": program,
            "args": [],
            "cwd": cwd,
            "console": "integratedTerminal",
        }
    path = tool_path_env(o)
    if path and dbg == "gdb":
        cfg["environment"] = [{"name": "PATH", "value": path}]
    elif path and dbg == "lldb":
        cfg["env"] = {"PATH": path}
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
    path_env = tool_path_env(o)
    if path_env:
        # Встроенный терминал проекта: `g++` — тот же компилятор, что в задачах.
        s["terminal.integrated.env.windows"] = {"PATH": path_env}
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
    # Сборка не удалась — показать ошибки, а не запускать под отладчиком старый exe.
    s["debug.onTaskErrors"] = "showErrors"
    # Code Runner: запуск в терминале, иначе программа не может читать ввод.
    s["code-runner.runInTerminal"] = True
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
  -performance-avoid-endl,
  -modernize-use-nodiscard,
  -modernize-use-std-print,
  -bugprone-easily-swappable-parameters,
  -readability-braces-around-statements,
  -readability-isolate-declaration,
  -readability-function-cognitive-complexity,
  -readability-else-after-return,
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


def has_non_ascii(folder: str) -> bool:
    """Есть ли в полном пути к папке символы вне ASCII (русские буквы и т.п.)."""
    try:
        return not str(Path(folder).resolve()).isascii()
    except OSError:
        return not str(folder).isascii()


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=4) + "\n"


def plan_files(folder: str, o: ProjectOptions, starter: bool = False) -> list[dict]:
    """Что будет записано: [{'path', 'content', 'exists', 'merge'}].

    merge=True — это .vscode/settings.json: в него дописываются только
    недостающие ключи (settings_apply), content здесь — словарь."""
    root = Path(folder)
    if has_non_ascii(folder):
        o = replace(o, non_ascii_path=True)
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
    files.append((".gitignore", GITIGNORE))
    if starter:
        # В папке нет исходников: кладём пример, чтобы сборку и отладку было на чём
        # проверить сразу. Существующие файлы не трогаются (exists).
        if o.build == "cmake":
            safe = re.sub(r"[^A-Za-z0-9_]+", "_", root.name).strip("_") or "app"
            files.insert(0, ("CMakeLists.txt", cmakelists(replace(o, name=safe))))
            files.insert(1, ("src/main.cpp", MAIN_FMT if o.vcpkg else MAIN_SIMPLE))
        else:
            files.insert(0, ("main.cpp", MAIN_OLYMPIAD if o.olympiad else MAIN_SIMPLE))
            if o.olympiad:
                files.insert(1, ("input.txt", "3\n1 2 3\n"))
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


# --- здоровье проекта: что в .vscode уже не соответствует машине -----------------
# Настройки проекта ломаются не в момент создания, а позже: компилятор удалили
# или переставили, проект скопировали с другого компьютера, папку перенесли в
# «C:\Users\Дмитрий». Снаружи это выглядит как «F5 не работает». Здесь такие
# случаи находятся по самим файлам, а fix_project пересоздаёт сборку и отладку
# под текущий компилятор (старые файлы уходят в .bak).


def _read_json(path: Path):
    from .detect import _loads_jsonc

    try:
        return _loads_jsonc(path.read_text(encoding="utf-8-sig")) if path.is_file() else None
    except OSError:
        return None


def _exe_missing(value) -> bool:
    """Путь к программе задан явно (с каталогом), а файла нет. Имя без каталога
    («gdb») ищется в PATH."""
    if not isinstance(value, str) or not value.strip() or "${" in value:
        return False
    v = value.strip().strip('"')
    if "\\" in v or "/" in v or ":" in v:
        return not Path(v).is_file()
    return which(v) is None


# Проблемы, которые чинит fix_project (остальным нужна установка расширения).
FIXABLE = frozenset(
    {"gdb_unicode", "missing_debugger", "missing_task", "missing_compiler", "no_path_env", "abs_args"}
)
ABS_PATH_RUNNERS = {"danielpinto8zz6.c-cpp-compile-run": "C/C++ Compile Run"}
_DEBUG_EXT = {
    "cppdbg": ("ms-vscode.cpptools", "C/C++ (cpptools)"),
    "cppvsdbg": ("ms-vscode.cpptools", "C/C++ (cpptools)"),
    "lldb": ("vadimcn.vscode-lldb", "CodeLLDB"),
}


def project_problems(folder: str, exts=None) -> list[dict]:
    """Что в настройках проекта не заработает на этой машине: [{'key', 'text'}].
    Пустой список — всё в порядке или проект ещё не настроен. exts — установленные
    расширения VS Code: с ними проверяется и наличие расширения отладчика."""
    from .cpp import _t

    root = Path(folder)
    vs = root / ".vscode"
    out: dict[str, str] = {}
    try:
        if not vs.is_dir():
            return []
    except OSError:
        return []
    launch = _read_json(vs / "launch.json")
    tasks = _read_json(vs / "tasks.json")
    props = _read_json(vs / "c_cpp_properties.json")
    tlist = tasks.get("tasks") if isinstance(tasks, dict) else None
    tlist = [t for t in tlist if isinstance(t, dict)] if isinstance(tlist, list) else []
    labels = {t.get("label") for t in tlist}
    confs = launch.get("configurations") if isinstance(launch, dict) else None
    for c in confs if isinstance(confs, list) else ():
        if not isinstance(c, dict):
            continue
        if c.get("type") == "cppdbg":
            if has_non_ascii(folder) and str(c.get("MIMode", "gdb")).lower() == "gdb":
                out["gdb_unicode"] = _t(
                    "Отладка настроена через gdb, а в пути к папке есть русские буквы: "
                    "gdb такой путь не открывает, F5 ответит «No such file or directory».",
                    "Debugging uses gdb, but the folder path has non-English letters: gdb "
                    "cannot open such a path, F5 answers 'No such file or directory'.",
                )
            if _exe_missing(c.get("miDebuggerPath")):
                out["missing_debugger"] = _t(
                    "Отладчик из launch.json не найден: {p}.",
                    "The debugger from launch.json was not found: {p}.",
                ).format(p=c.get("miDebuggerPath"))
        need = _DEBUG_EXT.get(str(c.get("type") or "").lower())
        if exts is not None and need and need[0] not in {str(e).lower() for e in exts}:
            out["no_debug_ext"] = _t(
                "Отладка настроена на расширение {n}, а оно не установлено — F5 не "
                "сработает. Поставьте его на странице «C / C++» → «Установка».",
                "Debugging is set up for the {n} extension, which is not installed — F5 "
                "will not work. Install it on 'C / C++' → 'Install'.",
            ).format(n=need[1])
        pre = c.get("preLaunchTask")
        if isinstance(pre, str) and pre and "${" not in pre and pre not in labels:
            out["missing_task"] = _t(
                "launch.json перед запуском зовёт задачу «{t}», а в tasks.json её нет.",
                "launch.json runs the task '{t}' before launch, but tasks.json has no such task.",
            ).format(t=pre)
    # Расширения, которые сами собирают файл и передают g++ ПОЛНЫЙ путь: в папке
    # с русскими буквами новые MSYS2 на нём падают, как бы ни были настроены задачи.
    ext_set = {str(e).lower() for e in (exts or ())}
    if has_non_ascii(folder):
        for ext_id, title in ABS_PATH_RUNNERS.items():
            if ext_id in ext_set:
                out["abs_runner"] = _t(
                    "Расширение «{n}» собирает файл само и передаёт g++ полный путь с "
                    "русскими буквами — сборка падает («Illegal byte sequence»). При запуске "
                    "VS Code из лаунчера оно выключается для этой папки автоматически. "
                    "Собирайте Ctrl+Shift+B, отлаживайте F5.",
                    "The '{n}' extension builds the file itself and passes g++ the full path "
                    "with non-English letters — the build fails ('Illegal byte sequence'). "
                    "When VS Code is started from the launcher it is turned off for this "
                    "folder automatically. Build with Ctrl+Shift+B, debug with F5.",
                ).format(n=title)
    for t in tlist:
        args = t.get("args")
        if (
            t.get("type") == "process"
            and isinstance(args, list)
            and "${file}" in args
            and has_non_ascii(folder)
        ):
            out["abs_args"] = _t(
                "Задача сборки передаёт компилятору полный путь к файлу, а в нём русские "
                "буквы: новые сборки MSYS2 на нём падают («cannot open output file … "
                "Illegal byte sequence»).",
                "The build task passes the full file path to the compiler, and it has "
                "non-English letters: recent MSYS2 builds fail on it ('cannot open output "
                "file … Illegal byte sequence').",
            )
        cmd = t.get("command")
        if t.get("type") == "process" and _exe_missing(cmd):
            out["missing_compiler"] = _t(
                "Компилятор из tasks.json не найден: {p}.",
                "The compiler from tasks.json was not found: {p}.",
            ).format(p=cmd)
        elif (
            t.get("label") == BUILD_TASK
            and t.get("type") == "process"
            and isinstance(cmd, str)
            and ("\\" in cmd or "/" in cmd)
            and not (t.get("options") or {}).get("env")
        ):
            out["no_path_env"] = _t(
                "Задача сборки не добавляет каталог компилятора в PATH: g++ из MSYS2 "
                "может молча завершиться с ошибкой, а программа — не найти свои DLL.",
                "The build task does not add the compiler folder to PATH: g++ from MSYS2 "
                "may fail silently and the program may not find its DLLs.",
            )
    pconfs = props.get("configurations") if isinstance(props, dict) else None
    for c in pconfs if isinstance(pconfs, list) else ():
        if isinstance(c, dict) and _exe_missing(c.get("compilerPath")):
            out["missing_compiler"] = _t(
                "Компилятор из c_cpp_properties.json не найден: {p}.",
                "The compiler from c_cpp_properties.json was not found: {p}.",
            ).format(p=c.get("compilerPath"))
    return [{"key": k, "text": v} for k, v in out.items()]


def auto_options(folder: str, exts=()) -> ProjectOptions | None:
    """Настройки проекта без вопросов: активный компилятор, движок подсказок и
    система сборки — по тому, что уже лежит в папке. None — компилятора нет."""
    from . import cpp
    from .detect import cpp_project_hints

    comps = cpp.find_compilers()
    comp = cpp.active_compiler(comps)
    if comp is None:
        return None
    root = Path(folder)
    settings = _read_json(root / ".vscode" / "settings.json")
    clangd = (root / ".clangd").is_file() or (
        isinstance(settings, dict) and settings.get("C_Cpp.intelliSenseEngine") == "disabled"
    )
    o = options_from_compiler(comp, engine="clangd" if clangd else "cpptools")
    o.has_cpptools = "ms-vscode.cpptools" in {str(e).lower() for e in exts}
    hints = cpp_project_hints(folder)
    o.build = "cmake" if hints.get("build") == "cmake" else "single"
    o.vcpkg = bool(hints.get("vcpkg"))
    o.name = root.name or "app"
    old = ""
    try:
        old = (root / ".vscode" / "tasks.json").read_text(encoding="utf-8-sig")
    except OSError:
        pass
    m = re.search(r"-std=(c\+\+\d\d)", old)
    if m and m.group(1) in STANDARDS:
        o.std = m.group(1)  # стандарт, который человек уже выбрал
    o.olympiad = RUN_TASK in old
    return o


FIX_FILES = (".vscode/tasks.json", ".vscode/launch.json", ".vscode/c_cpp_properties.json")


def fix_project(folder: str, o: ProjectOptions) -> list[str]:
    """Пересоздать сборку и отладку под текущий компилятор. Прежние файлы
    сохраняются рядом как .bak-<время>. Возвращает отчёт."""
    plan = [i for i in plan_files(folder, o) if i["path"] in FIX_FILES]
    return apply_plan(folder, plan, overwrite={i["path"] for i in plan})


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
    ".gitignore": "чтобы git не подхватывал exe и папку сборки",
    "main.cpp": "пример программы: папка пустая, а запускать что-то надо",
    "src/main.cpp": "пример программы для CMake-проекта",
    "input.txt": "входные данные для олимпиадной задачи",
    "CMakeLists.txt": "описание сборки CMake",
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
    ".gitignore": "keeps exe files and the build folder out of git",
    "main.cpp": "a sample program: the folder is empty and you need something to run",
    "src/main.cpp": "a sample program for the CMake project",
    "input.txt": "input data for the contest task",
    "CMakeLists.txt": "CMake build description",
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
