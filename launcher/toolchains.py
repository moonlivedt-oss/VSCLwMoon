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
    # Варианты версии для выбора в UI (#4): ((winget_id, метка), ...). Первый
    # обычно совпадает с winget_id по умолчанию. Пусто — версия одна.
    versions: tuple[tuple[str, str], ...] = ()
    # Команда-подтверждение установки: наличия probe в PATH бывает мало. Пример —
    # .NET: `dotnet.exe` кладут и рантаймы (Docker, приложения), но без SDK
    # `dotnet build` не работает. Тогда verify_cmd=("--list-sdks",): пакет считаем
    # установленным, только если запуск `probe[0] --list-sdks` вернул код 0 и
    # непустой stdout. Пусто — проверяем как раньше, лишь по наличию в PATH.
    verify_cmd: tuple[str, ...] = ()

    def tools(self) -> tuple[str, ...]:
        """Все инструменты пакета: provides, если задан, иначе probe."""
        return self.provides or self.probe

    def with_version(self, winget_id: str) -> Package:
        """Копия пакета с другим winget_id (выбранная версия, #4). Если id не из
        списка versions — возвращаем как есть (не даём подменить на произвольное).
        title подставляем из versions, чтобы UI/лог показывали выбранную версию."""
        import dataclasses

        for vid, vtitle in self.versions:
            if vid == winget_id:
                return dataclasses.replace(self, winget_id=vid, title=vtitle)
        return self


@dataclass(frozen=True)
class Toolchain:
    key: str  # совпадает с ключом стека
    title: str
    note: str
    packages: tuple[Package, ...] = field(default_factory=tuple)


# --- каталог ---------------------------------------------------------------
# Каталог живёт в data/toolchains.json (#6) — пользователь правит его под себя
# без изменения кода. Загружаем в те же dataclass'ы Package/Toolchain. Git
# в JSON нет как стека, но тулчейн нужен — держим здесь и в JSON.

# Минимальный встроенный фолбэк: если data/toolchains.json отсутствует или
# битый (например, повреждён при правке), лаунчер не должен остаться совсем без
# каталога. Полный каталог — в JSON; здесь только самое необходимое.
_FALLBACK_TOOLCHAINS: dict[str, Toolchain] = {
    "python": Toolchain(
        "python",
        "Python",
        "Интерпретатор Python и pip.",
        (
            Package(
                "Python.Python.3.13",
                "Python 3.13",
                ("python", "pip"),
                note="Сам прописывает PATH при установке.",
            ),
        ),
    ),
    "git": Toolchain(
        "git",
        "Git",
        "Система контроля версий — нужна и самой VS Code.",
        (
            Package(
                "Git.Git", "Git for Windows", ("git",), note="Сам прописывает PATH при установке."
            ),
        ),
    ),
}


def _package_from_dict(d: dict) -> Package | None:
    """Собрать Package из записи JSON. None, если нет обязательных полей или
    id/probe не проходят валидацию — битую запись пропускаем, а не роняем каталог."""
    if not isinstance(d, dict):
        return None
    wid = d.get("winget_id")
    probe = d.get("probe")
    if not isinstance(wid, str) or not valid_winget_id(wid):
        return None
    if not isinstance(probe, list) or not probe or not all(isinstance(e, str) and e for e in probe):
        return None

    def _strs(key: str) -> tuple[str, ...]:
        v = d.get(key)
        return tuple(x for x in v if isinstance(x, str)) if isinstance(v, list) else ()

    versions: list[tuple[str, str]] = []
    for v in d.get("versions") or ():
        if (
            isinstance(v, dict)
            and isinstance(v.get("winget_id"), str)
            and valid_winget_id(v["winget_id"])
        ):
            versions.append((v["winget_id"], str(v.get("title") or v["winget_id"])))
    return Package(
        winget_id=wid,
        title=str(d.get("title") or wid),
        probe=tuple(probe),
        note=str(d.get("note") or ""),
        optional=bool(d.get("optional", False)),
        path_hints=_strs("path_hints"),
        version_arg=str(d.get("version_arg") or "--version"),
        provides=_strs("provides"),
        versions=tuple(versions),
        verify_cmd=_strs("verify_cmd"),
    )


