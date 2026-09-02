# -*- coding: utf-8 -*-
"""Тесты Фазы 3 (тулчейны): JSON-каталог (#6), выбор версии (#4),
перечитывание PATH из реестра (#1), менеджеры версий (#7), флаги winget по
версии (#9), установка с правами админа (#10).

Запуск:  python -m pytest tests/test_phase3.py
"""
import json

from launcher import env_path
from launcher import toolchains as tc
from launcher import paths


# --- #6: JSON-каталог -------------------------------------------------------

def _write_catalog(tmp_path, data) -> None:
    (tmp_path / "toolchains.json").write_text(
        json.dumps(data), encoding="utf-8")


def test_load_toolchains_from_json(tmp_path, monkeypatch):
    data = {"toolchains": {
        "python": {"title": "Python", "note": "n", "packages": [
            {"winget_id": "Python.Python.3.13", "title": "Python 3.13",
             "probe": ["python", "pip"]}]},
    }}
    _write_catalog(tmp_path, data)
    monkeypatch.setattr(paths, "TOOLCHAINS_FILE", tmp_path / "toolchains.json")
    chains = tc.load_toolchains()
    assert set(chains) == {"python"}
    assert chains["python"].packages[0].winget_id == "Python.Python.3.13"


def test_load_toolchains_skips_invalid_packages(tmp_path, monkeypatch):
    data = {"toolchains": {
        "x": {"title": "X", "packages": [
            {"winget_id": "evil;calc", "title": "bad", "probe": ["x"]},   # id инъекция
            {"winget_id": "Good.Tool", "title": "ok", "probe": ["good"]},
        ]},
        "empty": {"title": "E", "packages": [
            {"winget_id": "no.probe", "title": "np", "probe": []}]},       # без probe
    }}
    _write_catalog(tmp_path, data)
    monkeypatch.setattr(paths, "TOOLCHAINS_FILE", tmp_path / "toolchains.json")
    chains = tc.load_toolchains()
    assert list(chains["x"].packages)[0].winget_id == "Good.Tool"   # битый пропущен
    assert len(chains["x"].packages) == 1
    assert "empty" not in chains          # тулчейн без валидных пакетов выкинут


def test_load_toolchains_fallback_on_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "TOOLCHAINS_FILE", tmp_path / "nope.json")
    chains = tc.load_toolchains()
    assert "python" in chains and "git" in chains   # встроенный фолбэк


def test_shipped_catalog_has_new_languages():
    # #2: языки, добавленные в поставку.
    for key in ("php", "terraform", "docker", "lua", "deno", "bun", "zig"):
        assert key in tc.TOOLCHAINS, key


def test_shipped_catalog_ids_valid():
    for chain in tc.TOOLCHAINS.values():
        for pkg in chain.packages:
            assert tc.valid_winget_id(pkg.winget_id), pkg.winget_id
            for vid, _t in pkg.versions:
                assert tc.valid_winget_id(vid), vid


# --- #4: выбор версии -------------------------------------------------------

def test_with_version_switches_id_and_title():
    py = tc.get_toolchain("python").packages[0]
    v = py.with_version("Python.Python.3.12")
    assert v.winget_id == "Python.Python.3.12"
    assert "3.12" in v.title
    assert v.probe == py.probe   # остальное неизменно


def test_with_version_rejects_unknown_id():
    py = tc.get_toolchain("python").packages[0]
    # id не из списка versions -> не подменяем (защита от произвольной подстановки).
    assert py.with_version("Attacker.Package").winget_id == py.winget_id


# --- #9: флаги winget по версии --------------------------------------------

def test_parse_winget_version():
    assert tc._parse_winget_version("v1.29.290") == (1, 29, 290)
    assert tc._parse_winget_version("v1.3.2431") == (1, 3, 2431)
    assert tc._parse_winget_version(None) == (0,)
    assert tc._parse_winget_version("junk") == (0,)


def test_disable_interactivity_gate(monkeypatch):
    monkeypatch.setattr(tc, "winget_version", lambda: "v1.29.290")
    assert tc.winget_supports_disable_interactivity() is True
    monkeypatch.setattr(tc, "winget_version", lambda: "v1.3.2431")
    assert tc.winget_supports_disable_interactivity() is False


# --- #7: менеджеры версий ---------------------------------------------------

def test_detected_managers_for_node(monkeypatch):
    monkeypatch.setattr(tc, "which", lambda e: "C:/nvm/nvm.exe" if e == "nvm" else None)
    monkeypatch.delenv("NVM_HOME", raising=False)
    monkeypatch.delenv("FNM_DIR", raising=False)
    monkeypatch.delenv("VOLTA_HOME", raising=False)
    assert "nvm-windows" in tc.detected_managers_for("web")
    assert tc.detected_managers_for("python") == []


