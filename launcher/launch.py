# -*- coding: utf-8 -*-
"""Что выключить и как запустить VS Code с этим набором.

Читаемо: чистые функции без IO. Берём (installed, ext_index, selected),
возвращаем список выключаемых расширений, оценку экономии и готовые
CLI-аргументы. Сам запуск процесса — в vscode.launch_detached.
"""
from .categories import WEIGHT, WEIGHT_MB
from .safety import safe_arg, valid_ext_id
from .vscode import code_image_name


def required_by_enabled(enabled: set[str],
                        dep_map: dict[str, set[str]]) -> set[str]:
    """Транзитивное замыкание зависимостей включённого набора (#1).

    Для каждого включённого расширения собираем всё, от чего оно зависит
    (extensionDependencies + extensionPack, см. manifests.build_dependency_map),
    и зависимости зависимостей — чтобы получить полный список того, что обязано
    остаться включённым. Циклы в графе не зацикливают обход: идём только по
    ещё не добавленным."""
    result: set[str] = set()
    stack = list(enabled)
    while stack:
        cur = stack.pop()
        for dep in dep_map.get(cur, ()):
            if dep not in result:
                result.add(dep)
                stack.append(dep)
    return result


def compute_disabled(installed: list[str], ext_index: dict[str, str],
                     selected_cats: set[str],
                     force_disable: set[str] | None = None,
                     force_enable: set[str] | None = None,
                     dep_map: dict[str, set[str]] | None = None) -> list[str]:
    """Выключаем расширения из невыбранных категорий. always_on и всё,
    чего нет в карте, остаётся включённым (безопасный дефолт).

    Персональные оверрайды по одному расширению (задаются в окне «Подробнее»)
    перекрывают решение по стеку:
    - force_enable — всегда держать включённым, даже если стек выключен;
    - force_disable — всегда выключать, даже если стек включён (в т.ч. always_on).
    force_enable имеет приоритет над force_disable, если id попал в оба набора.

    dep_map (#1) — карта зависимостей расширений (id -> от кого зависит). Если
    задана, из списка на выключение вытаскиваются те, от кого зависит хоть одно
    оставшееся включённым расширение: иначе VS Code тихо не активировал бы
    включённый плагин из-за погашенной зависимости. Явный force_disable сильнее
    защиты по зависимости — это осознанный выбор пользователя."""
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

    if dep_map:
        disabled = _keep_dependencies_enabled(installed, disabled, fd, dep_map)
    return disabled


def _keep_dependencies_enabled(installed: list[str], disabled: list[str],
                               force_disable: set[str],
                               dep_map: dict[str, set[str]]) -> list[str]:
    """Убрать из `disabled` те расширения, что нужны включённому набору как
    зависимость (#1). Итерируем до неподвижной точки: вытащенная зависимость
    сама включается и может «спасти» свою зависимость. force_disable не спасаем
    — пользователь выключил его явно."""
    disabled_set = set(disabled)
    installed_set = set(installed)
    while True:
        enabled_set = installed_set - disabled_set
        needed = required_by_enabled(enabled_set, dep_map) & installed_set
        rescue = {d for d in disabled_set if d in needed and d not in force_disable}
        if not rescue:
            break
        disabled_set -= rescue
    return [d for d in disabled if d in disabled_set]


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
    cats_off = {cat for e in disabled
                if (cat := ext_index.get(e)) is not None and cat != "always_on"}
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
