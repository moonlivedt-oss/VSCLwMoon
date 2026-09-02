# -*- coding: utf-8 -*-
"""Защита от инъекций в CLI VS Code.

Три функции, три зоны ответственности:
- valid_ext_id  — только id вида publisher.name из безопасных символов пускаем
                  в командную строку (иначе подменённый categories.json/
                  extensions.json может протащить shell-инъекцию);
- shell_safe    — убираем shell-метасимволы для запуска через cmd;
- safe_arg      — shell_safe + режем ведущие '-', чтобы путь/имя профиля не
                  превратились в CLI-флаг Code.exe (argument injection —
                  актуально даже при запуске без оболочки).
"""
import re

# publisher.name; строгие символы без пробелов, кавычек и метасимволов.
_EXT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*\.[A-Za-z0-9][A-Za-z0-9._-]*$")


def valid_ext_id(ext_id: str) -> bool:
    return bool(ext_id) and bool(_EXT_ID_RE.match(ext_id))


def shell_safe(s: str) -> str:
    """Убирает то, чем можно вырваться из кавычек в cmd или подставить
    переменную окружения. В нормальных путях и именах профилей таких
    символов не бывает."""
    return "".join(ch for ch in (s or "") if ch not in '"\r\n%')


def safe_arg(s: str) -> str:
    """shell_safe + защита от argument injection: срезаем ведущие дефисы
    и пробелы, чтобы значение вроде '--disable-workspace-trust' или
    '--extensions-dir=...' в поле папки/профиля не было воспринято Code.exe
    как флаг. Внутренние дефисы сохраняются — 'D:\\my-project' цел."""
    return shell_safe(s).strip().lstrip("-").strip()
