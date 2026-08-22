# -*- coding: utf-8 -*-
"""Логика лаунчера без GUI: поиск CLI, данные о расширениях, конфиг,
установка/удаление, сборка команды запуска, замер памяти."""
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ASSETS_DIR = ROOT / "assets"
CATEGORIES_FILE = DATA_DIR / "categories.json"
DESCRIPTIONS_FILE = DATA_DIR / "plugin_descriptions.json"
BANNER_FILE = ASSETS_DIR / "banner.png"
# Личный конфиг остаётся в корне: он пользовательский и в .gitignore.
CONFIG_FILE = ROOT / "launcher_config.json"

# Ориентировочная «тяжесть» стека и её отражение в памяти. Ключи — как в categories.json.
WEIGHT = {
    "sonar": "heavy", "java": "heavy", "azure": "heavy", "cpp": "heavy",
    "python": "medium", "sql": "medium", "git": "medium",
    "web": "light", "graphics3d": "light", "markdown": "light",
    "powershell": "light",
}
WEIGHT_LABEL = {"heavy": "тяжёлый", "medium": "средний", "light": "лёгкий"}
WEIGHT_MB = {"heavy": 500, "medium": 150, "light": 30}


def find_code_cli() -> str | None:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = [
        local / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd",
        Path("C:/Program Files/Microsoft VS Code/bin/code.cmd"),
        local / "Programs" / "Microsoft VS Code Insiders" / "bin" / "code-insiders.cmd",
        Path("C:/Program Files/Microsoft VS Code Insiders/bin/code-insiders.cmd"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    from shutil import which
    return which("code") or which("code-insiders")


def load_categories() -> dict:
    with open(CATEGORIES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


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


def extensions_dir(code_cli: str | None) -> Path:
    """Папка установленных расширений. Учитывает VSCODE_EXTENSIONS и Insiders."""
    env = os.environ.get("VSCODE_EXTENSIONS")
    if env:
        return Path(env)
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    if code_cli and "insiders" in code_cli.lower():
        return home / ".vscode-insiders" / "extensions"
    return home / ".vscode" / "extensions"


def read_installed_from_disk(code_cli: str | None) -> list[str]:
    """Быстрое чтение id из extensions.json (~3 мс). Пусто — файла нет/битый."""
    f = extensions_dir(code_cli) / "extensions.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        ids = {(e.get("identifier") or {}).get("id", "").lower()
               for e in data if isinstance(e, dict)}
        ids.discard("")
        return sorted(ids)
    except Exception:
        return []


def list_installed_extensions(code_cli: str) -> list[str]:
    """Надёжный фолбэк: спрашиваем сам VS Code (~0.5 с, спавнит Node)."""
    try:
        out = subprocess.run(
            [os.environ.get("COMSPEC", "cmd.exe"), "/c", code_cli, "--list-extensions"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        return [ln.strip().lower() for ln in out.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


def install_extension(code_cli: str, ext_id: str) -> tuple[bool, str]:
    """Установить расширение из маркетплейса. Возвращает (успех, вывод)."""
    try:
        out = subprocess.run(
            [os.environ.get("COMSPEC", "cmd.exe"), "/c", code_cli,
             "--install-extension", ext_id, "--force"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        )
        text = ((out.stdout or "") + "\n" + (out.stderr or "")).strip()
        return out.returncode == 0, text
    except Exception as e:
        return False, str(e)


def uninstall_extension(code_cli: str, ext_id: str) -> tuple[bool, str]:
    """Удалить расширение. Возвращает (успех, вывод)."""
    try:
        out = subprocess.run(
            [os.environ.get("COMSPEC", "cmd.exe"), "/c", code_cli,
             "--uninstall-extension", ext_id],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        text = ((out.stdout or "") + "\n" + (out.stderr or "")).strip()
        return out.returncode == 0, text
    except Exception as e:
        return False, str(e)


def load_installed(code_cli: str | None) -> tuple[list[str], str]:
    """Единая точка: сначала чтение с диска, затем фолбэк на CLI. (ids, источник)."""
    ids = read_installed_from_disk(code_cli)
    if ids:
        return ids, "extensions.json"
    if code_cli:
        return list_installed_extensions(code_cli), "code --list-extensions"
    return [], "нет источника"


def build_ext_index(cats: dict) -> dict[str, str]:
    """id -> ключ категории ('always_on' или ключ из categories)."""
    idx = {}
    for e in cats.get("always_on", {}).get("extensions", []):
        idx[e.lower()] = "always_on"
    for key, cat in cats.get("categories", {}).items():
        for e in cat.get("extensions", []):
            idx[e.lower()] = key
    return idx


def compute_disabled(installed: list[str], ext_index: dict[str, str],
                     selected_cats: set[str]) -> list[str]:
    """Выключаем расширения из невыбранных категорий. always_on и всё, чего нет
    в карте, остаётся включённым."""
    disabled = []
    for ext in installed:
        cat = ext_index.get(ext)
        if cat is None or cat == "always_on":
            continue
        if cat not in selected_cats:
            disabled.append(ext)
    return disabled


def estimate_saved_mb(disabled: list[str], ext_index: dict[str, str]) -> int:
    """Оценка освобождаемой памяти: каждую выключаемую категорию считаем один
    раз и только если у неё реально выключается установленное расширение."""
    cats_off = {ext_index.get(e) for e in disabled}
    cats_off.discard(None)
    cats_off.discard("always_on")
    return sum(WEIGHT_MB.get(WEIGHT.get(c, "light"), 30) for c in cats_off)


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"presets": {}, "recent_folders": [], "last_selected": [], "kill_first": True}


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def code_image_name(code_cli: str) -> str:
    """Имя процесса для taskkill: 'Code.exe' или 'Code - Insiders.exe'."""
    return "Code - Insiders.exe" if "insiders" in (code_cli or "").lower() else "Code.exe"


def code_memory_mb(code_cli: str | None) -> tuple[int, int]:
    """Фактический расход памяти запущенного VS Code: (МБ, число процессов)."""
    image = code_image_name(code_cli)
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
    except Exception:
        return 0, 0
    import csv, io
    total_kb, n = 0, 0
    for row in csv.reader(io.StringIO(out.stdout)):
        if len(row) < 5:
            continue
        digits = "".join(ch for ch in row[4] if ch.isdigit())
        if digits:
            total_kb += int(digits); n += 1
    return round(total_kb / 1024), n


def build_launch_command(code_cli: str, disabled: list[str], folder: str,
                         new_window: bool, kill_first: bool,
                         profile: str = "", disable_gpu: bool = False,
                         bare: bool = False) -> str:
    parts = []
    if kill_first:
        parts.append(f'taskkill /F /IM "{code_image_name(code_cli)}" >nul 2>&1')
        parts.append("timeout /t 2 /nobreak >nul")
    cmd = [f'"{code_cli}"']
    if new_window or kill_first:
        cmd.append("--new-window")
    if profile:
        cmd.append(f'--profile "{profile}"')
    if bare:
        cmd.append("--disable-extensions")
    else:
        for d in disabled:
            cmd.append(f"--disable-extension {d}")
    if disable_gpu:
        cmd.append("--disable-gpu")
    if folder:
        cmd.append(f'"{folder}"')
    parts.append(" ".join(cmd))
    return " & ".join(parts)


def launch(cmd_line: str) -> None:
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    subprocess.Popen(cmd_line, shell=True,
                     creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                     close_fds=True)


def selftest(selected_csv: str):
    """Прогон логики без GUI: что включится/выключится и итоговая команда."""
    import time
    cats = load_categories()
    idx = build_ext_index(cats)
    code_cli = find_code_cli()
    print("code CLI:", code_cli)
    t0 = time.perf_counter()
    installed, source = load_installed(code_cli)
    dt = (time.perf_counter() - t0) * 1000
    print(f"установлено расширений: {len(installed)}  (источник: {source}, {dt:.0f} мс)")
    mb, nproc = code_memory_mb(code_cli)
    print(f"VS Code сейчас: {mb} МБ, {nproc} процессов"
          if nproc else "VS Code сейчас не запущен")
    selected = {s.strip() for s in selected_csv.split(",") if s.strip()}
    print("выбранные категории:", selected)
    disabled = compute_disabled(installed, idx, selected)
    unknown = [e for e in installed if e not in idx]
    print(f"будет ВКЛючено: {len(installed) - len(disabled)}  |  ВЫКЛючено: {len(disabled)}")
    print(f"~экономия памяти: {estimate_saved_mb(disabled, idx)} МБ")
    print("unknown (не в карте, останутся вкл):", unknown)
    print("--- disabled ---")
    for d in sorted(disabled):
        print("  ", d)
    print("\n--- команда ---")
    print(build_launch_command(code_cli or "code", disabled, str(ROOT), True, True))
