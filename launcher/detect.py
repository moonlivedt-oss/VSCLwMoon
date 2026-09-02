# -*- coding: utf-8 -*-
"""Автоопределение стеков по содержимому папки проекта.

Чистая логика без GUI и без обращения к VS Code. Берём путь к проекту,
бегло сканируем файлы (с обрезкой тяжёлых каталогов и потолком по числу
записей, чтобы не подвесить окно на гигантском репозитории) и возвращаем
ключи стеков, которые в этом проекте, скорее всего, нужны.

Дальше GUI пересекает результат с реально установленными расширениями —
поэтому здесь можно детектировать щедро: стек без установленных плагинов
всё равно не будет предложен.
"""
from __future__ import annotations

import os
from pathlib import Path

# Точное имя файла в корне/подпапке -> ключ стека.
FILENAME_MARKERS: dict[str, str] = {
    "requirements.txt": "python", "pyproject.toml": "python", "pipfile": "python",
    "setup.py": "python", "setup.cfg": "python", "poetry.lock": "python",
    "environment.yml": "python",
    "package.json": "web", "tsconfig.json": "web", "jsconfig.json": "web",
    "go.mod": "go", "go.sum": "go",
    "cargo.toml": "rust", "cargo.lock": "rust",
    "pom.xml": "java", "build.gradle": "java", "build.gradle.kts": "java",
    "settings.gradle": "java",
    "dockerfile": "docker", "docker-compose.yml": "docker",
    "docker-compose.yaml": "docker", "compose.yml": "docker",
    "compose.yaml": "docker", ".dockerignore": "docker",
    "composer.json": "php",
    "gemfile": "ruby", "gemfile.lock": "ruby",
    "cmakelists.txt": "cpp", "meson.build": "cpp",
    "svelte.config.js": "svelte_astro",
    "azure-pipelines.yml": "azure", "azure-pipelines.yaml": "azure",
}

# Расширение файла (в нижнем регистре, с точкой) -> ключ стека.
SUFFIX_MARKERS: dict[str, str] = {
    ".py": "python",
    ".ts": "web", ".tsx": "web", ".jsx": "web", ".vue": "web",
    ".cs": "dotnet", ".csproj": "dotnet", ".sln": "dotnet",
    ".rs": "rust", ".go": "go", ".java": "java", ".kt": "java",
    ".cpp": "cpp", ".cxx": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".hh": "cpp", ".c": "cpp", ".h": "cpp",
    ".php": "php", ".rb": "ruby", ".lua": "lua", ".sql": "sql",
    ".md": "markdown", ".markdown": "markdown",
    ".ps1": "powershell", ".psm1": "powershell",
    ".graphql": "graphql", ".gql": "graphql",
    ".tf": "terraform", ".tfvars": "terraform",
    ".ipynb": "data",
    ".svelte": "svelte_astro", ".astro": "svelte_astro",
}

# Имя файла начинается с... -> ключ стека (для config-файлов с суффиксом версии).
PREFIX_MARKERS: tuple[tuple[str, str], ...] = (
    ("astro.config.", "svelte_astro"),
    ("vite.config.", "web"),
    ("webpack.config.", "web"),
    ("next.config.", "web"),
)

# Каталоги, которые не открывают ничего нового, но раздувают обход.
PRUNE_DIRS: frozenset[str] = frozenset({
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__",
    "dist", "build", "out", "target", ".next", ".nuxt", "vendor",
    "bin", "obj", ".idea", ".vscode", "coverage", ".mypy_cache",
    ".pytest_cache", ".gradle", ".tox", "site-packages", ".terraform",
})


def detect_stacks(folder, available: set[str] | None = None,
                  max_entries: int = 4000) -> set[str]:
    """Ключи стеков, подходящих проекту в `folder`.

    Обход прунит тяжёлые каталоги и останавливается после `max_entries`
    просмотренных записей — на большом репозитории детект остаётся быстрым
    и не блокирует окно. `available`, если задан, ограничивает результат
    существующими в карте ключами (чужой categories.json может не иметь
    какого-то стека). Несуществующий путь -> пустое множество."""
    try:
        root = Path(folder)
    except Exception:
        return set()
    if not folder or not root.exists() or not root.is_dir():
        return set()

    found: set[str] = set()
    seen = 0
    for _dirpath, dirnames, filenames in os.walk(root):
        # `.git` в списке каталогов — верный признак git-проекта; отмечаем
        # до того, как выкинем его из обхода.
        if ".git" in dirnames:
            found.add("git")
        dirnames[:] = [d for d in dirnames if d.lower() not in PRUNE_DIRS]
        for name in filenames:
            seen += 1
            low = name.lower()
            key = FILENAME_MARKERS.get(low)
            if key:
                found.add(key)
            else:
                suf = os.path.splitext(low)[1]
                key = SUFFIX_MARKERS.get(suf)
                if key:
                    found.add(key)
                else:
                    for pref, pkey in PREFIX_MARKERS:
                        if low.startswith(pref):
                            found.add(pkey)
                            break
        if seen >= max_entries:
            break

    if available is not None:
        found &= available
    return found


def _loads_jsonc(text: str):
    """Разобрать JSON, терпя JSONC (// и /* */ комментарии, хвостовые запятые) —
    файлы VS Code часто с комментариями. Сначала честный json, при неудаче —
    грубая чистка комментариев и повтор. None, если не разобралось."""
    import json
    try:
        return json.loads(text)
    except Exception:
        pass
    import re
    no_block = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    no_line = re.sub(r"(^|\s)//[^\n]*", "", no_block)
    no_trail = re.sub(r",(\s*[}\]])", r"\1", no_line)
    try:
        return json.loads(no_trail)
    except Exception:
        return None


def detect_recommended_stacks(folder, ext_index: dict[str, str]) -> set[str]:
    """Стеки, на которые указывают РЕКОМЕНДАЦИИ воркспейса из
    `<folder>/.vscode/extensions.json` (#3).

    VS Code позволяет проекту перечислить рекомендованные расширения; их id
    точно называют нужные инструменты. Мапим каждый рекомендованный id на его
    стек через ext_index и возвращаем множество ключей стеков. always_on и id,
    которых нет в карте, отбрасываются. Файла нет/битый — пустое множество."""
    if not folder or not ext_index:
        return set()
    try:
        f = Path(folder) / ".vscode" / "extensions.json"
        if not f.is_file():
            return set()
        data = _loads_jsonc(f.read_text(encoding="utf-8-sig"))
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    recs = data.get("recommendations")
    if not isinstance(recs, list):
        return set()
    keys: set[str] = set()
    for rec in recs:
        if not isinstance(rec, str):
            continue
        cat = ext_index.get(rec.lower())
        if cat and cat != "always_on":
            keys.add(cat)
    return keys
