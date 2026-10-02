# -*- coding: utf-8 -*-
"""Глубокая проверка окружения: всё, из-за чего «VS Code / сборка не работает»,
хотя сам лаунчер ни при чём.

Поверх toolchains.environment_report (тулчейны, PATH, JAVA_HOME):
- VS Code: версия, вид установки, `code` в PATH, целы ли settings.json и
  keybindings.json, проблемы совместимости расширений;
- команды: какие python/node/git/gcc/java… реально запускаются, их версии,
  заглушка Microsoft Store вместо Python, несколько копий одной команды;
- переменные окружения: *_HOME/ROOT на несуществующие папки, PYTHONHOME,
  ELECTRON_RUN_AS_NODE и следы VS Code в постоянном окружении;
- PATH глазами «умной починки» (кто кого перекрывает);
- место на дисках, длинные пути, русские буквы в TEMP и профиле, прокси.

Только чтение. Итог — словарь с полем issues [{severity, text, action}], его
показывают окно («Обслуживание» → «Проверить окружение») и CLI --doctor.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import env_path
from .i18n import get_language

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _t(ru: str, en: str) -> str:
    return en if get_language() == "en" else ru


# Команды, которые обычно нужны из VS Code: (имя, аргументы версии).
COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("code", ("--version",)),
    ("git", ("--version",)),
    ("python", ("--version",)),
    ("py", ("--version",)),
    ("node", ("--version",)),
    ("npm", ("--version",)),
    ("java", ("-version",)),
    ("gcc", ("--version",)),
    ("g++", ("--version",)),
    ("clang", ("--version",)),
    ("gdb", ("--version",)),
    ("cmake", ("--version",)),
    ("ninja", ("--version",)),
    ("make", ("--version",)),
    ("mingw32-make", ("--version",)),
    ("dotnet", ("--version",)),
    ("go", ("version",)),
    ("rustc", ("--version",)),
    ("cargo", ("--version",)),
)

# Переменные-«дом» инструментов: если заданы, должны указывать на папку.
HOME_VARS = (
    "JAVA_HOME",
    "GOROOT",
    "GOPATH",
    "CARGO_HOME",
    "RUSTUP_HOME",
    "ANDROID_HOME",
    "ANDROID_SDK_ROOT",
    "VCPKG_ROOT",
    "DOTNET_ROOT",
    "MAVEN_HOME",
    "M2_HOME",
    "GRADLE_HOME",
    "NVM_HOME",
    "NVM_SYMLINK",
    "PYTHONHOME",
    "CONDA_PREFIX",
)


# --- команды --------------------------------------------------------------


def _all_on_path(name: str, path: str | None = None) -> list[str]:
    """Все копии команды в PATH по порядку поиска cmd (как `where`)."""
    exts = [e.lower() for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e]
    out: list[str] = []
    seen: set[str] = set()
    for d in env_path.path_entries(os.environ.get("PATH", "") if path is None else path):
        d = os.path.expandvars(d.strip().strip('"'))
        for ext in exts:
            f = os.path.join(d, name + ext)
            key = os.path.normcase(os.path.abspath(f))
            if key not in seen and os.path.isfile(f):
                seen.add(key)
                out.append(f)
                break
    return out


def is_store_stub(path: str) -> bool:
    """Заглушка Microsoft Store (WindowsApps\\python.exe нулевого размера):
    вместо Python открывает магазин."""
    low = path.lower()
    if "\\windowsapps\\" not in low:
        return False
    try:
        return os.path.getsize(path) == 0 or os.path.basename(low).startswith("python")
    except OSError:
        return True


def _version_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line and re.search(r"\d+\.\d+", line):
            return line[:90]
    return ""


def probe_command(name: str, args: tuple[str, ...], timeout: float = 8.0) -> dict:
    """{name, path, copies, version, stub, error} для одной команды."""
    copies = _all_on_path(name)
    rec = {
        "name": name,
        "path": copies[0] if copies else "",
        "copies": copies,
        "version": "",
        "stub": False,
        "error": "",
    }
    if not copies:
        return rec
    exe = copies[0]
    if is_store_stub(exe) and name.startswith("python"):
        rec["stub"] = True
        return rec
    cmd = [exe, *args]
    if exe.lower().endswith((".cmd", ".bat")):
        cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", exe, *args]
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_NO_WINDOW,
            stdin=subprocess.DEVNULL,
        )
        rec["version"] = _version_line(out.stdout) or _version_line(out.stderr)
        if out.returncode != 0 and not rec["version"]:
            rec["error"] = (
                (out.stderr or out.stdout or "").strip().splitlines()[-1:][0][:120]
                if (out.stderr or out.stdout or "").strip()
                else f"код {out.returncode}"
            )
    except subprocess.TimeoutExpired:
        rec["error"] = _t("не ответила за {s} с", "no answer in {s} s").format(s=int(timeout))
    except OSError as e:
        rec["error"] = str(e)[:120]
    return rec


def probe_commands(commands=COMMANDS) -> list[dict]:
    """Все команды параллельно: последовательно это 10–20 секунд."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(lambda c: probe_command(*c), commands))


