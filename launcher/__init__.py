# -*- coding: utf-8 -*-
"""VS Code Launcher — переключатель нагрузки расширений.

Публичный код разложен по модулям (импортируй нужный напрямую или через
фасад core.py):

- paths           — пути, ROOT/CONFIG_DIR, файлы данных и лога;
- safety          — valid_ext_id, shell_safe, safe_arg;
- config          — load_config, save_config, setup_logging;
- categories      — карта стеков, поиск дублей, WEIGHT/*, рекомендации;
- vscode          — CLI, чтение/установка расширений, память, kill/launch;
- winmem          — нативный (ctypes) замер памяти процессов Windows;
- weights         — реальный вес стеков: размер на диске + калибровка по замерам;
- quicklaunch     — запуск пресета одной функцией (окно, CLI и трей);
- toolchains      — установка языковых тулчейнов (компиляторы, SDK) через winget;
- env_path        — управление пользовательским PATH через реестр (без setx);
- launch          — compute_disabled, build_launch_*, selection_signature;
- settings_apply  — apply_settings + ротация бэкапов;
- selftest        — CLI-прогон логики без GUI;
- theme           — палитры Catppuccin Mocha/Latte и QSS;
- gui_widgets     — CategoryCard и микро-фабрики виджетов;
- gui_workers     — фоновые QThread'ы (ExtLoader, MemProbe, Installer);
- gui_tray        — значок в трее: запуск пресета без открытия окна;
- gui             — окно PyQt6, диалоги, точка входа run_gui;
- core            — фасад для обратной совместимости (импорты).
"""

__version__ = "1.4.0"
