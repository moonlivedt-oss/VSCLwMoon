# -*- coding: utf-8 -*-
"""Тесты Фазы 2: экспорт .code-profile (#4), выбор установки VS Code (#18),
мастер раскладки (#6), автоскачивание обновления (#10).

Запуск:  python -m pytest tests/test_phase2.py
"""
import json
from pathlib import Path

from launcher import core, updates
from launcher.profile_export import (
    build_profile_extensions, build_profile_template, profile_file_content,
)


# --- #4: экспорт .code-profile ---------------------------------------------

def test_build_profile_extensions_shape_and_display():
    manifests = {"ms-python.python": {"display": "Python"}}
    got = build_profile_extensions(["ms-python.python", "redhat.java"], manifests)
    # id есть в манифесте -> displayName из него; нет -> сам id.
    assert {"identifier": {"id": "ms-python.python"}, "displayName": "Python"} in got
    assert {"identifier": {"id": "redhat.java"}, "displayName": "redhat.java"} in got


def test_build_profile_extensions_dedup_sort_and_validation():
    got = build_profile_extensions(
        ["B.b", "A.a", "A.a", "not a valid id", "также.невалид"])
    ids = [e["identifier"]["id"] for e in got]
    assert ids == ["a.a", "b.b"]        # нижний регистр, отсортировано, без дублей
    assert all("." in i for i in ids)   # мусорные id отброшены


def test_build_profile_template_is_stringified_json():
    tpl = build_profile_template("My Stacks", ["a.a"], {"a.a": {"display": "A"}})
    assert tpl["name"] == "My Stacks"
    # Контентные поля — СТРОКИ со stringified JSON (как в родном экспорте VS Code).
    assert isinstance(tpl["extensions"], str)
    parsed = json.loads(tpl["extensions"])
    assert parsed == [{"identifier": {"id": "a.a"}, "displayName": "A"}]
    assert "settings" not in tpl        # settings не передавали — поля нет


def test_build_profile_template_includes_settings_when_given():
    tpl = build_profile_template("P", ["a.a"], settings={"editor.formatOnSave": True})
    assert isinstance(tpl["settings"], str)
    assert json.loads(tpl["settings"]) == {"editor.formatOnSave": True}


def test_build_profile_template_sanitizes_name():
    tpl = build_profile_template("  \n\t  ", [])
    assert tpl["name"] == "VS Code Launcher"   # пустое/мусорное имя -> дефолт


def test_profile_file_content_roundtrips():
    content = profile_file_content("Web", ["dbaeumer.vscode-eslint"])
    doc = json.loads(content)
    assert doc["name"] == "Web"
    assert json.loads(doc["extensions"])[0]["identifier"]["id"] == "dbaeumer.vscode-eslint"


def test_profile_export_reexported_from_core():
    assert core.profile_file_content("X", []).strip().startswith("{")


# --- #18: перечисление установок VS Code -----------------------------------

def test_list_code_installs_finds_stable_in_localappdata(tmp_path, monkeypatch):
    # Создаём стандартную стабильную установку под LOCALAPPDATA.
    cli = tmp_path / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd"
    cli.parent.mkdir(parents=True)
    cli.write_text("", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(core.vscode, "which", lambda name: None, raising=False)
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: None)

    installs = core.list_code_installs()
    paths = [p for _label, p in installs]
    assert str(cli) in paths


