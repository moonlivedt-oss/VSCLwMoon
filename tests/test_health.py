# -*- coding: utf-8 -*-
"""Сводка здоровья при старте и исправление переменных окружения."""

from launcher import cleanup, compat, envcheck, health


def test_quick_health_sums(monkeypatch):
    monkeypatch.setattr(
        cleanup,
        "scan_vscode",
        lambda cli: [
            {"kind": "cpptools", "bytes": 300},
            {"kind": "history", "bytes": 20},
        ],
    )
    monkeypatch.setattr("launcher.vscode.read_installed_from_disk", lambda cli: ["a.b"])
    monkeypatch.setattr(
        "launcher.manifests.read_extension_manifests", lambda cli: {"a.b": {"engine": "^9.0.0"}}
    )
    monkeypatch.setattr(compat, "context", lambda cli: {"version": "1.121.0"})
    res = health.quick_health("code.cmd")
    assert res == {
        "cleanup_safe_bytes": 300,
        "cleanup_risky_bytes": 20,
        "compat_errors": 1,
        "compat_warnings": 0,
    }
    assert health.quick_health(None)["compat_errors"] == 0


def test_quick_health_survives_errors(monkeypatch):
    def boom(cli):
        raise OSError("нет")

    monkeypatch.setattr(cleanup, "scan_vscode", boom)
    monkeypatch.setattr("launcher.vscode.read_installed_from_disk", boom)
    assert health.quick_health("code.cmd")["cleanup_safe_bytes"] == 0


def test_size_label():
    assert health.size_label(5 * 1024**3) == "5.0 ГБ"
    assert health.size_label(300 * 1024**2) == "300 МБ"


def test_fixable_env_vars(monkeypatch, tmp_path):
    values = {
        "GOPATH": str(tmp_path / "missing"),
        "GOROOT": str(tmp_path),
        "JAVA_HOME": str(tmp_path / "nojdk"),
        "VSCODE_IPC_HOOK": "x",
        "VSCODE_EXTENSIONS": "D:\\ext",
        "ELECTRON_RUN_AS_NODE": "1",
    }
    monkeypatch.setattr(envcheck.env_path, "read_user_env_var", lambda n: values.get(n, ""))
    monkeypatch.setattr(envcheck, "_user_env_names", lambda: list(values))
    names = [f[0] for f in envcheck.fixable_env_vars()]
    assert names == ["GOPATH", "VSCODE_IPC_HOOK", "ELECTRON_RUN_AS_NODE"]


def test_fix_env_vars_logs_old_values(monkeypatch, tmp_path):
    monkeypatch.setattr("launcher.paths.CONFIG_DIR", tmp_path)
    monkeypatch.setattr(envcheck.env_path, "read_user_env_var", lambda n: "C:\\old")
    deleted = []
    monkeypatch.setattr(
        envcheck.env_path,
        "delete_user_env_var",
        lambda n: (deleted.append(n) or True, f"Переменная {n} удалена."),
    )
    msgs = envcheck.fix_env_vars(["GOPATH"])
    assert deleted == ["GOPATH"] and "GOPATH" in msgs[0]
    assert "GOPATH\tC:\\old" in (tmp_path / "env_history.txt").read_text(encoding="utf-8")