def toolchain_mix(cmds: list[dict]) -> list[dict]:
    """gcc, g++ и gdb из разных сборок: программа собирается одной libstdc++, а
    запускается/отлаживается с другой — падения без понятной причины."""
    dirs = {c["name"]: os.path.normcase(os.path.dirname(c["path"]))
            for c in cmds if c["name"] in ("gcc", "g++", "gdb") and c["path"] and not c["error"]}
    if len(set(dirs.values())) <= 1:
        return []
    shown = ", ".join(f"{n}: {d}" for n, d in sorted(dirs.items()))
    return [{"severity": "warning", "action": "path", "text": _t(
        "Компилятор и отладчик C/C++ из разных сборок ({d}) — программа может падать при "
        "запуске или отладке. Оставьте одну сборку первой в PATH.",
        "The C/C++ compiler and debugger come from different builds ({d}) — programs may crash "
        "when run or debugged. Keep one build first on PATH.").format(d=shown)}]


# --- VS Code --------------------------------------------------------------


def _parse_jsonc_file(path: Path) -> str:
    """'' — файл в порядке (или его нет), иначе текст ошибки."""
    if not path.is_file():
        return ""
    from .detect import _loads_jsonc

    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as e:
        return str(e)
    if not text.strip():
        return ""
    data = _loads_jsonc(text)
    return "" if data is not None else _t("не разбирается как JSON", "cannot be parsed as JSON")


def vscode_info(code_cli: str | None) -> dict:
    from . import compat
    from .vscode import extensions_dir, vscode_user_settings_path

    install = compat.vscode_install_dir(code_cli)
    kind = ""
    if install is not None:
        low = str(install).lower()
        if (install / "data").is_dir():
            kind = "portable"
        elif "program files" in low:
            kind = "system"
        else:
            kind = "user"
    settings = vscode_user_settings_path(code_cli)
    ext_dir = extensions_dir(code_cli)
    try:
        n_ext = sum(1 for d in ext_dir.iterdir() if d.is_dir())
    except OSError:
        n_ext = 0
    return {
        "cli": code_cli or "",
        "version": compat.vscode_version(code_cli),
        "install": str(install or ""),
        "kind": kind,
        "on_path": bool(shutil.which("code")),
        "ext_dir": str(ext_dir),
        "ext_folders": n_ext,
        "ext_dir_env": os.environ.get("VSCODE_EXTENSIONS", ""),
        "settings": str(settings or ""),
        "settings_error": _parse_jsonc_file(settings) if settings else "",
        "keybindings_error": _parse_jsonc_file(settings.with_name("keybindings.json"))
        if settings
        else "",
    }


def compat_counts(code_cli: str | None) -> dict:
    """Сколько проблем совместимости у всего установленного (как в отчёте)."""
    from . import compat
    from .manifests import read_extension_manifests
    from .vscode import read_installed_from_disk

    installed = read_installed_from_disk(code_cli)
    issues = compat.check(
        installed,
        read_extension_manifests(code_cli),
        installed=installed,
        ctx=compat.context(code_cli),
    )
    return {s: sum(1 for i in issues if i["severity"] == s) for s in ("error", "warning", "info")}