def test_manager_warning_via_env(monkeypatch):
    monkeypatch.setattr(tc, "which", lambda e: None)
    monkeypatch.setenv("PYENV", r"C:\Users\me\.pyenv")
    warn = tc.manager_warning_for("python")
    assert "pyenv-win" in warn and "PATH" in warn


# --- #1: перечитать PATH из реестра ----------------------------------------

def test_refresh_process_path_adds_registry_dirs(monkeypatch):
    monkeypatch.setattr(env_path, "read_machine_path", lambda: r"C:\sys\bin")
    monkeypatch.setattr(env_path, "read_user_path", lambda: r"C:\Users\me\tool\bin")
    monkeypatch.setenv("PATH", r"C:\existing")
    changed = env_path.refresh_process_path_from_registry()
    assert changed is True
    import os
    assert env_path.contains_dir(os.environ["PATH"], r"C:\Users\me\tool\bin")
    assert env_path.contains_dir(os.environ["PATH"], r"C:\existing")   # старое не потеряли


def test_refresh_process_path_noop_when_all_present(monkeypatch):
    monkeypatch.setattr(env_path, "read_machine_path", lambda: r"C:\a")
    monkeypatch.setattr(env_path, "read_user_path", lambda: "")
    monkeypatch.setenv("PATH", r"C:\a")
    assert env_path.refresh_process_path_from_registry() is False


# --- #10: установка с правами админа (без реального winget) ------------------

def test_install_elevated_without_winget(monkeypatch):
    monkeypatch.setattr(tc, "winget_path", lambda: None)
    pkg = tc.get_toolchain("dotnet").packages[0]
    ok, msg = tc.install_package_elevated(pkg)
    assert not ok and "winget" in msg.lower()


def test_install_elevated_rejects_bad_id(monkeypatch):
    monkeypatch.setattr(tc, "winget_path", lambda: "C:/winget.exe")
    bad = tc.Package("evil;calc", "Evil", ("evil",))
    ok, msg = tc.install_package_elevated(bad)
    assert not ok and "id" in msg.lower()


# --- #5: что обновить -------------------------------------------------------

def test_list_upgradable_ids_parses_output(monkeypatch):
    monkeypatch.setattr(tc, "winget_path", lambda: "C:/winget.exe")
    monkeypatch.setattr(tc, "winget_supports_disable_interactivity", lambda: True)

    class _R:
        returncode = 0
        stdout = ("Name        Id                    Version  Available\n"
                  "-----------------------------------------------------\n"
                  "Go          GoLang.Go             1.22.0   1.23.0\n"
                  "Something   Other.Thing           1.0      2.0\n")
        stderr = ""
    monkeypatch.setattr(tc.subprocess, "run", lambda *a, **k: _R())
    ids = tc.list_upgradable_ids()
    assert "GoLang.Go" in ids          # наш каталог
    assert "Other.Thing" not in ids    # не наш пакет игнорируем


def test_outdated_packages_filters_installed(monkeypatch):
    monkeypatch.setattr(tc, "package_installed", lambda pkg: pkg.winget_id == "GoLang.Go")
    monkeypatch.setattr(tc, "package_status",
                        lambda pkg: {"installed": True, "version": "go1.22"})
    rows = tc.outdated_packages(upgradable={"GoLang.Go"})
    assert len(rows) == 1 and rows[0]["package"].winget_id == "GoLang.Go"


def test_list_upgradable_without_winget(monkeypatch):
    monkeypatch.setattr(tc, "winget_path", lambda: None)
    assert tc.list_upgradable_ids() == set()


# --- #8: доктор окружения ---------------------------------------------------

def test_path_health_flags_dupes_and_missing(tmp_path):
    good = tmp_path / "bin"
    good.mkdir()
    s = f"{good}{__import__('os').pathsep}{good}{__import__('os').pathsep}C:\\nope\\zzz12345"
    h = env_path.path_health(s)
    assert h["count"] == 3
    assert len(h["duplicates"]) == 1          # второй good — дубликат
    assert any("zzz12345" in m for m in h["missing"])


def test_java_home_health(monkeypatch, tmp_path):
    monkeypatch.delenv("JAVA_HOME", raising=False)
    assert tc._java_home_health()["set"] is False
    # JAVA_HOME задан, но не JDK
    monkeypatch.setenv("JAVA_HOME", str(tmp_path))
    r = tc._java_home_health()
    assert r["set"] is True and r["ok"] is False
    # настоящий JDK-layout
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "java.exe").write_text("")
    assert tc._java_home_health()["ok"] is True


def test_environment_report_structure(monkeypatch):
    monkeypatch.setattr(tc, "package_status",
                        lambda pkg: {"installed": pkg.winget_id == "GoLang.Go",
                                     "version": "go1.22"})
    monkeypatch.setattr(tc, "winget_version", lambda: "v1.29")
    rep = tc.environment_report()
    assert "tools" in rep and "path" in rep and "java_home" in rep
    assert any(t["key"] == "go" for t in rep["tools"])
