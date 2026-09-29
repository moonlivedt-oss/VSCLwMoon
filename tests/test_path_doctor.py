# -*- coding: utf-8 -*-
"""Умная починка PATH на искусственных каталогах: проблемы, план, предпросмотр."""

import os

import pytest

from launcher import cpp, env_path
from launcher import path_doctor as pd


@pytest.fixture
def fs(tmp_path, monkeypatch):
    """Фабрика каталогов с «исполняемыми» файлами и своим System32."""
    root = tmp_path
    sysroot = root / "Windows"
    (sysroot / "System32").mkdir(parents=True)
    for t in ("find", "sort", "where"):
        (sysroot / "System32" / f"{t}.exe").write_bytes(b"")
    monkeypatch.setenv("SystemRoot", str(sysroot))
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    monkeypatch.setattr(env_path, "reserve_dirs", lambda: ())
    monkeypatch.setattr(pd, "_python_launcher_hint", lambda resolved: None)

    def make(name, *tools):
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        for t in tools:
            (d / f"{t}.exe").write_bytes(b"")
        return str(d)

    make.sys32 = str(sysroot / "System32")
    return make


def _kinds(rep):
    return sorted(i.kind for i in rep.issues)


def _all(rep):
    return {i.id for i in rep.issues if i.fixable}


def test_clean_path_has_no_issues(fs):
    a = fs("a", "git")
    rep = pd.analyze(fs.sys32, a, probe_versions=False)
    assert rep.issues == []


def test_junk_detected_and_removed(fs, tmp_path):
    a = fs("a", "git")
    missing = str(tmp_path / "gone")
    user = ";".join([a, a, "", missing, f'"{a}"', "%NO_SUCH_VAR_X%\\bin", fs.sys32])
    rep = pd.analyze(fs.sys32, user, probe_versions=False)
    kinds = _kinds(rep)
    assert kinds.count("dup") == 2  # повтор и тот же путь в кавычках
    assert {"empty", "missing", "unresolved", "cross_dup"} <= set(kinds)
    pv = pd.preview(rep, _all(rep))
    assert pv["user"] == a
    assert not pv["lost"] and not pv["machine_changed"]


def test_trailing_slash_is_not_a_problem(fs):
    a = fs("a", "git")
    rep = pd.analyze(fs.sys32, a + "\\", probe_versions=False)
    assert rep.issues == []


def test_quoted_entry_is_tidied(fs):
    a = fs("a", "git")
    rep = pd.analyze(fs.sys32, f' "{a}" ', probe_versions=False)
    assert _kinds(rep) == ["tidy"]
    assert pd.preview(rep, _all(rep))["user"] == a


def test_offline_drive_is_kept(fs, monkeypatch):
    rep = pd.analyze(fs.sys32, r"Q:\nowhere\bin", probe_versions=False)
    if os.path.isdir("Q:\\"):
        pytest.skip("диск Q: существует на этой машине")
    iss = rep.issues[0]
    assert iss.kind == "offline" and not iss.fixable


def test_store_alias_moved_behind_real_python(fs):
    stub = fs("Microsoft/WindowsApps", "python", "winget")
    real = fs("Python310", "python", "pip")
    rep = pd.analyze(fs.sys32, ";".join([stub, real]), probe_versions=False)
    iss = next(i for i in rep.issues if i.kind == "store_alias")
    pv = pd.preview(rep, {iss.id})
    assert pv["user"].split(";") == [real, stub]
    assert ("python", os.path.join(stub, "python.exe"), os.path.join(real, "python.exe")) in pv[
        "changed"
    ]
    assert not pv["lost"]  # winget остаётся


def test_toolchain_shadowing_python(fs):
    """Ровно случай пользователя: MSYS2 ucrt64 с python стоит раньше Python310."""
    tc = fs("msys64/ucrt64/bin", "g++", "gcc", "python", "cmake")
    py = fs("Python310", "python")
    other = fs("cargo", "cargo")
    rep = pd.analyze(fs.sys32, ";".join([tc, other, py]), probe_versions=False)
    iss = next(i for i in rep.issues if i.kind == "toolchain_shadow")
    assert iss.selected and "python" in iss.title
    pv = pd.preview(rep, {iss.id})
    assert pv["user"].split(";") == [other, py, tc]
    after = pd.resolve_all(pv["user"].split(";"))
    assert after["python"] == os.path.join(py, "python.exe")
    assert after["g++"] == os.path.join(tc, "g++.exe")


