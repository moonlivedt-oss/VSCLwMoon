# -*- coding: utf-8 -*-
"""Тесты локализации: overlay ru→en (launcher/i18n.py).

Overlay-подход не ломает UI при частичном переводе, но два дефекта он сам не
ловит, а платит за них рантайм:
- в переводе потерян/лишний {}-плейсхолдер → .format() падает у пользователя;
- перевод пустой → в UI дыра вместо текста.
Здесь оба ловятся статически, без запуска GUI.
"""
import string

import pytest

from launcher import i18n


def _fields(s: str) -> set:
    """Имена {name}-подстановок в строке (позиционные {} тоже учитываются)."""
    return {name for _, name, _, _ in string.Formatter().parse(s) if name is not None}


@pytest.mark.parametrize("lang", list(i18n.TRANSLATIONS))
@pytest.mark.parametrize("key,val", [
    kv for tbl in i18n.TRANSLATIONS.values() for kv in tbl.items()
])
def test_placeholder_parity(lang, key, val):
    # Набор {}-подстановок ключа и перевода обязан совпадать — иначе .format()
    # с теми же kwargs упадёт KeyError или оставит дыру.
    assert _fields(key) == _fields(val), f"плейсхолдеры разошлись: {key!r} → {val!r}"


@pytest.mark.parametrize("lang,tbl", list(i18n.TRANSLATIONS.items()))
def test_no_empty_translation(lang, tbl):
    for key, val in tbl.items():
        assert val.strip(), f"пустой перевод [{lang}] для {key!r}"


def test_underscore_ru_is_identity():
    i18n.set_language("ru")
    assert i18n._("Готово") == "Готово"
    assert i18n._("нет такого ключа вообще") == "нет такого ключа вообще"


def test_underscore_en_translates_and_falls_back():
    i18n.set_language("en")
    try:
        assert i18n._("Готово") == "Done"                       # есть в таблице
        assert i18n._("нет такого ключа") == "нет такого ключа"  # нет → исходник
    finally:
        i18n.set_language("ru")


def test_set_language_normalizes():
    try:
        i18n.set_language("en-US"); assert i18n.get_language() == "en"
        i18n.set_language("English"); assert i18n.get_language() == "en"
        i18n.set_language("ru"); assert i18n.get_language() == "ru"
        i18n.set_language("de"); assert i18n.get_language() == "ru"  # незнакомое → ru
    finally:
        i18n.set_language("ru")
