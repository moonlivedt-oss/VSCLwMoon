# -*- coding: utf-8 -*-
"""Сколько стек стоит на самом деле: размер на диске и калибровка по замерам.

Проблема, которую решает модуль. Оценка экономии до сих пор бралась из таблицы
WEIGHT_MB — три числа (500/150/30 МБ) на все стеки сразу. Это честная грубая
прикидка, но у конкретного человека Java может стоить 300 МБ, а Python — 600,
и таблица всегда будет врать в одну или другую сторону.

Здесь два источника настоящих чисел, оба локальные и без сети:

1. Размер расширений на диске (extension_sizes). Не память, но твёрдый факт
   про стек: 1.2 ГБ C++-тулинга и 4 МБ Markdown — разные вещи, и это видно
   сразу, без единого запуска.

2. Калибровка по собственным замерам (measured_stack_costs). Лаунчер уже пишет
   фактический footprint под подпись выбора (config.footprint_history). Если
   два замера отличаются ровно одним стеком, их разница — цена этого стека в
   мегабайтах, измеренная на этой машине с этими расширениями. Чем больше
   человек пользуется лаунчером, тем точнее становятся его числа.
"""

from __future__ import annotations

import os
from pathlib import Path

from .categories import WEIGHT, WEIGHT_MB
from .safety import valid_ext_id

# Потолок обхода: расширения вроде ms-vscode.cpptools содержат десятки тысяч
# файлов, и полный обход всей папки расширений мог бы занять секунды.
MAX_ENTRIES_PER_EXT = 20000


def _dir_size(path: Path, max_entries: int = MAX_ENTRIES_PER_EXT) -> int:
    """Суммарный размер файлов в папке (байты), с потолком по числу записей.
    Обход через os.scandir: st_size приходит вместе с записью каталога, без
    отдельного stat на файл — это в разы быстрее на папках с тысячами файлов."""
    total = 0
    seen = 0
    stack = [str(path)]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    seen += 1
                    if seen > max_entries:
                        return total
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def folder_to_ext_id(folder_name: str) -> str:
    """'ms-python.python-2024.2.0-win32-x64' -> 'ms-python.python'.

    Режем по первому сегменту, который начинается с цифры: это версия. Имена
    расширений с цифры не начинаются, а версия — всегда. Папки без точки
    (не расширение, например .obsolete) отбрасываем."""
    name = (folder_name or "").strip().lower()
    if "." not in name:
        return ""
    keep: list[str] = []
    for part in name.split("-"):
        if part[:1].isdigit():
            break
        keep.append(part)
    ext_id = "-".join(keep)
    # Служебные записи папки расширений ('.obsolete', '.init-default-profile')
    # тоже содержат точку — отсеиваем их той же проверкой, что и весь остальной
    # код: в id пускаем только форму publisher.name.
    return ext_id if valid_ext_id(ext_id) else ""


def extension_sizes(code_cli: str | None) -> dict[str, int]:
    """id(lower) -> размер расширения на диске в МБ.

    Читаем сами папки, а не extensions.json: так попадают и поставленные
    вручную. Ошибку чтения глушим в пустой словарь — размеры это дополнение,
    без них UI работает по-прежнему."""
    from .vscode import extensions_dir

    root = extensions_dir(code_cli)
    out: dict[str, int] = {}
    try:
        entries = [d for d in root.iterdir() if d.is_dir()]
    except OSError:
        return {}
    for d in entries:
        ext_id = folder_to_ext_id(d.name)
        if not ext_id:
            continue
        mb = round(_dir_size(d) / (1024 * 1024))
        # Несколько версий одного расширения в папке — берём наибольшую.
        out[ext_id] = max(out.get(ext_id, 0), mb)
    return out


