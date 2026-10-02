# -*- coding: utf-8 -*-
"""«Удалить полностью»: что считается папкой пакета и что удалять нельзя.

Удаление каталога необратимо, поэтому главное здесь — отказы: системные места,
профиль, папка лаунчера и чужие каталоги, в которых лишь лежит одноимённый exe.
"""

import os
from pathlib import Path

import pytest

from launcher import env_path
from launcher import toolchains as tc
from launcher.theme import PALETTE_SETS, build_qss, make_palette

PY = tc.Package(winget_id="Python.Python.3.13", title="Python 3.13", probe=("python",))


@pytest.mark.parametrize(
    "var", ["SystemRoot", "ProgramFiles", "USERPROFILE", "LOCALAPPDATA", "SystemDrive"]
)
def test_system_places_are_never_deletable(var):
    path = os.environ.get(var)
    if not path:
        pytest.skip(f"{var} не задан")
    assert not tc.safe_to_delete(path + ("\\" if path.endswith(":") else ""))


def test_launcher_folder_and_its_parents_are_protected():
    root = Path(tc.__file__).resolve().parent.parent
    assert not tc.safe_to_delete(str(root))
    assert not tc.safe_to_delete(str(root.parent))
    assert not tc.safe_to_delete(
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    )


def test_ordinary_folder_is_deletable_and_missing_is_not(tmp_path):
    d = tmp_path / "Python313"
    d.mkdir()
    assert tc.safe_to_delete(str(d))
    assert not tc.safe_to_delete(str(tmp_path / "нет"))


def _fake_install(tmp_path, monkeypatch, folder: str):
    exe_dir = tmp_path / folder / "bin"
    exe_dir.mkdir(parents=True)
    (exe_dir / "python.exe").write_text("")
    monkeypatch.setattr(tc, "which", lambda name: str(exe_dir / "python.exe"))
    monkeypatch.setattr(tc, "_winget_package_roots", lambda: [])
    monkeypatch.setattr(tc, "winget_has", lambda wid: wid == PY.winget_id)
    return tmp_path / folder


def test_folder_found_by_exe_when_name_matches_package(tmp_path, monkeypatch):
    root = _fake_install(tmp_path, monkeypatch, "Python313")
    assert tc.purge_locations(PY) == [str(root.resolve())]


def test_foreign_folder_with_same_exe_is_left_alone(tmp_path, monkeypatch):
    # python.exe лежит в MSYS2: удаляя Python, стирать MSYS2 нельзя.
    _fake_install(tmp_path, monkeypatch, "ucrt64")
    assert tc.purge_locations(PY) == []


def test_other_version_of_same_language_is_left_alone(tmp_path, monkeypatch):
    # В PATH стоит Python 3.10, а удаляют пакет Python 3.13.
    _fake_install(tmp_path, monkeypatch, "Python310")
    assert tc.purge_locations(PY) == []


def test_folder_not_guessed_when_winget_does_not_know_the_package(tmp_path, monkeypatch):
    _fake_install(tmp_path, monkeypatch, "Python313")
    monkeypatch.setattr(tc, "winget_has", lambda wid: False)
    assert tc.purge_plan(PY)["dirs"] == [] and tc.purge_plan(PY)["ids"] == []


def test_build_words_in_id_do_not_identify_a_folder():
    assert not tc._folder_matches_id("ucrt64", "BrechtSanders.WinLibs.POSIX.UCRT")
    assert tc._folder_matches_id("jdk-25.0.1.8-hotspot", "EclipseAdoptium.Temurin.25.JDK")
    assert not tc._folder_matches_id("jdk-21.0.2", "EclipseAdoptium.Temurin.25.JDK")
    assert tc._folder_matches_id("Go", "GoLang.Go")


def test_winget_package_folder_matched_by_id(tmp_path, monkeypatch):
    pkgs = tmp_path / "Packages"
    mine = pkgs / "Python.Python.3.13_Microsoft.Winget.Source_8wekyb"
    other = pkgs / "Python.Python.3.12_Microsoft.Winget.Source_8wekyb"
    mine.mkdir(parents=True)
    other.mkdir()
    monkeypatch.setattr(tc, "which", lambda name: None)
    monkeypatch.setattr(tc, "winget_has", lambda wid: True)
    monkeypatch.setattr(tc, "_winget_package_roots", lambda: [pkgs])
    assert tc.purge_locations(PY) == [str(mine.resolve())]


def test_purge_removes_folder_and_path_entries(tmp_path, monkeypatch):
    root = _fake_install(tmp_path, monkeypatch, "Python313")
    (root / "Lib").mkdir()
    (root / "Lib" / "x.py").write_text("1")
    entry = str(root / "bin")
    removed: list[str] = []
    monkeypatch.setattr(env_path, "read_user_path", lambda: entry + r";C:\keep")
    monkeypatch.setattr(env_path, "read_machine_path", lambda: r"C:\Windows")
    monkeypatch.setattr(
        env_path, "remove_from_user_path", lambda d: (removed.append(d) or True, "")
    )
    monkeypatch.setattr(env_path, "_broadcast_env_change", lambda: None)
    monkeypatch.setattr(tc, "_run_winget", lambda *a, **k: (True, "ok"))
    monkeypatch.setattr(tc, "_purge_elevated", lambda *a: pytest.fail("UAC не нужен"))
    plan = tc.purge_plan(PY)
    assert plan["dirs"] == [str(root.resolve())] and plan["user_path"] == [entry]
    assert plan["machine_path"] == []
    monkeypatch.setattr(tc, "which", lambda name: None)  # после удаления exe нет
    ok, report = tc.purge_package(PY, plan)
    assert ok, report
    assert not root.exists() and removed == [entry]


def test_declined_uac_is_reported_and_folder_kept(tmp_path, monkeypatch):
    root = _fake_install(tmp_path, monkeypatch, "Python313")
    monkeypatch.setattr(env_path, "read_user_path", lambda: "")
    monkeypatch.setattr(env_path, "read_machine_path", lambda: "")
    monkeypatch.setattr(tc, "_run_winget", lambda *a, **k: (True, "ok"))
    monkeypatch.setattr(tc, "_rmtree", lambda d: False)  # без прав не удалилось
    monkeypatch.setattr(tc, "_purge_elevated", lambda dirs, mp: (False, tc._UAC_DENIED))
    ok, report = tc.purge_package(PY, tc.purge_plan(PY))
    assert not ok and root.exists()
    assert tc._UAC_DENIED in report and "НЕ удалена" in report


def test_catalog_purge_dirs_are_loaded():
    rust = tc.get_toolchain("rust")
    assert rust and any(".cargo" in d for d in rust.packages[0].purge_dirs)


@pytest.mark.parametrize("key", list(PALETTE_SETS))
@pytest.mark.parametrize("mode", ["dark", "light"])
def test_checked_checkbox_has_a_tick_image(key, mode):
    qss = build_qss(make_palette(mode, key))
    part = qss.split("QCheckBox::indicator:checked {", 1)[1].split("}", 1)[0]
    path = part.split('url("', 1)[1].split('"', 1)[0]
    assert Path(path).is_file() and "\\" not in path