def load_toolchains() -> dict[str, Toolchain]:
    """Каталог тулчейнов из data/toolchains.json (#6). При отсутствии/битом файле
    — встроенный фолбэк, чтобы приложение не осталось без каталога. Пакеты с
    невалидным id/без probe пропускаются (в духе safety.py)."""
    import json

    from .paths import TOOLCHAINS_FILE

    try:
        data = json.loads(TOOLCHAINS_FILE.read_text(encoding="utf-8-sig"))
    except Exception as e:
        log.warning("toolchains.json не прочитан (%s) — встроенный фолбэк", e)
        return dict(_FALLBACK_TOOLCHAINS)
    chains_raw = data.get("toolchains") if isinstance(data, dict) else None
    if not isinstance(chains_raw, dict):
        log.warning("toolchains.json без объекта 'toolchains' — встроенный фолбэк")
        return dict(_FALLBACK_TOOLCHAINS)
    out: dict[str, Toolchain] = {}
    for key, tc_raw in chains_raw.items():
        if not isinstance(tc_raw, dict):
            continue
        pkgs = [
            p
            for p in (_package_from_dict(x) for x in tc_raw.get("packages") or ())
            if p is not None
        ]
        if not pkgs:
            continue
        out[key] = Toolchain(
            key, str(tc_raw.get("title") or key), str(tc_raw.get("note") or ""), tuple(pkgs)
        )
    return out or dict(_FALLBACK_TOOLCHAINS)


