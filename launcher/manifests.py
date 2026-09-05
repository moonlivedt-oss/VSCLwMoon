# -*- coding: utf-8 -*-
"""Чтение манифестов установленных расширений (их package.json).

Каждое расширение VS Code — это папка в extensions_dir с package.json, где
лежат поля, которых нет в extensions.json:
- extensionDependencies / extensionPack — от кого расширение зависит (нужно
  для #1: не гасить зависимость включённого расширения);
- categories / contributes.languages / activationEvents — по чему можно
  угадать стек незнакомого расширения (нужно для #3/#6).

Модуль только читает диск и разбирает JSON — никакой логики решения «что
выключить» здесь нет (она в launch.py, чистая и тестируемая отдельно).
"""

from __future__ import annotations

import json
from pathlib import Path

from .safety import valid_ext_id
from .vscode import extensions_dir

# --- сбор манифестов -------------------------------------------------------


def _relative_locations(ext_dir: Path) -> dict[str, str]:
    """id(lower) -> имя папки расширения из extensions.json.

    extensions.json — это индекс, который ведёт сам VS Code: у каждой записи
    есть identifier.id и relativeLocation (папка внутри extensions_dir). Если
    файла нет или он битый — вернём пусто, и вызывающий просканирует папки."""
    f = ext_dir / "extensions.json"
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, str] = {}
    for e in data if isinstance(data, list) else ():
        if not isinstance(e, dict):
            continue
        ext_id = ((e.get("identifier") or {}).get("id") or "").lower()
        rel = e.get("relativeLocation") or ""
        if ext_id and rel:
            out[ext_id] = rel
    return out


def _parse_manifest(pkg: Path) -> dict | None:
    """Разобрать package.json расширения в компактную запись с нужными полями.
    None — файла нет или он не читается."""
    try:
        data = json.loads(pkg.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    publisher = str(data.get("publisher") or "").lower()
    name = str(data.get("name") or "").lower()
    ext_id = f"{publisher}.{name}" if publisher and name else ""

    def _id_list(key: str) -> list[str]:
        raw = data.get(key)
        if not isinstance(raw, list):
            return []
        return [x.lower() for x in raw if isinstance(x, str) and valid_ext_id(x)]

    contributes = data.get("contributes")
    if not isinstance(contributes, dict):
        contributes = {}
    langs: list[str] = []
    for lang in contributes.get("languages") or []:
        if isinstance(lang, dict) and isinstance(lang.get("id"), str):
            langs.append(lang["id"].lower())

    acts = data.get("activationEvents")
    on_languages = []
    if isinstance(acts, list):
        for a in acts:
            if isinstance(a, str) and a.startswith("onLanguage:"):
                on_languages.append(a.split(":", 1)[1].lower())

    cats = data.get("categories")
    categories = [c for c in cats if isinstance(c, str)] if isinstance(cats, list) else []

    return {
        "id": ext_id,
        "depends": _id_list("extensionDependencies"),
        "pack": _id_list("extensionPack"),
        "categories": categories,
        "languages": sorted(set(langs) | set(on_languages)),
        "display": str(data.get("displayName") or "").strip(),
    }


def read_extension_manifests(code_cli: str | None) -> dict[str, dict]:
    """id(lower) -> разобранный манифест для всех установленных расширений.

    Сначала идём по extensions.json (точные папки), для остатка — грубый скан
    папок extensions_dir (портативные сборки, ручная установка). Любое чтение
    завёрнуто в try: одно битое расширение не должно ронять сбор."""
    ext_dir = extensions_dir(code_cli)
    if not ext_dir.exists():
        return {}
    out: dict[str, dict] = {}

    rel = _relative_locations(ext_dir)
    for ext_id, folder in rel.items():
        m = _parse_manifest(ext_dir / folder / "package.json")
        if m is not None:
            out[ext_id] = m

    # Фолбэк: расширения, которых не было в extensions.json (или файла нет) —
    # портативные сборки, ручная установка. Уже разобранные по индексу папки
    # пропускаем, поэтому при полном extensions.json скан почти ничего не стоит.
    known_folders = {f.lower() for f in rel.values()}
    try:
        subdirs = [d for d in ext_dir.iterdir()
                   if d.is_dir() and d.name.lower() not in known_folders]
    except OSError:
        subdirs = []
    for d in subdirs:
        m = _parse_manifest(d / "package.json")
        if m is not None and m["id"] and m["id"] not in out:
            out[m["id"]] = m
    return out


# --- граф зависимостей (для #1) --------------------------------------------


def build_dependency_map(manifests: dict[str, dict]) -> dict[str, set[str]]:
    """id -> множество id, от которых расширение зависит напрямую.

    Объединяем extensionDependencies (жёсткая зависимость) и extensionPack
    (пакет тянет за собой набор — тоже не должен гаснуть, пока включён сам
    пакет). Пустые записи опускаем, чтобы карта не пухла."""
    dep_map: dict[str, set[str]] = {}
    for ext_id, m in manifests.items():
        deps = set(m.get("depends") or ()) | set(m.get("pack") or ())
        deps.discard(ext_id)  # само на себя не ссылаемся
        if deps:
            dep_map[ext_id] = deps
    return dep_map
