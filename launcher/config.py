# -*- coding: utf-8 -*-
"""launcher_config.json и лог.

Три вещи, которые пишет сам лаунчер:
- load_config / save_config — пресеты, последний выбор, геометрия и т.п.;
- setup_logging             — файловый лог с ротацией + хук на необработанные
                              исключения (у собранного exe должен оставаться
                              след при падении).

Конфиг переживает всё: чужие правки руками, обрыв записи, откат на старую
версию программы. Поэтому load_config не доверяет содержимому — каждый
известный ключ проверяется по типу (validate_config), а нечитаемый файл
уезжает в карантин рядом, чтобы его можно было посмотреть, а не гадать,
«куда делись настройки».
"""
import json
import os
import sys
from logging import Logger
from pathlib import Path

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
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
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
CONFIG_VERSION = 3

# Ожидаемый тип и значение по умолчанию для каждого известного ключа.
# Ключ не в таблице (например, пришедший из будущей версии) сохраняется как
# есть — обновление вниз-вверх не должно терять чужие данные.
_SCHEMA: dict[str, tuple[type, object]] = {
    "presets": (dict, {}),
    "recent_folders": (list, []),
    "last_selected": (list, []),
    "kill_first": (bool, True),
    "soft_close": (bool, False),
    "new_window": (bool, True),
    "disable_gpu": (bool, False),
    "check_updates": (bool, True),
    "profile": (str, ""),
    "theme": (str, "dark"),
    "lang": (str, "ru"),
    "geometry": (str, ""),
    "code_cli": (str, ""),
    "folder_stacks": (dict, {}),
    "folder_auto": (list, []),
    "extra_categories": (dict, {}),
    "overrides": (dict, {}),
    "footprint_history": (dict, {}),
    "baseline_full": (dict, {}),
    "installed_cache": (dict, {}),
    "ext_sizes": (dict, {}),
    "tray": (bool, True),
    "close_to_tray": (bool, False),
}

# Ключи, которые нужны всегда: их создаём, даже если в файле их не было.
_REQUIRED = (
    "presets", "recent_folders", "last_selected", "kill_first",
    "folder_stacks", "folder_auto", "extra_categories",
)


def validate_config(cfg: dict) -> list[str]:
    """Привести значения известных ключей к ожидаемым типам. Правит cfg на
    месте, возвращает список исправленных ключей (для лога).

    Битый тип (список вместо словаря, строка вместо булева) — не повод терять
    весь конфиг: сбрасываем ТОЛЬКО испорченный ключ на дефолт, остальное
    остаётся. Так одна кривая правка руками не стирает пресеты."""
    fixed: list[str] = []
    for key, (typ, default) in _SCHEMA.items():
        if key not in cfg:
            continue
        value = cfg[key]
        if typ is bool:
            # 0/1 из JSON — валидное булево, приводим молча.
            if isinstance(value, bool):
                continue
            if isinstance(value, int) and value in (0, 1):
                cfg[key] = bool(value)
                continue
        elif isinstance(value, typ) and not (typ is not bool and isinstance(value, bool)):
            continue
        cfg[key] = type(default)(default) if isinstance(default, (dict, list)) else default
        fixed.append(key)
    return fixed


def migrate_config(cfg: dict) -> dict:
    """Привести конфиг любой прежней версии к текущей форме (#15).

    Только добавляет недостающие ключи и нормализует форму — ничего не удаляет
    и не перезаписывает корректные пользовательские значения. Идемпотентна:
    повторный вызов на уже мигрированном конфиге ничего не меняет. Возвращает
    тот же объект (правится на месте) для удобства вызова."""
    if not isinstance(cfg, dict):
        cfg = {}
    validate_config(cfg)
    for key in _REQUIRED:
        default = _SCHEMA[key][1]
        cfg.setdefault(key, dict(default) if isinstance(default, dict)
                       else list(default) if isinstance(default, list) else default)
    # Пресеты исторически хранились как список ключей стеков; теперь значение
    # может быть и словарём {stacks, folder, kill, ...} (#4). Обе формы валидны,
    # normalize_preset разбирает любую — здесь ничего конвертировать не нужно.
    #
    # v3: замеры памяти получили метку метрики (см. MEMORY_METRIC). Записи без
    # метки сделаны прежним замером через PowerShell/WorkingSetPrivate — они не
    # сравнимы с нынешним нативным Private Bytes, поэтому помечаем их старой
    # меткой, а не выбрасываем: если пользователь откатится, они пригодятся.
    if cfg.get("config_version", 0) < 3:
        for rec in list(cfg.get("footprint_history", {}).values()):
            if isinstance(rec, dict):
                rec.setdefault("metric", "ws-private-perf")
        base = cfg.get("baseline_full")
        if isinstance(base, dict):
            base.setdefault("metric", "ws-private-perf")
    cfg["config_version"] = CONFIG_VERSION
    return cfg


