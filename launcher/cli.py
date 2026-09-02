# -*- coding: utf-8 -*-
r"""Тихий режим запуска без GUI (#10, расширен #4/#5/#19/#20/#21).

Позволяет открыть VS Code с нужным набором стеков из командной строки —
для ярлыков, скриптов, планировщика. PyQt6 не импортируется, поэтому режим
работает и там, где GUI не нужен.

    python vscode_launcher.py --run --preset web --folder D:\proj
    python vscode_launcher.py --run --stacks python,git
    python vscode_launcher.py --stacks python,git          # dry-run: показать команду
    python vscode_launcher.py --stacks python,git --json    # то же, но JSON
    python vscode_launcher.py --list-stacks                 # доступные стеки
    python vscode_launcher.py --list-presets
    python vscode_launcher.py --make-shortcut web.cmd --preset web

Коды возврата: 0 — успех/dry-run; 2 — ошибка использования (нет CLI VS Code,
неизвестный пресет для ярлыка); 3 — процесс VS Code не удалось запустить.
"""
from __future__ import annotations

import argparse
import json as _json
import sys

from .categories import WEIGHT, WEIGHT_LABEL, build_ext_index, load_categories
from .config import load_config
from .launch import (
    build_launch_args, build_launch_command, compute_disabled, estimate_saved_mb,
)
from .manifests import build_dependency_map, read_extension_manifests
from .presets import build_shortcut_cmd, normalize_preset, preset_stacks
from .vscode import (
    kill_vscode, launch_detached, load_installed, resolve_code_cli,
)
from . import toolchains as _tc


def _resolve_selected(args, cfg: dict, valid_keys: set[str]) -> tuple[set[str], list[str]]:
    """Собрать выбранные ключи из --preset и --stacks. Возвращает (ключи,
    предупреждения о неизвестных ключах). Пресет любой формы (список ключей или
    словарь-профиль) разбирается через preset_stacks."""
    selected: set[str] = set()
    warns: list[str] = []
    if args.preset:
        value = cfg.get("presets", {}).get(args.preset)
        if value is None:
            warns.append(f"Пресет не найден: {args.preset!r}")
        else:
            selected |= set(preset_stacks(value))
    if args.stacks:
        for k in (s.strip() for s in args.stacks.split(",")):
            if not k:
                continue
            if k in valid_keys:
                selected.add(k)
            else:
                warns.append(f"Неизвестный стек: {k!r}")
    return selected, warns


