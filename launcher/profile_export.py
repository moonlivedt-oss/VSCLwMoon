# -*- coding: utf-8 -*-
"""Экспорт выбора стеков в нативный профиль VS Code (.code-profile) — #4.

VS Code умеет Profiles: набор расширений, живущий отдельно. Наш выбор стеков —
это по сути «какие расширения нужны сейчас»; здесь мы превращаем его в файл
`.code-profile`, который VS Code принимает через «Profiles: Import…». Тогда
вместо флагов `--disable-extension` пользователь получает постоянный профиль
ровно с включёнными стеками — дружим с нативной фичей, а не конкурируем.

Формат: объект IUserDataProfileTemplate — { name, extensions?, settings?, ... },
где каждое КОНТЕНТНОЕ поле это СТРОКА со stringified JSON (так делает сам
VS Code при экспорте). Нам достаточно name + extensions. Чистая логика без IO:
на вход id включённых расширений и манифесты (для displayName), на выход —
готовая строка файла.
"""
from __future__ import annotations

import json

from .safety import valid_ext_id


def build_profile_extensions(enabled: list[str],
                             manifests: dict[str, dict] | None = None) -> list[dict]:
    """Массив расширений профиля: [{identifier:{id}, displayName}, ...].

    Только валидные id (мусор/инъекцию в файл не пускаем). displayName берём из
    манифеста, иначе — сам id (VS Code при импорте всё равно ставит по
    identifier.id). Порядок стабильный (отсортирован), дубли убраны."""
    manifests = manifests or {}
    out: list[dict] = []
    seen: set[str] = set()
    for ext_id in sorted({e.lower() for e in enabled}):
        if ext_id in seen or not valid_ext_id(ext_id):
            continue
        seen.add(ext_id)
        m = manifests.get(ext_id) or {}
        display = (m.get("display") or "").strip() or ext_id
        out.append({"identifier": {"id": ext_id}, "displayName": display})
    return out


def build_profile_template(name: str, enabled: list[str],
                           manifests: dict[str, dict] | None = None,
                           settings: dict | None = None) -> dict:
    """Шаблон профиля VS Code (IUserDataProfileTemplate).

    Контентные поля — строки со stringified JSON, как в родном экспорте. Кладём
    name + extensions; settings добавляем, только если переданы (например
    рекомендованные настройки стеков). Имя очищаем от управляющих символов."""
    clean_name = "".join(ch for ch in (name or "").strip()
                         if ch.isprintable()) or "VS Code Launcher"
    template: dict = {
        "name": clean_name,
        "extensions": json.dumps(build_profile_extensions(enabled, manifests),
                                 ensure_ascii=False),
    }
    if settings:
        template["settings"] = json.dumps(settings, ensure_ascii=False, indent=2)
    return template


def profile_file_content(name: str, enabled: list[str],
                         manifests: dict[str, dict] | None = None,
                         settings: dict | None = None) -> str:
    """Готовое содержимое .code-profile (строка для записи в файл)."""
    return json.dumps(build_profile_template(name, enabled, manifests, settings),
                      ensure_ascii=False, indent=2)
