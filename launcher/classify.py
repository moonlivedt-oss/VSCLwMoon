# -*- coding: utf-8 -*-
"""Угадать стек для незнакомого расширения по его манифесту (#3).

Чистая логика без IO: на вход — разобранный манифест (см. manifests.py),
на выход — ключ стека из карты или None. Нужна, чтобы пользователь с чужим
набором расширений не разбирал 90+ плагинов вручную: лаунчер предлагает
раскладку, а решение остаётся за человеком (мастер #6 показывает и даёт
принять/поправить).

Ключи стеков совпадают с ключами в data/categories.json — если в твоей карте
какого-то стека нет, отфильтруй результат по имеющимся ключам на стороне GUI.
"""

from __future__ import annotations

# languageId (как в contributes.languages / onLanguage:) -> ключ стека.
LANG_TO_STACK: dict[str, str] = {
    "python": "python",
    "go": "go",
    "rust": "rust",
    "java": "java",
    "kotlin": "java",
    "cpp": "cpp",
    "c": "cpp",
    "cuda-cpp": "cpp",
    "objective-c": "cpp",
    "objective-cpp": "cpp",
    "csharp": "dotnet",
    "fsharp": "dotnet",
    "vb": "dotnet",
    "php": "php",
    "ruby": "ruby",
    "lua": "lua",
    "sql": "sql",
    "mysql": "sql",
    "pgsql": "sql",
    "plsql": "sql",
    "markdown": "markdown",
    "powershell": "powershell",
    "typescript": "web",
    "javascript": "web",
    "typescriptreact": "web",
    "javascriptreact": "web",
    "vue": "web",
    "html": "web",
    "css": "web",
    "scss": "web",
    "less": "web",
    "svelte": "svelte_astro",
    "astro": "svelte_astro",
    "graphql": "graphql",
    "terraform": "terraform",
    "hcl": "terraform",
    "dockerfile": "docker",
    "dockercompose": "docker",
    "shellscript": "config",
    "yaml": "config",
    "toml": "config",
}

# Категория маркетплейса -> ключ стека. Работает как запасной сигнал, когда по
# языкам ничего не вышло. Берём только те категории, что уверенно ложатся на
# конкретный стек; размытые ('Other', 'Linters', 'Formatters') намеренно не
# маппим — лучше оставить незнакомым, чем угадать неверно.
CATEGORY_TO_STACK: dict[str, str] = {
    "data science": "data",
    "notebooks": "data",
    "machine learning": "data",
}


def classify_extension(manifest: dict) -> str | None:
    """Ключ стека для расширения или None, если уверенно не определяется.

    Порядок сигналов — от точного к грубому:
    1. языки, которые расширение обслуживает (contributes.languages +
       onLanguage:...) — самый надёжный признак «для какого языка плагин»;
    2. категории маркетплейса — запасной сигнал для узкого набора категорий.

    Если языки указывают на несколько разных стеков (мульти-язычный плагин),
    возвращаем None: навязывать один стек такому расширению неправильно."""
    if not isinstance(manifest, dict):
        return None

    stacks = {
        LANG_TO_STACK[lang] for lang in manifest.get("languages", ()) if lang in LANG_TO_STACK
    }
    if len(stacks) == 1:
        return next(iter(stacks))
    if len(stacks) > 1:
        return None  # многоязычный плагин — не приписываем одному стеку

    for c in manifest.get("categories", ()):
        key = CATEGORY_TO_STACK.get(str(c).lower())
        if key:
            return key
    return None


def suggest_categories(
    installed: list[str],
    ext_index: dict[str, str],
    manifests: dict[str, dict],
    available: set[str] | None = None,
) -> dict[str, str]:
    """Предложения раскладки для расширений, которых ещё нет в карте.

    Берём только установленные id, отсутствующие в ext_index (незнакомые), и
    возвращаем {id: предполагаемый_ключ_стека} — лишь там, где classify_extension
    что-то уверенно вернул. `available`, если задан, ограничивает предложения
    ключами, реально существующими в карте пользователя."""
    out: dict[str, str] = {}
    for ext_id in installed:
        low = ext_id.lower()
        if low in ext_index:
            continue
        m = manifests.get(low)
        if not m:
            continue
        key = classify_extension(m)
        if key and (available is None or key in available):
            out[low] = key
    return out
