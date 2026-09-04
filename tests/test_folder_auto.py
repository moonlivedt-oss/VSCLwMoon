# -*- coding: utf-8 -*-
"""Тесты авто-применения набора стеков по папке (#1+, config.py).

Обычная память по папке (remember/recall) только ПОДСКАЗЫВАЕТ набор — его ещё
надо подтвердить кликом. Авто-флаг снимает этот клик: помеченная папка при
выборе получает свой набор сама. Здесь — чистая логика этого флага.
"""
from launcher.config import (
    folder_auto_stacks, is_folder_auto, migrate_config,
    recall_folder_stacks, remember_folder_stacks, set_folder_auto,
)


def test_migrate_seeds_folder_auto():
    cfg = migrate_config({})
    assert cfg["folder_auto"] == []


def test_set_and_check_auto():
    cfg = migrate_config({})
    assert not is_folder_auto(cfg, r"D:\Proj")
    set_folder_auto(cfg, r"D:\Proj", True)
    assert is_folder_auto(cfg, r"D:\Proj")
    # нормализация ключа: тот же путь в другом регистре/слэшах — та же папка
    assert is_folder_auto(cfg, "d:/proj/")
    set_folder_auto(cfg, r"D:\Proj", False)
    assert not is_folder_auto(cfg, r"D:\Proj")


def test_set_auto_idempotent_no_dupes():
    cfg = migrate_config({})
    set_folder_auto(cfg, r"D:\Proj", True)
    set_folder_auto(cfg, r"D:\Proj", True)
    assert cfg["folder_auto"].count(cfg["folder_auto"][0]) == 1


def test_auto_stacks_needs_both_flag_and_memory():
    cfg = migrate_config({})
    # флаг есть, а выбора для папки ещё нет → None (нечего применять)
    set_folder_auto(cfg, r"D:\Proj", True)
    assert folder_auto_stacks(cfg, r"D:\Proj") is None
    # запомнили выбор → авто-набор возвращается
    remember_folder_stacks(cfg, r"D:\Proj", ["python", "git"])
    assert folder_auto_stacks(cfg, r"D:\Proj") == ["git", "python"]
    # выбор есть, но папка не авто → None (работает обычная подсказка)
    remember_folder_stacks(cfg, r"D:\Other", ["web"])
    assert folder_auto_stacks(cfg, r"D:\Other") is None


def test_eviction_drops_stale_auto_flag():
    # Вытеснение старых папок из folder_stacks убирает и их авто-флаг,
    # чтобы не копить мусор про давно забытые проекты.
    cfg = migrate_config({})
    set_folder_auto(cfg, r"D:\Old", True)
    remember_folder_stacks(cfg, r"D:\Old", ["python"], cap=1)
    remember_folder_stacks(cfg, r"D:\New", ["web"], cap=1)  # вытеснит D:\Old
    assert recall_folder_stacks(cfg, r"D:\Old") is None
    assert not is_folder_auto(cfg, r"D:\Old")
