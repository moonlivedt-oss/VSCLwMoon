# -*- coding: utf-8 -*-
"""VS Code Launcher — переключатель нагрузки расширений.

Публичный код разложен по модулям (импортируй нужный напрямую или через
фасад core.py):

- paths           — пути, ROOT/CONFIG_DIR, файлы данных и лога;
- safety          — valid_ext_id, shell_safe, safe_arg;
- config          — load_config, save_config, setup_logging;
- categories      — карта стеков, поиск дублей, WEIGHT/*, рекомендации;
- vscode          — CLI, чтение/установка расширений, память, kill/launch;
- toolchains      — установка языковых тулчейнов (компиляторы, SDK) через winget;
- env_path        — управление пользовательским PATH через реестр (без setx);
- launch          — compute_disabled, estimate_saved_mb, build_launch_*;
- settings_apply  — apply_settings + ротация бэкапов;
- selftest        — CLI-прогон логики без GUI;
- theme           — палитры Catppuccin Mocha/Latte и QSS;
- gui_widgets     — CategoryCard и микро-фабрики виджетов;
- gui_workers     — фоновые QThread'ы (ExtLoader, MemProbe, Installer);
- gui             — окно PyQt6, диалоги, точка входа run_gui;
- core            — фасад для обратной совместимости (импорты).
"""

__version__ = "1.1.0"
