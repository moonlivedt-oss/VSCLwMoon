# -*- coding: utf-8 -*-
"""Запуск VS Code по имени пресета — одной функцией, без GUI.

Раньше «собрать набор и стартовать редактор» было расписано отдельно в окне и
отдельно в CLI: одинаковые пять шагов (разобрать пресет, прочитать список
расширений, построить карту зависимостей, посчитать выключаемое, запустить).
Теперь это одно место, и им пользуются все точки входа — окно, тихий CLI и
меню в трее. Разойтись в поведении они больше не могут: например, личные
исключения по расширениям приводятся к нижнему регистру здесь, а не трижды
по-разному (в CLI этого не делалось вовсе, и исключение, записанное с
заглавной буквы, молча не срабатывало).
"""
from __future__ import annotations

from .i18n import _
from .launch import build_launch_args, compute_disabled, selection_signature
from .manifests import build_dependency_map, read_extension_manifests
from .presets import normalize_preset
from .vscode import kill_vscode, launch_detached, load_installed


def resolve_overrides(cfg: dict) -> tuple[set[str], set[str]]:
    """(force_disable, force_enable) из конфига — персональные исключения по
    одному расширению. Битую форму игнорируем: исключения не должны мешать
    запуску."""
    ov = cfg.get("overrides", {})
    if not isinstance(ov, dict):
        return set(), set()
    dis = ov.get("disable", [])
    ena = ov.get("enable", [])
    return (
        {str(e).lower() for e in dis if isinstance(e, str)},
        {str(e).lower() for e in ena if isinstance(e, str)},
    )


def plan_launch(code_cli: str | None, cfg: dict, ext_index: dict[str, str],
                stacks, options: dict | None = None,
                installed: list[str] | None = None,
                dep_map: dict[str, set[str]] | None = None) -> dict:
    """Что именно произойдёт при запуске с этим набором — без побочных эффектов.

    Возвращает {"disabled", "args", "signature", "installed", "options"}.
    Отдельно от launch_preset, чтобы то же самое можно было показать в
    предпросмотре и проверить в тестах, ничего не запуская.

    installed и dep_map можно передать готовыми: окно и CLI уже держат их в
    руках, и перечитывать extensions.json с сотней package.json на каждый
    запуск незачем. Не передали — прочитаем сами (так работает трей)."""
    given = options or {}
    # Явные локальные переменные вместо dict[str, object]: и типы видны, и
    # опечатка в имени опции не проедет молча в аргументы запуска.
    folder = str(given.get("folder", "") or "")
    profile = str(given.get("profile", "") or "")
    kill = bool(given.get("kill", False))
    gpu_off = bool(given.get("gpu_off", False))
    bare = bool(given.get("bare", False))
    new_window = bool(given.get("new_window", True))
    opts = {"folder": folder, "profile": profile, "kill": kill,
            "gpu_off": gpu_off, "bare": bare, "new_window": new_window}
    if installed is None:
        installed, _src = load_installed(code_cli)
    force_disable, force_enable = resolve_overrides(cfg)
    if dep_map is None:
        try:
            dep_map = build_dependency_map(read_extension_manifests(code_cli))
        except Exception:
            dep_map = {}
    keys = {str(s) for s in stacks}
    disabled = compute_disabled(installed, ext_index, keys,
                                force_disable, force_enable, dep_map=dep_map)
    args = build_launch_args(disabled, folder, new_window, kill,
                             profile=profile, disable_gpu=gpu_off, bare=bare)
    return {
        "disabled": disabled,
        "args": args,
        "signature": selection_signature(keys, bare),
        "installed": installed,
        "options": opts,
    }


def launch_preset(code_cli: str | None, cfg: dict, ext_index: dict[str, str],
                  name: str) -> tuple[bool, str]:
    """Открыть VS Code по сохранённому пресету. (успех, сообщение).

    Пресет несёт и набор стеков, и опции запуска (папка, закрыть редактор,
    без GPU, профиль) — они применяются целиком, как если бы пользователь
    выбрал этот пресет в окне и нажал «Запустить»."""
    if not code_cli:
        return False, _("Не найден CLI VS Code.")
    value = cfg.get("presets", {}).get(name)
    if value is None:
        return False, _("Пресет не найден: {name}").format(name=name)
    p = normalize_preset(value)
    plan = plan_launch(code_cli, cfg, ext_index, p["stacks"], {
        "folder": p["folder"], "profile": p["profile"], "kill": p["kill"],
        "gpu_off": p["gpu_off"], "bare": p["bare"], "new_window": p["new_window"],
    })
    if p["kill"]:
        kill_vscode(code_cli)
    try:
        launch_detached(code_cli, plan["args"])
    except Exception as e:
        return False, _("Не удалось запустить VS Code: {err}").format(err=e)
    n = len(plan["disabled"])
    return True, (_("Пресет «{name}»: голый режим.").format(name=name) if p["bare"]
                  else _("Пресет «{name}»: выключено расширений — {n}.").format(
                      name=name, n=n))