TOOLCHAINS: dict[str, Toolchain] = load_toolchains()


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
            out = subprocess.run(
                [wg, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                creationflags=_NO_WINDOW,
            )
            ver = (out.stdout or "").strip() or None
        except Exception:
            ver = None
    _winget_cache["version"] = ver
    return ver


def _parse_winget_version(s: str | None) -> tuple[int, ...]:
    """'v1.29.290' -> (1, 29, 290). Пусто/битое -> (0,)."""
    if not s:
        return (0,)
    nums = re.findall(r"\d+", s)
    return tuple(int(n) for n in nums) if nums else (0,)


def winget_supports_disable_interactivity() -> bool:
    """Флаг `--disable-interactivity` появился в winget 1.4 (#9). На более старых
    winget он не распознаётся и ломает вызов, поэтому добавляем его только когда
    версия достаточно свежая. Версию winget уже кэшируем."""
    return _parse_winget_version(winget_version()) >= (1, 4)


# --- определение, что уже стоит --------------------------------------------


def probe_version(exe: str) -> str | None:
    """Короткая строка версии инструмента `exe` или None, если его нет в PATH.

    Сначала проверяем наличие в PATH (which) — дёшево и без запуска процесса;
    затем спрашиваем версию. Любой сбой запуска трактуем как «нет»."""
    if not exe or which(exe) is None:
        return None
    # Разные инструменты понимают разный флаг: `go` хочет `version` (а на
    # `--version` ругается «flag provided but not defined»), `dotnet` — тоже
    # `--version`, но на голое `version` пишет ошибку. Поэтому предпочитаем
    # вариант с кодом возврата 0; ответ упавшей команды (её текст ошибки)
    # держим лишь как запасной, если ни один флаг не отработал успешно.
    fallback: str | None = None
    for arg in ("--version", "version"):
        try:
            out = subprocess.run(
                [exe, arg],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                creationflags=_NO_WINDOW,
            )
        except Exception:
            continue
        text = ((out.stdout or "") + " " + (out.stderr or "")).strip()
        if not text:
            continue
        line = text.splitlines()[0].strip()[:120]
        if out.returncode == 0:
            return line  # успешный ответ — берём сразу
        if fallback is None:
            fallback = line  # неуспешный — запомним на крайний случай
    if fallback is not None:
        return fallback
    return "установлен"  # в PATH есть, но версию не отдал — этого достаточно


def _verify_cmd_ok(pkg: Package) -> bool:
    """Запустить команду-подтверждение пакета (verify_cmd) на его probe[0] и
    проверить, что она вернула код 0 и непустой stdout. Для случаев, когда
    probe в PATH есть, но инструмент неполон (.NET: рантайм без SDK)."""
    if not pkg.verify_cmd or not pkg.probe:
        return True
    exe = pkg.probe[0]
    if which(exe) is None:
        return False
    try:
        out = subprocess.run(
            [exe, *pkg.verify_cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=_NO_WINDOW,
        )
    except Exception:
        return False
    return out.returncode == 0 and bool((out.stdout or "").strip())


def package_installed(pkg: Package) -> bool:
    """Пакет считаем установленным, если ЛЮБОЙ его probe-бинарь виден в PATH.
    Если задан verify_cmd — дополнительно требуем, чтобы команда-подтверждение
    отработала (наличия мультиплексора вроде dotnet.exe без SDK недостаточно)."""
    if not any(which(exe) is not None for exe in pkg.probe):
        return False
    return _verify_cmd_ok(pkg)


def package_status(pkg: Package) -> dict:
    """{'installed': bool, 'version': str|None} — для строки в UI/CLI."""
    if not package_installed(pkg):
        return {"installed": False, "version": None}
    ver = None
    for exe in pkg.probe:
        ver = probe_version(exe)
        if ver:
            break
    return {"installed": True, "version": ver}


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
    r"msys64\ucrt64\bin",
    r"msys64\mingw64\bin",
    r"msys64\mingw32\bin",
    r"mingw64\bin",
    r"mingw32\bin",
    r"MinGW\bin",
    r"ProgramData\mingw64\mingw64\bin",
    r"Program Files\LLVM\bin",
    r"Program Files\CMake\bin",
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
_DISK_SCAN_ROOTS: tuple[str, ...] = tuple("C:\\" + rel for rel in _DISK_SCAN_RELATIVE)


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
    -1978335189,  # 0x8A15002B APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE
    -1978335135,  # 0x8A150061 no applicable installer / already installed
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


def install_package_elevated(pkg: Package, scope: str = "machine") -> tuple[bool, str]:
    """Поставить пакет с правами администратора (#10) — для пакетов, что требуют
    machine-scope и упираются в UAC (код -1978334967). Запускаем winget через
    PowerShell `Start-Process -Verb RunAs` (появится запрос UAC) и ждём выхода.

    Вывод самого winget тут не перехватить (elevated-процесс отдельный), поэтому
    ориентируемся на код возврата. Аргументы — фиксированный список с уже
    проверенным id; пользовательский ввод сюда не попадает."""
    wg = winget_path()
    if wg is None:
        return False, (
            "winget не найден. Установите «App Installer» из Microsoft "
            "Store — он входит в состав Windows 10/11."
        )
    if not valid_winget_id(pkg.winget_id):
        return False, f"Недопустимый id пакета: {pkg.winget_id!r}"
    inner = [
        "install",
        "--id",
        pkg.winget_id,
        "--exact",
        "--accept-source-agreements",
        "--accept-package-agreements",
        "--source",
        "winget",
    ]
    if scope in ("user", "machine"):
        inner += ["--scope", scope]
    # Массив аргументов PowerShell: каждый в одинарных кавычках с экранированием.
    ps_args = ", ".join("'" + a.replace("'", "''") + "'" for a in inner)
    ps = (
        f"try {{ $p = Start-Process -FilePath '{wg.replace(chr(39), chr(39) * 2)}' "
        f"-ArgumentList {ps_args} -Verb RunAs -Wait -PassThru; exit $p.ExitCode }} "
        f"catch {{ exit 1223 }}"
    )  # 1223 = ERROR_CANCELLED (UAC отклонён)
    log.info("winget install %s (elevated, scope=%s)", pkg.winget_id, scope)
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return False, "Операция не уложилась в 30 минут и была прервана."
    except Exception as e:
        return False, str(e)
    code = out.returncode
    if code in _WINGET_OK_CODES:
        env_path.refresh_process_path_from_registry()
        note = repair_path_for(pkg)
        msg = "Установлено с правами администратора."
        return True, (msg + "\n" + note).strip() if note else msg
    if code == 1223:
        return False, "Запрос прав администратора (UAC) отклонён — установка отменена."
    return False, explain_winget_code(code, (out.stdout or "") + (out.stderr or ""))


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


def _run_winget(action: str, pkg: Package, scope: str | None, repair: bool) -> tuple[bool, str]:
    """Общий вызов winget для install/upgrade/uninstall.

    Возвращает (успех, вывод). Подпроцесс — списком аргументов и с
    CREATE_NO_WINDOW. При успехе install/upgrade и repair=True чиним PATH.
    Ошибку переводим в человеческую строку через explain_winget_code."""
    wg = winget_path()
    if wg is None:
        return False, (
            "winget не найден. Установите «App Installer» из Microsoft "
            "Store — он входит в состав Windows 10/11."
        )
    if not valid_winget_id(pkg.winget_id):
        return False, f"Недопустимый id пакета: {pkg.winget_id!r}"

    args = [
        wg,
        action,
        "--id",
        pkg.winget_id,
        "--exact",
        "--accept-source-agreements",
        "--source",
        "winget",
    ]
    if winget_supports_disable_interactivity():  # #9: только на winget ≥ 1.4
        args.append("--disable-interactivity")
    if action in ("install", "upgrade"):
        args += ["--accept-package-agreements"]
    if action in ("install", "upgrade") and scope in ("user", "machine"):
        args += ["--scope", scope]
    log.info("winget %s %s (scope=%s)", action, pkg.winget_id, scope)
    try:
        out = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
            creationflags=_NO_WINDOW,
        )
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
        # #1: пакет мог прописать PATH сам (Python/Node/Go/JDK…) — подтянем его
        # в процесс из реестра, чтобы probe/статус увидели инструмент сразу, без
        # перезапуска лаунчера, и repair ниже не добавлял лишнего.
        if action in ("install", "upgrade"):
            env_path.refresh_process_path_from_registry()
        if repair:
            note = repair_path_for(pkg)
            if note:
                text = (text + "\n" + note).strip()
                log.info("%s", note)
    else:
        reason = explain_winget_code(out.returncode, text)
        log.warning("winget %s %s: код %s — %s", action, pkg.winget_id, out.returncode, reason)
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
            (p for p in root.iterdir() if p.is_dir()), key=lambda p: id_hint not in p.name.lower()
        )
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

    Осмысленно для C/C++ (путь к компилятору) и Python (путь к интерпретатору).
    Для остальных языков расширения находят тулчейн по PATH сами."""
    if key == "cpp":
        # Предпочитаем g++, иначе clang++. Режим IntelliSense должен совпадать с
        # выбранным компилятором: для clang — windows-clang-x64, иначе расширение
        # применит неверную модель препроцессора/интринсиков.
        gpp = _compiler_path("g++")
        mode = "windows-gcc-x64"
        if not gpp:
            gpp = _compiler_path("clang++")
            mode = "windows-clang-x64"
        if not gpp:
            return {}
        return {
            "C_Cpp.default.compilerPath": gpp,
            "C_Cpp.default.cStandard": "c17",
            "C_Cpp.default.cppStandard": "c++20",
            "C_Cpp.default.intelliSenseMode": mode,
        }
    if key == "python":
        # Расширение Python само ищет интерпретаторы, но явный путь избавляет от
        # «Select Interpreter» на первом запуске и фиксирует нужный python.
        py = which("python") or which("python3")
        if not py:
            return {}
        return {"python.defaultInterpreterPath": py}
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


# --- менеджеры версий: предупреждение о конфликте (#7) ---------------------
# Многие ставят Node через nvm-windows/fnm/volta, Python через pyenv-win. Второй
# экземпляр того же языка из winget конфликтует с менеджером за PATH (какой
# `node`/`python` возьмётся — вопрос порядка PATH). Не запрещаем, но
# предупреждаем: пусть пользователь решит осознанно.

# ключ тулчейна -> кортежи (имя менеджера, exe для which, env-переменная).
_LANG_MANAGERS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "web": (
        ("nvm-windows", "nvm", "NVM_HOME"),
        ("fnm", "fnm", "FNM_DIR"),
        ("Volta", "volta", "VOLTA_HOME"),
    ),
    "python": (("pyenv-win", "pyenv", "PYENV"),),
}


def _manager_present(exe: str, env_var: str) -> bool:
    """Менеджер версий считаем установленным, если его команда в PATH или задана
    его переменная окружения."""
    if exe and which(exe) is not None:
        return True
    return bool(env_var and os.environ.get(env_var))


def detected_managers_for(key: str) -> list[str]:
    """Имена установленных менеджеров версий, управляющих языком тулчейна `key`
    (#7). Пусто — конфликта нет."""
    return [
        name for name, exe, env_var in _LANG_MANAGERS.get(key, ()) if _manager_present(exe, env_var)
    ]


def manager_warning_for(key: str) -> str:
    """Текст предупреждения, если для языка тулчейна установлен менеджер версий
    (#7). Пустая строка — предупреждать не о чем."""
    names = detected_managers_for(key)
    if not names:
        return ""
    return (
        "Обнаружен менеджер версий: " + ", ".join(names) + ". "
        "Установка через winget может конфликтовать с ним за PATH — "
        "возможно, версию лучше ставить средствами самого менеджера."
    )


# --- что обновить (#5) -----------------------------------------------------


def _catalog_known_ids() -> set[str]:
    """Все winget-id из каталога, включая варианты версий — по ним ищем в выводе
    `winget upgrade`, что относится к нашим тулчейнам."""
    known: set[str] = set()
    for chain in TOOLCHAINS.values():
        for pkg in chain.packages:
            known.add(pkg.winget_id)
            known.update(vid for vid, _t in pkg.versions)
    return known


def list_upgradable_ids(timeout: float = 120) -> set[str]:
    """Множество winget-id наших тулчейнов, для которых доступно обновление (#5).

    Гоняем `winget upgrade` (он перечисляет всё обновляемое) и оставляем те id,
    что есть в каталоге. Парсинг устойчив к локализации таблицы: разбиваем строки
    на токены и берём те, что точно совпали с известным id. Пусто — нечего
    обновлять или winget недоступен."""
    wg = winget_path()
    if wg is None:
        return set()
    args = [wg, "upgrade", "--accept-source-agreements", "--source", "winget"]
    if winget_supports_disable_interactivity():
        args.append("--disable-interactivity")
    try:
        out = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_NO_WINDOW,
        )
    except Exception:
        return set()
    known = _catalog_known_ids()
    found: set[str] = set()
    for line in (out.stdout or "").splitlines():
        for tok in line.split():
            if tok in known:
                found.add(tok)
    return found


