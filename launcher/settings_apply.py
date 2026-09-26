# -*- coding: utf-8 -*-
"""Автонастройка settings.json пользователя VS Code.

Дописываем НЕДОСТАЮЩИЕ рекомендованные ключи, существующие не трогаем,
делаем бэкап с ротацией. Файл с комментариями (JSONC — обычное дело для
settings.json) не пересобираем: новые ключи вставляются текстом перед
закрывающей скобкой, так что комментарии и порядок остаются как были.
Результат перепроверяется разбором; не разобралось — файл не трогаем.
"""

import json
import re
from pathlib import Path

SETTINGS_BACKUP_KEEP = 5  # сколько последних бэкапов settings.json хранить


def _rotate_settings_backups(folder: Path, keep: int = SETTINGS_BACKUP_KEEP) -> int:
    """Оставляет только `keep` последних бэкапов settings.backup-*.json,
    старые удаляет. Возвращает число удалённых файлов. Тихо игнорирует ошибки:
    ротация не критична, лишний файл лучше упавшей автонастройки."""
    if keep < 0:
        keep = 0
    try:
        backups = sorted(folder.glob("settings.backup-*.json"))
    except Exception:
        return 0
    removed = 0
    for old in backups[:-keep] if keep else backups:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def _significant_positions(text: str) -> list[int]:
    """Индексы значимых символов JSONC: вне строк, комментариев и пробелов.
    Строки учитываются целиком (их кавычки значимы), комментарии // и /* */
    пропускаются."""
    out: list[int] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            out.append(i)
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            if i < n:
                out.append(i)
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif ch.isspace():
            i += 1
        else:
            out.append(i)
            i += 1
    return out


def insert_keys_jsonc(raw: str, missing: dict) -> str | None:
    """Вставить ключи перед закрывающей скобкой объекта верхнего уровня,
    не трогая остальной текст. None — структура не распознана."""
    sig = _significant_positions(raw)
    if len(sig) < 2 or raw[sig[0]] != "{" or raw[sig[-1]] != "}":
        return None
    close = sig[-1]
    prev = raw[sig[-2]]
    # Отступ берём у первого ключа файла, чтобы вставка не выбивалась.
    m = re.search(r'^([ \t]+)"', raw, re.M)
    ind = m.group(1) if m else "  "
    body = ",\n".join(
        ind
        + json.dumps(k, ensure_ascii=False)
        + ": "
        + json.dumps(v, ensure_ascii=False, indent=ind).replace("\n", "\n" + ind)
        for k, v in missing.items()
    )
    lead = "" if prev in "{," else ","
    # Запятая встаёт сразу за последним значением, а комментарии между ним и
    # закрывающей скобкой остаются на своих местах — новые ключи идут после них.
    at = sig[-2] + 1
    return raw[:at] + lead + raw[at:close].rstrip() + "\n" + body + "\n" + raw[close:]


def apply_settings(path: Path, to_add: dict) -> tuple[bool, str]:
    """Безопасно дописать НЕДОСТАЮЩИЕ ключи в settings.json:
    сначала бэкап (с ротацией), существующие ключи не трогаем, при JSONC
    (комментарии/хвостовые запятые) отказываемся — чтобы не сломать файл.
    Возвращает (успех, сообщение)."""
    if not to_add:
        return False, "Нет рекомендованных настроек для установленных стеков."
    from .detect import _loads_jsonc

    existing: dict = {}
    raw = ""
    jsonc = False
    if path.exists():
        raw = path.read_text(encoding="utf-8-sig")
        try:
            existing = json.loads(raw) if raw.strip() else {}
        except Exception:
            existing = _loads_jsonc(raw)
            jsonc = True
            if existing is None:
                return (
                    False,
                    "settings.json не разбирается даже как JSONC — "
                    "автоприменение отменено, чтобы не сломать файл. Скопируй "
                    "настройки и вставь вручную.",
                )
        if not isinstance(existing, dict):
            return False, "settings.json имеет неожиданный формат."
    missing = {k: v for k, v in to_add.items() if k not in existing}
    if not missing:
        return True, "Все рекомендованные настройки уже заданы — ничего не добавлено."
    from datetime import datetime

    rotated = 0
    if path.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"settings.backup-{ts}.json")
        backup.write_text(path.read_text(encoding="utf-8-sig"), encoding="utf-8")
        # Ротация после записи нового бэкапа: старьё чистится, свежий сохранён.
        rotated = _rotate_settings_backups(path.parent)
    else:
        backup = None
        path.parent.mkdir(parents=True, exist_ok=True)
    if jsonc:
        new_text = insert_keys_jsonc(raw, missing)
        check = _loads_jsonc(new_text) if new_text is not None else None
        if (
            not isinstance(check, dict)
            or any(k not in check for k in missing)
            or any(check.get(k) != v for k, v in existing.items())
        ):
            return (
                False,
                "Не удалось безопасно вставить ключи в settings.json с "
                "комментариями — файл не изменён. Скопируй настройки и вставь "
                "вручную.",
            )
        path.write_text(new_text, encoding="utf-8")
    else:
        existing.update(missing)
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    msg = f"Добавлено настроек: {len(missing)}."
    if backup:
        msg += f"\nБэкап: {backup.name}"
        if rotated:
            msg += f" (удалено старых бэкапов: {rotated})"
    return True, msg


def missing_settings(path: Path | None, to_add: dict) -> dict:
    """Только те ключи из to_add, которых ещё нет в settings.json (для
    предпросмотра). Файл не читается или не разбирается — отдаём всё как есть."""
    if not path or not path.exists():
        return dict(to_add)
    from .detect import _loads_jsonc
    try:
        existing = _loads_jsonc(path.read_text(encoding="utf-8-sig"))
    except OSError:
        existing = None
    if not isinstance(existing, dict):
        return dict(to_add)
    return {k: v for k, v in to_add.items() if k not in existing}
