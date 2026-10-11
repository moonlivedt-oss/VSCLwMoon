# Участие в разработке

Спасибо за интерес к VS Code Launcher! Код - Python 3.12+ и PyQt6, всё остальное из stdlib.

## Быстрый цикл

```powershell
git clone https://github.com/moonlivedt-oss/VSCLwMoon.git
cd VSCLwMoon
py -3.14 -m pip install -e .[dev]
scripts\Запустить.bat               # окно
py -3.14 -m pytest                  # тесты (то же гоняет CI на Windows, Python 3.12 и 3.14)
py -3.14 -m ruff check launcher tests
py -3.14 -m mypy
```

Логику без окна удобно проверять из командной строки: `py vscode_launcher.py --help`
(список стеков, размеры, `--compat-report`, `--startup-costs` и т.д.).

## Правила

- Логика - в модулях без Qt (`launcher/core.py`, `compat.py`, `env_path.py`, `toolchains.py`,
  `moonperf.py`...), окно только вызывает её. Новая логика - с тестом в `tests/`.
- Всё, что меняет систему (PATH, установка, удаление, запись `settings.json`), спрашивает
  подтверждение и делает бэкап; аргументы внешних команд - только списком, без `shell=True`.
- Видимый текст - по-русски и по-английски (`launcher/i18n.py`), без эмодзи.
- Изменения записывайте в `CHANGELOG.md`, раздел `[Unreleased]`.

## Релиз

Версия - в `pyproject.toml` и `launcher/__init__.py`. Тег `vX.Y.Z` запускает в CI сборку
`VSCodeLauncher.exe` и прикладывает его к релизу вместе с SHA256.
