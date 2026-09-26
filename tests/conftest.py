# -*- coding: utf-8 -*-
"""Общая изоляция тестов.

Окно и CLI сохраняют конфиг через config.save_config в launcher_config.json
рядом с программой. Без подмены пути любой GUI-тест, щёлкнувший галочку,
перезаписывал настоящий конфиг пользователя тестовым. Поэтому каждый тест
по умолчанию пишет конфиг во временную папку; тесты, которым нужен свой
путь, по-прежнему подменяют его сами.
"""

import pytest

from launcher import config, paths


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    cf = tmp_path / "launcher_config.json"
    monkeypatch.setattr(config, "CONFIG_FILE", cf)
    monkeypatch.setattr(paths, "CONFIG_FILE", cf)
    yield