def quarantine_config(path: "Path | None" = None) -> "Path | None":
    """Отложить нечитаемый конфиг в сторону под именем *.corrupt-<время>.json.

    Молча стартовать с дефолтов и затереть файл при первом же save_config —
    значит потерять пресеты пользователя без следа. Копия рядом позволяет
    достать их руками. Возвращает путь к копии или None."""
    from datetime import datetime
    path = path or CONFIG_FILE
    try:
        if not path.exists():
            return None
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        dst = path.with_name(f"{path.stem}.corrupt-{ts}{path.suffix}")
        dst.write_bytes(path.read_bytes())
        return dst
    except Exception:
        return None


def load_config() -> dict:
    if CONFIG_FILE.exists():
        import logging
        log = logging.getLogger("launcher")
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
        except Exception as e:
            # Битый конфиг — не роняем запуск, откат на дефолты. Но след в лог
            # и копию рядом: иначе «слетели настройки» не отличить от первого
            # запуска, а восстановить пресеты будет неоткуда.
            saved = quarantine_config()
            log.warning("Не прочитать %s (%s) — дефолты%s", CONFIG_FILE.name, e,
                        f"; копия: {saved.name}" if saved else "")
            return migrate_config({})
        cfg = migrate_config(raw)
        return cfg
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


def remember_folder_stacks(cfg: dict, folder: str, stacks,
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

# Метка метрики, которой сделаны замеры. Пока лаунчер мерил память через
# PowerShell-счётчик WorkingSetPrivate, записи были в одной шкале; нативный
# замер (winmem.py) отдаёт Private Bytes — число другое. Сравнивать их между
# собой нельзя: «экономия» вышла бы разницей несравнимых величин. Поэтому у
# каждой записи есть метка, и старые записи просто не участвуют в расчёте.
MEMORY_METRIC = "private-bytes"


def record_footprint(cfg: dict, signature: str, mb: int, n: int,
                     cap: int = FOOTPRINT_CAP, metric: str = MEMORY_METRIC) -> None:
    """Запомнить фактический замер памяти для подписи выбора. Ничего не пишет
    на диск — только правит cfg (сохранение — за вызывающим). Нулевой замер
    (VS Code не запущен) игнорируем: он не отражает footprint набора."""
    if not signature or mb <= 0 or n <= 0:
        return
    hist = cfg.setdefault("footprint_history", {})
    hist[signature] = {"mb": int(mb), "n": int(n), "metric": metric}
    if len(hist) > cap:
        # Простая эвикция: режем до cap, сохраняя порядок вставки (dict в py3.7+
        # упорядочен) — свежие записи в конце и переживают чистку.
        for key in list(hist)[:-cap]:
            del hist[key]


def lookup_footprint(cfg: dict, signature: str,
                     metric: str = MEMORY_METRIC) -> dict | None:
    """Ранее замеренный footprint для подписи выбора или None. Запись, сделанную
    другой метрикой, не отдаём — она не сравнима с текущими числами."""
    rec = cfg.get("footprint_history", {}).get(signature)
    if isinstance(rec, dict) and rec.get("metric", "ws-private-perf") == metric:
        return rec
    return None


# --- базлайн «всё включено» для реальной экономии (#2) ---------------------
# Оценка WEIGHT_MB — грубая. Чтобы показать ФАКТИЧЕСКУЮ экономию, запоминаем
# замеренный working set VS Code, запущенного без единого выключенного стека
# (disabled == 0, не bare): это и есть полный footprint сборки пользователя.
# Тогда saved_real = baseline − текущий_замер этого набора.

def record_baseline(cfg: dict, mb: int, n: int, metric: str = MEMORY_METRIC) -> None:
    """Запомнить фактический footprint полного набора (все стеки включены).
    Нулевой замер (VS Code не запущен) игнорируем."""
    if mb <= 0 or n <= 0:
        return
    cfg["baseline_full"] = {"mb": int(mb), "n": int(n), "metric": metric}


def lookup_baseline(cfg: dict, metric: str = MEMORY_METRIC) -> dict | None:
    """Замеренный footprint полного набора или None (только текущей метрикой)."""
    base = cfg.get("baseline_full")
    if isinstance(base, dict) and base.get("metric", "ws-private-perf") == metric and base.get("mb"):
        return base
    return None


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
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, CONFIG_FILE)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