def test_system32_shadow_needs_admin(fs):
    git_usr = fs("Git/usr/bin", "find", "sort", "bash")
    machine = ";".join([git_usr, fs.sys32])
    rep = pd.analyze(machine, "", probe_versions=False)
    iss = next(i for i in rep.issues if i.kind == "shadow_system")
    assert iss.admin and "find" in iss.detail
    pv = pd.preview(rep, {iss.id})
    assert pv["machine"].split(";") == [fs.sys32, git_usr] and pv["machine_changed"]


def test_missing_system32_is_error(fs):
    a = fs("a", "git")
    rep = pd.analyze(a, "", probe_versions=False)
    iss = next(i for i in rep.issues if i.kind == "no_system32")
    assert iss.level == "error"
    assert pd.preview(rep, {iss.id})["machine"].startswith("%SystemRoot%")


def test_gcc_mix_demotes_second(fs):
    a = fs("msys", "g++", "gcc")
    b = fs("mingw", "g++", "gcc", "cmake")
    rep = pd.analyze(fs.sys32, ";".join([a, b]), probe_versions=False)
    iss = next(i for i in rep.issues if i.kind == "gcc_mix")
    assert pd.preview(rep, {iss.id})["user"].split(";") == [a, b]  # уже в конце


def test_reserve_dirs_not_dead(fs, tmp_path, monkeypatch):
    gobin = str(tmp_path / "go" / "bin")
    monkeypatch.setattr(env_path, "reserve_dirs", lambda: (gobin,))
    rep = pd.analyze(fs.sys32, gobin, probe_versions=False)
    assert rep.issues == []


def test_compact_uses_variables(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\x\AppData\Local")
    assert pd.compact(r"C:\Users\x\AppData\Local\Programs\Git") == r"%LOCALAPPDATA%\Programs\Git"
    assert pd.compact(r"D:\tools") == r"D:\tools"


def test_unselected_hint_not_applied(fs):
    a = fs("a", "git")
    rep = pd.analyze(fs.sys32, a, probe_versions=False)
    assert pd.preview(rep, set())["user_changed"] is False


def test_backups_list_and_restore(tmp_path, monkeypatch):
    from launcher import paths

    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path)
    (tmp_path / "path_backup_20260101_101010.txt").write_text("A;B", encoding="utf-8")
    (tmp_path / "machine_path_backup_20260202_202020.txt").write_text("M", encoding="utf-8")
    bk = pd.list_backups()
    assert [b["scope"] for b in bk] == ["machine", "user"]
    written = {}
    monkeypatch.setattr(env_path, "read_user_path", lambda: "CUR")
    monkeypatch.setattr(env_path, "_backup_path", lambda v, s: None)
    monkeypatch.setattr(env_path, "_write_user_path", lambda v: written.setdefault("user", v))
    monkeypatch.setattr(env_path, "_broadcast_env_change", lambda: None)
    monkeypatch.setattr(env_path, "refresh_process_path_from_registry", lambda: False)
    ok, _msg = pd.restore_backup(bk[1]["file"])
    assert ok and written["user"] == "A;B"


def test_cpp_fix_keeps_toolchain_behind_python(tmp_path):
    """Основной GCC встаёт только перед конкурентом, а не в начало PATH."""

    def d(name, *files):
        p = tmp_path / name
        p.mkdir()
        for f in files:
            (p / f).write_bytes(b"")
        return str(p)

    py = d("py", "python.exe")
    msys = d("msys", "g++.exe", "python.exe")
    mingw = d("mingw", "g++.exe", "cmake.exe")
    plan = cpp.path_fix_plan(msys, "remove", user_path=";".join([py, msys, mingw]), machine_path="")
    assert plan["user_new"].split(";") == [py, msys]