def test_list_code_installs_dedups_path(tmp_path, monkeypatch):
    cli = tmp_path / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd"
    cli.parent.mkdir(parents=True)
    cli.write_text("", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # which возвращает тот же путь -> не должен задвоиться.
    import shutil
    monkeypatch.setattr(shutil, "which",
                        lambda name: str(cli) if name == "code" else None)
    installs = core.list_code_installs()
    paths = [p.lower() for _label, p in installs]
    assert paths.count(str(cli).lower()) == 1


# --- #6: оверлей раскладки (build_ext_index) --------------------------------

def _cats():
    return {
        "always_on": {"extensions": ["core.ext"]},
        "categories": {
            "python": {"extensions": ["ms-python.python"]},
            "go": {"extensions": []},
        },
    }


def test_overlay_maps_unknown_to_valid_key():
    idx = core.build_ext_index(_cats(), {"guess.go": "go"})
    assert idx["guess.go"] == "go"
    assert idx["ms-python.python"] == "python"   # карта не пострадала


def test_overlay_ignores_invalid_key():
    # 'nosuch' нет среди категорий -> предложение отбрасывается.
    idx = core.build_ext_index(_cats(), {"x.y": "nosuch"})
    assert "x.y" not in idx


def test_overlay_never_overrides_existing_mapping():
    # Расширение уже в карте (python) -> оверлей его не перетирает на go.
    idx = core.build_ext_index(_cats(), {"ms-python.python": "go"})
    assert idx["ms-python.python"] == "python"


def test_overlay_none_is_noop():
    assert core.build_ext_index(_cats()) == core.build_ext_index(_cats(), None)


# --- #10: автоскачивание и применение обновления ----------------------------

def test_parse_release_info_picks_exe_and_sha():
    data = {
        "tag_name": "v2.0.0",
        "assets": [
            {"name": "VSCodeLauncher.exe",
             "browser_download_url": "https://x/exe"},
            {"name": "VSCodeLauncher.exe.sha256",
             "browser_download_url": "https://x/sha"},
            {"name": "notes.txt", "browser_download_url": "https://x/txt"},
        ],
    }
    info = updates.parse_release_info(data)
    assert info == {"tag": "v2.0.0", "exe_url": "https://x/exe",
                    "sha256_url": "https://x/sha"}


def test_parse_release_info_none_without_exe():
    assert updates.parse_release_info({"tag_name": "v1", "assets": []}) is None


def test_parse_sha256_text_variants():
    h = "a" * 64
    assert updates.parse_sha256_text(h) == h
    assert updates.parse_sha256_text(f"{h.upper()}  VSCodeLauncher.exe") == h
    assert updates.parse_sha256_text("no hash here") is None


def test_sha256_of_file(tmp_path):
    import hashlib
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello world")
    assert updates.sha256_of(p) == hashlib.sha256(b"hello world").hexdigest()


def test_build_update_swap_bat_contains_paths_and_wait():
    bat = updates.build_update_swap_bat(r"C:\app\VSCodeLauncher.exe",
                                        r"C:\app\new.exe", "VSCodeLauncher.exe")
    assert "VSCodeLauncher.exe" in bat
    assert r"C:\app\new.exe" in bat
    assert ":wait" in bat and "goto wait" in bat
    assert "start " in bat and "del " in bat


class _FakeResp:
    def __init__(self, data: bytes):
        self._data = data
        self.headers = {}
    def read(self, *a):
        return self._data
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def test_download_and_verify_matching_sha(tmp_path, monkeypatch):
    import hashlib
    payload = b"new-exe-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    dest = tmp_path / "new.exe"

    monkeypatch.setattr(updates, "download_file",
                        lambda url, d, timeout=60.0, progress=None: Path(d).write_bytes(payload))
    monkeypatch.setattr(updates.urllib.request, "urlopen",
                        lambda req, timeout=0: _FakeResp(digest.encode()))
    ok, msg = updates.download_and_verify(
        {"exe_url": "http://x/exe", "sha256_url": "http://x/sha"}, dest)
    assert ok is True and dest.exists()


def test_download_and_verify_bad_sha_removes_file(tmp_path, monkeypatch):
    dest = tmp_path / "new.exe"
    monkeypatch.setattr(updates, "download_file",
                        lambda url, d, timeout=60.0, progress=None: Path(d).write_bytes(b"x"))
    monkeypatch.setattr(updates.urllib.request, "urlopen",
                        lambda req, timeout=0: _FakeResp(b"f" * 64))
    ok, msg = updates.download_and_verify(
        {"exe_url": "http://x/exe", "sha256_url": "http://x/sha"}, dest)
    assert ok is False and not dest.exists()   # битый файл удалён
