# -*- coding: utf-8 -*-
"""Автонастройка settings.json пользователя VS Code.

Дописываем НЕДОСТАЮЩИЕ рекомендованные ключи, существующие не трогаем,
делаем бэкап с ротацией. При JSONC (комментарии, хвостовые запятые)
отказываемся — чтобы точно не сломать файл.
"""
import json
from pathlib import Path

SETTINGS_BACKUP_KEEP = 5   # сколько последних бэкапов settings.json хранить


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


def apply_settings(path: Path, to_add: dict) -> tuple[bool, str]:
    """Безопасно дописать НЕДОСТАЮЩИЕ ключи в settings.json:
    сначала бэкап (с ротацией), существующие ключи не трогаем, при JSONC
    (комментарии/хвостовые запятые) отказываемся — чтобы не сломать файл.
    Возвращает (успех, сообщение)."""
    if not to_add:
        return False, "Нет рекомендованных настроек для установленных стеков."
    existing: dict = {}
    if path.exists():
        raw = path.read_text(encoding="utf-8-sig")
        try:
            existing = json.loads(raw) if raw.strip() else {}
        except Exception:
            return (False, "В settings.json есть комментарии или JSONC-синтаксис — "
                    "автоприменение отменено, чтобы не сломать файл. Скопируй "
                    "настройки и вставь вручную.")
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
    existing.update(missing)
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    msg = f"Добавлено настроек: {len(missing)}."
    if backup:
        msg += f"\nБэкап: {backup.name}"
        if rotated:
            msg += f" (удалено старых бэкапов: {rotated})"
    return True, msg