# --- переменные окружения, диски, сеть ----------------------------------------


def env_var_issues() -> list[dict]:
    out: list[dict] = []
    for var in HOME_VARS:
        val = os.environ.get(var) or env_path.read_user_env_var(var)
        if not val:
            continue
        p = os.path.expandvars(val)
        if not os.path.isdir(p):
            out.append(
                {
                    "severity": "warning",
                    "action": "java" if var == "JAVA_HOME" else None,
                    "text": _t(
                        "{var} указывает на несуществующую папку: {p}",
                        "{var} points to a missing folder: {p}",
                    ).format(var=var, p=val),
                }
            )
    if os.environ.get("PYTHONHOME") or env_path.read_user_env_var("PYTHONHOME"):
        out.append(
            {
                "severity": "warning",
                "action": None,
                "text": _t(
                    "Задан PYTHONHOME — любой другой Python (и отладчик lldb) берёт чужую стандартную "
                    "библиотеку и падает. Обычно эту переменную надо удалить.",
                    "PYTHONHOME is set — any other Python (and the lldb debugger) picks up a foreign "
                    "standard library and crashes. Usually this variable should be removed.",
                ),
            }
        )
    if os.environ.get("PYTHONPATH") or env_path.read_user_env_var("PYTHONPATH"):
        out.append(
            {
                "severity": "info",
                "action": None,
                "text": _t(
                    "Задан PYTHONPATH — он подмешивается во все проекты Python.",
                    "PYTHONPATH is set — it leaks into every Python project.",
                ),
            }
        )
    for var in ("ELECTRON_RUN_AS_NODE", "ELECTRON_NO_ATTACH_CONSOLE"):
        if env_path.read_user_env_var(var):
            out.append(
                {
                    "severity": "error",
                    "action": None,
                    "text": _t(
                        "В постоянном окружении задан {var} — VS Code, запущенный не через лаунчер, "
                        "стартует без окна. Удалите переменную (Параметры → «Переменные среды»).",
                        "{var} is set in the persistent environment — VS Code started outside the "
                        "launcher starts without a window. Remove the variable (Settings → "
                        "'Environment variables').",
                    ).format(var=var),
                }
            )
    leftovers = [
        k
        for k in _user_env_names()
        if k.upper().startswith("VSCODE_") and k.upper() != "VSCODE_EXTENSIONS"
    ]
    if leftovers:
        out.append(
            {
                "severity": "warning",
                "action": None,
                "text": _t(
                    "В постоянном окружении остались служебные переменные VS Code: {v} — новые окна "
                    "могут «подключаться» к старому процессу.",
                    "VS Code service variables were left in the persistent environment: {v} — new "
                    "windows may attach to an old process.",
                ).format(v=", ".join(leftovers)),
            }
        )
    for label, val in (
        ("TEMP", os.environ.get("TEMP", "")),
        ("USERPROFILE", os.environ.get("USERPROFILE", "")),
    ):
        if val and any(ord(ch) > 127 for ch in val):
            out.append(
                {
                    "severity": "info",
                    "action": None,
                    "text": _t(
                        "В пути {var} есть не латинские буквы ({p}) — часть компиляторов и отладчиков "
                        "(gdb, старые MinGW) с такими путями не работает.",
                        "The {var} path has non-Latin letters ({p}) — some compilers and debuggers "
                        "(gdb, old MinGW) cannot handle such paths.",
                    ).format(var=label, p=val),
                }
            )
    return out