def _merge_options(args, cfg: dict) -> dict:
    """Слить опции запуска из словарной формы пресета (#4) с флагами командной
    строки. Явные флаги CLI имеют приоритет: булевы объединяются по ИЛИ (если
    пресет ИЛИ флаг просит закрыть/без-GPU/голый — так и делаем), а строки
    (папка/профиль) берутся из CLI, если заданы, иначе из пресета."""
    value = cfg.get("presets", {}).get(args.preset) if args.preset else None
    opt = normalize_preset(value if isinstance(value, dict) else [])
    return {
        "folder": args.folder or opt["folder"],
        "profile": args.profile or opt["profile"],
        "kill": bool(args.kill or opt["kill"]),
        "gpu_off": bool(args.gpu_off or opt["gpu_off"]),
        "bare": bool(args.bare or opt["bare"]),
        # Новое окно по умолчанию; --no-new-window или пресет могут его снять.
        "new_window": (not args.no_new_window) and opt["new_window"],
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vscode_launcher",
        description="Запуск VS Code с выбранным набором стеков расширений.")
    p.add_argument("--stacks", metavar="a,b,c",
                   help="ключи стеков через запятую (как в data/categories.json)")
    p.add_argument("--preset", metavar="ИМЯ", help="имя сохранённого пресета")
    p.add_argument("--folder", metavar="ПУТЬ", default="", help="папка проекта")
    p.add_argument("--profile", metavar="ИМЯ", default="", help="профиль VS Code")
    p.add_argument("--bare", action="store_true",
                   help="голый режим: полностью без расширений")
    p.add_argument("--gpu-off", action="store_true", help="--disable-gpu")
    p.add_argument("--kill", action="store_true",
                   help="жёстко закрыть VS Code перед стартом (память освободится)")
    p.add_argument("--no-new-window", action="store_true",
                   help="не форсировать новое окно")
    p.add_argument("--code-cli", metavar="ПУТЬ", default="",
                   help="путь к code.cmd/Code.exe (портативная/нестандартная сборка)")
    p.add_argument("--run", action="store_true",
                   help="действительно запустить (без флага — dry-run: только показать команду)")
    p.add_argument("--json", action="store_true",
                   help="машиночитаемый вывод (для скриптов)")
    p.add_argument("--quiet", action="store_true",
                   help="без пояснительного вывода (для ярлыков)")
    p.add_argument("--list-presets", action="store_true",
                   help="показать сохранённые пресеты и выйти")
    p.add_argument("--list-stacks", action="store_true",
                   help="показать доступные стеки (ключ, нагрузка, установлено) и выйти")
    p.add_argument("--make-shortcut", metavar="ПУТЬ", default="",
                   help="создать .cmd-ярлык, открывающий VS Code с пресетом (--preset)")
    p.add_argument("--list-toolchains", action="store_true",
                   help="показать доступные языковые тулчейны и выйти")
    p.add_argument("--toolchain-status", metavar="КЛЮЧ", nargs="?",
                   const="*", default=None,
                   help="статус тулчейна (напр. cpp); без значения — по всем")
    p.add_argument("--install-toolchain", metavar="КЛЮЧ", default="",
                   help="установить тулчейн через winget (напр. cpp) и прописать PATH")
    p.add_argument("--upgrade-toolchain", metavar="КЛЮЧ", default="",
                   help="обновить установленные пакеты тулчейна через winget upgrade")
    p.add_argument("--uninstall-toolchain", metavar="КЛЮЧ", default="",
                   help="удалить пакеты тулчейна через winget и очистить PATH")
    p.add_argument("--configure-vscode", metavar="КЛЮЧ", default="",
                   help="прописать компилятор тулчейна в settings.json VS Code (сейчас cpp)")
    p.add_argument("--add-existing", metavar="КЛЮЧ", default="",
                   help="добавить в PATH уже установленный на диске компилятор (без загрузки)")
    p.add_argument("--include-optional", action="store_true",
                   help="с --install/--upgrade-toolchain: и дополнительные пакеты (CMake/Ninja/Clang)")
    p.add_argument("--doctor", action="store_true",
                   help="проверить окружение: тулчейны с версиями, здоровье PATH, JAVA_HOME (#8)")
    p.add_argument("--outdated", action="store_true",
                   help="показать тулчейны, для которых доступно обновление (winget upgrade) (#5)")
    return p


