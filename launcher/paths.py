# -*- coding: utf-8 -*-
r"""Пути к ресурсам, конфигу и логу.

Один источник правды по путям: другие модули импортируют константы отсюда
и не занимаются определением, где живёт data/ или где писать конфиг.

Учитывает PyInstaller: в собранном exe ресурсы (data/, assets/) распакованы
в _MEIPASS, а личный конфиг и лог пишем рядом с exe, чтобы они переживали
перезапуск.

Папка рядом с exe не всегда доступна на запись: exe могли положить в
Program Files, на сетевой диск, во «Загрузки» с блокировкой антивируса или
запустить с флешки только для чтения. Раньше в этом случае первая же запись
конфига падала, а лог молча не писался — и пользователь терял настройки при
каждом запуске. Теперь при недоступной на запись папке мы уходим в
%LOCALAPPDATA%\VSCodeLauncher и один раз переносим туда старый конфиг.
"""
import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    _PREFERRED_CONFIG_DIR = Path(sys.executable).parent
else:
    ROOT = Path(__file__).resolve().parent.parent
    _PREFERRED_CONFIG_DIR = ROOT

DATA_DIR = ROOT / "data"
ASSETS_DIR = ROOT / "assets"

CATEGORIES_FILE = DATA_DIR / "categories.json"
DESCRIPTIONS_FILE = DATA_DIR / "plugin_descriptions.json"
RECOMMENDED_FILE = DATA_DIR / "recommended_settings.json"
TOOLCHAINS_FILE = DATA_DIR / "toolchains.json"   # каталог языковых тулчейнов (#6)

ICON_FILE = ASSETS_DIR / "app.ico"
LOGO_FILE = ASSETS_DIR / "logo.png"   # необязательный логотип в шапке

APP_NAME = "VSCodeLauncher"
CONFIG_NAME = "launcher_config.json"
LOG_NAME = "launcher.log"


def fallback_config_dir() -> Path:
    r"""Куда уходим, если рядом с exe писать нельзя: %LOCALAPPDATA%\VSCodeLauncher.
    Без LOCALAPPDATA (экзотика/не-Windows) — ~/.vscode-launcher."""
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_NAME
    return Path.home() / ".vscode-launcher"


def dir_writable(path: Path) -> bool:
    """Реально ли можно создать файл в этой папке. Проверяем записью пробного
    файла, а не os.access: на Windows права из ACL и «виртуализация» Program
    Files делают os.access ненадёжным."""
    probe = path / f".write-probe-{os.getpid()}"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_text("", encoding="ascii")
        return True
    except Exception:
        return False
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def resolve_config_dir(preferred: Path | None = None) -> tuple[Path, bool]:
    """Куда писать конфиг и лог: (папка, ушли_ли_в_фолбэк).

    Сначала пробуем папку рядом с exe/исходниками — там конфиг виден рядом с
    программой, это удобно для портативного запуска. Если писать туда нельзя —
    %LOCALAPPDATA%. Если и там нельзя (совсем экзотика) — возвращаем
    предпочтительную: пусть падение будет явным, а не в случайном месте."""
    preferred = preferred or _PREFERRED_CONFIG_DIR
    if dir_writable(preferred):
        return preferred, False
    fb = fallback_config_dir()
    if dir_writable(fb):
        return fb, True
    return preferred, False


def migrate_config_file(old_dir: Path, new_dir: Path, name: str = CONFIG_NAME) -> bool:
    """Перенести конфиг из старого расположения в новое ОДИН раз.

    Копируем (не перемещаем): исходная папка может быть только для чтения, да и
    оставить пользователю старый файл безопаснее. Копируем только если в новом
    месте файла ещё нет — иначе затёрли бы актуальные настройки старыми."""
    src, dst = old_dir / name, new_dir / name
    if dst.exists() or not src.is_file():
        return False
    try:
        dst.write_bytes(src.read_bytes())
        return True
    except Exception:
        return False


CONFIG_DIR, CONFIG_DIR_IS_FALLBACK = resolve_config_dir()
if CONFIG_DIR_IS_FALLBACK:
    migrate_config_file(_PREFERRED_CONFIG_DIR, CONFIG_DIR)

CONFIG_FILE = CONFIG_DIR / CONFIG_NAME
LOG_FILE = CONFIG_DIR / LOG_NAME