def fixable_env_vars() -> list[tuple[str, str, str]]:
    """Ваши (HKCU) переменные, которые безопасно удалить: [(имя, значение, почему)].

    - *_HOME/ROOT на несуществующую папку (кроме JAVA_HOME — у него своя починка);
    - ELECTRON_RUN_AS_NODE / ELECTRON_NO_ATTACH_CONSOLE — ломают запуск VS Code;
    - служебные VSCODE_* (кроме VSCODE_EXTENSIONS — это осознанный выбор).
    Системные переменные не трогаем: на них нужны права администратора."""
    out: list[tuple[str, str, str]] = []
    for var in HOME_VARS:
        if var == "JAVA_HOME":
            continue
        val = env_path.read_user_env_var(var)
        if val and not os.path.isdir(os.path.expandvars(val)):
            out.append((var, val, _t("папки нет", "folder is missing")))
    for name in _user_env_names():
        up = name.upper()
        if up in ("ELECTRON_RUN_AS_NODE", "ELECTRON_NO_ATTACH_CONSOLE") or (
            up.startswith("VSCODE_") and up != "VSCODE_EXTENSIONS"
        ):
            out.append((name, env_path.read_user_env_var(name),
                        _t("мешает запуску VS Code", "breaks VS Code startup")))
    return out


def fix_env_vars(names) -> list[str]:
    """Удалить переменные из HKCU; прежние значения — в env_history.txt рядом с
    конфигом, чтобы можно было вернуть руками. Возвращает строки отчёта."""
    from datetime import datetime

    from .paths import CONFIG_DIR

    out: list[str] = []
    for name in names:
        old = env_path.read_user_env_var(name)
        ok, msg = env_path.delete_user_env_var(name)
        if ok:
            try:
                with open(CONFIG_DIR / "env_history.txt", "a", encoding="utf-8") as fh:
                    fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\t{name}\t{old}\n")
            except OSError:
                pass
        out.append(msg)
    return out


def _user_env_names() -> list[str]:
    try:
        import winreg
    except ImportError:
        return []
    names: list[str] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            i = 0
            while True:
                try:
                    names.append(winreg.EnumValue(key, i)[0])
                except OSError:
                    break
                i += 1
    except OSError:
        pass
    return names


def long_paths_enabled() -> bool | None:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem"
        ) as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except Exception:
        return None


def disk_space(paths) -> list[dict]:
    """Свободное место на дисках, где живут VS Code, расширения и TEMP."""
    seen: set[str] = set()
    out: list[dict] = []
    for p in paths:
        if not p:
            continue
        drive = Path(p).anchor.upper()
        if not drive or drive in seen:
            continue
        seen.add(drive)
        try:
            u = shutil.disk_usage(drive)
        except OSError:
            continue
        out.append(
            {
                "drive": drive,
                "free_gb": round(u.free / 2**30, 1),
                "total_gb": round(u.total / 2**30, 1),
            }
        )
    return out