def _launcher_invocation() -> list[str]:
    """Как позвать лаунчер из .cmd-ярлыка. Собранный exe — сам себе точка входа;
    из исходников — интерпретатор + vscode_launcher.py. Пытаемся взять
    оконный pythonw.exe, чтобы ярлык не мигал консолью."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    from pathlib import Path
    py = sys.executable
    pyw = str(Path(py).with_name("pythonw.exe"))
    if Path(pyw).exists():
        py = pyw
    from .paths import ROOT
    return [py, str(ROOT / "vscode_launcher.py")]


def _list_stacks(cats: dict, installed: list[str], ext_index: dict, as_json: bool) -> int:
    inst = set(installed)
    rows = []
    for key, cat in cats.get("categories", {}).items():
        exts = cat.get("extensions", [])
        n_inst = sum(1 for e in exts if e.lower() in inst)
        weight = WEIGHT.get(key, "light")
        rows.append({"key": key, "title": cat.get("title", key),
                     "weight": weight, "extensions": len(exts),
                     "installed": n_inst})
    if as_json:
        print(_json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("Стеки не загружены (проверь data/categories.json).")
        return 0
    print("Доступные стеки:")
    for r in rows:
        label = WEIGHT_LABEL.get(r["weight"], r["weight"])
        print(f"  {r['key']:<14} [{label:<8}] "
              f"установлено {r['installed']}/{r['extensions']}  — {r['title']}")
    return 0


def _make_shortcut(args, cfg: dict) -> int:
    if not args.preset:
        print("Ошибка: для --make-shortcut нужен --preset ИМЯ.")
        return 2
    if args.preset not in cfg.get("presets", {}):
        print(f"Ошибка: пресет не найден: {args.preset!r}")
        return 2
    body = build_shortcut_cmd(_launcher_invocation(), args.preset)
    try:
        from pathlib import Path
        path = Path(args.make_shortcut)
        if path.suffix.lower() != ".cmd":
            path = path.with_suffix(".cmd")
        path.write_text(body, encoding="utf-8")
    except Exception as e:
        print("Не удалось записать ярлык:", e)
        return 2
    print(f"Ярлык создан: {path}  (двойной клик открывает VS Code с пресетом "
          f"{args.preset!r}).")
    return 0


def _list_toolchains(as_json: bool) -> int:
    """Показать каталог тулчейнов: ключ, что ставит, установлено ли."""
    rows: list[dict] = []
    for key in _tc.toolchain_keys():
        tc = _tc.get_toolchain(key)
        if tc is None:
            continue
        pkgs: list[dict] = []
        for st in _tc.toolchain_status(key):
            pkg = st["package"]
            pkgs.append({"id": pkg.winget_id, "title": pkg.title,
                         "optional": pkg.optional, "installed": st["installed"],
                         "version": st["version"]})
        rows.append({"key": key, "title": tc.title, "note": tc.note,
                     "packages": pkgs})
    if as_json:
        print(_json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    summ = _tc.toolchain_summary()
    if not summ["winget"]:
        print("! winget не найден — установка недоступна (установите «App Installer»).")
    else:
        print(f"winget: {_tc.winget_version() or 'найден'}")
    print(f"Готовы: {summ['ready']}/{summ['total']} тулчейнов. "
          f"Доступные (ключ совпадает с ключом стека):")
    for r in rows:
        done = sum(1 for p in r["packages"] if p["installed"] and not p["optional"])
        req = sum(1 for p in r["packages"] if not p["optional"])
        print(f"  {r['key']:<8} {done}/{req} осн. — {r['title']}: {r['note']}")
    if summ["missing"]:
        print(f"\nНе хватает: {', '.join(summ['missing'])}")
    print("\nСтатус подробнее:  --toolchain-status [КЛЮЧ]")
    print("Установить:        --install-toolchain КЛЮЧ [--include-optional]")
    print("Обновить/удалить:  --upgrade-toolchain КЛЮЧ | --uninstall-toolchain КЛЮЧ")
    print("Настроить VS Code: --configure-vscode cpp   |   уже есть: --add-existing cpp")
    print("Проверить:         --doctor (окружение)   |   --outdated (обновления)")
    return 0


def _doctor(as_json: bool) -> int:
    """#8: отчёт об окружении — тулчейны с версиями, здоровье PATH, JAVA_HOME."""
    rep = _tc.environment_report()
    if as_json:
        print(_json.dumps(rep, ensure_ascii=False, indent=2))
        return 0
    print("winget:", rep.get("winget") or "не найден")
    tools = rep.get("tools", [])
    print(f"Установленные тулчейны ({len(tools)}):")
    for t in tools:
        print(f"  ✓ {t['title']} — {t.get('version') or ''}")
    jh = rep.get("java_home", {})
    if jh.get("set"):
        print("JAVA_HOME:", jh.get("path"),
              "" if jh.get("ok") else f"({jh.get('reason')})")
    else:
        print("JAVA_HOME: не задан")
    ph = rep.get("path", {})
    print(f"PATH: {ph.get('count', 0)} записей, длина {ph.get('length', 0)}")
    if ph.get("duplicates"):
        print(f"  дубликаты: {len(ph['duplicates'])}")
    if ph.get("missing"):
        print(f"  несуществующие каталоги: {len(ph['missing'])}")
    return 0


