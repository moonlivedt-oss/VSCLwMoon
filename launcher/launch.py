# -*- coding: utf-8 -*-
"""Что выключить и как запустить VS Code с этим набором.

Читаемо: чистые функции без IO. Берём (installed, ext_index, selected),
возвращаем список выключаемых расширений, оценку экономии и готовые
CLI-аргументы. Сам запуск процесса — в vscode.launch_detached.
"""
from .categories import WEIGHT, WEIGHT_MB
from .safety import safe_arg, valid_ext_id
from .vscode import code_image_name


def compute_disabled(installed: list[str], ext_index: dict[str, str],
                     selected_cats: set[str],
                     force_disable: set[str] | None = None,
                     force_enable: set[str] | None = None) -> list[str]:
    """Выключаем расширения из невыбранных категорий. always_on и всё,
    чего нет в карте, остаётся включённым (безопасный дефолт).

    Персональные оверрайды по одному расширению (задаются в окне «Подробнее»)
    перекрывают решение по стеку:
    - force_enable — всегда держать включённым, даже если стек выключен;
    - force_disable — всегда выключать, даже если стек включён (в т.ч. always_on).
    force_enable имеет приоритет над force_disable, если id попал в оба набора."""
    fe = {e.lower() for e in (force_enable or ())}
    fd = {e.lower() for e in (force_disable or ())}
    disabled = []
    for ext in installed:
        if ext in fe:
            continue
        if ext in fd:
            disabled.append(ext)
            continue
        cat = ext_index.get(ext)
        if cat is None or cat == "always_on":
            continue
        if cat not in selected_cats:
            disabled.append(ext)
    return disabled


def disabled_by_category(disabled: list[str],
                         ext_index: dict[str, str]) -> list[tuple[str, list[str]]]:
    """Группирует выключаемые расширения по стеку для предпросмотра «что
    выключится». Возвращает список (ключ_категории, [id, ...]), отсортированный
    по ключу; расширения-оверрайды из выключенных стеков попадают в свою
    категорию, а не в карте — в псевдокатегорию '(не в карте)'."""
    groups: dict[str, list[str]] = {}
    for ext in disabled:
        cat = ext_index.get(ext) or "(не в карте)"
        groups.setdefault(cat, []).append(ext)
    return [(cat, sorted(exts)) for cat, exts in sorted(groups.items())]


def selection_signature(enabled_keys, bare: bool = False) -> str:
    """Компактная подпись текущего выбора — ключ для истории замеров памяти
    (#6): один и тот же набор стеков даёт одну подпись, чтобы показать
    «в прошлый раз с этим набором было X МБ»."""
    if bare:
        return "bare"
    keys = sorted(k for k in enabled_keys if k)
    return "|".join(keys) if keys else "core-only"


def estimate_saved_mb(disabled: list[str], ext_index: dict[str, str]) -> int:
    """Оценка освобождаемой памяти: каждую выключаемую категорию считаем
    один раз и только если у неё реально выключается установленное расширение."""
    cats_off = {ext_index.get(e) for e in disabled}
    cats_off.discard(None)
    cats_off.discard("always_on")
    return sum(WEIGHT_MB.get(WEIGHT.get(c, "light"), 30) for c in cats_off)


def build_launch_command(code_cli: str, disabled: list[str], folder: str,
                         new_window: bool, kill_first: bool,
                         profile: str = "", disable_gpu: bool = False,
                         bare: bool = False) -> str:
    """Строка для cmd.exe (эквивалент, показывается в диалоге и уходит в скрипт/
    ярлык). Сам лаунчер запускает Code.exe напрямую — см. build_launch_args."""
    folder = safe_arg(folder)        # защита от shell- и argument-инъекции
    profile = safe_arg(profile)
    parts = []
    if kill_first:
        parts.append(f'taskkill /F /IM "{code_image_name(code_cli)}" >nul 2>&1')
        parts.append("timeout /t 2 /nobreak >nul")
    cmd = [f'"{code_cli}"']
    if new_window or kill_first:
        cmd.append("--new-window")
    if profile:
        cmd.append(f'--profile "{profile}"')
    if bare:
        cmd.append("--disable-extensions")
    else:
        for d in disabled:
            if valid_ext_id(d):   # мусор/инъекцию в команду не пускаем
                cmd.append(f'--disable-extension "{d}"')
    if disable_gpu:
        cmd.append("--disable-gpu")
    if folder:
        cmd.append(f'"{folder}"')
    parts.append(" ".join(cmd))
    return " & ".join(parts)


def build_launch_args(disabled: list[str], folder: str, new_window: bool,
                      kill_first: bool, profile: str = "",
                      disable_gpu: bool = False, bare: bool = False) -> list[str]:
    """Аргументы запуска СПИСКОМ (без строки-команды) — для запуска без
    оболочки. Никакого экранирования не нужно: каждый аргумент уходит в argv
    как есть. safe_arg дополнительно срезает ведущие дефисы, чтобы путь/
    профиль не превратился в флаг Code.exe (argument injection)."""
    folder = safe_arg(folder)
    profile = safe_arg(profile)
    args: list[str] = []
    if new_window or kill_first:
        args.append("--new-window")
    if profile:
        args += ["--profile", profile]
    if bare:
        args.append("--disable-extensions")
    else:
        for d in disabled:
            if valid_ext_id(d):
                args += ["--disable-extension", d]
    if disable_gpu:
        args.append("--disable-gpu")
    if folder:
        args.append(folder)
    return args
