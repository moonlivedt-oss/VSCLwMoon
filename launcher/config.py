# -*- coding: utf-8 -*-
"""launcher_config.json и лог.

Три вещи, которые пишет сам лаунчер:
- load_config / save_config — пресеты, последний выбор, геометрия и т.п.;
- setup_logging             — файловый лог с ротацией + хук на необработанные
                              исключения (у собранного exe должен оставаться
                              след при падении).
"""
import json
import os
import sys
from logging import Logger

from .paths import CONFIG_FILE, LOG_FILE


def setup_logging() -> Logger:
    """Логгер 'launcher' с ротацией в файл. Повторный вызов не плодит хендлеры."""
    import logging
    from logging.handlers import RotatingFileHandler
    logger = logging.getLogger("launcher")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    try:
        h = RotatingFileHandler(str(LOG_FILE), maxBytes=512_000,
                                backupCount=1, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    except Exception:
        pass

    def _hook(exc_type, exc, tb):
        logger.error("Необработанное исключение", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook
    return logger


# Версия схемы launcher_config.json. Растёт, когда меняется форма данных —
# migrate_config приводит старый конфиг к текущей форме, не теряя настроек.
CONFIG_VERSION = 2


def migrate_config(cfg: dict) -> dict:
    """Привести конфиг любой прежней версии к текущей форме (#15).

    Только добавляет недостающие ключи и нормализует форму — ничего не удаляет
    и не перезаписывает пользовательские значения. Идемпотентна: повторный
    вызов на уже мигрированном конфиге ничего не меняет. Возвращает тот же
    объект (правится на месте) для удобства вызова."""
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.setdefault("presets", {})
    cfg.setdefault("recent_folders", [])
    cfg.setdefault("last_selected", [])
    cfg.setdefault("kill_first", True)
    cfg.setdefault("folder_stacks", {})   # #1: выбор стеков, привязанный к папке
    cfg.setdefault("folder_auto", [])     # #1+: папки, для которых набор применяется без вопроса
    cfg.setdefault("extra_categories", {})  # #6: раскладка незнакомых расширений из мастера
    # Пресеты исторически хранились как список ключей стеков; теперь значение
    # может быть и словарём {stacks, folder, kill, ...} (#4). Обе формы валидны,
    # normalize_preset разбирает любую — здесь ничего конвертировать не нужно.
    cfg["config_version"] = CONFIG_VERSION
    return cfg


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return migrate_config(json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig")))
        except Exception as e:
            # Битый конфиг — не роняем запуск, откат на дефолты. Но след в лог:
            # иначе «слетели настройки» не отличить от первого запуска.
            import logging; logging.getLogger("launcher").warning("Не прочитать %s (%s) — дефолты", CONFIG_FILE.name, e)
    return migrate_config({})


# --- память выбора стеков по папке проекта (#1) ----------------------------
# Один и тот же проект почти всегда открывают с одним набором стеков. Запоминаем
# выбор под нормализованным путём к папке и предлагаем его при следующем выборе
# этой папки — без ручного пересоставления галочек каждый раз.

FOLDER_STACKS_CAP = 40   # сколько папок помнить (чтобы конфиг не пух)


def _folder_key(folder: str) -> str:
    """Нормализованный ключ папки: без регистра и разнобоя слэшей — чтобы
    'D:\\Proj' и 'd:/proj/' указывали на одну запись."""
    if not folder:
        return ""
    try:
        return os.path.normcase(os.path.normpath(folder))
    except Exception:
        return folder.strip().lower()


def remember_folder_stacks(cfg: dict, folder: str, stacks, n: int | None = None,
                           cap: int = FOLDER_STACKS_CAP) -> None:
    """Запомнить выбор стеков для папки. Пустой список — валиден (осознанный
    выбор «только ядро»). Ничего не пишет на диск — только правит cfg."""
    key = _folder_key(folder)
    if not key:
        return
    fs = cfg.setdefault("folder_stacks", {})
    fs.pop(key, None)   # переставляем в конец: свежие переживают чистку
    fs[key] = sorted({str(s) for s in stacks})
    if len(fs) > cap:
        auto = cfg.get("folder_auto", [])
        for old in list(fs)[:-cap]:
            del fs[old]
            if old in auto: auto.remove(old)  # не держим авто-флаг для забытой папки


def recall_folder_stacks(cfg: dict, folder: str) -> list[str] | None:
    """Ранее запомненный выбор стеков для папки или None, если папка новая."""
    return cfg.get("folder_stacks", {}).get(_folder_key(folder))


def set_folder_auto(cfg: dict, folder: str, on: bool) -> None:
    """Пометить папку авто-применяемой: при её выборе запомненный набор стеков
    включается сам, без строки-подсказки. Только правит cfg (не пишет на диск)."""
    key = _folder_key(folder)
    if not key:
        return
    auto = cfg.setdefault("folder_auto", [])
    if on and key not in auto:
        auto.append(key)
    elif not on and key in auto:
        auto.remove(key)


def is_folder_auto(cfg: dict, folder: str) -> bool:
    """Помечена ли папка как авто-применяемая."""
    return _folder_key(folder) in cfg.get("folder_auto", [])


def folder_auto_stacks(cfg: dict, folder: str) -> list[str] | None:
    """Набор стеков для авто-применения при выборе папки: запомненный выбор,
    если папка помечена авто и выбор для неё есть. Иначе None — тогда работает
    обычная строка-подсказка."""
    if not is_folder_auto(cfg, folder):
        return None
    return recall_folder_stacks(cfg, folder)


# --- история фактических замеров памяти (#6) -------------------------------
# Держим по одной записи на подпись выбора (launch.selection_signature):
# после запуска мы замеряем реальный working set и складываем его сюда, чтобы
# в следующий раз показать не грубую оценку WEIGHT_MB, а «замерено ранее: X МБ».

FOOTPRINT_CAP = 40   # сколько разных наборов помнить (чтобы конфиг не пух)


def record_footprint(cfg: dict, signature: str, mb: int, n: int,
                     cap: int = FOOTPRINT_CAP) -> None:
    """Запомнить фактический замер памяти для подписи выбора. Ничего не пишет
    на диск — только правит cfg (сохранение — за вызывающим). Нулевой замер
    (VS Code не запущен) игнорируем: он не отражает footprint набора."""
    if not signature or mb <= 0 or n <= 0:
        return
    hist = cfg.setdefault("footprint_history", {})
    hist[signature] = {"mb": int(mb), "n": int(n)}
    if len(hist) > cap:
        # Простая эвикция: режем до cap, сохраняя порядок вставки (dict в py3.7+
        # упорядочен) — свежие записи в конце и переживают чистку.
        for key in list(hist)[:-cap]:
            del hist[key]


def lookup_footprint(cfg: dict, signature: str) -> dict | None:
    """Ранее замеренный footprint для подписи выбора или None."""
    return cfg.get("footprint_history", {}).get(signature)


# --- базлайн «всё включено» для реальной экономии (#2) ---------------------
# Оценка WEIGHT_MB — грубая. Чтобы показать ФАКТИЧЕСКУЮ экономию, запоминаем
# замеренный working set VS Code, запущенного без единого выключенного стека
# (disabled == 0, не bare): это и есть полный footprint сборки пользователя.
# Тогда saved_real = baseline − текущий_замер этого набора.

def record_baseline(cfg: dict, mb: int, n: int) -> None:
    """Запомнить фактический footprint полного набора (все стеки включены).
    Нулевой замер (VS Code не запущен) игнорируем."""
    if mb <= 0 or n <= 0:
        return
    cfg["baseline_full"] = {"mb": int(mb), "n": int(n)}


def lookup_baseline(cfg: dict) -> dict | None:
    """Замеренный footprint полного набора или None."""
    return cfg.get("baseline_full")


def measured_savings_mb(cfg: dict, signature: str) -> int | None:
    """Фактическая экономия набора относительно базлайна «всё включено»:
    baseline.mb − footprint(signature).mb. None, если не хватает замеров или
    разница неположительна (шум замера — не показываем «экономию» вниз)."""
    base = lookup_baseline(cfg)
    fp = lookup_footprint(cfg, signature)
    if not base or not fp:
        return None
    saved = base["mb"] - fp["mb"]
    return saved if saved > 0 else None


def save_config(cfg: dict) -> None:
    """Атомарная запись: пишем во временный файл рядом и подменяем им целевой
    (os.replace атомарен в пределах одного тома). Прерванная на середине
    запись не повредит текущий launcher_config.json."""
    data = json.dumps(cfg, ensure_ascii=False, indent=2)
    tmp = CONFIG_FILE.with_name(f"{CONFIG_FILE.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, CONFIG_FILE)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
