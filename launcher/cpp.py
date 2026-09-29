# -*- coding: utf-8 -*-
r"""Доктор C++: какие компиляторы стоят, не смешаны ли тулчейны, собирается ли код.

На Windows C++ ломается не в редакторе, а в окружении. Типичные беды:
- в PATH два разных GCC (MSYS2 и WinLibs, Code::Blocks, Strawberry Perl), и
  программа, собранная одним, при запуске подхватывает `libstdc++-6.dll`
  другого — «точка входа не найдена» (0xC0000139);
- g++ из одного места, gdb/make из другого — отладчик не понимает типы STL;
- Clang поставлен из LLVM, но нацелен на MSVC, которого нет, — «'iostream'
  file not found»;
- компилятор древний и не знает C++20.

Модуль всё это находит (`cpp_report`), проверяет пробной сборкой
(`smoke_test`) и умеет навести порядок в PATH (`path_fix_plan` /
`apply_path_fix`). Здесь же — MSYS2 (pacman) и vcpkg: их нельзя поставить
одним `winget install`.

Безопасность как в toolchains.py: подпроцессы — списком аргументов, без shell,
с CREATE_NO_WINDOW; имена пакетов pacman проходят строгий фильтр.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from typing import Any
from pathlib import Path
from shutil import which

from . import env_path

log = logging.getLogger("launcher")

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Коды завершения Windows, которые означают «не та DLL», а не ошибку программы.
STATUS_ENTRYPOINT_NOT_FOUND = 0xC0000139
STATUS_DLL_NOT_FOUND = 0xC0000135
STATUS_ACCESS_VIOLATION = 0xC0000005

# Минимальные версии, с которыми C++20 и CMake-пресеты работают без сюрпризов.
MIN_GCC = 12  # C++20: модули-заглушки, ranges, concepts без дыр
MIN_CLANG = 17  # полноценный C++20 и свежий clangd
MIN_CMAKE = (3, 25)  # CMakePresets.json версии 6
MIN_MSVC_TOOLSET = (14, 30)  # VS 2022

# Файлы, по которым каталог считается «тулчейном GCC»: два таких каталога в PATH
# и есть смесь рантаймов.
GCC_MARKERS = ("g++.exe", "gcc.exe", "libstdc++-6.dll")

# Инструменты, происхождение которых показываем в отчёте.
TOOLS = (
    "gcc",
    "g++",
    "gdb",
    "mingw32-make",
    "make",
    "cmake",
    "ninja",
    "clang",
    "clang++",
    "clangd",
    "clang-format",
    "clang-tidy",
    "lldb",
    "ccache",
    "cppcheck",
    "vcpkg",
    "conan",
)


def _run(args: list[str], timeout: float = 30, cwd: str | None = None, env=None):
    """subprocess.run с нашими умолчаниями. None, если процесс не запустился."""
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
            env=env,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def _out(proc) -> str:
    if proc is None:
        return ""
    return ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.expandvars(p or ""))).rstrip("\\/")


def parse_version(text: str) -> tuple[int, ...]:
    """Первая версия вида 1.2[.3] в тексте -> (1, 2, 3). Пусто -> ()."""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not m:
        return ()
    return tuple(int(g) for g in m.groups() if g is not None)


def _ver_str(v: tuple[int, ...]) -> str:
    return ".".join(str(x) for x in v)


# --- компиляторы ------------------------------------------------------------


@dataclass
class Compiler:
    """Найденный компилятор C++."""

    path: str
    kind: str  # gcc | clang | msvc
    version: str = ""
    target: str = ""
    origin: str = ""
    active: bool = False  # первый в PATH для своего вида (его и вызовет `g++`)
    on_path: bool = False
    vcvars: str = ""  # только MSVC: vcvars64.bat для окружения сборки

    @property
    def bin_dir(self) -> str:
        return str(Path(self.path).parent)

    @property
    def major(self) -> int:
        v = parse_version(self.version)
        return v[0] if v else 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bin_dir"] = self.bin_dir
        return d


def origin_of(path: str, version_line: str = "") -> str:
    """Откуда компилятор: MSYS2 UCRT64, WinLibs, LLVM, MSVC… По пути и по
    строке версии (WinLibs пишет «built by Brecht Sanders», MSYS2 — «MSYS2
    project»)."""
    p = _norm(path)
    v = (version_line or "").lower()
    for env in ("ucrt64", "clang64", "mingw64", "mingw32", "clangarm64"):
        if f"msys64\\{env}\\" in p or f"msys2\\{env}\\" in p:
            return f"MSYS2 {env.upper()}"
    if "msys2" in v:
        return "MSYS2"
    if "brecht sanders" in v or "brechtsanders" in p:
        return "WinLibs"
    if "\\microsoft visual studio\\" in p or p.endswith("\\cl.exe"):
        return "MSVC"
    if "\\llvm\\" in p:
        return "LLVM"
    if "\\swift\\" in p:
        return "Swift"
    if "\\git\\mingw64\\" in p:
        return "Git for Windows"
    if "strawberry" in p:
        return "Strawberry Perl"
    if "codeblocks" in p:
        return "Code::Blocks"
    if "chocolatey" in p:
        return "Chocolatey"
    if "\\cygwin" in p:
        return "Cygwin"
    if "mingw" in p:
        return "MinGW"
    return "другое"


def _probe_gcc(path: str) -> Compiler:
    ver = _run([path, "-dumpfullversion"], timeout=15)
    line = _run([path, "--version"], timeout=15)
    tgt = _run([path, "-dumpmachine"], timeout=15)
    first = (_out(line).splitlines() or [""])[0]
    version = (ver.stdout or "").strip() if ver and ver.returncode == 0 else ""
    if not version:
        version = _ver_str(parse_version(first))
    return Compiler(
        path=path,
        kind="gcc",
        version=version,
        target=(tgt.stdout or "").strip() if tgt else "",
        origin=origin_of(path, first),
    )


def _probe_clang(path: str) -> Compiler:
    out = _out(_run([path, "--version"], timeout=15))
    m = re.search(r"clang version (\d+(?:\.\d+)*)", out)
    t = re.search(r"Target:\s*(\S+)", out)
    return Compiler(
        path=path,
        kind="clang",
        version=m.group(1) if m else _ver_str(parse_version(out)),
        target=t.group(1) if t else "",
        origin=origin_of(path, out),
    )


def vswhere_path() -> str | None:
    base = os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
    p = Path(base) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    return str(p) if p.is_file() else None


def find_msvc() -> list[Compiler]:
    """Установки MSVC через vswhere: только те, где есть компонент VC Tools.
    Каждая даёт cl.exe (Hostx64\\x64) и vcvars64.bat для окружения сборки."""
    vw = vswhere_path()
    if not vw:
        return []
    proc = _run(
        [
            vw,
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
            "-utf8",
        ],
        timeout=30,
    )
    out: list[Compiler] = []
    for inst in (proc.stdout or "").splitlines() if proc else ():
        inst = inst.strip()
        if not inst:
            continue
        tools = Path(inst) / "VC" / "Tools" / "MSVC"
        vcvars = Path(inst) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
        try:
            vers = sorted(
                (d for d in tools.iterdir() if d.is_dir()),
                key=lambda d: parse_version(d.name),
                reverse=True,
            )
        except OSError:
            continue
        for d in vers[:1]:
            cl = d / "bin" / "Hostx64" / "x64" / "cl.exe"
            if cl.is_file():
                out.append(
                    Compiler(
                        path=str(cl),
                        kind="msvc",
                        version=d.name,
                        target="x86_64-pc-windows-msvc",
                        origin="MSVC",
                        vcvars=str(vcvars) if vcvars.is_file() else "",
                    )
                )
    return out


def _path_dirs() -> list[str]:
    return [os.path.expandvars(e) for e in env_path.path_entries(os.environ.get("PATH", ""))]


def _extra_roots() -> list[str]:
    """Типовые каталоги установки вне PATH (MSYS2 на любом диске, LLVM…)."""
    from .toolchains import _disk_scan_roots

    roots = list(_disk_scan_roots())
    for r in msys2_roots():
        for env in ("ucrt64", "clang64", "mingw64"):
            roots.append(str(Path(r) / env / "bin"))
    return roots


def find_compilers(scan_disk: bool = True) -> list[Compiler]:
    """Все компиляторы C++: из PATH (по порядку), с типовых мест на диске и MSVC.

    `active` — тот g++/clang++, который реально вызовется командой из терминала
    (первый в PATH). Дубли по нормализованному пути отбрасываются."""
    seen: set[str] = set()
    found: list[Compiler] = []
    active_seen: set[str] = set()

    def add(path: Path, kind: str, on_path: bool):
        key = _norm(str(path))
        if key in seen or not path.is_file():
            return
        seen.add(key)
        c = _probe_gcc(str(path)) if kind == "gcc" else _probe_clang(str(path))
        c.on_path = on_path
        if on_path and kind not in active_seen:
            c.active = True
            active_seen.add(kind)
        found.append(c)

    for d in _path_dirs():
        for exe, kind in (("g++.exe", "gcc"), ("clang++.exe", "clang")):
            add(Path(d) / exe, kind, True)
    if scan_disk:
        for d in _extra_roots():
            for exe, kind in (("g++.exe", "gcc"), ("clang++.exe", "clang")):
                add(Path(d) / exe, kind, False)
    for c in find_msvc():
        if _norm(c.path) not in seen:
            seen.add(_norm(c.path))
            found.append(c)
    return found


def any_compiler() -> bool:
    """Есть ли хоть какой-то C++-компилятор (в PATH или MSVC). Дёшево: без запуска
    процессов, кроме vswhere."""
    if which("g++") or which("clang++") or which("cl"):
        return True
    return bool(find_msvc())


def active_compiler(compilers: list[Compiler], prefer: str = "gcc") -> Compiler | None:
    """Компилятор по умолчанию для настроек проекта: активный нужного вида, затем
    любой активный, затем первый найденный."""
    for c in compilers:
        if c.active and c.kind == prefer:
            return c
    for c in compilers:
        if c.active:
            return c
    return compilers[0] if compilers else None


# --- происхождение инструментов и смесь тулчейнов --------------------------


def tool_locations() -> dict[str, str]:
    """{инструмент: полный путь} для того, что видно в PATH."""
    return {t: p for t in TOOLS if (p := which(t))}


def gcc_dirs(path_str: str | None = None) -> list[str]:
    """Каталоги PATH (по порядку), где лежит компилятор GCC. Больше одного —
    потенциальная смесь."""
    entries = env_path.path_entries(os.environ.get("PATH", "") if path_str is None else path_str)
    out: list[str] = []
    seen: set[str] = set()
    for e in entries:
        d = os.path.expandvars(e)
        key = _norm(d)
        if key in seen:
            continue
        seen.add(key)
        try:
            if any((Path(d) / m).is_file() for m in ("g++.exe", "gcc.exe")):
                out.append(d)
        except OSError:
            continue
    return out


def first_dll(name: str, path_str: str | None = None) -> str | None:
    """Какую копию DLL загрузчик найдёт первой по PATH (без учёта каталога exe)."""
    for e in env_path.path_entries(os.environ.get("PATH", "") if path_str is None else path_str):
        p = Path(os.path.expandvars(e)) / name
        try:
            if p.is_file():
                return str(p)
        except OSError:
            continue
    return None


def _same_dir(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return _norm(str(Path(a).parent)) == _norm(str(Path(b).parent))


def _t(ru: str, en: str) -> str:
    """Текст на языке интерфейса: отчёт доктора видит человек, а язык окна —
    глобальная настройка процесса (i18n)."""
    from .i18n import get_language

    return en if get_language() == "en" else ru


def analyze(compilers: list[Compiler], tools: dict[str, str]) -> list[dict]:
    """Проблемы окружения: [{'level': error|warn|info, 'text', 'fix'}].

    fix — ключ действия, которое UI может предложить кнопкой: 'path' (навести
    порядок в PATH), 'install:<toolchain>' (поставить набор). Тексты — на языке
    интерфейса (_t)."""
    issues: list[dict] = []

    def add(level, text, fix=""):
        issues.append({"level": level, "text": text, "fix": fix})

    gcc_active = next((c for c in compilers if c.kind == "gcc" and c.active), None)
    clang_active = next((c for c in compilers if c.kind == "clang" and c.active), None)
    msvc = [c for c in compilers if c.kind == "msvc"]

    if not compilers:
        add(
            "error",
            _t(
                "Не найден ни один компилятор C++. Поставьте его на вкладке «Установка»: "
                "MinGW (проще всего), MSYS2 или MSVC Build Tools.",
                "No C++ compiler found. Install one on the 'Install' tab: MinGW "
                "(simplest), MSYS2 or MSVC Build Tools.",
            ),
            "install:cpp",
        )
        return issues
    if not gcc_active and not clang_active and not msvc:
        add(
            "error",
            _t(
                "Компиляторы есть на диске, но ни один не в PATH: из терминала `g++` не "
                "запустится. Выберите основной тулчейн — лаунчер пропишет его.",
                "Compilers exist on disk but none is on PATH: `g++` will not start from "
                "a terminal. Pick the main toolchain and the launcher will add it.",
            ),
            "path",
        )

    # 1. Смесь GCC-рантаймов в PATH.
    dirs = gcc_dirs()
    if len(dirs) > 1:
        add(
            "warn",
            _t(
                "В PATH несколько тулчейнов GCC: {dirs}. Программа может подхватить "
                "чужую libstdc++-6.dll и не запуститься. Оставьте один основной.",
                "Several GCC toolchains on PATH: {dirs}. A program may load another "
                "build's libstdc++-6.dll and fail to start. Keep one main toolchain.",
            ).format(dirs="; ".join(dirs)),
            "path",
        )
    if gcc_active:
        dll = first_dll("libstdc++-6.dll")
        if dll and not _same_dir(dll, gcc_active.path):
            git_note = ""
            if origin_of(dll) == "Git for Windows":
                git_note = " " + _t(
                    "Это каталог Git for Windows: он попадает в PATH только внутри "
                    "Git Bash, так что беда проявится в терминале Git Bash (в том числе "
                    "встроенном в VS Code), а в cmd/PowerShell — нет.",
                    "This is the Git for Windows folder: it is on PATH only inside Git "
                    "Bash, so the problem shows up in Git Bash terminals (including the "
                    "one inside VS Code), not in cmd/PowerShell.",
                )
            add(
                "error",
                _t(
                    "g++ берётся из {gxx}, а первой в PATH найдётся libstdc++-6.dll из "
                    "{dll}. Собранные программы будут падать с «точка входа не найдена» "
                    "(0xC0000139).",
                    "g++ comes from {gxx}, but the first libstdc++-6.dll on PATH is in "
                    "{dll}. Built programs will crash with 'entry point not found' "
                    "(0xC0000139).",
                ).format(gxx=gcc_active.bin_dir, dll=Path(dll).parent)
                + git_note,
                "path",
            )
        # 2. gdb/make не из того же тулчейна.
        gdb = tools.get("gdb")
        if gdb and not _same_dir(gdb, gcc_active.path):
            add(
                "warn",
                _t(
                    "gdb ({gdb}) не из того же тулчейна, что g++ ({gxx}): отладчик может "
                    "не показывать содержимое std::vector/std::string (другие "
                    "pretty-printers).",
                    "gdb ({gdb}) is not from the same toolchain as g++ ({gxx}): the "
                    "debugger may not show std::vector/std::string contents (different "
                    "pretty-printers).",
                ).format(gdb=Path(gdb).parent, gxx=gcc_active.bin_dir),
                "path",
            )
        mk = tools.get("mingw32-make") or tools.get("make")
        if mk and not _same_dir(mk, gcc_active.path) and len(dirs) > 1:
            add(
                "info",
                _t(
                    "make берётся из {mk}, а g++ — из {gxx}. Обычно безвредно, но при "
                    "смешанных тулчейнах сборка может позвать не тот компилятор.",
                    "make comes from {mk} and g++ from {gxx}. Usually harmless, but with "
                    "mixed toolchains a build may call the wrong compiler.",
                ).format(mk=Path(mk).parent, gxx=gcc_active.bin_dir),
            )
        if gcc_active.major and gcc_active.major < MIN_GCC:
            add(
                "warn",
                _t(
                    "GCC {v} устарел: C++20 поддержан не полностью (нужен {m}+). Обновите набор.",
                    "GCC {v} is outdated: C++20 support is incomplete (need {m}+). "
                    "Update the toolchain.",
                ).format(v=gcc_active.version, m=MIN_GCC),
                "install:cpp",
            )
    if gcc_active and not tools.get("gdb"):
        add(
            "warn",
            _t(
                "g++ есть, а gdb нет — отладка из VS Code (cppdbg) не запустится.",
                "g++ is present but gdb is not — debugging from VS Code (cppdbg) will not start.",
            ),
        )

    # 3. Clang.
    if clang_active:
        if clang_active.major and clang_active.major < MIN_CLANG:
            add(
                "warn",
                _t(
                    "Clang {v} устарел (нужен {m}+): C++20/23 и clangd будут расходиться "
                    "с GCC. Обновите LLVM.",
                    "Clang {v} is outdated (need {m}+): C++20/23 and clangd will "
                    "disagree with GCC. Update LLVM.",
                ).format(v=clang_active.version, m=MIN_CLANG),
                "install:cpp_llvm",
            )
        if "msvc" in clang_active.target and not msvc:
            add(
                "warn",
                _t(
                    "Clang нацелен на MSVC (Target: {t}), а MSVC Build Tools не "
                    "установлены — стандартная библиотека не найдётся. Либо поставьте "
                    "MSVC, либо собирайте с --target=x86_64-w64-mingw32 (нужен MinGW).",
                    "Clang targets MSVC (Target: {t}) but MSVC Build Tools are not "
                    "installed, so the standard library will not be found. Install MSVC "
                    "or build with --target=x86_64-w64-mingw32 (needs MinGW).",
                ).format(t=clang_active.target),
                "install:cpp_msvc",
            )
    clangd = tools.get("clangd")
    if clangd:
        cv = parse_version(_out(_run([clangd, "--version"], timeout=15)))
        if cv and cv[0] < MIN_CLANG:
            add(
                "warn",
                _t(
                    "clangd {v} устарел — подсказки для C++20 будут неточными. Обновите LLVM.",
                    "clangd {v} is outdated — C++20 code intelligence will be "
                    "inaccurate. Update LLVM.",
                ).format(v=_ver_str(cv)),
                "install:cpp_llvm",
            )
        if clang_active and cv and clang_active.major and cv[0] != clang_active.major:
            add(
                "info",
                _t(
                    "clangd {a} и clang {b} разных версий.",
                    "clangd {a} and clang {b} are different versions.",
                ).format(a=_ver_str(cv), b=clang_active.version),
            )

    # 4. CMake.
    cmake = tools.get("cmake")
    if cmake:
        cv = parse_version(_out(_run([cmake, "--version"], timeout=15)))
        if cv and cv[:2] < MIN_CMAKE:
            add(
                "warn",
                _t(
                    "CMake {v} устарел: CMakePresets.json v6 требует {m}+.",
                    "CMake {v} is outdated: CMakePresets.json v6 needs {m}+.",
                ).format(v=_ver_str(cv), m=_ver_str(MIN_CMAKE)),
                "install:cpp",
            )
    # 5. MSVC.
    for c in msvc:
        if parse_version(c.version)[:2] < MIN_MSVC_TOOLSET:
            add(
                "warn",
                _t(
                    "MSVC {v} старше VS 2022 — C++20 поддержан частично.",
                    "MSVC {v} is older than VS 2022 — C++20 support is partial.",
                ).format(v=c.version),
            )
        if not c.vcvars:
            add(
                "warn",
                _t(
                    "У MSVC {v} нет vcvars64.bat — окружение сборки не поднять.",
                    "MSVC {v} has no vcvars64.bat — the build environment cannot be set up.",
                ).format(v=c.version),
            )
    return issues


# --- пробная сборка ----------------------------------------------------------

SMOKE_SRC = """#include <algorithm>
#include <iostream>
#include <ranges>
#include <string>
#include <vector>

