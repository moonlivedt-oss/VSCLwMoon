# -*- coding: utf-8 -*-
"""lldb из LLVM и Python, который ему нужен: что именно не так и что предложить."""

import pytest

from launcher import cpp


@pytest.fixture
def llvm(tmp_path, monkeypatch):
    """Каталог «LLVM\\bin» с lldb.exe; DLL Python нигде в PATH нет."""
    monkeypatch.setattr(cpp, "terminal_path", lambda: str(tmp_path))
    monkeypatch.setattr(cpp, "which", lambda name: None)

    def make(imports: bytes):
        (tmp_path / "lldb.exe").write_bytes(b"MZ stub")
        (tmp_path / "liblldb.dll").write_bytes(b"\x00" * 64 + imports + b"\x00" * 64)
        return str(tmp_path)

    return make


def _python_at(tmp_path, name: str, dll: str) -> str:
    home = tmp_path / name
    home.mkdir()
    (home / dll).write_bytes(b"")
    return str(home)


def test_dll_name_read_from_liblldb(llvm, tmp_path):
    llvm(b"KERNEL32.dll\x00python311.dll\x00python3.dll\x00")
    assert cpp.lldb_python_dll(str(tmp_path / "lldb.exe")) == "python311.dll"
    llvm(b"PYTHON3.DLL")
    assert cpp.lldb_python_dll(str(tmp_path / "lldb.exe")) == "python3.dll"
    assert cpp.lldb_python_dll(str(tmp_path / "нет" / "lldb.exe")) == ""


def test_stable_abi_offers_to_connect_installed_python(llvm, tmp_path, monkeypatch):
    # Как на машине из отчёта: lldb нужен python3.dll, Python 3.14 стоит, но не в PATH.
    bin_dir = llvm(b"python3.dll")
    home = _python_at(tmp_path, "py314", "python3.dll")
    monkeypatch.setattr(cpp, "python_homes", lambda: [("3.14", home)])
    issue = cpp.lldb_python_issue(bin_dir)
    assert issue and issue["fix"] == "lldbpath:3.14" and home in issue["text"]


def test_offers_install_when_no_python_has_the_dll(llvm, monkeypatch):
    bin_dir = llvm(b"python3.dll")
    monkeypatch.setattr(cpp, "python_homes", lambda: [])
    assert cpp.lldb_python_issue(bin_dir)["fix"] == f"python:{cpp.LLDB_DEFAULT_PYTHON}"
    bin_dir = llvm(b"python310.dll")
    assert cpp.lldb_python_issue(bin_dir)["fix"] == "python:3.10"


def test_no_issue_when_dll_is_reachable_or_lldb_has_no_python(llvm, tmp_path, monkeypatch):
    bin_dir = llvm(b"no python here")
    assert cpp.lldb_python_issue(bin_dir) is None
    bin_dir = llvm(b"python3.dll")
    home = _python_at(tmp_path, "onpath", "python3.dll")
    monkeypatch.setattr(cpp, "terminal_path", lambda: home)  # DLL уже в PATH
    assert cpp.lldb_python_issue(bin_dir) is None


def test_connect_appends_python_folder_to_user_path(monkeypatch):
    added = []
    monkeypatch.setattr(cpp, "python_registered", lambda ver: "C:\\Py314\\")
    monkeypatch.setattr(cpp.env_path, "add_to_user_path", lambda d: (added.append(d) or True, "ok"))
    ok, _msg = cpp.connect_python_to_lldb("3.14")
    assert ok and added == ["C:\\Py314"]
    monkeypatch.setattr(cpp, "python_registered", lambda ver: "")
    assert cpp.connect_python_to_lldb("3.14")[0] is False


def test_install_rejects_bad_version_and_does_not_prepend_path(monkeypatch):
    assert cpp.install_python_for_lldb("3.11 & calc")[0] is False
    from launcher import toolchains as tc

    seen = {}

    def fake(action, pkg, scope, repair):
        seen.update(action=action, id=pkg.winget_id, repair=repair)
        return True, "ok"

    monkeypatch.setattr(tc, "_run_winget", fake)
    monkeypatch.setattr(cpp, "python_registered", lambda ver: "C:\\Py311")
    monkeypatch.setattr(cpp.env_path, "add_to_user_path", lambda d: (True, "ok"))
    ok, _msg = cpp.install_python_for_lldb("3.11")
    assert ok and seen == {"action": "install", "id": "Python.Python.3.11", "repair": False}