def stack_disk_mb(
    ext_index: dict[str, str], sizes: dict[str, int], installed: list[str] | None = None
) -> dict[str, int]:
    """Ключ стека -> сколько МБ на диске занимают его установленные расширения.
    always_on не считаем: он всегда включён и на выбор не влияет."""
    only = {e.lower() for e in installed} if installed is not None else None
    out: dict[str, int] = {}
    for ext_id, mb in sizes.items():
        if only is not None and ext_id not in only:
            continue
        key = ext_index.get(ext_id)
        if not key or key == "always_on":
            continue
        out[key] = out.get(key, 0) + int(mb)
    return out


# --- калибровка по собственным замерам -------------------------------------


def _signature_set(sig: str) -> set[str] | None:
    """Подпись выбора обратно во множество ключей. None — подпись не про набор
    стеков ('bare': голый режим меряет совсем другое)."""
    if not sig or sig == "bare":
        return None
    if sig == "core-only":
        return set()
    return set(sig.split("|"))


def measured_stack_costs(cfg: dict) -> dict[str, int]:
    """Ключ стека -> его цена в МБ, вычисленная из собственных замеров.

    Идея: два замера, наборы которых отличаются ровно одним стеком, дают цену
    этого стека как разницу footprint'ов. Если разниц для стека набралось
    несколько — берём медиану: один шумный замер (открыт тяжёлый проект, идёт
    фоновая индексация) не должен задавать число.

    Отрицательные разницы отбрасываем — это шум замера, а не «стек экономит
    память». Пусто — данных ещё не хватает, вызывающий работает по WEIGHT_MB."""
    hist = cfg.get("footprint_history", {})
    if not isinstance(hist, dict):
        return {}
    from .config import MEMORY_METRIC

    points: list[tuple[set[str], int]] = []
    for sig, rec in hist.items():
        if not isinstance(rec, dict) or rec.get("metric", "ws-private-perf") != MEMORY_METRIC:
            continue
        keys = _signature_set(str(sig))
        mb = rec.get("mb")
        if keys is None or not isinstance(mb, int) or mb <= 0:
            continue
        points.append((keys, mb))

    deltas: dict[str, list[int]] = {}
    for i, (keys_a, mb_a) in enumerate(points):
        for keys_b, mb_b in points[i + 1 :]:
            diff = keys_a ^ keys_b
            if len(diff) != 1:
                continue
            key = next(iter(diff))
            # Цена стека = во сколько дороже тот набор, где он включён.
            cost = (mb_a - mb_b) if key in keys_a else (mb_b - mb_a)
            if cost > 0:
                deltas.setdefault(key, []).append(cost)

    out: dict[str, int] = {}
    for key, values in deltas.items():
        values.sort()
        mid = len(values) // 2
        median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) // 2
        out[key] = int(median)
    return out


def stack_cost_mb(key: str, measured: dict[str, int] | None = None) -> tuple[int, bool]:
    """Цена стека в МБ и флаг «это настоящий замер, а не таблица».
    Замер есть — берём его; нет — падаем на WEIGHT_MB по классу нагрузки."""
    if measured and key in measured:
        return int(measured[key]), True
    return WEIGHT_MB.get(WEIGHT.get(key, "light"), 30), False


def estimate_saved_mb(
    disabled: list[str], ext_index: dict[str, str], cfg: dict | None = None
) -> tuple[int, int]:
    """Оценка освобождаемой памяти для набора выключаемых расширений.

    Возвращает (МБ, сколько стеков посчитано по замеру). Второе число говорит
    UI, насколько цифре можно верить: «~340 МБ (2 из 5 стеков по замерам)»
    честнее, чем просто «340 МБ».

    По смыслу совместимо со старым launch.estimate_saved_mb: каждая выключаемая
    категория считается один раз и только если у неё реально выключается
    установленное расширение."""
    measured = measured_stack_costs(cfg) if cfg else {}
    cats_off = {
        cat for e in disabled if (cat := ext_index.get(e)) is not None and cat != "always_on"
    }
    total = 0
    n_measured = 0
    for cat in cats_off:
        mb, is_real = stack_cost_mb(cat, measured)
        total += mb
        n_measured += 1 if is_real else 0
    return total, n_measured
