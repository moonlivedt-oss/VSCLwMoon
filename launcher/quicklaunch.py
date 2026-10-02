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

import os

from . import compat
from .i18n import _
from .launch import build_launch_args, compute_disabled, selection_signature
from .manifests import build_dependency_map, read_extension_manifests
from .presets import normalize_preset
from .vscode import (kill_vscode, launch_detached, load_installed,
                     vscode_process_count, wait_vscode_closed)


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


def conflicting_extensions(cfg: dict, folder: str, installed, force_enable=()) -> list[str]:
    """Расширения, которые на этот запуск надо выключить, чтобы проект собирался.

    Сейчас это сборщики, передающие g++ полный путь (C/C++ Compile Run): в папке с
    русскими буквами новые MSYS2 на нём падают, и F5/F6 ломается. Выключаем
    только на этот запуск (флаг --disable-extension, ничего не удаляется), если
    включена автопочинка и человек не держит расширение «всегда включённым»."""
    if not folder or not cfg.get("auto_fix", True):
        return []
    from .cpp_project import ABS_PATH_RUNNERS, has_non_ascii

    if not has_non_ascii(folder):
        return []
    have = {str(e).lower() for e in installed}
    keep = {str(e).lower() for e in force_enable}
    return [e for e in ABS_PATH_RUNNERS if e in have and e not in keep]


def plan_launch(code_cli: str | None, cfg: dict, ext_index: dict[str, str],
                stacks, options: dict | None = None,
                installed: list[str] | None = None,
                dep_map: dict[str, set[str]] | None = None,
                manifests: dict[str, dict] | None = None,
                extra_disable=None, compat_mode: str | None = None) -> dict:
    """Что именно произойдёт при запуске с этим набором — без побочных эффектов.

    Возвращает {"disabled", "args", "signature", "installed", "options"}.
    Отдельно от launch_preset, чтобы то же самое можно было показать в
    предпросмотре и проверить в тестах, ничего не запуская.

    installed и dep_map можно передать готовыми: окно и CLI уже держат их в
    руках, и перечитывать extensions.json с сотней package.json на каждый
    запуск незачем. Не передали — прочитаем сами (так работает трей).

    extra_disable — что ещё выключить на этот запуск (окно передаёт сюда выбор
    человека из диалога совместимости). compat_mode — режим проверки
    совместимости (compat.py): None — из настроек; окно, спросившее само,
    передаёт 'off'. В режиме 'auto' проблемные расширения выключаются здесь же
    (compat_disabled), найденное перечисляется в compat_issues."""
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
    auto_off = conflicting_extensions(cfg, folder, installed, force_enable)
    force_disable |= set(auto_off)
    force_disable |= {str(e).lower() for e in (extra_disable or ())}
    mode = compat.mode_of(cfg) if compat_mode is None else compat_mode
    if manifests is None and (dep_map is None or (mode != "off" and not bare)):
        try:
            manifests = read_extension_manifests(code_cli)
        except Exception:
            manifests = {}
    if dep_map is None:
        dep_map = build_dependency_map(manifests or {})
    keys = {str(s) for s in stacks}
    disabled = compute_disabled(installed, ext_index, keys,
                                force_disable, force_enable, dep_map=dep_map)
    issues: list[dict] = []
    compat_off: set[str] = set()
    if mode != "off" and not bare:
        try:
            off = set(disabled)
            issues, compat_off = compat.resolve(
                [e for e in installed if e not in off], manifests or {},
                compat.vscode_version(code_cli), installed, mode,
                cfg.get("compat_ignored") or (),
                ctx=compat.context(code_cli),
            )
        except Exception:
            issues, compat_off = [], set()
        if compat_off:
            disabled = compute_disabled(installed, ext_index, keys,
                                        force_disable | compat_off, force_enable,
                                        dep_map=dep_map)
    args = build_launch_args(disabled, folder, new_window, kill,
                             profile=profile, disable_gpu=gpu_off, bare=bare)
    return {
        "disabled": disabled,
        "auto_disabled": [] if bare else auto_off,
        "compat_issues": issues,
        "compat_disabled": sorted(compat_off),
        "args": args,
        "signature": selection_signature(keys, bare),
        "installed": installed,
        "options": opts,
    }


