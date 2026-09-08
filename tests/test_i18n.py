# -*- coding: utf-8 -*-
"""Тесты локализации: overlay ru→en (launcher/i18n.py).

Overlay-подход не ломает UI при частичном переводе, но три дефекта он сам не
ловит, а платит за них рантайм:
- в переводе потерян/лишний {}-плейсхолдер → .format() падает у пользователя;
- перевод пустой → в UI дыра вместо текста;
- строку обернули в _(), а перевод добавить забыли → в EN-режиме русский текст.
Всё три ловятся статически, без запуска GUI.
"""
import ast
import pathlib
import re
import string

import pytest

from launcher import i18n

LAUNCHER_DIR = pathlib.Path(i18n.__file__).parent
CYRILLIC = re.compile("[а-яА-Я]")

# Строки, которые сравниваются с чужим выводом, а не показываются человеку.
NOT_UI = {"администратор"}


def _underscore_literals() -> dict[str, list[str]]:
    """Все литералы из вызовов _("...") по всему пакету: текст -> где встретился."""
    out: dict[str, list[str]] = {}
    for path in sorted(LAUNCHER_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_" and node.args):
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    out.setdefault(arg.value, []).append(f"{path.name}:{node.lineno}")
    return out


def _ui_literals_outside_underscore() -> list[str]:
    """Русские строки интерфейса, которые вообще не обёрнуты в _().

    Пропускаем докстринги (их человек не видит) и аргументы log.* — файл лога
    ведём по-русски намеренно, он для разбора проблем, а не для чтения в окне.
    """
    found: list[str] = []
    for path in sorted(LAUNCHER_DIR.glob("gui*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name) and fn.id == "_" and node.args:
                    skip.update(id(x) for x in ast.walk(node.args[0]))
                if (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                        and fn.value.id in {"log", "logging", "logger"}):
                    for a in node.args:
                        skip.update(id(x) for x in ast.walk(a))
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
                body = getattr(node, "body", None)
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    skip.add(id(body[0].value))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and CYRILLIC.search(node.value) and id(node) not in skip
                    and node.value.strip() not in NOT_UI):
                found.append(f"{path.name}:{node.lineno}: {node.value[:60]}")
    return found


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


def test_every_underscore_string_has_english():
    """Обернули в _() — значит, обещали перевод. Без этого EN-режим тихо
    показывает русский: overlay возвращает исходник и никто не падает."""
    en = i18n.TRANSLATIONS["en"]
    missing = {text: where for text, where in _underscore_literals().items() if text not in en}
    assert not missing, "нет английского перевода: " + "; ".join(
        f"{where[0]} {text[:50]!r}" for text, where in sorted(missing.items())
    )


def test_no_hardcoded_russian_in_gui():
    """Строка интерфейса мимо _() не переводится вообще ничем — ловим сразу."""
    stray = _ui_literals_outside_underscore()
    assert not stray, "русский текст интерфейса без _(): " + "; ".join(stray)


def test_set_language_normalizes():
    try:
        i18n.set_language("en-US"); assert i18n.get_language() == "en"
        i18n.set_language("English"); assert i18n.get_language() == "en"
        i18n.set_language("ru"); assert i18n.get_language() == "ru"
        i18n.set_language("de"); assert i18n.get_language() == "ru"  # незнакомое → ru
    finally:
        i18n.set_language("ru")
