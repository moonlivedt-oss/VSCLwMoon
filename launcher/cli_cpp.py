# -*- coding: utf-8 -*-
r"""CLI для C++: доктор, порядок в PATH, настройка и создание проектов.

    python vscode_launcher.py --cpp-doctor [--no-smoke] [--json]
    python vscode_launcher.py --cpp-fix-path D:\msys64\ucrt64\bin [--remove] [--yes]
    python vscode_launcher.py --cpp-setup D:\proj [--engine clangd] [--build cmake]
    python vscode_launcher.py --cpp-new D:\code\hello --template cmake
    python vscode_launcher.py --msys2 [sfml,fmt]
    python vscode_launcher.py --install-vcpkg

Отдельный модуль, чтобы cli.py не разрастался: тут только разбор флагов и
вывод, логика — в cpp.py и cpp_project.py.
"""

from __future__ import annotations

import json as _json
from pathlib import Path


def add_arguments(p) -> None:
    g = p.add_argument_group("C++")
    g.add_argument(
        "--cpp-doctor",
        action="store_true",
        help="доктор C++: компиляторы, смесь тулчейнов в PATH, пробная сборка C++20",
    )
    g.add_argument("--no-smoke", action="store_true", help="с --cpp-doctor: без пробной сборки")
    g.add_argument(
        "--cpp-fix-path",
        metavar="КАТАЛОГ_BIN",
        default="",
        help="сделать этот тулчейн GCC основным в PATH (предпросмотр; применить --yes)",
    )
    g.add_argument(
        "--remove",
        action="store_true",
        help="с --cpp-fix-path: убрать другие тулчейны GCC из PATH, а не опустить в конец",
    )
    g.add_argument(
        "--cpp-setup",
        metavar="ПАПКА",
        default="",
        help="сгенерировать .vscode (tasks/launch/IntelliSense) и CMakePresets под компилятор",
    )
    g.add_argument(
        "--cpp-new",
        metavar="ПУТЬ",
        default="",
        help="создать C++-проект (последняя часть пути — имя проекта)",
    )
    g.add_argument(
        "--template",
        choices=("single", "olympiad", "cmake", "cmake_vcpkg"),
        default="cmake",
        help="с --cpp-new: шаблон проекта",
    )
    g.add_argument(
        "--engine",
        choices=("cpptools", "clangd"),
        default="cpptools",
        help="движок подсказок C++ для проекта",
    )
    g.add_argument(
        "--build",
        choices=("single", "cmake"),
        default="",
        help="с --cpp-setup: одиночные файлы или CMake (по умолчанию — по проекту)",
    )
    g.add_argument("--std", choices=("c++17", "c++20", "c++23"), default="c++20")
    g.add_argument(
        "--compiler",
        metavar="ПУТЬ",
        default="",
        help="путь к g++/clang++/cl (по умолчанию — активный в PATH)",
    )
    g.add_argument(
        "--olympiad",
        action="store_true",
        help="с --cpp-setup: задача «собрать -O2 и запустить на input.txt»",
    )
    g.add_argument(
        "--overwrite",
        action="store_true",
        help="с --cpp-setup: перезаписать существующие файлы (старые — в .bak)",
    )
    g.add_argument(
        "--msys2",
        metavar="БИБЛИОТЕКИ",
        nargs="?",
        const="-",
        default=None,
        help="MSYS2: поставить GCC/CMake/Ninja/gdb через pacman (+ библиотеки: sfml,fmt…)",
    )
    g.add_argument(
        "--install-vcpkg",
        action="store_true",
        help="клонировать и собрать vcpkg, прописать VCPKG_ROOT и PATH",
    )


def dispatch(args) -> int | None:
    """Выполнить C++-команду, если она задана. None — это не C++-команда."""
    if args.cpp_doctor:
        return _doctor(args.json, smoke=not args.no_smoke)
    if args.cpp_fix_path:
        return _fix_path(args.cpp_fix_path, args.remove, args.yes, args.json)
    if args.cpp_setup:
        return _setup(args)
    if args.cpp_new:
        return _new(args)
    if args.msys2 is not None:
        return _msys2(args.msys2)
    if args.install_vcpkg:
        return _vcpkg()
    return None