def compat_summary(plan: dict) -> str:
    """Хвост сообщения трея/CLI о совместимости: что выключено и что осталось."""
    out = ""
    if plan.get("compat_disabled"):
        out += " " + _("Выключены несовместимые: {ids}.").format(
            ids=", ".join(plan["compat_disabled"]))
    left = plan.get("compat_issues") or []
    if left:
        out += " " + _("Проблем совместимости: {n} — подробности в окне лаунчера "
                       "(«Обслуживание» → «Совместимость расширений»).").format(n=len(left))
    return out


def launch_last(code_cli: str | None, cfg: dict, ext_index: dict[str, str]) -> tuple[bool, str]:
    """Открыть VS Code с тем же набором и опциями, что в прошлый раз (то, что
    стоит в окне лаунчера) — без открытия окна."""
    recent = cfg.get("recent_folders") or [""]
    value = {
        "stacks": list(cfg.get("last_selected", [])),
        "folder": recent[0] if isinstance(recent[0], str) else "",
        "kill": bool(cfg.get("kill_first", True)),
        "gpu_off": bool(cfg.get("disable_gpu", False)),
        "new_window": bool(cfg.get("new_window", True)),
        "profile": str(cfg.get("profile", "") or ""),
    }
    return launch_preset(code_cli, cfg, ext_index, _("последний выбор"), value=value)


def launch_preset(code_cli: str | None, cfg: dict, ext_index: dict[str, str],
                  name: str, value=None) -> tuple[bool, str]:
    """Открыть VS Code по сохранённому пресету. (успех, сообщение).

    Пресет несёт и набор стеков, и опции запуска (папка, закрыть редактор,
    без GPU, профиль) — они применяются целиком, как если бы пользователь
    выбрал этот пресет в окне и нажал «Запустить»."""
    if not code_cli:
        return False, _("Не найден CLI VS Code.")
    if value is None:
        value = cfg.get("presets", {}).get(name)
    if value is None:
        return False, _("Пресет не найден: {name}").format(name=name)
    p = normalize_preset(value)
    lost_folder = ""
    if p["folder"] and not os.path.exists(p["folder"]):
        # Папку проекта удалили или переименовали: открываем редактор без неё и
        # говорим об этом, а не передаём VS Code несуществующий путь.
        lost_folder, p["folder"] = p["folder"], ""
    plan = plan_launch(code_cli, cfg, ext_index, p["stacks"], {
        "folder": p["folder"], "profile": p["profile"], "kill": p["kill"],
        "gpu_off": p["gpu_off"], "bare": p["bare"], "new_window": p["new_window"],
    })
    already_open = False
    if p["kill"] and vscode_process_count(code_cli) > 0:
        if cfg.get("soft_close", False):
            # Мягко: VS Code сам сохранит/спросит про несохранённое. Не закрылся —
            # запуск отменяем, а не добиваем принудительно: там может висеть
            # вопрос «сохранить файл?».
            kill_vscode(code_cli, graceful=True)
            if not wait_vscode_closed(code_cli, timeout=20.0):
                return False, _(
                    "VS Code не закрылся (возможно, ждёт ответа про несохранённые "
                    "файлы) — запуск отменён. Закройте его и повторите."
                )
        else:
            kill_vscode(code_cli)
            if not wait_vscode_closed(code_cli):  # иначе новый процесс уйдёт в старый
                already_open = True
    elif not p["kill"]:
        already_open = vscode_process_count(code_cli) > 0
    try:
        launch_detached(code_cli, plan["args"])
    except Exception as e:
        return False, _("Не удалось запустить VS Code: {err}").format(err=e)
    n = len(plan["disabled"])
    msg = (_("Пресет «{name}»: голый режим.").format(name=name) if p["bare"]
           else _("Пресет «{name}»: выключено расширений — {n}.").format(
               name=name, n=n))
    if plan.get("auto_disabled"):
        msg += " " + _("Автоматически выключено для этой папки: {ids}.").format(
            ids=", ".join(plan["auto_disabled"])
        )
    msg += compat_summary(plan)
    if already_open and (p["bare"] or n):
        # Уже запущенный VS Code новые --disable-extension не применяет.
        msg += " " + _(
            "VS Code уже был открыт, поэтому набор расширений не изменился: "
            "закройте его окна и запустите пресет снова."
        )
    if lost_folder:
        msg += " " + _("Папка пресета не найдена, открыто без неё: {folder}").format(
            folder=lost_folder
        )
    return True, msg
