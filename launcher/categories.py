# -*- coding: utf-8 -*-
"""Карта стеков расширений: чтение, индекс, дубли, рекомендации.

Всё, что связано с data/categories.json, data/plugin_descriptions.json и
data/recommended_settings.json, живёт здесь. Ориентировочная нагрузка
стеков на память (WEIGHT/WEIGHT_MB) — тоже здесь: это данные о картe,
а не о VS Code как таковом.
"""
import json

from .paths import CATEGORIES_FILE, DESCRIPTIONS_FILE, RECOMMENDED_FILE, ROOT

# Ориентировочная «тяжесть» стека и её отражение в памяти.
# Ключи — как в categories.json. Значения — грубые оценки для UI-подсказок,
# не точный прогноз: реальный расход зависит от проекта и версии расширения.
WEIGHT = {
    "sonar": "heavy", "java": "heavy", "azure": "heavy", "cpp": "heavy",
    "rust": "heavy", "data": "heavy", "dotnet": "heavy",
    "python": "medium", "sql": "medium", "git": "medium",
    "go": "medium", "docker": "medium", "php": "medium", "ruby": "medium",
    "terraform": "medium",
    "web": "light", "graphics3d": "light", "markdown": "light",
    "powershell": "light", "remote": "light", "api": "light", "config": "light",
    "lua": "light", "svelte_astro": "light", "graphql": "light",
}
WEIGHT_LABEL = {"heavy": "тяжёлый", "medium": "средний", "light": "лёгкий"}
WEIGHT_MB = {"heavy": 500, "medium": 150, "light": 30}

# Человеческое пояснение к нагрузке — для тултипов, чтобы цвет бейджа читался
# смыслом: чем тяжелее стек, тем больше выигрыш от того, что он выключен.
WEIGHT_HELP = {
    "heavy": "Тяжёлый стек: языковые серверы и анализаторы держат в памяти "
             "сотни МБ, даже когда вы их не трогаете. Наибольшая экономия — "
             "когда он выключен и сегодня не нужен.",
    "medium": "Средний стек: заметный, но умеренный расход памяти. Держите "
              "включённым для своих языков, выключайте на чужих проектах.",
    "light": "Лёгкий стек: почти не влияет на память. Можно спокойно держать "
             "включённым — на экономию он влияет мало.",
}


def load_categories() -> tuple[dict, str]:
    """Читает карту категорий. Возвращает (данные, ошибка). При проблеме —
    безопасная пустая структура и текст ошибки для показа в окне, чтобы
    битый или отсутствующий categories.json не ронял приложение."""
    empty: dict = {"always_on": {"extensions": []}, "categories": {}}
    try:
        with open(CATEGORIES_FILE, encoding="utf-8-sig") as f:  # терпим BOM
            data = json.load(f)
    except FileNotFoundError:
        return empty, f"Не найден {CATEGORIES_FILE.name} — стеки не загружены."
    except json.JSONDecodeError as e:
        return empty, f"Ошибка в {CATEGORIES_FILE.name}: {e}"
    except Exception as e:
        return empty, f"Не удалось прочитать {CATEGORIES_FILE.name}: {e}"
    if not isinstance(data, dict):
        return empty, f"{CATEGORIES_FILE.name}: ожидается объект верхнего уровня."
    data.setdefault("always_on", {"extensions": []})
    data.setdefault("categories", {})
    return data, ""


def load_descriptions() -> dict[str, str]:
    """Карта id(lower) -> «что делает». Берётся из plugin_descriptions.json,
    иначе разбирается соседний VS_code_Info/Extensions.md, иначе пусто."""
    if DESCRIPTIONS_FILE.exists():
        try:
            return {k.lower(): v for k, v in
                    json.loads(DESCRIPTIONS_FILE.read_text(encoding="utf-8")).items()}
        except Exception:
            pass
    md = ROOT.parent / "VS_code_Info" / "Extensions.md"
    if md.exists():
        import re
        rx = re.compile(r"^-\s+\*\*`([^`]+)`\*\*.*?—\s*(.+)$")
        out = {}
        for raw in md.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("- ~~"):
                continue
            m = rx.match(line)
            if m:
                txt = m.group(2).replace("**", "").replace("~~", "").replace("`", "").strip()
                out[m.group(1).strip().lower()] = txt
        return out
    return {}


def load_recommended() -> dict:
    """Рекомендованные настройки VS Code по категориям: ключ -> {настройки}."""
    if RECOMMENDED_FILE.exists():
        try:
            return json.loads(RECOMMENDED_FILE.read_text(encoding="utf-8-sig"))
        except Exception:
            return {}
    return {}


def build_ext_index(cats: dict,
                    overlay: dict[str, str] | None = None) -> dict[str, str]:
    """id -> ключ категории ('always_on' или ключ из categories).
    При дубликатах побеждает последнее упоминание; find_duplicate_extensions
    возвращает такие расширения для явного предупреждения.

    overlay (#6) — пользовательская раскладка незнакомых расширений из мастера
    (cfg['extra_categories'], {id: ключ}). Применяется НЕразрушающе: только для
    id, которых ещё нет в карте, и только для существующих ключей категорий —
    сама categories.json остаётся нетронутой, а ручная правка карты всегда
    важнее оверлея."""
    idx = {}
    for e in cats.get("always_on", {}).get("extensions", []):
        idx[e.lower()] = "always_on"
    for key, cat in cats.get("categories", {}).items():
        for e in cat.get("extensions", []):
            idx[e.lower()] = key
    if overlay:
        valid = set(cats.get("categories", {}))
        for ext_id, key in overlay.items():
            low = str(ext_id).lower()
            if low not in idx and key in valid:
                idx[low] = key
    return idx


def find_duplicate_extensions(cats: dict) -> dict[str, list[str]]:
    """Расширения, встречающиеся в двух и более местах карты (включая
    always_on). Нужны, чтобы явно предупредить пользователя: без этого
    build_ext_index молча оставляет последнее назначение, и стек, куда
    расширение было положено раньше, теряет его без объяснения.
    Возвращает {ext_id: [ключ1, ключ2, ...]}, порядок ключей — как встретили."""
    seen: dict[str, list[str]] = {}
    for e in cats.get("always_on", {}).get("extensions", []):
        seen.setdefault(e.lower(), []).append("always_on")
    for key, cat in cats.get("categories", {}).items():
        for e in cat.get("extensions", []):
            seen.setdefault(e.lower(), []).append(key)
    return {ext: keys for ext, keys in seen.items() if len(keys) > 1}


def categories_present(installed: list[str], ext_index: dict[str, str]) -> set[str]:
    """Категории, у которых есть хотя бы одно установленное расширение
    (без always_on) — для рекомендаций settings.json."""
    present = {cat for e in installed
               if (cat := ext_index.get(e)) is not None and cat != "always_on"}
    return present


def recommended_for(keys, recommended: dict) -> dict:
    """Слить рекомендации выбранных категорий в один словарь настроек."""
    merged: dict = {}
    for k in keys:
        merged.update(recommended.get(k, {}))
    return merged
