# -*- coding: utf-8 -*-
"""Тесты установки тулчейнов и управления PATH (без winget и без реестра).

Всё, что стучится наружу (winget, реестр, which), подменяется monkeypatch —
проверяем только чистую логику: валидацию id, целостность каталога,
идемпотентность PATH и ветвления install_package.

Запуск:  python -m pytest tests/test_toolchains.py
"""
import os

import pytest

from launcher import env_path, toolchains as tc


# --- валидатор id winget ---------------------------------------------------

def test_valid_winget_id_accepts_real_ids():
    assert tc.valid_winget_id("EclipseAdoptium.Temurin.21.JDK")
    assert tc.valid_winget_id("BrechtSanders.WinLibs.POSIX.UCRT")
    assert tc.valid_winget_id("Microsoft.DotNet.SDK.8")


@pytest.mark.parametrize("bad", [
    "", "foo bar", "foo;calc", 'foo"&calc', "foo|bar", "foo\ncalc",
    "-flag", ".leadingdot", "foo/bar",
])
def test_valid_winget_id_rejects_injection(bad):
    assert not tc.valid_winget_id(bad)


# --- целостность каталога --------------------------------------------------

def test_catalog_ids_are_all_valid_and_probes_present():
    for key, chain in tc.TOOLCHAINS.items():
        assert chain.key == key
        assert chain.packages, f"{key}: пустой список пакетов"
        for pkg in chain.packages:
            assert tc.valid_winget_id(pkg.winget_id), pkg.winget_id
            assert pkg.probe, f"{pkg.winget_id}: нет probe-бинарей"
            assert all(isinstance(e, str) and e for e in pkg.probe)


def test_catalog_keys_match_known_stack_keys():
    # Тулчейн, чей ключ совпадает со стеком (detect.py), связывает «обнаружен
    # стек» с «поставить его тулчейн». Часть тулчейнов — просто доступные к
    # установке инструменты без стека (deno/bun/zig): их auto-detect по папке
    # не предлагает, но поставить можно.
    from launcher import detect
    stack_keys = set(detect.FILENAME_MARKERS.values()) | set(detect.SUFFIX_MARKERS.values())
    stack_keys.add("git")   # git детектится по каталогу .git, а не по маркеру файла
    EXTRA = {"deno", "bun", "zig"}   # внестековые, но устанавливаемые
    for key in tc.TOOLCHAINS:
        assert key in stack_keys or key in EXTRA, \
            f"тулчейн {key!r} не соответствует ни стеку, ни списку внестековых"


def test_get_toolchain_and_keys():
    assert tc.get_toolchain("java").title == "Java (JDK)"
    assert tc.get_toolchain("nope") is None
    assert "cpp" in tc.toolchain_keys()


# --- статус пакета (which/probe подменяются) -------------------------------

def test_package_installed_uses_which(monkeypatch):
    pkg = tc.get_toolchain("go").packages[0]   # probe ("go",)
    monkeypatch.setattr(tc, "which", lambda e: "C:/go/bin/go.exe" if e == "go" else None)
    assert tc.package_installed(pkg)
    monkeypatch.setattr(tc, "which", lambda e: None)
    assert not tc.package_installed(pkg)


def test_missing_required_skips_optional(monkeypatch):
    # Ничего не установлено: cpp должен вернуть только обязательный компилятор,
    # а CMake/LLVM (optional) — не попадают в «обязательно поставить».
    monkeypatch.setattr(tc, "which", lambda e: None)
    missing = tc.missing_required("cpp")
    assert [p.winget_id for p in missing] == ["BrechtSanders.WinLibs.POSIX.UCRT"]


# --- install_package: ветвление без реального winget -----------------------

def test_install_package_without_winget(monkeypatch):
    monkeypatch.setattr(tc, "winget_path", lambda: None)
    pkg = tc.get_toolchain("go").packages[0]
    ok, msg = tc.install_package(pkg)
    assert not ok and "winget" in msg.lower()


def test_install_package_rejects_bad_id(monkeypatch):
    monkeypatch.setattr(tc, "winget_path", lambda: "C:/winget.exe")
    bad = tc.Package("evil;calc", "Evil", ("evil",))
    ok, msg = tc.install_package(bad)
    assert not ok and "id" in msg.lower()


def test_install_package_success_triggers_path_repair(monkeypatch):
    monkeypatch.setattr(tc, "winget_path", lambda: "C:/winget.exe")

    class _R:
        returncode = 0
        stdout = "Successfully installed"
        stderr = ""
    monkeypatch.setattr(tc.subprocess, "run", lambda *a, **k: _R())
    called = {}
    # probe всё ещё «не видит» бинарь → должен пойти в repair_path_for
    monkeypatch.setattr(tc, "package_installed", lambda pkg: False)
    monkeypatch.setattr(tc, "find_bin_dir_for", lambda pkg: None)  # без обхода ФС
    monkeypatch.setattr(tc.env_path, "is_on_path", lambda d: False)

    def _add(d):
        called["dir"] = d
        return True, "ok"
    monkeypatch.setattr(tc.env_path, "add_to_user_path", _add)
    pkg = tc.Package("Some.Tool", "Some", ("sometool",),
                     path_hints=("C:/tools/bin",))
    ok, msg = tc.install_package(pkg)
    assert ok
    assert called["dir"] == "C:/tools/bin"
    assert "PATH" in msg