def proxy_info(settings_path: str) -> dict:
    env = {
        k: os.environ[k]
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy")
        if os.environ.get(k)
    }
    vs: dict = {}
    if settings_path:
        try:
            from .detect import _loads_jsonc

            data = _loads_jsonc(Path(settings_path).read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                vs = {
                    k: data[k]
                    for k in ("http.proxy", "http.proxyStrictSSL", "http.proxySupport")
                    if k in data
                }
        except Exception:
            pass
    return {"env": env, "vscode": vs}


# --- сборка отчёта ----------------------------------------------------------


def deep_report(code_cli: str | None) -> dict:
    """Полный отчёт. Медленные части (команды, совместимость) — параллельно и
    с таймаутами; любая сломавшаяся часть не роняет остальные."""
    from . import toolchains as tc

    rep = tc.environment_report()
    issues: list[dict] = []

    def safe(fn, default):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — одна проверка не должна рвать отчёт
            issues.append(
                {
                    "severity": "info",
                    "action": None,
                    "text": _t("Проверка не выполнилась: {e}", "A check failed: {e}").format(e=e),
                }
            )
            return default

    vs = safe(lambda: vscode_info(code_cli), {})
    rep["vscode"] = vs
    if not code_cli:
        issues.append(
            {
                "severity": "error",
                "action": None,
                "text": _t(
                    "VS Code не найден. Укажите его в «Обслуживание» → «Установка VS Code».",
                    "VS Code was not found. Set it in 'Maintenance' → 'VS Code installation'.",
                ),
            }
        )
    if vs.get("settings_error"):
        issues.append(
            {
                "severity": "error",
                "action": None,
                "text": _t(
                    "settings.json VS Code повреждён ({e}) — редактор работает с настройками по "
                    "умолчанию. Файл: {f}",
                    "VS Code settings.json is broken ({e}) — the editor runs "
                    "with default settings. File: {f}",
                ).format(e=vs["settings_error"], f=vs["settings"]),
            }
        )
    if vs.get("keybindings_error"):
        issues.append(
            {
                "severity": "warning",
                "action": None,
                "text": _t(
                    "keybindings.json повреждён — ваши сочетания клавиш не действуют.",
                    "keybindings.json is broken — your key bindings do not apply.",
                ),
            }
        )
    if code_cli and not vs.get("on_path"):
        issues.append(
            {
                "severity": "info",
                "action": None,
                "text": _t(
                    "Команды code нет в PATH — «code .» в терминале не сработает (лаунчеру это не мешает).",
                    "The code command is not on PATH — 'code .' in a terminal will not work "
                    "(the launcher does not need it).",
                ),
            }
        )

    cmds = safe(probe_commands, [])
    rep["commands"] = cmds
    for c in cmds:
        if c["stub"]:
            issues.append(
                {
                    "severity": "warning",
                    "action": "path",
                    "text": _t(
                        "«{n}» — заглушка Microsoft Store: вместо Python откроется магазин. Поставьте "
                        "Python или уберите заглушку («Починить PATH»).",
                        "'{n}' is the Microsoft Store stub: it opens the Store instead of Python. "
                        "Install Python or remove the stub ('Fix PATH').",
                    ).format(n=c["name"]),
                }
            )
        elif c["path"] and c["error"]:
            issues.append(
                {
                    "severity": "warning",
                    "action": None,
                    "text": _t(
                        "«{n}» есть в PATH, но не запускается: {e} ({p})",
                        "'{n}' is on PATH but does not run: {e} ({p})",
                    ).format(n=c["name"], e=c["error"], p=c["path"]),
                }
            )

    issues += toolchain_mix(cmds)

    compat_n = safe(lambda: compat_counts(code_cli), {}) if code_cli else {}
    rep["compat"] = compat_n
    if compat_n.get("error") or compat_n.get("warning"):
        issues.append(
            {
                "severity": "warning" if not compat_n.get("error") else "error",
                "action": "compat",
                "text": _t(
                    "Расширения: ошибок совместимости {e}, предупреждений {w} — подробности в отчёте "
                    "«Совместимость расширений».",
                    "Extensions: {e} compatibility errors, {w} warnings — see the 'Extension "
                    "compatibility' report.",
                ).format(e=compat_n.get("error", 0), w=compat_n.get("warning", 0)),
            }
        )

    issues += safe(env_var_issues, [])
    fixable = safe(fixable_env_vars, [])
    rep["fixable_env"] = fixable
    if fixable:
        issues.append({"severity": "info", "action": "envvar", "text": _t(
            "Можно убрать переменных: {n} ({names}) — кнопка «Исправить переменные».",
            "Variables that can be removed: {n} ({names}) — 'Fix variables' button.").format(
                n=len(fixable), names=", ".join(f[0] for f in fixable))})
    jh = rep.get("java_home") or {}
    if jh.get("set") and not jh.get("ok") and not any(i.get("action") == "java" for i in issues):
        issues.append(
            {
                "severity": "warning",
                "action": "java",
                "text": _t("JAVA_HOME: {p} — {r}", "JAVA_HOME: {p} — {r}").format(
                    p=jh.get("path"), r=jh.get("reason")
                ),
            }
        )

    def _pd():
        from . import path_doctor as pd

        r = pd.analyze(probe_versions=False)
        return [
            {"level": i.level, "title": i.title} for i in r.issues if i.level in ("error", "warn")
        ]

    pd_issues = safe(_pd, [])
    rep["path_doctor"] = pd_issues
    if pd_issues:
        n_err = sum(1 for i in pd_issues if i["level"] == "error")
        issues.append(
            {
                "severity": "error" if n_err else "warning",
                "action": "path",
                "text": _t(
                    "PATH: проблем {n} (из них серьёзных {e}) — например: {first}. «Починить PATH» "
                    "покажет и исправит.",
                    "PATH: {n} problems ({e} serious) — e.g. {first}. 'Fix PATH' "
                    "shows and fixes them.",
                ).format(n=len(pd_issues), e=n_err, first=pd_issues[0]["title"]),
            }
        )
    total_len = len(env_path.read_user_path()) + len(env_path.read_machine_path())
    if total_len > 8000:
        issues.append(
            {
                "severity": "warning",
                "action": "path",
                "text": _t(
                    "PATH длиннее 8000 символов ({n}) — cmd и часть программ его обрезают, хвостовые "
                    "записи «пропадают».",
                    "PATH is longer than 8000 characters ({n}) — cmd and some "
                    "programs truncate it and trailing entries 'disappear'.",
                ).format(n=total_len),
            }
        )

    disks = disk_space(
        [
            vs.get("install"),
            vs.get("ext_dir"),
            os.environ.get("TEMP"),
            os.environ.get("USERPROFILE"),
        ]
    )
    rep["disks"] = disks
    for d in disks:
        if d["free_gb"] < 2:
            sev = "error"
        elif d["free_gb"] < 10:
            sev = "warning"
        else:
            continue
        issues.append(
            {
                "severity": sev,
                "action": "cleanup",
                "text": _t(
                    "На диске {d} свободно {f} ГБ — установка расширений и сборка могут падать. "
                    "Поможет «Уборка VS Code».",
                    "Only {f} GB free on drive {d} — extension installs "
                    "and builds may fail. 'VS Code cleanup' helps.",
                ).format(d=d["drive"], f=d["free_gb"]),
            }
        )

    lp = long_paths_enabled()
    rep["long_paths"] = lp
    if lp is False:
        issues.append(
            {
                "severity": "info",
                "action": None,
                "text": _t(
                    "Длинные пути Windows выключены (LongPathsEnabled) — глубокие node_modules и "
                    "проекты с длинными путями могут не собираться.",
                    "Windows long paths are off (LongPathsEnabled) — deep node_modules and projects "
                    "with long paths may fail to build.",
                ),
            }
        )
    rep["proxy"] = safe(lambda: proxy_info(vs.get("settings", "")), {})
    order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: order.get(i["severity"], 9))
    rep["issues"] = issues
    return rep


