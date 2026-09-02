# -*- coding: utf-8 -*-
"""CLI-режим: прогон логики без GUI.

Показывает что включится/выключится и итоговую команду. Полезен для CI,
для отладки карты категорий и для быстрого ответа на вопрос «а что вообще
происходит при таких галочках».

    python vscode_launcher.py --selftest python,web
"""
import time

from .categories import build_ext_index, load_categories
from .classify import suggest_categories
from .launch import build_launch_command, compute_disabled, estimate_saved_mb
from .manifests import build_dependency_map, read_extension_manifests
from .paths import ROOT
from .vscode import code_footprint_mb, find_code_cli, load_installed


def selftest(selected_csv: str):
    cats, cats_err = load_categories()
    if cats_err:
        print("categories.json:", cats_err)
    idx = build_ext_index(cats)
    code_cli = find_code_cli()
    print("code CLI:", code_cli)
    t0 = time.perf_counter()
    installed, source = load_installed(code_cli)
    dt = (time.perf_counter() - t0) * 1000
    print(f"установлено расширений: {len(installed)}  (источник: {source}, {dt:.0f} мс)")
    mb, nproc = code_footprint_mb(code_cli)
    print(f"VS Code сейчас: {mb} МБ (private WS), {nproc} процессов"
          if nproc else "VS Code сейчас не запущен")
    manifests = read_extension_manifests(code_cli)
    dep_map = build_dependency_map(manifests)
    selected = {s.strip() for s in selected_csv.split(",") if s.strip()}
    print("выбранные категории:", selected)
    disabled = compute_disabled(installed, idx, selected, dep_map=dep_map)
    unknown = [e for e in installed if e not in idx]
    print(f"будет ВКЛючено: {len(installed) - len(disabled)}  |  ВЫКЛючено: {len(disabled)}")
    print(f"~экономия памяти: {estimate_saved_mb(disabled, idx)} МБ")
    if dep_map:
        print(f"граф зависимостей: у {len(dep_map)} расширений (#1)")
    print("unknown (не в карте, останутся вкл):", unknown)
    if unknown:
        suggestions = suggest_categories(installed, idx, manifests,
                                         available=set(cats.get("categories", {})))
        if suggestions:
            print("предложить разложить (#3):")
            for ext_id, key in sorted(suggestions.items()):
                print(f"   {ext_id} -> {key}")
    print("--- disabled ---")
    for d in sorted(disabled):
        print("  ", d)
    print("\n--- команда ---")
    print(build_launch_command(code_cli or "code", disabled, str(ROOT), True, True))

    from .toolchains import toolchain_summary, winget_version
    summ = toolchain_summary()
    print("\n--- тулчейны ---")
    print(f"winget: {winget_version() or 'не найден'}")
    print(f"готовы: {summ['ready']}/{summ['total']}, "
          f"не хватает: {', '.join(summ['missing']) or '—'}")
