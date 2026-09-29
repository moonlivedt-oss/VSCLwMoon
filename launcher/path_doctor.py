# -*- coding: utf-8 -*-
r"""Умная починка PATH: анализ, план с предпросмотром, применение и откат.

Простая чистка (env_path.clean_*) убирает дубли и мёртвые записи в одной ветке.
Этого мало: реальные поломки PATH на Windows — это порядок и затенение.

Как Windows собирает PATH: сначала системный (HKLM), потом пользовательский
(HKCU), команда ищется по каталогам слева направо с расширениями из PATHEXT.
Поэтому модуль смотрит на обе ветки вместе и на то, ЧТО реально запустится:

- мусор: пустые сегменты, кавычки/пробелы/хвостовой слэш, дубли внутри ветки,
  пользовательская копия системной записи, мёртвые каталоги, %VAR%, которых
  нет, файл вместо каталога; каталог на отключённом диске не мёртвый —
  только отмечается;
- затенение: заглушка Microsoft Store (`python` из WindowsApps) раньше
  настоящего Python; каталоги раньше System32, которые подменяют
  find/sort/where; несколько тулчейнов GCC; `java` не из JAVA_HOME; более
  свежая версия инструмента спрятана за старой;
- длина: длинные записи сокращаются через %LOCALAPPDATA%, %USERPROFILE%…

Каждая проблема — отдельный пункт со своими операциями (удалить, заменить,
передвинуть). Перед применением `preview` симулирует новый PATH и показывает,
какие команды начнут запускать другой файл, а какие пропадут. Запись — с
бэкапом обеих веток; `restore_backup` возвращает любой бэкап.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import env_path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Команды, за которыми следим при симуляции «что запустится».
WATCH_TOOLS = (
    "python",
    "python3",
    "py",
    "pip",
    "node",
    "npm",
    "git",
    "java",
    "javac",
    "g++",
    "gcc",
    "gdb",
    "clang",
    "clangd",
    "cmake",
    "ninja",
    "mingw32-make",
    "go",
    "cargo",
    "rustc",
    "dotnet",
    "php",
    "ruby",
    "deno",
    "code",
    "winget",
    "powershell",
    "pwsh",
    "where",
    "find",
    "sort",
    "curl",
    "tar",
    "ssh",
)
# Утилиты Windows, которые легко подменить каталогом раньше System32
# (классика — Git\usr\bin с юниксовыми find/sort).
SYSTEM_TOOLS = ("find", "sort", "where", "timeout", "tar", "curl", "ssh", "more", "tree", "fc")
# Семейства, где «новее спрятан за старым» — реальная путаница.
# Python сюда не входит: у него пара каталогов (python и Scripts с pip), и поднять
# один без другого — хуже, чем оставить; для него — подсказка про «py -X.Y».
VERSION_FAMILIES = ("node", "java", "go", "cmake", "git")
LENGTH_WARN = 2047
# Префиксы для сокращения записей (только в пользовательском PATH: он
# REG_EXPAND_SZ, и переменные пользователя там раскрываются).
_COMPACT_VARS = ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "ProgramFiles(x86)", "ProgramFiles")


def _t(ru: str, en: str) -> str:
    from .i18n import get_language

    return en if get_language() == "en" else ru


# --- записи -------------------------------------------------------------------


@dataclass
class Entry:
    scope: str  # machine | user
    index: int  # позиция в исходной строке своей ветки (с пустыми сегментами)
    raw: str

    @property
    def clean(self) -> str:
        return clean_raw(self.raw)

    @property
    def expanded(self) -> str:
        return os.path.expandvars(self.clean)

    @property
    def norm(self) -> str:
        return norm(self.raw)


def clean_raw(raw: str) -> str:
    """Запись без внешних пробелов и кавычек и без хвостового слэша (кроме
    корня диска «C:\\»)."""
    s = (raw or "").strip().strip('"').strip()
    if len(s) > 3 and s.endswith(("\\", "/")):
        s = s.rstrip("\\/")
    return s


def norm(raw: str) -> str:
    s = clean_raw(raw)
    try:
        return os.path.normcase(os.path.normpath(os.path.expandvars(s)))
    except Exception:
        return s.lower()


def split_raw(value: str) -> list[str]:
    """Сегменты PATH как есть, включая пустые (их тоже надо показать)."""
    if not value:
        return []
    parts = value.split(";")
    # Хвостовая «;» — обычное дело и не проблема: последний пустой сегмент не считаем.
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return parts


def entry_state(e: Entry) -> str:
    """ok | empty | unresolved | offline | missing | file."""
    c = e.clean
    if not c:
        return "empty"
    exp = os.path.expandvars(c)
    if "%" in exp:
        return "unresolved"
    drive = os.path.splitdrive(exp)[0]
    if drive and len(drive) == 2 and not os.path.isdir(drive + "\\"):
        return "offline"
    try:
        p = Path(exp)
        if p.is_dir():
            return "ok"
        if p.exists():
            return "file"
    except OSError:
        return "missing"
    return "missing"


# --- что запустится ---------------------------------------------------------------


def _pathext() -> list[str]:
    raw = os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD"
    exts = [x.lower() for x in raw.split(";") if x]
    return [x for x in exts if x in (".com", ".exe", ".bat", ".cmd")] or [".exe"]


def _dir_has(d: str, tool: str, exts: list[str]) -> str | None:
    for ext in exts:
        p = os.path.join(d, tool + ext)
        if os.path.lexists(p):  # алиасы WindowsApps — reparse points
            return p
    return None


def resolve_all(dirs: list[str], tools=WATCH_TOOLS) -> dict[str, str]:
    """{команда: полный путь}, как её нашёл бы cmd по этому списку каталогов."""
    exts = _pathext()
    out: dict[str, str] = {}
    for tool in tools:
        for d in dirs:
            hit = _dir_has(d, tool, exts)
            if hit:
                out[tool] = hit
                break
    return out


def providers(dirs: list[str], tool: str) -> list[str]:
    """Все каталоги по порядку, где есть команда `tool`."""
    exts = _pathext()
    return [d for d in dirs if _dir_has(d, tool, exts)]


def _probe_version(exe: str) -> tuple[int, ...]:
    if "windowsapps" in exe.lower():
        return ()
    try:
        out = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=_NO_WINDOW,
        )
    except Exception:
        return ()
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", (out.stdout or "") + " " + (out.stderr or ""))
    return tuple(int(g) for g in m.groups() if g) if m else ()


# --- проблемы и операции -------------------------------------------------------------


@dataclass(frozen=True)
class Op:
    """Операция над веткой PATH. idx — индекс исходного сегмента в своей ветке.
    remove | replace(new) | move_front | move_end | move_after(anchor_scope,
    anchor_idx) | to_machine_front | insert_front(new) (idx=-1)."""

    action: str
    scope: str
    idx: int
    new: str = ""
    anchor_idx: int = -1


@dataclass
class Issue:
    id: str
    kind: str
    level: str  # error | warn | info
    title: str
    detail: str
    ops: list[Op] = field(default_factory=list)
    selected: bool = True
    admin: bool = False

    @property
    def fixable(self) -> bool:
        return bool(self.ops)


@dataclass
class Report:
    machine_raw: str
    user_raw: str
    entries: list[Entry]
    issues: list[Issue]
    resolved: dict[str, str]

    def by_id(self, iid: str) -> Issue | None:
        return next((i for i in self.issues if i.id == iid), None)


def _parse(machine_raw: str, user_raw: str) -> list[Entry]:
    out = [Entry("machine", i, r) for i, r in enumerate(split_raw(machine_raw))]
    out += [Entry("user", i, r) for i, r in enumerate(split_raw(user_raw))]
    return out


def _effective_dirs(entries: list[Entry]) -> list[str]:
    return [e.expanded for e in entries if e.clean]


def _system32() -> str:
    return norm(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32"))


def _reserve_norms() -> set[str]:
    keep = {norm(x) for x in env_path.reserve_dirs()}
    try:
        from .toolchains import catalog_path_hints

        keep |= {norm(x) for x in catalog_path_hints()}
    except Exception:
        pass
    return keep


def analyze(
    machine_raw: str | None = None, user_raw: str | None = None, probe_versions: bool = True
) -> Report:
    """Разобрать обе ветки и найти проблемы. Строки можно передать явно (тесты)."""
    machine_raw = env_path.read_machine_path() if machine_raw is None else machine_raw
    user_raw = env_path.read_user_path() if user_raw is None else user_raw
    entries = _parse(machine_raw, user_raw)
    issues: list[Issue] = []
    counter = [0]

    def add(kind, level, title, detail, ops=(), selected=True):
        counter[0] += 1
        admin = any(o.scope == "machine" or o.action == "to_machine_front" for o in ops)
        issues.append(
            Issue(
                f"{kind}-{counter[0]}",
                kind,
                level,
                title,
                detail,
                list(ops),
                selected and bool(ops),
                admin,
            )
        )

    def where(e: Entry) -> str:
        return _t("системный", "system") if e.scope == "machine" else _t("ваш", "user")

    reserve = _reserve_norms()
    seen: dict[str, Entry] = {}
    dead: set[tuple[str, int]] = set()
    for e in entries:
        st = entry_state(e)
        label = e.raw.strip() or _t("(пусто)", "(empty)")
        if st == "empty":
            add(
                "empty",
                "info",
                _t("Пустой сегмент", "Empty segment"),
                _t("Лишняя «;» в {w} PATH.", "A stray ';' in the {w} PATH.").format(w=where(e)),
                [Op("remove", e.scope, e.index)],
            )
            dead.add((e.scope, e.index))
            continue
        if st == "unresolved":
            add(
                "unresolved",
                "warn",
                label,
                _t(
                    "Переменная в пути не задана — запись никуда не ведёт.",
                    "The variable in this entry is not set — it leads nowhere.",
                ),
                [Op("remove", e.scope, e.index)],
            )
            dead.add((e.scope, e.index))
            continue
        if st == "offline":
            add(
                "offline",
                "info",
                label,
                _t(
                    "Диск сейчас не подключён. Запись не трогаем: вернётся вместе с диском.",
                    "The drive is not connected right now. Left as is: it works again when the "
                    "drive is back.",
                ),
            )
            continue
        if st == "file":
            add(
                "file",
                "warn",
                label,
                _t(
                    "Это файл, а не каталог — Windows такую запись пропускает.",
                    "This is a file, not a folder — Windows skips such an entry.",
                ),
                [Op("remove", e.scope, e.index)],
            )
            dead.add((e.scope, e.index))
            continue
        if st == "missing":
            if e.norm in reserve:
                continue  # каталог появится при установке инструмента
            add(
                "missing",
                "warn",
                label,
                _t(
                    "Каталога нет: программу удалили или перенесли.",
                    "The folder does not exist: the program was removed or moved.",
                ),
                [Op("remove", e.scope, e.index)],
            )
            dead.add((e.scope, e.index))
            continue
        # дубли
        first = seen.get(e.norm)
        if first is not None:
            if first.scope == e.scope:
                add(
                    "dup",
                    "info",
                    label,
                    _t(
                        "Повтор в {w} PATH — второй экземпляр ничего не даёт.",
                        "Repeated in the {w} PATH — the second copy does nothing.",
                    ).format(w=where(e)),
                    [Op("remove", e.scope, e.index)],
                )
            else:
                add(
                    "cross_dup",
                    "info",
                    label,
                    _t(
                        "Уже есть в системном PATH, который просматривается раньше вашего — "
                        "ваша копия лишняя.",
                        "Already in the system PATH, which is searched first — your copy is "
                        "redundant.",
                    ),
                    [Op("remove", e.scope, e.index)],
                )
            dead.add((e.scope, e.index))
            continue
        seen[e.norm] = e
        # Хвостовой слэш безвреден (его ставят сами установщики) — трогаем только
        # кавычки и пробелы: они реально ломают часть программ.
        if e.raw.strip().strip('"').strip() != e.raw:
            add(
                "tidy",
                "info",
                label,
                _t(
                    "Кавычки или пробелы вокруг пути ломают часть программ: {c}",
                    "Quotes or spaces around the path break some programs: {c}",
                ).format(c=e.clean),
                [Op("replace", e.scope, e.index, new=e.clean)],
            )

    live = [e for e in entries if (e.scope, e.index) not in dead and entry_state(e) == "ok"]
    dirs = [e.expanded for e in live]
    resolved = resolve_all(dirs)
    by_norm = {e.norm: e for e in live}

    def entry_of(path: str) -> Entry | None:
        return by_norm.get(norm(os.path.dirname(path)))

    # Заглушка Microsoft Store раньше настоящего Python.
    for tool in ("python", "python3"):
        hit = resolved.get(tool)
        if not hit or "\\microsoft\\windowsapps" not in hit.lower():
            continue
        stub = entry_of(hit)
        real = [d for d in providers(dirs, tool) if "windowsapps" not in d.lower()]
        if stub is None:
            continue
        if real:
            real_e = by_norm.get(norm(real[0]))
            if real_e is not None and real_e.scope == stub.scope:
                add(
                    "store_alias",
                    "warn",
                    _t("«{t}» открывает Microsoft Store", "'{t}' opens the Microsoft Store").format(
                        t=tool
                    ),
                    _t(
                        "Заглушка из WindowsApps стоит раньше настоящего Python ({r}). WindowsApps "
                        "переедет в конец — winget и другие команды оттуда останутся.",
                        "The WindowsApps stub comes before the real Python ({r}). WindowsApps moves "
                        "to the end — winget and other commands from it keep working.",
                    ).format(r=real[0]),
                    [Op("move_end", stub.scope, stub.index)],
                )
                break
        else:
            add(
                "store_alias",
                "info",
                _t("«{t}» — заглушка Microsoft Store", "'{t}' is a Microsoft Store stub").format(
                    t=tool
                ),
                _t(
                    "Настоящий Python не найден: команда откроет Магазин. Поставьте Python в "
                    "«Языках» или отключите алиас в «Параметры → Приложения → Псевдонимы».",
                    "No real Python found: the command opens the Store. Install Python in "
                    "'Languages' or turn the alias off in Settings → Apps → App execution aliases.",
                ),
            )
            break

    # Каталоги раньше System32 подменяют утилиты Windows.
    sys32 = _system32()
    sys_e = next((e for e in live if e.scope == "machine" and e.norm == sys32), None)
    if sys_e is None:
        add(
            "no_system32",
            "error",
            _t("В системном PATH нет System32", "System32 is missing from the system PATH"),
            _t(
                "Без него не работают базовые команды Windows. Вернуть в начало (нужны права "
                "администратора).",
                "Basic Windows commands break without it. Put it back at the start (needs "
                "administrator rights).",
            ),
            [Op("insert_front", "machine", -1, new=r"%SystemRoot%\system32")],
        )
    else:
        exts = _pathext()
        for e in live:
            if e.scope != "machine" or e.index >= sys_e.index or e.norm == sys32:
                continue
            shadowed = [
                t
                for t in SYSTEM_TOOLS
                if _dir_has(e.expanded, t, exts) and _dir_has(sys_e.expanded, t, exts)
            ]
            if shadowed:
                add(
                    "shadow_system",
                    "warn",
                    e.raw.strip(),
                    _t(
                        "Стоит раньше System32 и подменяет команды Windows: {t}. Переедет сразу "
                        "после System32.",
                        "Comes before System32 and overrides Windows commands: {t}. Moves right "
                        "after System32.",
                    ).format(t=", ".join(shadowed)),
                    [Op("move_after", "machine", e.index, anchor_idx=sys_e.index)],
                )

    # Несколько тулчейнов GCC.
    gxx = providers(dirs, "g++")
    if len(gxx) > 1:
        primary = by_norm.get(norm(gxx[0]))
        others = [by_norm.get(norm(d)) for d in gxx[1:]]
        others = [o for o in others if o is not None]
        ops = [Op("move_end", o.scope, o.index) for o in others]
        if (
            primary is not None
            and primary.scope == "user"
            and any(o.scope == "machine" for o in others)
        ):
            ops = [Op("to_machine_front", "user", primary.index)]
        if ops:
            add(
                "gcc_mix",
                "warn",
                _t("Несколько тулчейнов GCC", "Several GCC toolchains"),
                _t(
                    "Основной — {p}. Остальные уедут в конец PATH, чтобы программы не "
                    "подхватывали чужую libstdc++: {o}.",
                    "Main one: {p}. The others move to the end of PATH so programs do not load "
                    "a foreign libstdc++: {o}.",
                ).format(p=gxx[0], o="; ".join(gxx[1:])),
                ops,
            )

    # Каталог тулчейна (MSYS2/MinGW) перекрывает отдельно установленные программы:
    # в ucrt64\bin есть свои python, cmake, perl… и, стоя раньше, он подменяет
    # Python со всеми вашими pip-пакетами.
    for issue in _toolchain_shadow(live, dirs, by_norm):
        add(*issue[:4], issue[4], selected=issue[5])

    # java не из JAVA_HOME.
    jh = os.environ.get("JAVA_HOME") or env_path.read_user_env_var("JAVA_HOME")
    java = resolved.get("java")
    if jh and java:
        jbin = norm(os.path.join(jh, "bin"))
        if norm(os.path.dirname(java)) != jbin and os.path.isfile(
            os.path.join(jh, "bin", "java.exe")
        ):
            want = by_norm.get(jbin)
            cur = entry_of(java)
            if want is not None and cur is not None and want.scope == cur.scope:
                add(
                    "java_home",
                    "warn",
                    _t("java не из JAVA_HOME", "java is not from JAVA_HOME"),
                    _t(
                        "Команда java берётся из {c}, а JAVA_HOME указывает на {h}. Maven, Gradle и "
                        "VS Code возьмут разные JDK. {h}\\bin встанет раньше.",
                        "The java command comes from {c}, but JAVA_HOME points to {h}. Maven, "
                        "Gradle and VS Code will use different JDKs. {h}\\bin moves earlier.",
                    ).format(c=os.path.dirname(java), h=jh),
                    [Op("move_before", want.scope, want.index, anchor_idx=cur.index)],
                )

    # Свежая версия спрятана за старой.
    if probe_versions:
        for tool in VERSION_FAMILIES:
            if tool == "java" and any(i.kind == "java_home" for i in issues):
                continue
            # Каталоги компиляторов не в счёт: их python/cmake — часть тулчейна, а не
            # «ваш» инструмент (иначе проверка спорила бы с toolchain_shadow).
            provs = [
                d
                for d in providers(dirs, tool)
                if "windowsapps" not in d.lower() and not _is_toolchain_dir(d)
            ]
            if len(provs) < 2:
                continue
            exts = _pathext()
            vers = [(d, _probe_version(_dir_has(d, tool, exts) or "")) for d in provs[:4]]
            first_v = vers[0][1]
            best = max(vers, key=lambda x: x[1])
            if best[1] and first_v and best[1] > first_v:
                fe, be = by_norm.get(norm(vers[0][0])), by_norm.get(norm(best[0]))
                if fe is None or be is None:
                    continue
                if be.scope == fe.scope:
                    op = Op("move_before", be.scope, be.index, anchor_idx=fe.index)
                elif be.scope == "user":
                    op = Op("to_machine_front", "user", be.index)
                else:
                    continue
                add(
                    "newer_hidden",
                    "info",
                    _t(
                        "{t}: запускается {a}, а есть {b}", "{t}: runs {a}, but {b} is installed"
                    ).format(t=tool, a=".".join(map(str, first_v)), b=".".join(map(str, best[1]))),
                    _t(
                        "Сейчас первым в PATH {f}. Поднять {b} выше? Проверьте, что ваши проекты "
                        "не рассчитаны на старую версию.",
                        "{f} is first on PATH now. Move {b} up? Make sure your projects do not rely "
                        "on the older version.",
                    ).format(f=vers[0][0], b=best[0]),
                    [op],
                    selected=False,
                )

    # python из PATH старше того, что знает py-лаунчер.
    py_issue = _python_launcher_hint(resolved)
    if py_issue:
        add("python_version", "info", py_issue[0], py_issue[1])

    # Длина.
    for scope, raw in (("user", user_raw), ("machine", machine_raw)):
        if len(raw) <= LENGTH_WARN:
            continue
        ops = []
        if scope == "user":
            for e in entries:
                if e.scope == "user" and (e.scope, e.index) not in dead:
                    short = compact(e.clean)
                    if short != e.clean:
                        ops.append(Op("replace", "user", e.index, new=short))
        add(
            "length",
            "warn" if scope == "user" else "info",
            _t(
                "{w} PATH длиннее {n} символов ({l})",
                "{w} PATH is longer than {n} characters ({l})",
            ).format(
                w=_t("Ваш", "User") if scope == "user" else _t("Системный", "System"),
                n=LENGTH_WARN,
                l=len(raw),
            ),
            _t(
                "Часть старых программ и setx обрезают такой PATH. Длинные записи сократятся через "
                "%LOCALAPPDATA%/%USERPROFILE% — смысл тот же.",
                "Some old programs and setx truncate such a PATH. Long entries are shortened with "
                "%LOCALAPPDATA%/%USERPROFILE% — same meaning.",
            ),
            ops,
        )

    return Report(machine_raw, user_raw, entries, issues, resolved)


SHADOW_TOOLS = ("python", "python3", "pip", "git", "node", "npm", "cmake", "ninja", "perl", "curl")
# Их подмена ломает заметнее всего (пакеты pip, глобальные npm) — чиним по умолчанию.
SHADOW_IMPORTANT = {"python", "python3", "pip", "git", "node", "npm"}


def _is_toolchain_dir(d: str) -> bool:
    try:
        return any(os.path.isfile(os.path.join(d, n)) for n in ("g++.exe", "gcc.exe"))
    except OSError:
        return False


def _toolchain_shadow(live: list[Entry], dirs: list[str], by_norm: dict) -> list[tuple]:
    """Проблемы «каталог тулчейна раньше отдельной программы»:
    [(kind, level, title, detail, ops, selected)]."""
    found: dict[str, dict] = {}  # норм. каталог тулчейна -> {tools, anchor}
    for tool in SHADOW_TOOLS:
        provs = providers(dirs, tool)
        if len(provs) < 2 or not _is_toolchain_dir(provs[0]):
            continue
        tc = by_norm.get(norm(provs[0]))
        alt = next(
            (p for p in provs[1:] if not _is_toolchain_dir(p) and "windowsapps" not in p.lower()),
            None,
        )
        alt_e = by_norm.get(norm(alt)) if alt else None
        if tc is None or alt_e is None or alt_e.scope != tc.scope:
            continue
        rec = found.setdefault(tc.norm, {"entry": tc, "tools": [], "alts": [], "anchor": -1})
        rec["tools"].append(tool)
        rec["alts"].append(alt)
        rec["anchor"] = max(rec["anchor"], alt_e.index)
    out = []
    for rec in found.values():
        tc = rec["entry"]
        tools = ", ".join(rec["tools"])
        out.append(
            (
                "toolchain_shadow",
                "warn",
                _t("{d} перекрывает: {t}", "{d} overrides: {t}").format(d=tc.raw.strip(), t=tools),
                _t(
                    "В каталоге компилятора есть свои {t}, и он стоит раньше отдельно установленных "
                    "({a}). Каталог переедет сразу после них: компилятор останется доступен, а {t} "
                    "снова будут вашими.",
                    "The compiler folder ships its own {t} and comes before your standalone ones "
                    "({a}). It moves right after them: the compiler stays available and {t} are "
                    "yours again.",
                ).format(t=tools, a="; ".join(dict.fromkeys(rec["alts"]))),
                [Op("move_after", tc.scope, tc.index, anchor_idx=rec["anchor"])],
                bool(set(rec["tools"]) & SHADOW_IMPORTANT),
            )
        )
    return out


def _python_launcher_hint(resolved: dict[str, str]) -> tuple[str, str] | None:
    """`python` в PATH старше самого свежего Python, известного `py`.

    Только подсказка, без операции: поменять `python` может сломать проекты,
    настроенные на старую версию, а `py -3.14` работает и так."""
    py, python = resolved.get("py"), resolved.get("python")
    if not py or not python or "windowsapps" in python.lower():
        return None
    try:
        out = subprocess.run(
            [py, "-0p"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=_NO_WINDOW,
        )
    except Exception:
        return None
    best: tuple[tuple[int, ...], str] | None = None
    for line in (out.stdout or "").splitlines():
        m = re.search(r"-V:(\d+)\.(\d+)\S*\s+\*?\s*(\S.*python\.exe)", line, re.I)
        if m:
            ver = (int(m.group(1)), int(m.group(2)))
            if best is None or ver > best[0]:
                best = (ver, m.group(3).strip())
    cur = _probe_version(python)[:2]
    if not best or not cur or best[0] <= cur:
        return None
    a, b = ".".join(map(str, cur)), ".".join(map(str, best[0]))
    return (
        _t("python — {a}, а установлен {b}", "python is {a}, but {b} is installed").format(
            a=a, b=b
        ),
        _t(
            "Команда python запускает {a} ({p}). Свежий {b} вызывается как «py -{b}». "
            "Менять python не предлагаю: проекты на {a} могут на него рассчитывать.",
            "The python command runs {a} ({p}). The newer {b} is available as 'py -{b}'. "
            "Not changing python: projects on {a} may rely on it.",
        ).format(a=a, b=b, p=os.path.dirname(python)),
    )


def compact(path: str) -> str:
    """Заменить известный префикс переменной (%LOCALAPPDATA%\\…)."""
    low = path.lower()
    for var in _COMPACT_VARS:
        val = os.environ.get(var)
        if val and low.startswith(val.lower().rstrip("\\") + "\\"):
            return f"%{var}%" + path[len(val.rstrip("\\")) :]
    return path


# --- план ---------------------------------------------------------------------------


def build(report: Report, ids: set[str]) -> tuple[str, str]:
    """Новые (machine, user) после операций выбранных проблем."""
    lists = {
        "machine": [{"idx": i, "raw": r} for i, r in enumerate(split_raw(report.machine_raw))],
        "user": [{"idx": i, "raw": r} for i, r in enumerate(split_raw(report.user_raw))],
    }
    ops = [o for iss in report.issues if iss.id in ids for o in iss.ops]

    def find(scope, idx):
        for pos, it in enumerate(lists[scope]):
            if it["idx"] == idx:
                return pos
        return None

    # Порядок: замены, удаления, затем перестановки — так индексы остаются валидными.
    for o in ops:
        if o.action == "replace":
            pos = find(o.scope, o.idx)
            if pos is not None:
                lists[o.scope][pos]["raw"] = o.new
    removed = {(o.scope, o.idx) for o in ops if o.action == "remove"}
    for scope in lists:
        lists[scope] = [it for it in lists[scope] if (scope, it["idx"]) not in removed]
    for o in ops:
        if o.action in ("remove", "replace"):
            continue
        if o.action == "insert_front":
            lists[o.scope].insert(0, {"idx": -100, "raw": o.new})
            continue
        pos = find(o.scope, o.idx)
        if pos is None:
            continue
        item = lists[o.scope].pop(pos)
        if o.action == "move_front":
            lists[o.scope].insert(0, item)
        elif o.action == "move_end":
            lists[o.scope].append(item)
        elif o.action == "to_machine_front":
            lists["machine"].insert(0, item)
        elif o.action in ("move_after", "move_before"):
            apos = find(o.scope, o.anchor_idx)
            if apos is None:
                lists[o.scope].insert(pos, item)
            else:
                lists[o.scope].insert(apos + 1 if o.action == "move_after" else apos, item)
    join = lambda items: ";".join(it["raw"] for it in items)  # noqa: E731
    return join(lists["machine"]), join(lists["user"])


def _dirs_of(machine: str, user: str) -> list[str]:
    return _effective_dirs(_parse(machine, user))


def preview(report: Report, ids: set[str]) -> dict:
    """Что изменится: новые строки, какие команды запустят другой файл, какие
    пропадут, нужны ли права администратора."""
    machine, user = build(report, ids)
    before = resolve_all(_dirs_of(report.machine_raw, report.user_raw))
    after = resolve_all(_dirs_of(machine, user))
    changed = [
        (t, before.get(t), after.get(t))
        for t in WATCH_TOOLS
        if before.get(t) and after.get(t) and norm(before[t]) != norm(after[t])
    ]
    lost = [t for t in WATCH_TOOLS if before.get(t) and not after.get(t)]
    gained = [t for t in WATCH_TOOLS if after.get(t) and not before.get(t)]
    return {
        "machine": machine,
        "user": user,
        "machine_changed": machine != report.machine_raw,
        "user_changed": user != report.user_raw,
        "changed": changed,
        "lost": lost,
        "gained": gained,
        "length_before": (len(report.machine_raw), len(report.user_raw)),
        "length_after": (len(machine), len(user)),
    }


def describe_preview(pv: dict) -> list[str]:
    lines = []
    if not (pv["machine_changed"] or pv["user_changed"]):
        return [_t("Ничего не изменится.", "Nothing will change.")]
    for t, a, b in pv["changed"]:
        lines.append(_t("{t}: {a} → {b}", "{t}: {a} → {b}").format(t=t, a=a, b=b))
    if pv["lost"]:
        lines.append(
            _t("Пропадут команды: {t}", "Commands that disappear: {t}").format(
                t=", ".join(pv["lost"])
            )
        )
    if pv["gained"]:
        lines.append(
            _t("Появятся команды: {t}", "Commands that appear: {t}").format(
                t=", ".join(pv["gained"])
            )
        )
    if not pv["changed"] and not pv["lost"]:
        lines.append(
            _t(
                "Все команды продолжат запускать те же файлы.",
                "Every command keeps running the same file.",
            )
        )
    if pv["machine_changed"]:
        lines.append(
            _t(
                "Меняется системный PATH — понадобится подтверждение UAC.",
                "The system PATH changes — a UAC prompt will appear.",
            )
        )
    return lines


# --- применение и откат --------------------------------------------------------------


def apply(report: Report, ids: set[str]) -> tuple[bool, str]:
    """Записать выбранные исправления: бэкап обеих веток, запись (системной —
    через UAC), оповещение Windows, обновление PATH процесса."""
    pv = preview(report, ids)
    if not (pv["machine_changed"] or pv["user_changed"]):
        return False, _t("Менять нечего.", "Nothing to change.")
    msgs: list[str] = []
    if pv["machine_changed"]:
        backup = env_path._backup_path(report.machine_raw, "machine")
        if env_path.is_admin():
            try:
                env_path._write_machine_path_direct(pv["machine"])
            except Exception as e:
                return False, str(e)
        else:
            ok, msg = env_path._write_machine_path_elevated(pv["machine"])
            if not ok:
                return False, msg
        msgs.append(
            _t(
                "Системный PATH обновлён (бэкап: {b}).", "System PATH updated (backup: {b})."
            ).format(b=backup or "—")
        )
    if pv["user_changed"]:
        backup = env_path._backup_path(report.user_raw, "user")
        try:
            env_path._write_user_path(pv["user"])
        except Exception as e:
            return False, str(e)
        msgs.append(
            _t("Ваш PATH обновлён (бэкап: {b}).", "User PATH updated (backup: {b}).").format(
                b=backup or "—"
            )
        )
    env_path._broadcast_env_change()
    _refresh_process_path(report, pv)
    msgs.append(
        _t(
            "Откройте новый терминал и перезапустите VS Code.",
            "Open a new terminal and restart VS Code.",
        )
    )
    return True, "\n".join(msgs)


def _refresh_process_path(report: Report, pv: dict) -> None:
    """PATH процесса = новый системный + новый пользовательский + то, что было
    только у процесса (venv, родитель)."""
    old_reg = {norm(d) for d in _dirs_of(report.machine_raw, report.user_raw)}
    extras = [
        d for d in env_path.path_entries(os.environ.get("PATH", "")) if norm(d) not in old_reg
    ]
    new_dirs = _dirs_of(pv["machine"], pv["user"])
    os.environ["PATH"] = ";".join(new_dirs + extras)


def list_backups(limit: int = 10) -> list[dict]:
    """Бэкапы PATH, свежие первыми: [{'file', 'scope', 'time'}]."""
    from .paths import CONFIG_DIR

    out = []
    for f in Path(CONFIG_DIR).glob("*path_backup_*.txt"):
        scope = "machine" if f.name.startswith("machine_") else "user"
        m = re.search(r"(\d{8})_(\d{6})", f.name)
        stamp = (
            f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]} "
            f"{m.group(2)[:2]}:{m.group(2)[2:4]}"
            if m
            else f.name
        )
        out.append({"file": str(f), "scope": scope, "time": stamp})
    out.sort(key=lambda x: x["time"], reverse=True)
    return out[:limit]


def restore_backup(file: str) -> tuple[bool, str]:
    """Вернуть PATH из бэкапа. Текущее значение перед этим тоже сохраняется."""
    p = Path(file)
    try:
        value = p.read_text(encoding="utf-8")
    except OSError as e:
        return False, str(e)
    if p.name.startswith("machine_"):
        env_path._backup_path(env_path.read_machine_path(), "machine")
        if env_path.is_admin():
            env_path._write_machine_path_direct(value)
        else:
            ok, msg = env_path._write_machine_path_elevated(value)
            if not ok:
                return False, msg
    else:
        env_path._backup_path(env_path.read_user_path(), "user")
        env_path._write_user_path(value)
    env_path._broadcast_env_change()
    env_path.refresh_process_path_from_registry()
    return True, _t("PATH восстановлен из {f}.", "PATH restored from {f}.").format(f=p.name)


def summary(report: Report) -> dict:
    fix = [i for i in report.issues if i.fixable]
    return {
        "total": len(report.issues),
        "fixable": len(fix),
        "selected": sum(1 for i in fix if i.selected),
        "errors": sum(1 for i in report.issues if i.level == "error"),
        "warns": sum(1 for i in report.issues if i.level == "warn"),
    }
