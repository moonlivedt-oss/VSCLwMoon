# -*- coding: utf-8 -*-
"""Фасад: собирает публичный API из специализированных модулей.

Раньше здесь жило всё: пути, безопасность, конфиг, категории, работа с
VS Code, сборка команды, автонастройка и selftest. Модуль разросся, и
навигация ухудшилась. Теперь каждая зона живёт отдельно (см. импорты
ниже), а этот файл только пере-экспортирует их публичный API — чтобы
существующие импорты `from launcher import core` не сломались, а новый
код мог импортировать точечно из profile-модулей.

Куда что переехало:
- paths.py           — пути, ROOT/CONFIG_DIR, файлы данных и лога
- safety.py          — valid_ext_id, shell_safe, safe_arg
- config.py          — load_config, save_config, setup_logging
- categories.py      — карта стеков, дубли, WEIGHT*, рекомендации
- vscode.py          — CLI, чтение расширений, установка, память, kill/launch
- launch.py          — compute_disabled, estimate_saved_mb, build_launch_*
- settings_apply.py  — apply_settings + ротация бэкапов
- selftest.py        — CLI-прогон логики
"""
# Модули os и subprocess держим импортированными на уровне core, чтобы тесты
# могли патчить их через `monkeypatch.setattr(core.os, ...)` / `core.subprocess,...`
# — это singleton-модули, патч виден и в vscode.py / config.py.
import os          # noqa: F401  (нужно тестам для monkeypatch save_config)
import subprocess  # noqa: F401  (нужно тестам для monkeypatch kill_vscode)

# Подмодули доступны как атрибуты core: тесты патчат путь-константы через
# `monkeypatch.setattr(core.categories, "CATEGORIES_FILE", ...)`, потому что
# константы — не singleton, а обычные Path-объекты (в отличие от os/subprocess).
from . import (  # noqa: F401
    categories, classify, config, detect, env_path, launch, manifests, paths,
    presets, profile_export, safety, settings_apply, toolchains, updates, vscode,
)

from .paths import (
    ASSETS_DIR, CATEGORIES_FILE, CONFIG_DIR, CONFIG_FILE, DATA_DIR,
    DESCRIPTIONS_FILE, ICON_FILE, LOGO_FILE, LOG_FILE, RECOMMENDED_FILE, ROOT,
)
from .safety import safe_arg, shell_safe, valid_ext_id
from .config import (
    CONFIG_VERSION, load_config, lookup_baseline, lookup_footprint,
    measured_savings_mb, migrate_config, recall_folder_stacks, record_baseline,
    record_footprint, remember_folder_stacks, save_config, setup_logging,
    set_folder_auto, is_folder_auto, folder_auto_stacks,
)
from .detect import detect_recommended_stacks, detect_stacks
from .presets import (
    build_shortcut_cmd, normalize_preset, preset_has_options, preset_stacks,
)
from .updates import (
    build_update_swap_bat, check_for_update, download_and_verify,
    fetch_latest_release, fetch_latest_release_info, is_newer, parse_release_info,
    parse_sha256_text, parse_version, sha256_of,
)
from .categories import (
    WEIGHT, WEIGHT_HELP, WEIGHT_LABEL, WEIGHT_MB,
    build_ext_index, categories_present, find_duplicate_extensions,
    load_categories, load_descriptions, load_recommended, recommended_for,
)
from .vscode import (
    code_footprint_mb, code_gui_exe, code_image_name, code_memory_mb,
    code_private_ws_mb, extensions_dir,
    find_code_cli, install_extension, kill_vscode, launch_detached,
    list_code_installs, list_installed_extensions, load_installed, marketplace_url,
    read_installed_from_disk, resolve_code_cli, uninstall_extension,
    vscode_process_count, vscode_user_settings_path,
)
from .manifests import (
    build_dependency_map, read_extension_manifests,
)
from .classify import (
    classify_extension, suggest_categories,
)
from .profile_export import (
    build_profile_extensions, build_profile_template, profile_file_content,
)
from .launch import (
    build_launch_args, build_launch_command, compute_disabled,
    disabled_by_category, estimate_saved_mb, required_by_enabled,
    selection_signature,
)
from .settings_apply import (
    SETTINGS_BACKUP_KEEP, _rotate_settings_backups, apply_settings,
)
from .selftest import selftest

__all__ = [
    # paths
    "ROOT", "CONFIG_DIR", "DATA_DIR", "ASSETS_DIR",
    "CATEGORIES_FILE", "DESCRIPTIONS_FILE", "RECOMMENDED_FILE",
    "ICON_FILE", "LOGO_FILE", "CONFIG_FILE", "LOG_FILE",
    # safety
    "valid_ext_id", "shell_safe", "safe_arg",
    # config
    "setup_logging", "load_config", "save_config", "migrate_config",
    "CONFIG_VERSION", "record_footprint", "lookup_footprint",
    "remember_folder_stacks", "recall_folder_stacks",
    "record_baseline", "lookup_baseline", "measured_savings_mb",
    "set_folder_auto", "is_folder_auto", "folder_auto_stacks",
    # detect (#1, #3)
    "detect_stacks", "detect_recommended_stacks",
    # presets / лаунч-профили (#4, #5)
    "normalize_preset", "preset_stacks", "preset_has_options", "build_shortcut_cmd",
    # updates (#8, #10)
    "check_for_update", "fetch_latest_release", "is_newer", "parse_version",
    "fetch_latest_release_info", "parse_release_info", "parse_sha256_text",
    "sha256_of", "download_and_verify", "build_update_swap_bat",
    # categories
    "WEIGHT", "WEIGHT_HELP", "WEIGHT_LABEL", "WEIGHT_MB",
    "load_categories", "load_descriptions", "load_recommended",
    "build_ext_index", "find_duplicate_extensions",
    "categories_present", "recommended_for",
    # vscode
    "find_code_cli", "resolve_code_cli", "list_code_installs",
    "extensions_dir", "read_installed_from_disk",
    "list_installed_extensions", "load_installed",
    "install_extension", "uninstall_extension",
    "code_image_name", "code_gui_exe", "code_memory_mb", "vscode_process_count",
    "code_private_ws_mb", "code_footprint_mb",
    "kill_vscode", "launch_detached", "vscode_user_settings_path", "marketplace_url",
    # manifests / classify (#1, #3)
    "read_extension_manifests", "build_dependency_map",
    "classify_extension", "suggest_categories",
    # profile export (#4)
    "build_profile_extensions", "build_profile_template", "profile_file_content",
    # launch
    "compute_disabled", "estimate_saved_mb", "disabled_by_category",
    "required_by_enabled", "selection_signature",
    "build_launch_command", "build_launch_args",
    # settings_apply
    "SETTINGS_BACKUP_KEEP", "_rotate_settings_backups", "apply_settings",
    # selftest
    "selftest",
]