# --- repair_path_for: автопоиск bin среди распакованных пакетов -------------

def test_find_bin_dir_for_locates_probe(tmp_path, monkeypatch):
    # Имитируем распаковку WinLibs: …/Packages/BrechtSanders…/mingw64/bin/g++.exe
    root = tmp_path / "Packages"
    bind = root / "BrechtSanders.WinLibs.POSIX.UCRT_x" / "mingw64" / "bin"
    bind.mkdir(parents=True)
    (bind / "g++.exe").write_text("")
    monkeypatch.setattr(tc, "_winget_package_roots", lambda: [root])
    pkg = tc.get_toolchain("cpp").packages[0]   # probe g++, gcc, gdb
    assert tc.find_bin_dir_for(pkg) == str(bind)


def test_repair_path_for_adds_found_dir(tmp_path, monkeypatch):
    bind = tmp_path / "bin"
    bind.mkdir()
    monkeypatch.setattr(tc, "package_installed", lambda pkg: False)
    monkeypatch.setattr(tc, "find_bin_dir_for", lambda pkg: str(bind))
    added = {}
    monkeypatch.setattr(tc.env_path, "is_on_path", lambda d: False)
    monkeypatch.setattr(tc.env_path, "add_to_user_path",
                        lambda d: (added.setdefault("d", d), (True, "ok"))[1])
    pkg = tc.Package("Some.Tool", "Some", ("sometool",))
    note = tc.repair_path_for(pkg)
    assert added["d"] == str(bind)
    assert "PATH" in note


# --- env_path: чистая логика (без реестра) ---------------------------------

def test_path_entries_drops_empty():
    s = f"C:/a{os.pathsep}{os.pathsep}C:/b{os.pathsep} "
    assert env_path.path_entries(s) == ["C:/a", "C:/b"]


def test_contains_dir_normalizes_case_and_slashes():
    s = r"C:\Tools\Bin;C:\Other"
    assert env_path.contains_dir(s, "c:/tools/bin/")
    assert env_path.contains_dir(s, r"C:\Tools\Bin")
    assert not env_path.contains_dir(s, r"C:\Nope")


def test_compute_appended_is_idempotent():
    s = r"C:\a;C:\b"
    once = env_path.compute_appended(s, r"C:\c")
    assert once.endswith(r"C:\c")
    twice = env_path.compute_appended(once, r"C:\c")
    assert twice == once   # уже есть — не дублируем


def test_compute_appended_into_empty():
    assert env_path.compute_appended("", r"C:\a") == r"C:\a"


def test_add_to_user_path_rejects_missing_dir():
    ok, msg = env_path.add_to_user_path(r"Z:\definitely\nope\12345")
    assert not ok


def test_compute_removed_drops_matching_entry():
    s = r"C:\a;C:\tools\bin;C:\b"
    out = env_path.compute_removed(s, "c:/tools/bin/")
    assert env_path.path_entries(out) == [r"C:\a", r"C:\b"]
    # нет совпадения — строка не меняется по составу
    same = env_path.compute_removed(s, r"C:\nope")
    assert env_path.path_entries(same) == env_path.path_entries(s)


# --- новые возможности тулчейнов -------------------------------------------

def test_explain_winget_code_known_and_unknown():
    assert "администратор" in tc.explain_winget_code(-1978334967).lower()
    # неизвестный код — берём последнюю осмысленную строку вывода
    assert tc.explain_winget_code(-1, "line1\nreal reason") == "real reason"
    assert "код" in tc.explain_winget_code(-999, "")


def test_settings_for_toolchain_cpp(monkeypatch):
    monkeypatch.setattr(tc, "_compiler_path",
                        lambda exe: r"C:\mingw64\bin\g++.exe" if exe == "g++" else None)
    s = tc.settings_for_toolchain("cpp")
    assert s["C_Cpp.default.compilerPath"].endswith("g++.exe")
    assert s["C_Cpp.default.cppStandard"] == "c++20"
    # для языка без спец-настроек — пусто
    assert tc.settings_for_toolchain("go") == {}


def test_settings_for_toolchain_cpp_empty_when_no_compiler(monkeypatch):
    monkeypatch.setattr(tc, "_compiler_path", lambda exe: None)
    assert tc.settings_for_toolchain("cpp") == {}


def test_missing_toolchains_for_detects_cpp(tmp_path, monkeypatch):
    (tmp_path / "main.cpp").write_text("int main(){}")
    # g++ якобы не установлен → cpp попадает в «не хватает»
    monkeypatch.setattr(tc, "which", lambda e: None)
    missing = tc.missing_toolchains_for(str(tmp_path))
    assert "cpp" in missing


def test_upgrade_and_uninstall_without_winget(monkeypatch):
    monkeypatch.setattr(tc, "winget_path", lambda: None)
    pkg = tc.get_toolchain("cpp").packages[0]
    ok1, _m1 = tc.upgrade_package(pkg)
    ok2, _m2 = tc.uninstall_package(pkg)
    assert not ok1 and not ok2


def test_provides_shown_in_tools():
    pkg = tc.get_toolchain("cpp").packages[0]
    assert "mingw32-make" in pkg.tools()
    # у пакета без provides tools() == probe
    ninja = next(p for p in tc.get_toolchain("cpp").packages if p.winget_id.startswith("Ninja"))
    assert ninja.tools() == ninja.probe