def outdated_packages(upgradable: set[str] | None = None) -> list[dict]:
    """Установленные пакеты каталога, у которых есть обновление (#5):
    [{'key', 'package', 'version'}]. upgradable — результат list_upgradable_ids
    (передай готовый, чтобы не звать winget повторно); None — посчитаем сами."""
    if upgradable is None:
        upgradable = list_upgradable_ids()
    rows = []
    for key, chain in TOOLCHAINS.items():
        for pkg in chain.packages:
            if pkg.winget_id in upgradable and package_installed(pkg):
                rows.append({"key": key, "package": pkg, "version": package_status(pkg)["version"]})
    return rows


# --- доктор окружения (#8) --------------------------------------------------


def _java_home_health() -> dict:
    """Проверка JAVA_HOME: задан ли и указывает ли на JDK (есть bin\\java.exe)."""
    jh = os.environ.get("JAVA_HOME")
    if not jh:
        return {"set": False, "ok": False, "path": "", "reason": "не задан"}
    java_exe = Path(jh) / "bin" / "java.exe"
    if java_exe.exists():
        return {"set": True, "ok": True, "path": jh, "reason": ""}
    return {
        "set": True,
        "ok": False,
        "path": jh,
        "reason": "указывает не на JDK (нет bin\\java.exe)",
    }