def _doctor(as_json: bool, smoke: bool) -> int:
    from . import cpp

    rep = cpp.cpp_report(smoke=smoke)
    if as_json:
        print(_json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print("\n".join(cpp.format_report(rep)))
        if any(i.get("fix") == "path" for i in rep["issues"]):
            print("\nНавести порядок: --cpp-fix-path <каталог bin основного GCC> [--remove]")
    return 1 if any(i["level"] == "error" for i in rep["issues"]) else 0


def _fix_path(primary: str, remove: bool, yes: bool, as_json: bool) -> int:
    from . import cpp

    if not (Path(primary) / "g++.exe").is_file() and not (Path(primary) / "gcc.exe").is_file():
        print(f"Ошибка: в {primary} нет g++.exe/gcc.exe.")
        return 2
    plan = cpp.path_fix_plan(primary, "remove" if remove else "demote")
    if as_json and not yes:
        print(_json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    print(cpp.describe_plan(plan))
    if not yes:
        print("\nЭто предпросмотр. Применить: добавьте --yes")
        return 0
    ok, msg = cpp.apply_path_fix(plan)
    print(msg)
    return 0 if ok else 3


def _pick_compiler(path: str):
    from . import cpp

    comps = cpp.find_compilers(scan_disk=False)
    if path:
        want = Path(path).resolve()
        for c in comps:
            if Path(c.path).resolve() == want:
                return c
        if not want.is_file():
            return None
        kind = (
            "msvc"
            if want.name.lower() == "cl.exe"
            else ("clang" if "clang" in want.name.lower() else "gcc")
        )
        return cpp.Compiler(path=str(want), kind=kind)
    return cpp.active_compiler(comps, "gcc")


def _options(args, compiler):
    from . import cpp_project as cp

    o = cp.options_from_compiler(compiler, engine=args.engine)
    o.std = args.std
    o.olympiad = bool(args.olympiad)
    return o


def _setup(args) -> int:
    from . import cpp_project as cp
    from .detect import cpp_project_hints

    folder = args.cpp_setup
    if not Path(folder).is_dir():
        print(f"Ошибка: папка не найдена: {folder}")
        return 2
    comp = _pick_compiler(args.compiler)
    if comp is None:
        print("Ошибка: компилятор не найден. Проверьте --cpp-doctor или укажите --compiler.")
        return 2
    o = _options(args, comp)
    hints = cpp_project_hints(folder)
    o.build = args.build or ("cmake" if hints["build"] == "cmake" else "single")
    o.vcpkg = bool(hints["vcpkg"])
    o.name = Path(folder).name
    plan = cp.plan_files(folder, o)
    overwrite = (
        {i["path"] for i in plan if i["exists"] and not i["merge"]} if args.overwrite else set()
    )
    print(f"Компилятор: {comp.kind} {comp.version} — {comp.path}")
    print(f"Движок: {o.engine}, сборка: {o.build}, отладчик: {o.resolved_debugger()}")
    for line in cp.apply_plan(folder, plan, overwrite=overwrite):
        print("  " + line)
    return 0


def _new(args) -> int:
    from . import cpp_project as cp

    target = Path(args.cpp_new)
    comp = _pick_compiler(args.compiler)
    if comp is None:
        print("Ошибка: компилятор не найден. Проверьте --cpp-doctor или укажите --compiler.")
        return 2
    o = _options(args, comp)
    ok, msg = cp.new_project(str(target.parent), target.name, args.template, o)
    print(("Проект создан: " if ok else "Ошибка: ") + msg)
    return 0 if ok else 2


def _msys2(libs: str) -> int:
    from . import cpp

    chosen = tuple(x.strip() for x in libs.split(",") if x.strip() and x != "-")
    unknown = [x for x in chosen if x not in cpp.MSYS2_LIBS]
    if unknown:
        print("Неизвестные библиотеки: " + ", ".join(unknown))
        print("Доступны: " + ", ".join(sorted(cpp.MSYS2_LIBS)))
        return 2
    print("pacman ставит пакеты, это может занять несколько минут…")
    ok, msg = cpp.msys2_install_toolchain(libs=chosen)
    print(msg)
    return 0 if ok else 3


def _vcpkg() -> int:
    from . import cpp

    print("Клонирую vcpkg (несколько сотен МБ)…")
    ok, msg = cpp.install_vcpkg()
    print(msg)
    return 0 if ok else 3