int main() {
    std::vector<int> v{3, 1, 2};
    std::ranges::sort(v);
    std::string s = "ok";
    std::cout << s << ' ' << v.front() << '\\n';
    return 0;
}
"""


def explain_exit(code: int) -> str:
    """Человеческое объяснение кода выхода пробной программы."""
    c = code & 0xFFFFFFFF
    if c == STATUS_ENTRYPOINT_NOT_FOUND:
        return _t(
            "точка входа не найдена (0xC0000139): подхвачена чужая libstdc++/libgcc — "
            "смесь тулчейнов в PATH",
            "entry point not found (0xC0000139): another build's libstdc++/libgcc was "
            "loaded — mixed toolchains on PATH",
        )
    if c == STATUS_DLL_NOT_FOUND:
        return _t(
            "не найдена DLL рантайма (0xC0000135): каталог компилятора не в PATH",
            "runtime DLL not found (0xC0000135): the compiler folder is not on PATH",
        )
    if c == STATUS_ACCESS_VIOLATION:
        return _t("нарушение доступа (0xC0000005)", "access violation (0xC0000005)")
    return _t("код выхода {c}", "exit code {c}").format(c=code)


_TMP_RE = re.compile(r"\S*vscl_cpp_\w+[\\/]")


STEP_TITLES = {
    "compile": ("компиляция", "compile"),
    "link": ("линковка", "link"),
    "run": ("запуск", "run"),
    "debug": ("отладчик", "debugger"),
}


def step_title(name: str) -> str:
    ru, en = STEP_TITLES.get(name, (name, name))
    return _t(ru, en)


def _step(name: str, ok: bool, detail: str = "") -> dict:
    # Путь временного каталога в сообщениях компилятора — шум: оставляем имя файла.
    detail = _TMP_RE.sub("", detail or "").strip()
    return {"name": name, "ok": ok, "detail": detail[:600]}


def _tail(text: str, n: int = 6) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def _run_exe(exe: Path, cwd: str) -> dict:
    proc = _run([str(exe)], timeout=20, cwd=cwd)
    if proc is None:
        return _step("run", False, _t("не запустилась или зависла", "did not start or hung"))
    if proc.returncode != 0:
        return _step("run", False, explain_exit(proc.returncode))
    if "ok 1" not in (proc.stdout or ""):
        return _step(
            "run",
            False,
            _t("неожиданный вывод: {o}", "unexpected output: {o}").format(
                o=(proc.stdout or "").strip()[:80]
            ),
        )
    return _step("run", True, _t("вывод «ok 1»", "printed 'ok 1'"))


def _debugger_for(c: Compiler) -> tuple[str, str] | None:
    """(вид, путь) отладчика, парного компилятору: gdb рядом с g++, lldb рядом с
    clang, иначе из PATH."""
    if c.kind == "gcc":
        local = Path(c.bin_dir) / "gdb.exe"
        p = str(local) if local.is_file() else which("gdb")
        return ("gdb", p) if p else None
    if c.kind == "clang":
        local = Path(c.bin_dir) / "lldb.exe"
        p = str(local) if local.is_file() else which("lldb")
        return ("lldb", p) if p else None
    return None


def _debug_step(c: Compiler, exe: Path, cwd: str) -> dict:
    dbg = _debugger_for(c)
    if dbg is None:
        if c.kind == "msvc":
            return _step(
                "debug",
                True,
                _t(
                    "cppvsdbg входит в расширение cpptools",
                    "cppvsdbg comes with the cpptools extension",
                ),
            )
        return _step("debug", False, _t("не найден (gdb/lldb)", "not found (gdb/lldb)"))
    kind, path = dbg
    if kind == "gdb":
        proc = _run([path, "-batch", "-nx", "-ex", "run", str(exe)], timeout=60, cwd=cwd)
        text = _out(proc)
        ok = proc is not None and ("exited normally" in text or "ok 1" in text)
    else:
        proc = _run([path, "-b", "-o", "run", str(exe)], timeout=60, cwd=cwd)
        text = _out(proc)
        ok = proc is not None and ("exited with status = 0" in text or "ok 1" in text)
    return _step("debug", ok, f"{kind}: {path}" if ok else f"{kind}: {_tail(text, 3)}")


def smoke_test(c: Compiler, std: str = "c++20", extra: tuple[str, ...] = ()) -> dict:
    """Собрать, слинковать, запустить и прогнать под отладчиком пробную программу.

    Проверяем то, что реально ломается: заголовки и C++20 (компиляция), рантайм
    (линковка), совместимость DLL в PATH (запуск), пару компилятор-отладчик.
    Возвращает {'compiler': dict, 'steps': [...], 'ok': bool, 'flags': [...]}."""
    tmp = tempfile.mkdtemp(prefix="vscl_cpp_")
    steps: list[dict] = []
    try:
        src = Path(tmp) / "hello.cpp"
        src.write_text(SMOKE_SRC, encoding="utf-8")
        exe = Path(tmp) / "hello.exe"
        if c.kind == "msvc":
            steps += _smoke_msvc(c, tmp, std)
        else:
            obj = Path(tmp) / "hello.o"
            comp = _run(
                [c.path, f"-std={std}", "-g", "-O0", *extra, "-c", str(src), "-o", str(obj)],
                timeout=120,
                cwd=tmp,
            )
            if comp is None or comp.returncode != 0:
                steps.append(
                    _step(
                        "compile", False, _tail(_out(comp)) or _t("не запустился", "did not start")
                    )
                )
            else:
                steps.append(_step("compile", True, f"-std={std}"))
                link = _run([c.path, *extra, str(obj), "-o", str(exe)], timeout=120, cwd=tmp)
                if link is None or link.returncode != 0:
                    steps.append(
                        _step(
                            "link", False, _tail(_out(link)) or _t("не запустился", "did not start")
                        )
                    )
                else:
                    steps.append(_step("link", True))
        if steps and all(s["ok"] for s in steps) and exe.is_file():
            steps.append(_run_exe(exe, tmp))
            if steps[-1]["ok"]:
                steps.append(_debug_step(c, exe, tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {
        "compiler": c.to_dict(),
        "steps": steps,
        "ok": bool(steps) and all(s["ok"] for s in steps),
        "flags": list(extra),
    }


def _smoke_msvc(c: Compiler, tmp: str, std: str) -> list[dict]:
    """MSVC собирается только в окружении vcvars: пишем .bat и запускаем его."""
    if not c.vcvars:
        return [_step("compile", False, _t("нет vcvars64.bat", "no vcvars64.bat"))]
    msvc_std = "/std:c++latest" if std in ("c++23", "c++26") else f"/std:{std}"
    bat = Path(tmp) / "build.bat"
    bat.write_text(
        "@echo off\r\n"
        f'call "{c.vcvars}" >nul\r\n'
        "if errorlevel 1 exit /b 90\r\n"
        f"cl /nologo {msvc_std} /EHsc /Zi hello.cpp /Fe:hello.exe\r\n",
        encoding="utf-8",
    )
    proc = _run(["cmd", "/d", "/c", str(bat)], timeout=240, cwd=tmp)
    if proc is None:
        return [_step("compile", False, _t("не уложилась во время", "timed out"))]
    if proc.returncode == 90:
        return [
            _step("compile", False, _t("vcvars64.bat завершился с ошибкой", "vcvars64.bat failed"))
        ]
    if proc.returncode != 0:
        return [_step("compile", False, _tail(_out(proc)))]
    return [_step("compile", True, msvc_std), _step("link", True)]


def smoke_all(compilers: list[Compiler]) -> list[dict]:
    """Пробная сборка активным GCC, активным Clang и свежим MSVC.

    Clang, нацеленный на MSVC без MSVC, при провале пробуем ещё раз с
    `--target=x86_64-w64-mingw32`: так отчёт сразу говорит, какой флаг
    прописать в проект."""
    picked: list[Compiler] = []
    for kind in ("gcc", "clang"):
        c = next((x for x in compilers if x.kind == kind and x.active), None)
        c = c or next((x for x in compilers if x.kind == kind), None)
        if c:
            picked.append(c)
    msvc = next((x for x in compilers if x.kind == "msvc"), None)
    if msvc:
        picked.append(msvc)
    results = []
    has_gcc = any(x.kind == "gcc" for x in compilers)
    for c in picked:
        r = smoke_test(c)
        if not r["ok"] and c.kind == "clang" and "msvc" in c.target and has_gcc:
            alt = smoke_test(c, extra=("--target=x86_64-w64-mingw32",))
            if alt["ok"]:
                r = alt
        results.append(r)
    return results


def _first_line(text: str) -> str:
    return (text or "").strip().splitlines()[0] if (text or "").strip() else ""


def cpp_report(smoke: bool = True, scan_disk: bool = True) -> dict:
    """Полный отчёт доктора C++ (для GUI и CLI)."""
    compilers = find_compilers(scan_disk=scan_disk)
    tools = tool_locations()
    rep: dict[str, Any] = {
        "compilers": [c.to_dict() for c in compilers],
        "tools": tools,
        "gcc_dirs": gcc_dirs(),
        "issues": analyze(compilers, tools),
        "smoke": smoke_all(compilers) if smoke else [],
        "msys2": [str(r) for r in msys2_roots()],
        "vcpkg": vcpkg_root() or "",
    }
    for s in rep["smoke"]:
        if not s["ok"]:
            c = s["compiler"]
            failed = next((st for st in s["steps"] if not st["ok"]), None)
            rep["issues"].append(
                {
                    "level": "error",
                    "text": _t(
                        "Пробная сборка {k} {v} ({o}) не прошла на шаге «{step}»: {d}",
                        "Test build with {k} {v} ({o}) failed at '{step}': {d}",
                    ).format(
                        k=c["kind"],
                        v=c["version"],
                        o=c["origin"],
                        step=step_title(failed["name"]) if failed else "?",
                        d=_first_line((failed or {}).get("detail", "")),
                    ),
                    "fix": "path" if failed and failed["name"] == "run" else "",
                }
            )
    return rep


def format_report(rep: dict) -> list[str]:
    """Отчёт доктора C++ текстом — общий для окна и CLI, на языке интерфейса."""
    marks = {
        "error": _t("[ошибка]", "[error]"),
        "warn": _t("[внимание]", "[warning]"),
        "info": _t("[инфо]", "[info]"),
    }
    lines: list[str] = []
    comps = rep.get("compilers", [])
    lines.append(_t("Компиляторы C++ ({n}):", "C++ compilers ({n}):").format(n=len(comps)))
    for c in comps:
        flags = []
        if c.get("active"):
            flags.append(_t("активный", "active"))
        elif not c.get("on_path"):
            flags.append(_t("не в PATH", "not on PATH"))
        tag = f"  [{', '.join(flags)}]" if flags else ""
        lines.append(f"  {c['kind']:<5} {c['version']:<10} {c['origin']:<14} {c['path']}{tag}")
        if c.get("target"):
            lines.append(f"        target: {c['target']}")
    if not comps:
        lines.append("  " + _t("не найдено", "none found"))
    lines.append("")
    lines.append(_t("Инструменты в PATH:", "Tools on PATH:"))
    tools = rep.get("tools", {})
    for t in TOOLS:
        if t in tools:
            lines.append(f"  {t:<13} {tools[t]}")
    lines.append("")
    if rep.get("msys2"):
        lines.append("MSYS2: " + "; ".join(rep["msys2"]))
    if rep.get("vcpkg"):
        lines.append("vcpkg: " + rep["vcpkg"])
    smoke = rep.get("smoke", [])
    if smoke:
        lines.append("")
        lines.append(_t("Пробная сборка (C++20):", "Test build (C++20):"))
        for s in smoke:
            c = s["compiler"]
            sflags = (" " + " ".join(s.get("flags") or [])) if s.get("flags") else ""
            lines.append(f"  {c['kind']} {c['version']} ({c['origin']}){sflags}:")
            for st in s["steps"]:
                mark = _t("да ", "ok ") if st["ok"] else _t("НЕТ", "NO ")
                det = f" — {st['detail']}" if st["detail"] else ""
                lines.append(f"    {mark} {step_title(st['name'])}{det}")
    lines.append("")
    issues = rep.get("issues", [])
    if issues:
        lines.append(_t("Проблемы ({n}):", "Problems ({n}):").format(n=len(issues)))
        for i in issues:
            lines.append(f"  {marks.get(i['level'], '-')} {i['text']}")
    else:
        lines.append(_t("Проблем не найдено.", "No problems found."))
    return lines


# --- порядок в PATH ----------------------------------------------------------


def _is_gcc_dir(d: str) -> bool:
    try:
        return any((Path(os.path.expandvars(d)) / m).is_file() for m in GCC_MARKERS)
    except OSError:
        return False


def _tools_in(d: str) -> set[str]:
    try:
        names = {p.name.lower() for p in Path(os.path.expandvars(d)).iterdir()}
    except OSError:
        return set()
    return {t for t in TOOLS if f"{t}.exe" in names}


def path_fix_plan(
    primary_dir: str,
    mode: str = "demote",
    user_path: str | None = None,
    machine_path: str | None = None,
) -> dict:
    """Спланировать PATH, где основной тулчейн GCC — `primary_dir`.

    mode='demote' — остальные каталоги GCC уезжают в конец своей ветки, основной
    встаёт в начало; ничего не удаляется. mode='remove' — остальные каталоги GCC
    убираются совсем (в `lost_tools` — что вместе с ними пропадёт: cmake, ninja…).

    Windows собирает PATH как «системный + пользовательский». Если основной
    каталог в пользовательском, а конкурент в системном, конкурент всё равно
    окажется раньше. В этом случае основной переносится в начало системного
    PATH (понадобятся права администратора). Чистая функция поверх строк."""
    user_path = env_path.read_user_path() if user_path is None else user_path
    machine_path = env_path.read_machine_path() if machine_path is None else machine_path
    prim = _norm(primary_dir)
    u = env_path.path_entries(user_path)
    m = env_path.path_entries(machine_path)

    def conflicts(entries):
        return [e for e in entries if _norm(e) != prim and _is_gcc_dir(e)]

    cu, cm = conflicts(u), conflicts(m)
    prim_in_u = any(_norm(e) == prim for e in u)
    prim_in_m = any(_norm(e) == prim for e in m)
    removed: list[str] = []

    def reorder(entries, conf, put_first: bool):
        """Основной встаёт не в начало PATH, а только перед первым конкурентом
        (или остаётся на своём месте): иначе каталог тулчейна с python/cmake
        внутри перекрыл бы отдельно установленные Python и прочее."""
        conf_n = {_norm(c) for c in conf}
        pos = next((i for i, e in enumerate(entries) if _norm(e) == prim), None)
        first_conf = next((i for i, e in enumerate(entries) if _norm(e) in conf_n), None)
        rest = [e for e in entries if _norm(e) != prim and _norm(e) not in conf_n]
        tail = [] if mode == "remove" else conf
        if not put_first:
            return rest + tail
        if pos is not None and (first_conf is None or pos < first_conf):
            # Уже раньше всех конкурентов — место не меняем.
            before = [e for e in entries[:pos] if _norm(e) not in conf_n]
            return before + [entries[pos]] + [e for e in rest if e not in before] + tail
        # Встать туда, где стоял первый конкурент (или в начало, если основного не было).
        anchor = first_conf if first_conf is not None else 0
        before = [e for e in entries[:anchor] if _norm(e) not in conf_n and _norm(e) != prim]
        return before + [primary_dir] + [e for e in rest if e not in before] + tail

    # Куда ставить основной: в системный, если он уже там или если конкурент в
    # системном (иначе системный конкурент победит).
    to_machine = prim_in_m or bool(cm)
    new_m = reorder(m, cm, to_machine)
    new_u = reorder(u, cu, not to_machine)
    if mode == "remove":
        removed = cu + cm
    remaining = new_m + new_u
    have: set[str] = set()
    for e in remaining:
        have |= _tools_in(e)
    lost: set[str] = set()
    for e in removed:
        lost |= _tools_in(e) - have
    user_new = os.pathsep.join(new_u)
    machine_new = os.pathsep.join(new_m)
    return {
        "primary": primary_dir,
        "mode": mode,
        "user_old": user_path,
        "machine_old": machine_path,
        "user_new": user_new,
        "machine_new": machine_new,
        "user_changed": env_path.path_entries(user_new) != u,
        "machine_changed": env_path.path_entries(machine_new) != m,
        "moved_to_machine": to_machine and prim_in_u and not prim_in_m,
        "demoted": [] if mode == "remove" else cu + cm,
        "removed": removed,
        "lost_tools": sorted(lost),
        "needs_elevation": (env_path.path_entries(machine_new) != m) and not env_path.is_admin(),
        "was_on_path": prim_in_u or prim_in_m,
    }


def describe_plan(plan: dict) -> str:
    """Текст предпросмотра плана для диалога подтверждения."""
    lines = [f"Основной тулчейн: {plan['primary']}"]
    if not plan["was_on_path"]:
        lines.append("  будет добавлен в PATH")
    if plan["moved_to_machine"]:
        lines.append(
            "  переносится в начало системного PATH: конкурент стоит в системном, "
            "а он просматривается раньше пользовательского"
        )
    if plan["demoted"]:
        lines.append("В конец PATH уедут:")
        lines += [f"  {d}" for d in plan["demoted"]]
    if plan["removed"]:
        lines.append("Из PATH будут убраны:")
        lines += [f"  {d}" for d in plan["removed"]]
    if plan["lost_tools"]:
        lines.append("Вместе с ними пропадут: " + ", ".join(plan["lost_tools"]))
    if plan["machine_changed"]:
        lines.append("Меняется системный PATH — понадобятся права администратора (UAC).")
    if not (plan["user_changed"] or plan["machine_changed"]):
        lines.append("Менять нечего: основной тулчейн уже первый.")
    return "\n".join(lines)


def apply_path_fix(plan: dict) -> tuple[bool, str]:
    """Применить план: бэкап обеих веток, запись, оповещение системы и
    обновление PATH процесса. Возвращает (успех, сообщение)."""
    if not (plan["user_changed"] or plan["machine_changed"]):
        return False, "Менять нечего: основной тулчейн уже первый в PATH."
    msgs: list[str] = []
    if plan["machine_changed"]:
        backup = env_path._backup_path(plan["machine_old"], "machine")
        if env_path.is_admin():
            try:
                env_path._write_machine_path_direct(plan["machine_new"])
            except Exception as e:
                return False, f"Не удалось записать системный PATH: {e}"
        else:
            ok, msg = env_path._write_machine_path_elevated(plan["machine_new"])
            if not ok:
                return False, msg
        msgs.append(f"Системный PATH обновлён (бэкап: {backup or '—'}).")
    if plan["user_changed"]:
        backup = env_path._backup_path(plan["user_old"], "user")
        try:
            env_path._write_user_path(plan["user_new"])
        except Exception as e:
            return False, f"Не удалось записать пользовательский PATH: {e}"
        msgs.append(f"Пользовательский PATH обновлён (бэкап: {backup or '—'}).")
    env_path._broadcast_env_change()
    # PATH процесса: основной — вперёд, убранные — прочь, понижённые — в конец.
    proc = os.environ.get("PATH", "")
    for d in [plan["primary"], *plan["removed"], *plan["demoted"]]:
        proc = env_path.compute_removed(proc, d)
    tail = os.pathsep.join(plan["demoted"])
    os.environ["PATH"] = os.pathsep.join(x for x in (plan["primary"], proc, tail) if x)
    msgs.append("Откройте новый терминал и перезапустите VS Code, чтобы PATH подхватился.")
    log.info("PATH C++: основной %s, режим %s", plan["primary"], plan["mode"])
    return True, "\n".join(msgs)


# --- MSYS2 -------------------------------------------------------------------

MSYS2_ENVS: dict[str, str] = {
    "ucrt64": "mingw-w64-ucrt-x86_64-",
    "clang64": "mingw-w64-clang-x86_64-",
    "mingw64": "mingw-w64-x86_64-",
}
MSYS2_BASE = ("toolchain", "cmake", "ninja", "gdb")

# Библиотеки, которые предлагаем ставить через pacman: ключ -> имя пакета без
# префикса окружения.
MSYS2_LIBS: dict[str, str] = {
    "sfml": "sfml",
    "sdl2": "SDL2",
    "sdl3": "sdl3",
    "boost": "boost",
    "glfw": "glfw",
    "fmt": "fmt",
    "gtest": "gtest",
    "catch2": "catch",
    "qt6": "qt6-base",
    "opencv": "opencv",
    "raylib": "raylib",
}

_PACMAN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._-]*$")


def msys2_roots() -> list[Path]:
    """Установки MSYS2 (каталог с usr\\bin\\pacman.exe) на всех дисках."""
    out = []
    for letter in "CDEFGH":
        for name in ("msys64", "msys2", r"tools\msys64"):
            root = Path(f"{letter}:\\") / name
            try:
                if (root / "usr" / "bin" / "pacman.exe").is_file():
                    out.append(root)
            except OSError:
                continue
    return out


def msys2_env_bin(root: Path, env: str = "ucrt64") -> Path:
    return Path(root) / env / "bin"


def msys2_status(env: str = "ucrt64") -> dict:
    """{'root', 'bin', 'has_gcc', 'on_path'} для первой найденной установки."""
    roots = msys2_roots()
    if not roots:
        return {"root": "", "bin": "", "has_gcc": False, "on_path": False}
    b = msys2_env_bin(roots[0], env)
    return {
        "root": str(roots[0]),
        "bin": str(b),
        "has_gcc": (b / "g++.exe").is_file(),
        "on_path": env_path.is_on_path(str(b)),
    }


def pacman_packages(env: str, names: tuple[str, ...]) -> list[str]:
    """Имена пакетов с префиксом окружения; всё, что не прошло фильтр, отброшено."""
    prefix = MSYS2_ENVS.get(env)
    if not prefix:
        return []
    return [prefix + n for n in names if _PACMAN_NAME_RE.match(n)]


def msys2_pacman(root: Path, env: str, names: tuple[str, ...]) -> tuple[bool, str]:
    """Поставить пакеты окружения MSYS2 через pacman и прописать его bin в PATH.

    pacman запускаем внутри bash -lc: без login-окружения MSYS2 он работает
    нестабильно. Имена пакетов — только из фильтра выше, так что строка команды
    не собирается из произвольного ввода."""
    bash = Path(root) / "usr" / "bin" / "bash.exe"
    if not bash.is_file():
        return False, f"Не найден {bash}"
    pkgs = pacman_packages(env, names)
    if not pkgs:
        return False, "Нечего ставить."
    env_vars = {**os.environ, "MSYSTEM": env.upper(), "CHERE_INVOKING": "1"}
    cmd = "pacman -S --needed --noconfirm " + " ".join(pkgs)
    log.info("MSYS2 %s: %s", env, cmd)
    proc = _run([str(bash), "-lc", cmd], timeout=3600, env=env_vars)
    if proc is None:
        return False, "pacman не уложился во время или не запустился."
    text = _out(proc)
    if proc.returncode != 0:
        return False, _tail(text, 12) or f"pacman вернул код {proc.returncode}"
    b = msys2_env_bin(root, env)
    note = ""
    if b.is_dir() and not env_path.is_on_path(str(b)):
        _ok, note = env_path.add_to_user_path(str(b))
    return True, (_tail(text, 4) + ("\n" + note if note else "")).strip()


def msys2_install_toolchain(env: str = "ucrt64", libs: tuple[str, ...] = ()) -> tuple[bool, str]:
    """Компилятор, CMake, Ninja и gdb для окружения MSYS2 (+ библиотеки)."""
    roots = msys2_roots()
    if not roots:
        return False, "MSYS2 не найден. Сначала поставьте его (набор «MSYS2»)."
    names = MSYS2_BASE + tuple(MSYS2_LIBS[k] for k in libs if k in MSYS2_LIBS)
    return msys2_pacman(roots[0], env, names)


# --- vcpkg -------------------------------------------------------------------

VCPKG_REPO = "https://github.com/microsoft/vcpkg"


def vcpkg_root() -> str | None:
    """Каталог vcpkg: VCPKG_ROOT, затем `vcpkg` в PATH, затем типовые места."""
    for cand in (os.environ.get("VCPKG_ROOT"), env_path.read_user_env_var("VCPKG_ROOT")):
        if cand and (Path(cand) / "vcpkg.exe").is_file():
            return cand
    exe = which("vcpkg")
    if exe:
        return str(Path(exe).parent)
    for place in (Path.home() / "vcpkg", Path("C:/vcpkg"), Path("C:/src/vcpkg")):
        if (place / "vcpkg.exe").is_file():
            return str(place)
    return None


def install_vcpkg(dest: str | None = None) -> tuple[bool, str]:
    """Клонировать vcpkg, собрать его и прописать VCPKG_ROOT и PATH.

    Клон полный (не --depth 1): режим манифеста с builtin-baseline требует
    истории коммитов. Нужен git. Существующий каталог не трогаем."""
    if vcpkg_root():
        return False, f"vcpkg уже установлен: {vcpkg_root()}"
    git = which("git")
    if not git:
        return False, "Нужен git (тулчейн «Git»)."
    target = Path(dest) if dest else Path.home() / "vcpkg"
    if target.exists() and any(target.iterdir()):
        return False, f"Каталог не пуст: {target}"
    log.info("vcpkg: clone в %s", target)
    proc = _run([git, "clone", VCPKG_REPO, str(target)], timeout=3600)
    if proc is None or proc.returncode != 0:
        return False, "git clone не удался:\n" + _tail(_out(proc))
    boot = target / "bootstrap-vcpkg.bat"
    proc = _run(["cmd", "/d", "/c", str(boot), "-disableMetrics"], timeout=1200, cwd=str(target))
    if proc is None or proc.returncode != 0 or not (target / "vcpkg.exe").is_file():
        return False, "bootstrap-vcpkg не удался:\n" + _tail(_out(proc))
    msgs = [f"vcpkg установлен: {target}"]
    ok, m = env_path.set_user_env_var("VCPKG_ROOT", str(target))
    if ok:
        os.environ["VCPKG_ROOT"] = str(target)
        msgs.append(m)
    ok, m = env_path.add_to_user_path(str(target))
    if ok:
        msgs.append(m)
    return True, "\n".join(msgs)


# --- подсказки по проекту -----------------------------------------------------


def project_suggestions(hints: dict) -> list[dict]:
    """Что предложить C/C++-проекту по detect.cpp_project_hints: [{'text',
    'action'}]. action: setup (настроить проект), vcpkg (поставить vcpkg),
    install:<тулчейн>, pacman:<lib,lib> (библиотеки в MSYS2)."""
    if not hints.get("is_cpp"):
        return []
    out: list[dict] = []
    if not hints.get("has_vscode_cfg") and not hints.get("has_clangd_cfg"):
        what = {
            "cmake": _t("CMake-проект", "CMake project"),
            "make": _t("Проект на Makefile", "Makefile project"),
            "meson": _t("Проект Meson", "Meson project"),
        }.get(hints.get("build", ""), _t("C/C++-проект", "C/C++ project"))
        out.append(
            {
                "text": _t(
                    "{what} без настроек VS Code: сборка, отладка и подсказки не "
                    "настроены. Сгенерировать .vscode под ваш компилятор?",
                    "{what} without VS Code settings: build, debugging and code "
                    "intelligence are not set up. Generate .vscode for your compiler?",
                ).format(what=what),
                "action": "setup",
            }
        )
    if hints.get("vcpkg") and not vcpkg_root():
        out.append(
            {
                "text": _t(
                    "Проект использует vcpkg (vcpkg.json), а vcpkg не установлен.",
                    "The project uses vcpkg (vcpkg.json), but vcpkg is not installed.",
                ),
                "action": "vcpkg",
            }
        )
    if hints.get("vcpkg") and not find_msvc() and which("g++"):
        out.append(
            {
                "text": _t(
                    "vcpkg по умолчанию собирает библиотеки под MSVC. С MinGW нужен "
                    "триплет x64-mingw-static (настройщик проекта пропишет его в "
                    "CMakePresets.json) или MSVC Build Tools.",
                    "By default vcpkg builds libraries for MSVC. With MinGW you need the "
                    "x64-mingw-static triplet (project setup writes it into "
                    "CMakePresets.json) or MSVC Build Tools.",
                ),
                "action": "",
            }
        )
    if hints.get("conan") and not which("conan"):
        out.append(
            {
                "text": _t(
                    "Проект на Conan, а conan не установлен.",
                    "The project uses Conan, but conan is not installed.",
                ),
                "action": "install:cpp_tools",
            }
        )
    if hints.get("build") == "meson" and not which("meson"):
        out.append(
            {
                "text": _t(
                    "Проект на Meson, а meson не установлен.",
                    "The project uses Meson, but meson is not installed.",
                ),
                "action": "install:cpp_tools",
            }
        )
    if hints.get("build") in ("cmake", "meson") and not which("cmake") and not which("meson"):
        out.append(
            {
                "text": _t(
                    "Для сборки нужен CMake — его нет в PATH.",
                    "Building needs CMake — it is not on PATH.",
                ),
                "action": "install:cpp",
            }
        )
    libs = [lib for lib in hints.get("libs", []) if lib in MSYS2_LIBS]
    st = msys2_status()
    if libs and st["root"] and not hints.get("vcpkg"):
        missing = [lib for lib in libs if not _msys2_lib_present(st["bin"], lib)]
        if missing:
            out.append(
                {
                    "text": _t(
                        "В исходниках подключены: {libs}. Поставить их в MSYS2 через pacman?",
                        "The sources include: {libs}. Install them into MSYS2 with pacman?",
                    ).format(libs=", ".join(missing)),
                    "action": "pacman:" + ",".join(missing),
                }
            )
    return out


# Признак установленной библиотеки в окружении MSYS2: каталог заголовков.
_MSYS2_LIB_HEADERS = {
    "sfml": "SFML",
    "sdl2": "SDL2",
    "sdl3": "SDL3",
    "boost": "boost",
    "glfw": "GLFW",
    "fmt": "fmt",
    "gtest": "gtest",
    "catch2": "catch2",
    "qt6": "qt6",
    "opencv": "opencv4",
    "raylib": "raylib.h",
}


def _msys2_lib_present(bin_dir: str, lib: str) -> bool:
    inc = Path(bin_dir).parent / "include"
    name = _MSYS2_LIB_HEADERS.get(lib)
    return bool(name) and (inc / str(name)).exists()


def msys2_install_libs(libs: tuple[str, ...], env: str = "ucrt64") -> tuple[bool, str]:
    """Поставить библиотеки из MSYS2_LIBS в окружение MSYS2."""
    roots = msys2_roots()
    if not roots:
        return False, "MSYS2 не найден."
    names = tuple(MSYS2_LIBS[k] for k in libs if k in MSYS2_LIBS)
    if not names:
        return False, "Нет известных библиотек для установки."
    return msys2_pacman(roots[0], env, names)


# --- детекторы для каталога тулчейнов ---------------------------------------
# Пакеты, чьё наличие не видно по PATH: MSYS2 (свой каталог), MSVC (vcvars),
# vcpkg (переменная). toolchains.Package.detector ссылается на ключ отсюда.


def _detect_msys2() -> tuple[bool, str | None]:
    roots = msys2_roots()
    return (True, str(roots[0])) if roots else (False, None)


def _detect_msvc() -> tuple[bool, str | None]:
    found = find_msvc()
    return (True, f"MSVC {found[0].version}") if found else (False, None)


def _detect_vcpkg() -> tuple[bool, str | None]:
    root = vcpkg_root()
    return (True, root) if root else (False, None)


DETECTORS = {
    "msys2": _detect_msys2,
    "msvc": _detect_msvc,
    "vcpkg": _detect_vcpkg,
}


def detect(name: str) -> tuple[bool, str | None]:
    fn = DETECTORS.get(name)
    if fn is None:
        return False, None
    try:
        return fn()
    except Exception:
        return False, None


__all__ = [
    "Compiler",
    "analyze",
    "any_compiler",
    "apply_path_fix",
    "cpp_report",
    "describe_plan",
    "detect",
    "find_compilers",
    "find_msvc",
    "format_report",
    "gcc_dirs",
    "install_vcpkg",
    "msys2_install_toolchain",
    "msys2_roots",
    "msys2_status",
    "path_fix_plan",
    "smoke_all",
    "smoke_test",
    "vcpkg_root",
]