def find_jdk_home() -> str | None:
    """Каталог установленного JDK (значение для JAVA_HOME) или None.

    Сначала — по `javac` в PATH: он лежит в <JDK>\\bin, значит home — родитель
    каталога bin (javac, а не java: JRE тоже даёт java.exe, но без компилятора —
    для сборки нужен именно JDK). Затем — типовые каталоги установки Temurin/
    других OpenJDK на всех дисках, самая свежая версия первой."""
    javac = which("javac")
    if javac:
        home = Path(javac).resolve().parent.parent
        if (home / "bin" / "java.exe").exists():
            return str(home)
    patterns = (
        r"Program Files\Eclipse Adoptium",
        r"Program Files\Java",
        r"Program Files\Microsoft\jdk",
        r"Program Files\Amazon Corretto",
        r"Program Files\Zulu",
    )
    candidates: list[Path] = []
    for letter in "CDEFGH":
        drive = f"{letter}:\\"
        if not os.path.isdir(drive):
            continue
        for rel in patterns:
            base = Path(drive + rel)
            if not base.is_dir():
                continue
            for sub in base.iterdir():
                if sub.is_dir() and (sub / "bin" / "javac.exe").exists():
                    candidates.append(sub)
    if candidates:
        # Свежую версию — вперёд. Сортируем по ЧИСЛАМ в имени, а не по строке:
        # строковое сравнение ставит 'jdk-8' выше 'jdk-17' ('8' > '1') и выбрало
        # бы старый JDK. Числовой ключ даёт (21) > (17) > (8), как и ожидается.
        candidates.sort(key=lambda p: [int(n) for n in re.findall(r"\d+", p.name)], reverse=True)
        return str(candidates[0])
    return None