def _outdated(as_json: bool) -> int:
    """#5: тулчейны, для которых winget видит обновление."""
    rows = _tc.outdated_packages()
    if as_json:
        print(_json.dumps(
            [{"key": r["key"], "id": r["package"].winget_id, "version": r["version"]}
             for r in rows], ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("Обновлений для тулчейнов не найдено (или winget недоступен).")
        return 0
    print(f"Доступны обновления ({len(rows)}):")
    for r in rows:
        print(f"  ↑ {r['key']}: {r['package'].title} (сейчас {r['version'] or '?'})")
    return 0


def _toolchain_status(key: str, as_json: bool) -> int:
    # Без ключа (const '*') — сводный статус по всем тулчейнам.
    if key == "*":
        if as_json:
            print(_json.dumps(_tc.toolchain_summary(), ensure_ascii=False, indent=2))
            return 0
        summ = _tc.toolchain_summary()
        print(f"Готовы: {summ['ready']}/{summ['total']}. "
              f"Не хватает: {', '.join(summ['missing']) or '—'}")
        for k in _tc.toolchain_keys():
            _toolchain_status(k, False)
            print()
        return 0
    tc = _tc.get_toolchain(key)
    if not tc:
        print(f"Неизвестный тулчейн: {key!r}. Список: --list-toolchains")
        return 2
    rows = _tc.toolchain_status(key)
    if as_json:
        print(_json.dumps(
            [{"id": r["package"].winget_id, "optional": r["package"].optional,
              "installed": r["installed"], "version": r["version"]} for r in rows],
            ensure_ascii=False, indent=2))
        return 0
    print(f"Тулчейн {key} — {tc.title}: {tc.note}")
    for r in rows:
        pkg = r["package"]
        mark = "✓" if r["installed"] else "—"
        opt = " (доп.)" if pkg.optional else ""
        ver = f"  [{r['version']}]" if r["version"] else ""
        print(f"  {mark} {pkg.title}{opt}  «{pkg.winget_id}»{ver}")
        if pkg.provides:
            print(f"       даёт: {', '.join(pkg.provides)}")
    return 0


def _install_toolchain(key: str, include_optional: bool, out) -> int:
    tc = _tc.get_toolchain(key)
    if not tc:
        print(f"Неизвестный тулчейн: {key!r}. Список: --list-toolchains")
        return 2
    if not _tc.winget_available():
        print("Ошибка: winget не найден. Установите «App Installer» из Microsoft Store.")
        return 2
    todo = [p for p in tc.packages
            if (include_optional or not p.optional) and not _tc.package_installed(p)]
    if not todo:
        out(f"Тулчейн {key} уже установлен — ставить нечего.")
        return 0
    out(f"Устанавливаю тулчейн {key} ({tc.title}): {len(todo)} пакет(ов) через winget…")
    fails = 0
    for i, pkg in enumerate(todo, 1):
        out(f"[{i}/{len(todo)}] {pkg.title} ({pkg.winget_id})…")
        ok, msg = _tc.install_package(pkg)
        if ok:
            out(f"    готово. {msg.splitlines()[-1][:120] if msg else ''}".rstrip())
        else:
            fails += 1
            print(f"    ошибка: {(msg or '').strip()[:400]}")
    if fails:
        print(f"Готово с ошибками: не установлено {fails} из {len(todo)}.")
        return 3
    # Верификация: реально ли инструменты отвечают.
    for pkg in todo:
        ok, info = _tc.verify_package(pkg)
        out(f"    проверка {pkg.title}: {'OK — ' + info if ok else 'не отвечает в PATH'}")
    out("Готово. Откройте новый терминал, чтобы PATH подхватился.")
    if key == "cpp":
        out("Подсказка: пропишите компилятор в VS Code — --configure-vscode cpp")
    return 0


def _upgrade_toolchain(key: str, include_optional: bool, out) -> int:
    tc = _tc.get_toolchain(key)
    if not tc:
        print(f"Неизвестный тулчейн: {key!r}. Список: --list-toolchains")
        return 2
    if not _tc.winget_available():
        print("Ошибка: winget не найден.")
        return 2
    todo = [p for p in tc.packages
            if (include_optional or not p.optional) and _tc.package_installed(p)]
    if not todo:
        out(f"Тулчейн {key}: обновлять нечего (ничего не установлено).")
        return 0
    out(f"Обновляю тулчейн {key}: {len(todo)} пакет(ов) через winget upgrade…")
    fails = 0
    for i, pkg in enumerate(todo, 1):
        out(f"[{i}/{len(todo)}] {pkg.title}…")
        ok, msg = _tc.upgrade_package(pkg)
        if not ok:
            fails += 1
            print(f"    ошибка: {(msg or '').strip()[:300]}")
    if fails:
        print(f"Готово с ошибками: {fails} из {len(todo)}.")
        return 3
    out("Готово.")
    return 0


def _uninstall_toolchain(key: str, out) -> int:
    tc = _tc.get_toolchain(key)
    if not tc:
        print(f"Неизвестный тулчейн: {key!r}. Список: --list-toolchains")
        return 2
    todo = [p for p in tc.packages if _tc.package_installed(p)]
    if not todo:
        out(f"Тулчейн {key}: удалять нечего.")
        return 0
    out(f"Удаляю тулчейн {key}: {len(todo)} пакет(ов)…")
    fails = 0
    for i, pkg in enumerate(todo, 1):
        out(f"[{i}/{len(todo)}] {pkg.title}…")
        ok, msg = _tc.uninstall_package(pkg)
        if not ok:
            fails += 1
            print(f"    ошибка: {(msg or '').strip()[:300]}")
    if fails:
        print(f"Готово с ошибками: {fails} из {len(todo)}.")
        return 3
    out("Готово.")
    return 0


def _add_existing(key: str, out) -> int:
    """Добавить в PATH уже установленный на диске компилятор — без загрузки."""
    tc = _tc.get_toolchain(key)
    if not tc:
        print(f"Неизвестный тулчейн: {key!r}. Список: --list-toolchains")
        return 2
    added = 0
    for pkg in tc.packages:
        if pkg.optional or _tc.package_installed(pkg):
            continue
        bindir = _tc.find_tool_on_disk(pkg)
        if bindir:
            ok, msg = _tc.env_path.add_to_user_path(bindir)
            out(f"{pkg.title}: {msg}")
            added += 1 if ok else 0
        else:
            out(f"{pkg.title}: на диске не найден — используйте --install-toolchain {key}.")
    if added:
        out("Готово. Откройте новый терминал, чтобы PATH подхватился.")
    return 0


def _configure_vscode(key: str, cfg: dict, out) -> int:
    """Прописать компилятор тулчейна в settings.json пользователя VS Code."""
    if not _tc.get_toolchain(key):
        print(f"Неизвестный тулчейн: {key!r}. Список: --list-toolchains")
        return 2
    code_cli = resolve_code_cli(cfg)
    ok, msg = _tc.configure_vscode_for(key, code_cli)
    print(msg)
    return 0 if ok else 2


def cli_main(argv: list[str] | None = None) -> int:
    # argv=None → argparse сам возьмёт sys.argv[1:]. Так работает и как
    # console-script `vscode-launcher` (без аргументов), и при явном вызове
    # из vscode_launcher.py со списком флагов.
    # Кириллица в командной строке ломается о кодировку консоли Windows —
    # переводим stdout в UTF-8, если можем (Python 3.7+). Тихо игнорируем,
    # если поток не поддерживает reconfigure (перенаправление в файл и т.п.).
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # type: ignore[union-attr]
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    cfg = load_config()
    quiet = args.quiet
    out = (lambda *a: None) if quiet else print

    # Тулчейны не зависят от VS Code — обрабатываем до поиска его CLI.
    if args.list_toolchains:
        return _list_toolchains(args.json)
    if args.toolchain_status is not None:
        return _toolchain_status(args.toolchain_status, args.json)
    if args.install_toolchain:
        return _install_toolchain(args.install_toolchain, args.include_optional, out)
    if args.upgrade_toolchain:
        return _upgrade_toolchain(args.upgrade_toolchain, args.include_optional, out)
    if args.uninstall_toolchain:
        return _uninstall_toolchain(args.uninstall_toolchain, out)
    if args.add_existing:
        return _add_existing(args.add_existing, out)
    if args.configure_vscode:
        return _configure_vscode(args.configure_vscode, cfg, out)
    if args.doctor:
        return _doctor(args.json)
    if args.outdated:
        return _outdated(args.json)

    if args.list_presets:
        presets = cfg.get("presets", {})
        if not presets:
            print("Пресетов пока нет.")
            return 0
        print("Пресеты:")
        for name, value in presets.items():
            print(f"  {name}: {', '.join(preset_stacks(value)) or '(пусто)'}")
        return 0

    cats, cats_err = load_categories()
    if cats_err and not quiet:
        print("categories.json:", cats_err)
    ext_index = build_ext_index(cats, cfg.get("extra_categories"))  # #6: оверлей раскладки
    valid_keys = set(cats.get("categories", {}))
    code_cli = resolve_code_cli({**cfg, **({"code_cli": args.code_cli} if args.code_cli else {})})

    if args.make_shortcut:
        return _make_shortcut(args, cfg)

    installed, source = load_installed(code_cli)

    if args.list_stacks:
        return _list_stacks(cats, installed, ext_index, args.json)

    selected, warns = _resolve_selected(args, cfg, valid_keys)
    for w in warns:
        out("!", w)

    opts = _merge_options(args, cfg)
    ov = cfg.get("overrides", {})
    force_disable = set(ov.get("disable", []))
    force_enable = set(ov.get("enable", []))
    dep_map = build_dependency_map(read_extension_manifests(code_cli))
    disabled = compute_disabled(installed, ext_index, selected,
                                force_disable, force_enable, dep_map=dep_map)
    saved = estimate_saved_mb(disabled, ext_index)
    cmd = build_launch_command(code_cli or "code", disabled, opts["folder"],
                               opts["new_window"], opts["kill"], profile=opts["profile"],
                               disable_gpu=opts["gpu_off"], bare=opts["bare"])

    if args.json:
        print(_json.dumps({
            "code_cli": code_cli, "installed": len(installed), "source": source,
            "selected": sorted(selected), "disabled": sorted(disabled),
            "disabled_count": len(disabled), "estimated_saved_mb": saved,
            "bare": opts["bare"], "folder": opts["folder"], "command": cmd,
            "will_run": bool(args.run and code_cli),
        }, ensure_ascii=False, indent=2))
    else:
        out(f"CLI: {code_cli or 'не найден'} | расширений: {len(installed)} ({source})")
        out(f"выбранные стеки: {', '.join(sorted(selected)) or '(только ядро)'}")
        out(f"будет выключено: {len(disabled)} (~{saved} МБ)"
            if not opts["bare"] else "голый режим: все расширения выключены")
        out("команда:", cmd)

    if not args.run:
        if not args.json:
            out("(dry-run — добавь --run, чтобы запустить)")
        return 0
    if not code_cli:
        print("Ошибка: не найден CLI VS Code — запуск невозможен.")
        return 2

    if opts["kill"]:
        kill_vscode(code_cli)
    launch_args = build_launch_args(disabled, opts["folder"], opts["new_window"],
                                    opts["kill"], profile=opts["profile"],
                                    disable_gpu=opts["gpu_off"], bare=opts["bare"])
    try:
        launch_detached(code_cli, launch_args)
    except Exception as e:
        print("Ошибка запуска VS Code:", e)
        return 3
    out("Запущено.")
    return 0
