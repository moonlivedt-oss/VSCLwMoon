# -*- coding: utf-8 -*-
"""Совместимость расширений: что не заработает или будет мешать при запуске.

Лаунчер решает, какие расширения включить, но до сих пор не проверял, смогут
ли они работать вместе и с этим VS Code. Проблема всплывала уже в редакторе:
«расширение не активировано», двойные подсказки, клавиши Vim срабатывают
дважды. Здесь — чистая проверка набора, который будет включён:

- engine     — расширение требует более новый VS Code (engines.vscode), редактор
               его не запустит;
- platform   — сборка расширения под другую ОС (linux/darwin/alpine);
- missing_dep— нужное ему расширение (extensionDependencies) не установлено;
- dep_off    — нужное ему расширение выключено на этот запуск;
- conflict   — расширения из одной группы data/conflicts.json включены вместе;
- deprecated — устаревшее расширение (data/conflicts.json, раздел deprecated).

Проверка ничего не меняет на диске. Что делать с найденным — решают окно, трей
и CLI по настройке compat_check: 'warn' (спросить), 'auto' (выключить
проблемные на этот запуск), 'off' (не проверять).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .i18n import _, get_language
from .paths import DATA_DIR

CONFLICTS_FILE = DATA_DIR / "conflicts.json"
MODES = ("warn", "auto", "off")
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}

# --- версия VS Code -------------------------------------------------------


def vscode_install_dir(code_cli: str | None) -> Path | None:
    """Папка установки VS Code по пути к CLI: bin/code.cmd -> её родитель,
    Code.exe -> его папка. None — путь не похож ни на то, ни на другое."""
    if not code_cli:
        return None
    p = Path(code_cli)
    try:
        p = p.resolve()
    except OSError:
        pass
    if p.suffix.lower() == ".exe":
        return p.parent
    if p.parent.name.lower() == "bin":
        return p.parent.parent
    return None


def _version_key(v: str) -> tuple[int, int, int]:
    m = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)", v or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 0, 0)


def vscode_version(code_cli: str | None) -> str:
    """Версия установленного VS Code ('1.121.0') или '' — не удалось узнать.

    Читаем resources/app/package.json. Свежие сборки кладут его во вложенную
    папку с хэшем коммита (<install>/<hash>/resources/app); во время
    обновления таких папок бывает две — берём самую новую версию."""
    best = ""
    for app in _app_dirs(code_cli):
        try:
            data = json.loads((app / "package.json").read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        ver = str(data.get("version") or "") if isinstance(data, dict) else ""
        if _version_key(ver) > _version_key(best):
            best = ver
    return best


def _app_dirs(code_cli: str | None) -> list[Path]:
    """resources/app установленного VS Code: прямо в папке установки или во
    вложенной папке с хэшем коммита (свежие сборки)."""
    root = vscode_install_dir(code_cli)
    if root is None:
        return []
    cands = [root / "resources" / "app"]
    try:
        cands += [d / "resources" / "app" for d in root.iterdir() if d.is_dir()]
    except OSError:
        pass
    return [c for c in cands if (c / "package.json").is_file()]


_BUILTIN_CACHE: dict[str, frozenset[str]] = {}


def builtin_extensions(code_cli: str | None) -> frozenset[str]:
    """id встроенных расширений VS Code (resources/app/extensions/*). Кэш на
    процесс по папке: набор меняется только с обновлением редактора, а оно
    кладёт сборку в новую папку."""
    out: set[str] = set()
    for app in _app_dirs(code_cli):
        key = str(app).lower()
        if key not in _BUILTIN_CACHE:
            found: set[str] = set()
            try:
                subdirs = [d for d in (app / "extensions").iterdir() if d.is_dir()]
            except OSError:
                subdirs = []
            for d in subdirs:
                try:
                    data = json.loads((d / "package.json").read_text(encoding="utf-8-sig"))
                except Exception:
                    continue
                if isinstance(data, dict) and data.get("publisher") and data.get("name"):
                    found.add(f"{data['publisher']}.{data['name']}".lower())
            _BUILTIN_CACHE[key] = frozenset(found)
        out |= _BUILTIN_CACHE[key]
    return frozenset(out)


# --- engines.vscode: та же логика, что у самого VS Code --------------------
# Порт extensionValidator.ts (isValidVersion): VS Code понимает '*', '^x.y.z',
# '>=x.y.z' и 'x' вместо числа. Своя трактовка semver здесь не годится —
# нужна именно та, по которой редактор откажется запускать расширение.

_ENGINE_RE = re.compile(r"^(\^|>=)?((\d+)|x)\.((\d+)|x)\.((\d+)|x)(-.*)?$")


def _parse_engine(text: str) -> dict | None:
    text = (text or "").strip()
    if text == "*":
        return {"base": [0, 0, 0], "must": [False, False, False]}
    m = _ENGINE_RE.match(text)
    if not m:
        return None
    base, must = [], []
    for g in (2, 4, 6):
        is_x = m.group(g) == "x"
        base.append(0 if is_x else int(m.group(g)))
        must.append(not is_x)
    if m.group(1) == "^":
        if base[0] == 0:
            must[2] = False
        else:
            must[1] = must[2] = False
    elif m.group(1) == ">=":
        must = [False, False, False]
    return {"base": base, "must": must}


def engine_satisfied(engine: str, version: str) -> bool | None:
    """Подходит ли версия VS Code под engines.vscode расширения.
    None — не разобрать одно из двух (тогда и не предупреждаем)."""
    want = _parse_engine(engine)
    have = _version_key(version)
    if want is None or have == (0, 0, 0):
        return None
    base, must = list(want["base"]), list(want["must"])
    # «Всё, что ниже 1.0.0, совместимо с 1.x» — кроме точного совпадения.
    if have[0] == 1 and base[0] == 0 and not all(must):
        base, must = [1, 0, 0], [True, False, False]
    for i in range(3):
        if have[i] < base[i]:
            return False
        if have[i] > base[i]:
            return not must[i]
    return True


# --- платформа ------------------------------------------------------------

_FOREIGN_OS = ("linux", "darwin", "alpine")


def platform_mismatch(target: str) -> bool:
    """Расширение собрано под другую ОС. Тонкости архитектуры (x64 на arm64)
    не трогаем: VS Code там умеет запускать x64-сборки, ложная тревога хуже."""
    t = (target or "").lower()
    return t.startswith(_FOREIGN_OS)


# --- правила конфликтов ---------------------------------------------------


def load_rules(path: Path | None = None) -> dict:
    """data/conflicts.json в нормализованной форме: id в нижнем регистре,
    битые записи пропущены. Нет файла или он битый — пустые правила."""
    try:
        raw = json.loads((path or CONFLICTS_FILE).read_text(encoding="utf-8-sig"))
    except Exception:
        return {"conflicts": [], "deprecated": []}
    if not isinstance(raw, dict):
        return {"conflicts": [], "deprecated": []}
    conflicts = []
    for c in raw.get("conflicts") or []:
        if not isinstance(c, dict) or not isinstance(c.get("ids"), list):
            continue
        ids = [str(i).lower() for i in c["ids"] if isinstance(i, str)]
        if len(ids) < 2:
            continue
        keep = str(c.get("keep") or "").lower()
        conflicts.append({**c, "ids": ids, "keep": keep if keep in ids else ""})
    deprecated = []
    for d in raw.get("deprecated") or []:
        if isinstance(d, dict) and isinstance(d.get("id"), str):
            deprecated.append(
                {**d, "id": d["id"].lower(), "replaced_by": str(d.get("replaced_by") or "").lower()}
            )
    return {"conflicts": conflicts, "deprecated": deprecated}


def _reason(rule: dict) -> str:
    if get_language() == "en" and rule.get("reason_en"):
        return str(rule["reason_en"])
    return str(rule.get("reason") or "")


# --- контекст VS Code: всё, что знает о редакторе глубокая проверка ---------


def vscode_user_dir(code_cli: str | None) -> Path | None:
    """%APPDATA%\\Code (или Code - Insiders) — данные пользователя VS Code."""
    import os

    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    name = "Code - Insiders" if code_cli and "insiders" in code_cli.lower() else "Code"
    return Path(appdata) / name


def product_info(code_cli: str | None) -> dict:
    """quality и разрешённые экспериментальные API из product.json."""
    for app in _app_dirs(code_cli):
        try:
            data = json.loads((app / "product.json").read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if isinstance(data, dict):
            allowed = data.get("extensionEnabledApiProposals")
            return {
                "quality": str(data.get("quality") or ""),
                "proposals": {str(k).lower(): v for k, v in allowed.items()}
                if isinstance(allowed, dict)
                else {},
            }
    return {"quality": "", "proposals": {}}


def vscode_disabled_extensions(code_cli: str | None) -> frozenset[str]:
    """Расширения, выключенные в самом VS Code («Disable» в панели расширений).

    VS Code хранит их в globalStorage/state.vscdb (SQLite, ключ
    extensionsIdentifiers/disabled). Такое расширение не запустится, даже если
    лаунчер его «включает». Читаем копию только на чтение; не вышло — пусто."""
    user = vscode_user_dir(code_cli)
    if user is None:
        return frozenset()
    db = user / "User" / "globalStorage" / "state.vscdb"
    if not db.is_file():
        return frozenset()
    import sqlite3

    try:
        con = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True, timeout=1.0)
        try:
            row = con.execute(
                "SELECT value FROM ItemTable WHERE key = 'extensionsIdentifiers/disabled'"
            ).fetchone()
        finally:
            con.close()
        items = json.loads(row[0]) if row and row[0] else []
    except Exception:
        return frozenset()
    out = set()
    for it in items if isinstance(items, list) else []:
        ident = it.get("id") if isinstance(it, dict) else None
        if isinstance(ident, str):
            out.add(ident.lower())
    return frozenset(out)


def broken_extensions(ext_dir: Path) -> dict[str, str]:
    """Расширения, которые числятся установленными, но на диске их нет или
    package.json не читается: {id: причина}. VS Code такие показывает с
    ошибкой, а лаунчер раньше считал их рабочими."""
    try:
        data = json.loads((ext_dir / "extensions.json").read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    try:
        obsolete = json.loads((ext_dir / ".obsolete").read_text(encoding="utf-8-sig"))
        gone = (
            {str(k).lower() for k, v in obsolete.items() if v}
            if isinstance(obsolete, dict)
            else set()
        )
    except Exception:
        gone = set()
    out: dict[str, str] = {}
    for e in data if isinstance(data, list) else []:
        if not isinstance(e, dict):
            continue
        ident = e.get("identifier")
        ext_id = ident.get("id") if isinstance(ident, dict) else None
        rel = e.get("relativeLocation")
        if not isinstance(ext_id, str) or not isinstance(rel, str) or rel.lower() in gone:
            continue
        folder = ext_dir / rel
        if not folder.is_dir():
            out[ext_id.lower()] = "missing"
            continue
        try:
            pkg = json.loads((folder / "package.json").read_text(encoding="utf-8-sig"))
            if not isinstance(pkg, dict) or not pkg.get("name"):
                raise ValueError
        except Exception:
            out[ext_id.lower()] = "manifest"
    return out


def context(code_cli: str | None) -> dict:
    """Всё о редакторе для проверки: версия, встроенные, выключенные в VS Code,
    сломанные установки, разрешённые экспериментальные API."""
    from .vscode import extensions_dir

    prod = product_info(code_cli)
    try:
        broken = broken_extensions(extensions_dir(code_cli))
    except Exception:
        broken = {}
    return {
        "version": vscode_version(code_cli),
        "builtin": builtin_extensions(code_cli),
        "vscode_disabled": vscode_disabled_extensions(code_cli),
        "broken": broken,
        "quality": prod["quality"],
        "proposals": prod["proposals"],
    }


# --- сама проверка --------------------------------------------------------


def _name(ext_id: str, manifests: dict) -> str:
    disp = (manifests.get(ext_id) or {}).get("display") or ""
    if disp and not disp.startswith("%"):  # '%displayName%' — ключ локализации
        return f"{disp} ({ext_id})"
    return ext_id


def norm_key(key: str) -> str:
    """'Ctrl+Alt+N' и 'alt+ctrl+n' — одно сочетание; аккорды через пробел."""
    chords = []
    for chord in (key or "").lower().split():
        parts = [p for p in chord.split("+") if p]
        if not parts:
            continue
        chords.append("+".join(sorted(parts[:-1]) + [parts[-1]]))
    return " ".join(chords)


def check(
    enabled,
    manifests: dict[str, dict],
    vscode_ver: str = "",
    installed=(),
    rules: dict | None = None,
    builtin=(),
    ctx: dict | None = None,
) -> list[dict]:
    """Проблемы набора `enabled` (id расширений, которые будут включены).

    Каждая проблема: {"key", "kind", "ext", "others", "severity", "text",
    "disable"}. key стабилен между запусками — по нему человек может скрыть
    предупреждение. disable — что выключить на этот запуск, чтобы проблема
    ушла (пусто — автоматически решить нельзя, выбирает человек).

    ctx (см. context()) — глубокая часть: сломанные установки, выключенные в
    самом VS Code, экспериментальный API. Без него — только то, что видно по
    манифестам (так проверку легко звать из тестов)."""
    ctx = ctx or {}
    vscode_ver = vscode_ver or ctx.get("version", "")
    on = {str(e).lower() for e in enabled}
    have = {str(e).lower() for e in installed} | on
    # Встроенные в VS Code расширения (vscode.git, github.copilot-chat…) не
    # числятся в extensions.json, но зависимости на них вполне законны.
    builtin_on = {str(e).lower() for e in builtin} | set(ctx.get("builtin") or ())
    broken = ctx.get("broken") or {}
    vs_off = set(ctx.get("vscode_disabled") or ())
    stable = ctx.get("quality") == "stable"
    allowed = ctx.get("proposals") or {}
    rules = load_rules() if rules is None else rules
    out: list[dict] = []

    def add(kind, ext, severity, text, disable=(), others=()):
        others = sorted(others)
        out.append(
            {
                "key": ":".join([kind, ext, *others]),
                "kind": kind,
                "ext": ext,
                "others": others,
                "severity": severity,
                "text": text,
                "disable": sorted(set(disable)),
            }
        )

    for ext in sorted(on):
        m = manifests.get(ext) or {}
        nm = _name(ext, manifests)
        if ext in broken:
            add(
                "broken",
                ext,
                "error",
                (
                    _(
                        "{name}: папки расширения нет на диске — VS Code покажет ошибку. "
                        "Переустановите или удалите его."
                    )
                    if broken[ext] == "missing"
                    else _(
                        "{name}: файл package.json повреждён — расширение не загрузится. "
                        "Переустановите его."
                    )
                ).format(name=nm),
                [ext],
            )
            continue
        engine = m.get("engine") or ""
        if engine and vscode_ver and engine_satisfied(engine, vscode_ver) is False:
            add(
                "engine",
                ext,
                "error",
                _(
                    "{name} требует VS Code {need}, а установлен {have} — редактор его не "
                    "запустит. Обновите VS Code (Справка → Проверить наличие обновлений) или "
                    "поставьте прошлую версию расширения."
                ).format(name=nm, need=engine, have=vscode_ver),
                [ext],
            )
        if platform_mismatch(m.get("target_platform") or ""):
            add(
                "platform",
                ext,
                "error",
                _(
                    "{name} собрано для другой системы ({target}) — в Windows не запустится. "
                    "Переустановите его из маркетплейса."
                ).format(name=nm, target=m.get("target_platform")),
                [ext],
            )
        for dep in m.get("depends") or ():
            if dep == ext or dep in builtin_on or dep.startswith("vscode."):
                continue
            if dep in on and dep in vs_off:
                add(
                    "dep_vscode_off",
                    ext,
                    "error",
                    _(
                        "{name} не заработает: нужное ему расширение {dep} выключено в самом "
                        "VS Code (панель «Расширения» → «Включить»)."
                    ).format(name=nm, dep=_name(dep, manifests)),
                    [ext],
                    [dep],
                )
            elif dep in on:
                continue
            elif dep not in have:
                add(
                    "missing_dep",
                    ext,
                    "error",
                    _(
                        "{name} не заработает: нужное ему расширение {dep} не установлено. "
                        "Поставьте его на странице «Расширения» или в самом VS Code."
                    ).format(name=nm, dep=dep),
                    [ext],
                    [dep],
                )
            else:
                add(
                    "dep_off",
                    ext,
                    "error",
                    _(
                        "{name} не заработает: нужное ему расширение {dep} на этот запуск "
                        "выключено."
                    ).format(name=nm, dep=_name(dep, manifests)),
                    [ext],
                    [dep],
                )
        props = m.get("proposals") or []
        if props and stable and ext not in allowed:
            add(
                "proposed_api",
                ext,
                "info",
                _(
                    "{name} использует экспериментальный API VS Code ({api}) — в стабильной "
                    "версии часть его функций может не работать."
                ).format(name=nm, api=", ".join(props[:3])),
            )
        if ext in vs_off:
            add(
                "vscode_off",
                ext,
                "info",
                _(
                    "{name} выключено в самом VS Code — лаунчер его не включит, даже если "
                    "стек выбран."
                ).format(name=nm),
            )
        if m.get("star"):
            add(
                "startup",
                ext,
                "info",
                _(
                    "{name} загружается при каждом старте VS Code (activationEvents: *) — "
                    "замедляет запуск в любом проекте."
                ).format(name=nm),
            )
        missing_pack = [p for p in m.get("pack") or () if p not in have and p not in builtin_on]
        if missing_pack:
            add(
                "pack",
                ext,
                "info",
                _("Набор {name} установлен не полностью, нет: {ids}.").format(
                    name=nm, ids=", ".join(missing_pack[:5])
                ),
            )

    _check_contributions(on, manifests, add)

    for rule in rules.get("conflicts", ()):
        both = [i for i in rule["ids"] if i in on]
        if len(both) < 2:
            continue
        keep = rule.get("keep") or ""
        disable = [i for i in both if i != keep] if keep in both else []
        names = ", ".join(_name(i, manifests) for i in both)
        add(
            "conflict",
            both[0],
            "warning",
            _("Включены вместе: {names}. {reason}")
            .format(names=names, reason=_reason(rule))
            .strip(),
            disable,
            both[1:],
        )

    for rule in rules.get("deprecated", ()):
        ext = rule["id"]
        if ext not in on:
            continue
        repl = rule.get("replaced_by") or ""
        if repl and repl in on:
            add(
                "deprecated",
                ext,
                "warning",
                _("{name} устарело, его замена {repl} уже включена. {reason}")
                .format(
                    name=_name(ext, manifests), repl=_name(repl, manifests), reason=_reason(rule)
                )
                .strip(),
                [ext],
            )
        else:
            add(
                "deprecated",
                ext,
                "info",
                _("{name} устарело. {reason}")
                .format(name=_name(ext, manifests), reason=_reason(rule))
                .strip(),
            )

    out.sort(key=lambda i: (SEVERITY_ORDER.get(i["severity"], 9), i["key"]))
    return out


def _check_contributions(on: set[str], manifests: dict, add) -> None:
    """Пересечения того, что расширения регистрируют в VS Code.

    - одна и та же команда у двух расширений — второе падает при активации
      («command already exists»), обычно это оригинал и его форк;
    - один тип отладчика у двух — F5 берёт случайный из них;
    - одинаковое сочетание клавиш с одинаковым условием when — сработает одно;
    - одинаковое отображаемое имя у разных id — почти всегда дубль/форк."""

    def related(a: str, b: str) -> bool:
        ma, mb = manifests.get(a) or {}, manifests.get(b) or {}
        return (
            b in (ma.get("depends") or ())
            or a in (mb.get("depends") or ())
            or b in (ma.get("pack") or ())
            or a in (mb.get("pack") or ())
        )

    def owners(field: str) -> dict[str, list[str]]:
        idx: dict[str, list[str]] = {}
        for ext in sorted(on):
            for item in set((manifests.get(ext) or {}).get(field) or ()):
                idx.setdefault(item, []).append(ext)
        return idx

    pairs_cmd: dict[tuple[str, ...], list[str]] = {}
    for cmd, exts in owners("commands").items():
        exts = [e for e in exts if not any(related(e, o) for o in exts if o != e)]
        if len(exts) > 1:
            pairs_cmd.setdefault(tuple(exts), []).append(cmd)
    for owners_t, cmds in pairs_cmd.items():
        exts = list(owners_t)
        add(
            "dup_command",
            exts[0],
            "warning",
            _(
                "{names} регистрируют одни и те же команды ({cmds}) — второе расширение "
                "упадёт при запуске. Обычно это оригинал и его копия: оставьте одно."
            ).format(
                names=", ".join(_name(e, manifests) for e in exts),
                cmds=", ".join(sorted(cmds)[:3]) + ("…" if len(cmds) > 3 else ""),
            ),
            (),
            exts[1:],
        )

    for dbg, exts in owners("debuggers").items():
        exts = [e for e in exts if not any(related(e, o) for o in exts if o != e)]
        if len(exts) > 1:
            add(
                "dup_debugger",
                exts[0],
                "warning",
                _("Отладчик «{type}» есть сразу у {names} — F5 может запустить не тот.").format(
                    type=dbg, names=", ".join(_name(e, manifests) for e in exts)
                ),
                (),
                exts[1:],
            )

    keys: dict[tuple[str, str], set[str]] = {}
    for ext in sorted(on):
        for kb in (manifests.get(ext) or {}).get("keybindings") or ():
            try:
                key, when, _cmd = kb
            except (TypeError, ValueError):
                continue
            k = norm_key(key)
            if k:
                keys.setdefault((k, "".join(str(when).split())), set()).add(ext)
    for (k, _when), exts_set in sorted(keys.items()):
        exts = sorted(exts_set)
        if len(exts) > 1 and not any(related(a, b) for a in exts for b in exts if a != b):
            add(
                "keybinding",
                exts[0],
                "info",
                _("Сочетание {key} занято сразу у {names} — сработает только одно.").format(
                    key=k, names=", ".join(_name(e, manifests) for e in exts)
                ),
                (),
                exts[1:] + [k],
            )

    names: dict[str, list[str]] = {}
    for ext in sorted(on):
        disp = ((manifests.get(ext) or {}).get("display") or "").strip().lower()
        if disp and not disp.startswith("%"):
            names.setdefault(disp, []).append(ext)
    for exts in names.values():
        if len(exts) > 1:
            add(
                "same_name",
                exts[0],
                "info",
                _(
                    "Одинаковое название у разных расширений: {ids} — похоже на дубль или копию."
                ).format(ids=", ".join(exts)),
                (),
                exts[1:],
            )


def actionable(issues: list[dict], ignored=()) -> list[dict]:
    """То, о чём стоит говорить перед запуском: ошибки и предупреждения, кроме
    скрытых человеком («больше не напоминать»). info — только в отчёте."""
    skip = set(ignored or ())
    return [i for i in issues if i["severity"] != "info" and i["key"] not in skip]


def auto_disable(issues: list[dict]) -> set[str]:
    """Что выключить на этот запуск, чтобы снять проблемы, решаемые без человека."""
    out: set[str] = set()
    for i in issues:
        out.update(i["disable"])
    return out


def mode_of(cfg: dict) -> str:
    mode = cfg.get("compat_check", "warn")
    return mode if mode in MODES else "warn"


def resolve(
    enabled,
    manifests: dict,
    vscode_ver: str,
    installed,
    mode: str,
    ignored=(),
    rules: dict | None = None,
    builtin=(),
    ctx: dict | None = None,
) -> tuple[list[dict], set[str]]:
    """Проверить набор и, в режиме 'auto', выключать проблемные до тех пор,
    пока проверка не станет чистой (выключили X — от него мог зависеть Y).

    Возвращает (оставшиеся проблемы, что выключить). В режиме 'off' — пусто."""
    if mode == "off":
        return [], set()
    rules = load_rules() if rules is None else rules
    on = {str(e).lower() for e in enabled}
    extra: set[str] = set()

    def run() -> list[dict]:
        return actionable(
            check(on - extra, manifests, vscode_ver, installed, rules, builtin, ctx), ignored
        )

    for _round in range(6):
        issues = run()
        if mode != "auto":
            return issues, set()
        more = auto_disable(issues) - extra
        if not more:
            return issues, extra
        extra |= more
    return run(), extra


KIND_TITLES = {
    "broken": "Повреждённые установки",
    "engine": "Не подходят к версии VS Code",
    "platform": "Сборка для другой системы",
    "missing_dep": "Нет нужных расширений",
    "dep_off": "Нужное расширение выключено",
    "dep_vscode_off": "Нужное расширение выключено в VS Code",
    "conflict": "Мешают друг другу",
    "dup_command": "Одинаковые команды",
    "dup_debugger": "Одинаковые отладчики",
    "deprecated": "Устаревшие",
    "keybinding": "Одинаковые сочетания клавиш",
    "same_name": "Похожие на дубли",
    "proposed_api": "Экспериментальный API",
    "vscode_off": "Выключены в самом VS Code",
    "startup": "Грузятся при каждом старте",
    "pack": "Неполные наборы",
}


def _section(issues: list[dict]) -> list[str]:
    marks = {"error": _("ОШИБКА"), "warning": _("ВНИМАНИЕ"), "info": _("к сведению")}
    lines: list[str] = []
    order = list(KIND_TITLES)
    kinds = sorted(
        {i["kind"] for i in issues},
        key=lambda k: (
            min(SEVERITY_ORDER.get(i["severity"], 9) for i in issues if i["kind"] == k),
            order.index(k) if k in order else 99,
        ),
    )
    for kind in kinds:
        group = [i for i in issues if i["kind"] == kind]
        lines.append(f"— {_(KIND_TITLES.get(kind, kind))} ({len(group)}) —")
        for i in group:
            lines.append(f"[{marks.get(i['severity'], i['severity'])}] {i['text']}")
        lines.append("")
    return lines


def report(
    installed,
    manifests: dict,
    vscode_ver: str = "",
    rules: dict | None = None,
    builtin=(),
    ctx: dict | None = None,
    current=None,
) -> str:
    """Текстовый отчёт. current — набор текущего выбора в окне: его проблемы
    идут первым разделом (их покажет запуск), дальше — всё установленное, как
    если бы включили всё сразу, со сведениями «к сведению»."""
    installed = list(installed)
    ver = vscode_ver or (ctx or {}).get("version", "")
    issues = check(installed, manifests, ver, installed, rules, builtin, ctx)
    n_err = sum(1 for i in issues if i["severity"] == "error")
    n_warn = sum(1 for i in issues if i["severity"] == "warning")
    n_info = sum(1 for i in issues if i["severity"] == "info")
    head = [
        _("VS Code: {ver}. Установлено расширений: {n}.").format(
            ver=ver or _("версия не определена"), n=len(installed)
        ),
        _("Ошибок: {e}, предупреждений: {w}, к сведению: {i}.").format(e=n_err, w=n_warn, i=n_info),
        "",
    ]
    if current is not None:
        cur = actionable(check(current, manifests, ver, installed, rules, builtin, ctx))
        head.append(_("ТЕКУЩИЙ НАБОР ({n} расширений будет включено)").format(n=len(list(current))))
        head += _section(cur) if cur else [_("Проблем нет — запуск пройдёт без вопросов."), ""]
        head.append(_("ВСЁ УСТАНОВЛЕННОЕ"))
    if not issues:
        return "\n".join(head + [_("Проблем совместимости не найдено.")])
    return "\n".join(head + _section(issues)).rstrip()