def repair_java_home() -> tuple[bool, str]:
    """Настроить JAVA_HOME, если он не задан или указывает не на JDK (#8 → фикс).

    Находит установленный JDK (find_jdk_home) и прописывает JAVA_HOME в
    пользовательские переменные окружения (без прав администратора). Многие
    Java-инструменты (Maven, Gradle, некоторые расширения) читают именно
    JAVA_HOME, а не PATH. Если JDK найден дисковым сканом и его `bin` ещё не в
    PATH — дописываем и его, иначе `java`/`javac` из терминала не запустятся.
    Возвращает (изменили_ли, сообщение)."""
    health = _java_home_health()
    if health["ok"]:
        return False, f"JAVA_HOME уже настроен верно: {health['path']}"
    home = find_jdk_home()
    if not home:
        return False, (
            "JDK не найден. Сначала установите его "
            "(тулчейн «Java») — тогда JAVA_HOME можно будет прописать."
        )
    ok, msg = env_path.set_user_env_var("JAVA_HOME", home)
    if ok:
        log.info("JAVA_HOME установлен: %s", home)
    # JDK мог быть найден мимо PATH (дисковый скан) — тогда bin ещё не виден.
    bindir = str(Path(home) / "bin")
    if not env_path.is_on_path(bindir):
        added, amsg = env_path.add_to_user_path(bindir)
        if added:
            ok = True
            msg = f"{msg}\n{amsg}" if msg else amsg
            log.info("JDK bin добавлен в PATH: %s", bindir)
    return ok, msg


def environment_report() -> dict:
    """Холистическая диагностика окружения (#8): установленные тулчейны с
    версиями, здоровье PATH (дубли/мёртвые записи/длина) и корректность
    JAVA_HOME. Для отдельной кнопки «Проверить окружение» в UI/CLI."""
    tools = []
    for key, chain in TOOLCHAINS.items():
        for pkg in chain.packages:
            st = package_status(pkg)
            if st["installed"]:
                tools.append({"key": key, "title": pkg.title, "version": st["version"]})
    return {
        "tools": tools,
        "path": env_path.path_health(),
        # Раздельно user/machine (#3): чистка касается только пользовательского
        # PATH, системный требует прав администратора — покажем это явно.
        "path_user": env_path.path_health(env_path.read_user_path()),
        "path_machine": env_path.path_health(env_path.read_machine_path()),
        "java_home": _java_home_health(),
        "winget": winget_version(),
    }


# --- сводка (для CLI/selftest/UI) ------------------------------------------


def catalog_path_hints() -> tuple[str, ...]:
    """Все path_hints из каталога тулчейнов — резервные каталоги `bin`, которые
    чистка PATH не должна удалять как «мёртвые» (архивная сборка ещё не
    распакована / инструмент поставят позже). Передаётся в clean_*_path как keep."""
    hints: list[str] = []
    for chain in TOOLCHAINS.values():
        for pkg in chain.packages:
            hints.extend(pkg.path_hints)
    return tuple(dict.fromkeys(hints))  # уникальные, порядок сохранён


def toolchain_summary() -> dict:
    """Короткая сводка по всем тулчейнам: сколько всего, сколько с полностью
    установленными обязательными пакетами, список недостающих ключей."""
    total = len(TOOLCHAINS)
    missing = [k for k in TOOLCHAINS if missing_required(k)]
    return {
        "total": total,
        "ready": total - len(missing),
        "missing": missing,
        "winget": winget_available(),
    }