def format_lines(rep: dict) -> list[str]:
    """Отчёт текстом: сначала итог и проблемы, потом подробности по разделам."""
    marks = {
        "error": _t("ОШИБКА", "ERROR"),
        "warning": _t("ВНИМАНИЕ", "WARNING"),
        "info": _t("к сведению", "note"),
    }
    issues = rep.get("issues") or []
    n = {s: sum(1 for i in issues if i["severity"] == s) for s in marks}
    lines = [
        _t(
            "Итог: ошибок {e}, предупреждений {w}, к сведению {i}.",
            "Summary: {e} errors, {w} warnings, {i} notes.",
        ).format(e=n["error"], w=n["warning"], i=n["info"]),
        "",
    ]
    if issues:
        lines.append(_t("ПРОБЛЕМЫ", "PROBLEMS"))
        lines += [f"[{marks[i['severity']]}] {i['text']}" for i in issues]
    else:
        lines.append(_t("Проблем не найдено.", "No problems found."))
    lines.append("")

    vs = rep.get("vscode") or {}
    kinds = {
        "user": _t("для пользователя", "per-user"),
        "system": _t("для всех", "system-wide"),
        "portable": _t("портативная", "portable"),
    }
    lines.append("VS CODE")
    lines.append(
        "  "
        + _t("версия {v}, установка: {k}", "version {v}, install: {k}").format(
            v=vs.get("version") or "?", k=kinds.get(vs.get("kind", ""), "?")
        )
    )
    if vs.get("install"):
        lines.append("  " + vs["install"])
    lines.append(
        "  "
        + _t("расширений (папок): {n} — {d}", "extensions (folders): {n} — {d}").format(
            n=vs.get("ext_folders", 0), d=vs.get("ext_dir", "")
        )
    )
    if vs.get("ext_dir_env"):
        lines.append("  VSCODE_EXTENSIONS = " + vs["ext_dir_env"])
    c = rep.get("compat") or {}
    if c:
        lines.append(
            "  "
            + _t(
                "совместимость: ошибок {e}, предупреждений {w}, к сведению {i}",
                "compatibility: {e} errors, {w} warnings, {i} notes",
            ).format(e=c.get("error", 0), w=c.get("warning", 0), i=c.get("info", 0))
        )
    lines.append("")

    lines.append(_t("КОМАНДЫ (что запустится в терминале)", "COMMANDS (what a terminal runs)"))
    for cmd in rep.get("commands") or []:
        if not cmd["path"]:
            lines.append(f"  -  {cmd['name']:<8} " + _t("не найдена", "not found"))
            continue
        state = (
            _t("заглушка Microsoft Store", "Microsoft Store stub")
            if cmd["stub"]
            else cmd["version"] or cmd["error"] or "?"
        )
        mark = "✗" if cmd["stub"] or cmd["error"] else "✓"
        lines.append(f"  {mark}  {cmd['name']:<8} {state}")
        lines.append(f"       {cmd['path']}")
        if len(cmd["copies"]) > 1:
            lines.append(
                "       "
                + _t(
                    "ещё копий в PATH: {n} (используется первая)",
                    "more copies on PATH: {n} (the first one is used)",
                ).format(n=len(cmd["copies"]) - 1)
            )
    lines.append("")

    tools = rep.get("tools") or []
    lines.append(_t("ТУЛЧЕЙНЫ ({n})", "TOOLCHAINS ({n})").format(n=len(tools)))
    lines += [f"  ✓ {t['title']}  —  {t.get('version') or ''}" for t in tools] or ["  —"]
    lines.append("  winget: " + (rep.get("winget") or _t("не найден", "not found")))
    lines.append("")

    ph, pu, pm = rep.get("path", {}), rep.get("path_user", {}), rep.get("path_machine", {})
    lines.append("PATH")
    lines.append(
        "  "
        + _t("записей {n}, длина {l}", "{n} entries, length {l}").format(
            n=ph.get("count", 0), l=ph.get("length", 0)
        )
    )
    lines.append(
        "  "
        + _t(
            "ваш: дублей {d}, мёртвых {m}; системный: дублей {sd}, мёртвых {sm}",
            "user: {d} duplicates, {m} dead; system: {sd} duplicates, {sm} dead",
        ).format(
            d=len(pu.get("duplicates", [])),
            m=len(pu.get("missing", [])),
            sd=len(pm.get("duplicates", [])),
            sm=len(pm.get("missing", [])),
        )
    )
    for i in (rep.get("path_doctor") or [])[:8]:
        lines.append(f"  • {i['title']}")
    jh = rep.get("java_home") or {}
    lines.append("  JAVA_HOME: " + (jh.get("path") or _t("не задан", "not set")))
    lines.append("")

    disks = rep.get("disks") or []
    if disks:
        lines.append(_t("ДИСКИ", "DRIVES"))
        lines += [
            "  "
            + _t("{d} свободно {f} из {t} ГБ", "{d} {f} of {t} GB free").format(
                d=d["drive"], f=d["free_gb"], t=d["total_gb"]
            )
            for d in disks
        ]
        lines.append("")
    px = rep.get("proxy") or {}
    if px.get("env") or px.get("vscode"):
        lines.append(_t("СЕТЬ / ПРОКСИ", "NETWORK / PROXY"))
        lines += [f"  {k} = {v}" for k, v in (px.get("env") or {}).items()]
        lines += [f"  settings.json: {k} = {v}" for k, v in (px.get("vscode") or {}).items()]
    return lines
