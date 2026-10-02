# -*- coding: utf-8 -*-
"""Глубокие проверки: совместимость (вклады расширений, контекст VS Code),
расширенная уборка и проверка окружения."""

import json
import os
import sqlite3
import time

from launcher import cleanup, cli, compat, envcheck

NO_RULES = {"conflicts": [], "deprecated": []}


def _kinds(issues):
    return sorted((i["kind"], i["ext"]) for i in issues)


# --- совместимость: контекст -------------------------------------------------


def test_ctx_broken_and_vscode_disabled():
    ctx = {
        "broken": {"p.gone": "missing"},
        "vscode_disabled": {"p.lib", "p.off"},
        "quality": "stable",
        "proposals": {},
    }
    man = {"p.app": {"depends": ["p.lib"]}, "p.off": {}}
    issues = compat.check(["p.gone", "p.app", "p.lib", "p.off"], man, rules=NO_RULES, ctx=ctx)
    kinds = _kinds(issues)
    assert ("broken", "p.gone") in kinds
    assert ("dep_vscode_off", "p.app") in kinds
    assert ("vscode_off", "p.off") in kinds
    broken = next(i for i in issues if i["kind"] == "broken")
    assert broken["severity"] == "error" and broken["disable"] == ["p.gone"]


def test_proposed_api_only_on_stable_and_not_allowed():
    man = {"p.exp": {"proposals": ["chatProvider"]}, "p.ok": {"proposals": ["x"]}}
    ctx = {"quality": "stable", "proposals": {"p.ok": ["x"]}}
    assert _kinds(compat.check(["p.exp", "p.ok"], man, rules=NO_RULES, ctx=ctx)) == [
        ("proposed_api", "p.exp")
    ]
    assert compat.check(["p.exp"], man, rules=NO_RULES, ctx={"quality": "insider"}) == []


def test_startup_and_incomplete_pack_are_info():
    man = {"p.star": {"star": True}, "p.pack": {"pack": ["p.star", "p.absent"]}}
    issues = compat.check(["p.star", "p.pack"], man, rules=NO_RULES)
    assert _kinds(issues) == [("pack", "p.pack"), ("startup", "p.star")]
    assert compat.actionable(issues) == []


def test_duplicate_commands_and_debuggers():
    man = {
        "orig.ext": {"commands": ["x.run", "x.stop"], "debuggers": ["xdbg"]},
        "fork.ext": {"commands": ["x.run"], "debuggers": ["xdbg"]},
        # зависящее расширение может переобъявлять команды — это не конфликт
        "addon.ext": {"commands": ["x.stop"], "depends": ["orig.ext"]},
    }
    issues = compat.check(list(man), man, rules=NO_RULES)
    dup = [i for i in issues if i["kind"] == "dup_command"]
    assert len(dup) == 1 and {dup[0]["ext"], *dup[0]["others"]} == {"orig.ext", "fork.ext"} and dup[0]["severity"] == "warning"
    assert [i["kind"] for i in issues if i["kind"] == "dup_debugger"] == ["dup_debugger"]


def test_keybinding_conflict_needs_same_when():
    man = {
        "a.one": {"keybindings": [["Ctrl+Alt+M", "", "a.cmd"]]},
        "b.two": {"keybindings": [["alt+ctrl+m", "", "b.cmd"]]},
        "c.three": {"keybindings": [["ctrl+alt+m", "editorLangId == cpp", "c.cmd"]]},
    }
    kb = [i for i in compat.check(list(man), man, rules=NO_RULES) if i["kind"] == "keybinding"]
    assert len(kb) == 1 and kb[0]["ext"] == "a.one" and "b.two" in kb[0]["others"]
    assert compat.norm_key("Shift+Ctrl+K Ctrl+X") == "ctrl+shift+k ctrl+x"


def test_same_display_name():
    man = {"a.x": {"display": "Prettier"}, "b.x": {"display": "prettier"}}
    assert _kinds(compat.check(["a.x", "b.x"], man, rules=NO_RULES)) == [("same_name", "a.x")]


def test_report_current_section_and_counts():
    man = {"bad.one": {"engine": "^1.999.0"}, "p.star": {"star": True}}
    text = compat.report(["bad.one", "p.star"], man, "1.121.0", rules=NO_RULES, current=["p.star"])
    assert "Ошибок: 1, предупреждений: 0, к сведению: 1." in text
    cur, rest = text.split("ВСЁ УСТАНОВЛЕННОЕ")
    assert "Проблем нет" in cur and "bad.one" in rest


def test_vscode_disabled_from_state_db(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    gs = tmp_path / "Code" / "User" / "globalStorage"
    gs.mkdir(parents=True)
    con = sqlite3.connect(gs / "state.vscdb")
    con.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
    con.execute(
        "INSERT INTO ItemTable VALUES (?, ?)",
        ("extensionsIdentifiers/disabled", json.dumps([{"id": "Pub.Off"}, {"x": 1}])),
    )
    con.commit()
    con.close()
    assert compat.vscode_disabled_extensions("code.cmd") == {"pub.off"}


def test_broken_extensions(tmp_path):
    (tmp_path / "ok-1.0").mkdir()
    (tmp_path / "ok-1.0" / "package.json").write_text('{"name": "ok"}', encoding="utf-8")
    (tmp_path / "bad-1.0").mkdir()
    (tmp_path / "bad-1.0" / "package.json").write_text("{битый", encoding="utf-8")
    (tmp_path / "extensions.json").write_text(
        json.dumps(
            [
                {"identifier": {"id": "p.ok"}, "relativeLocation": "ok-1.0"},
                {"identifier": {"id": "p.bad"}, "relativeLocation": "bad-1.0"},
                {"identifier": {"id": "p.gone"}, "relativeLocation": "gone-1.0"},
                {"identifier": {"id": "p.del"}, "relativeLocation": "del-1.0"},
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / ".obsolete").write_text('{"del-1.0": true}', encoding="utf-8")
    assert compat.broken_extensions(tmp_path) == {"p.bad": "manifest", "p.gone": "missing"}


# --- уборка ------------------------------------------------------------------


def _write(p, data=b"x" * 10):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def _vscode_install(root, versions):
    for name, ver in versions:
        _write(
            root / name / "resources" / "app" / "package.json",
            json.dumps({"version": ver}).encode(),
        )
        _write(
            root / name / "resources" / "app" / "product.json",
            json.dumps({"commit": name + "ffff"}).encode(),
        )
    _write(root / "Code.exe")
    return root / "Code.exe"


def test_old_vscode_versions_never_newest(tmp_path):
    exe = _vscode_install(tmp_path, [("aaaaaaaaaa", "1.120.0"), ("bbbbbbbbbb", "1.121.0")])
    assert cleanup.old_vscode_versions(exe) == [tmp_path / "aaaaaaaaaa"]
    assert cleanup.current_commit(exe) == "bbbbbbbbbbffff"
    single = tmp_path / "single"
    assert cleanup.old_vscode_versions(_vscode_install(single, [("cccccccccc", "1.1.0")])) == []


def test_full_scan_new_kinds(tmp_path):
    ud = tmp_path / "Code"
    local = tmp_path / "Local"
    temp = tmp_path / "Temp"
    ext = tmp_path / "ext"
    ext.mkdir()
    _write(local / "Microsoft" / "vscode-cpptools" / "ipch" / "a" / "b.ipch")
    _write(local / "Microsoft" / "vscode-cpptools" / ("0" * 32) / ".BROWSE.VC.DB")
    _write(local / "Microsoft" / "vscode-cpptools" / "notahash" / "x")
    _write(ud / "Crashpad" / "reports" / "r.dmp")
    _write(ud / "Crashpad" / "settings.dat")
    _write(temp / "vscode-inno-updater-1.log")
    _write(temp / "vscode-stable-user-x64" / "CodeSetup.exe")
    _write(temp / "other.log")
    _write(ud / "User" / "globalStorage" / "gone.ext" / "data")
    _write(ud / "User" / "globalStorage" / "kept.ext" / "data")
    _write(ud / "User" / "globalStorage" / "vscode.git" / "data")
    _write(ud / "User" / "globalStorage" / "storage.json")
    proj = tmp_path / "proj"
    proj.mkdir()
    ws = ud / "User" / "workspaceStorage" / "w1"
    _write(ws / "workspace.json", json.dumps({"folder": proj.as_uri()}).encode())
    _write(ws / "state.vscdb")
    old = time.time() - 200 * 86400
    os.utime(ws / "state.vscdb", (old, old))
    os.utime(ws, (old, old))
    hist = ud / "User" / "History" / "h1"
    _write(
        hist / "entries.json",
        json.dumps({"resource": (tmp_path / "deleted.txt").as_uri()}).encode(),
    )
    items = cleanup.scan(
        ud,
        ext,
        None,
        installed=["kept.ext"],
        builtin={"vscode.git"},
        local_appdata=local,
        temp_dir=temp,
    )
    by = {}
    for i in items:
        by.setdefault(i["kind"], []).append(os.path.basename(i["path"]))
    assert sorted(by["cpptools"]) == sorted(["ipch", "0" * 32])
    assert by["crash"] == ["reports"]
    assert sorted(by["temp"]) == ["vscode-inno-updater-1.log", "vscode-stable-user-x64"]
    assert by["orphan_data"] == ["gone.ext"]
    assert by["workspace_old"] == ["w1"]
    assert by["history"] == ["h1"]
    safe = {i["kind"]: i["safe"] for i in items}
    assert safe["cpptools"] and not safe["orphan_data"] and not safe["history"]
    order = [k for k, _b, _n in cleanup.summarize(items)]
    assert order.index("history") > order.index("crash")  # безопасное сначала


def test_orphans_need_builtin_list(tmp_path):
    _write(tmp_path / "User" / "globalStorage" / "vscode.git" / "d")
    assert cleanup.orphan_extension_data(tmp_path, ["a.b"], set()) == []


def test_cli_cleanup_skips_risky_without_all(monkeypatch, capsys):
    items = [
        {"kind": "cpptools", "path": "C:\\x", "bytes": 10, "note": "", "mtime": 0, "safe": True},
        {"kind": "history", "path": "C:\\y", "bytes": 10, "note": "", "mtime": 0, "safe": False},
    ]
    monkeypatch.setattr(cleanup, "scan_vscode", lambda cli_: items)
    trashed = []
    monkeypatch.setattr(cleanup, "send_to_trash", lambda paths: trashed.extend(paths) or (True, ""))
    monkeypatch.setattr("launcher.vscode.vscode_process_count", lambda c: 0)
    assert cli._cleanup({}, apply=True, as_json=False) == 0
    assert trashed == ["C:\\x"]
    trashed.clear()
    cli._cleanup({}, apply=True, as_json=False, include_all=True)
    assert trashed == ["C:\\x", "C:\\y"]


# --- окружение ----------------------------------------------------------------


def test_all_on_path_and_store_stub(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "tool.exe")
    _write(b / "tool.cmd")
    found = envcheck._all_on_path("tool", f"{a};{b};{tmp_path / 'none'}")
    assert [os.path.basename(f) for f in found] == ["tool.exe", "tool.cmd"]
    assert envcheck.is_store_stub(r"C:\Users\u\AppData\Local\Microsoft\WindowsApps\python.exe")
    assert not envcheck.is_store_stub(r"C:\Python312\python.exe")


def test_toolchain_mix():
    same = [
        {"name": "gcc", "path": "D:\\m\\bin\\gcc.exe", "error": ""},
        {"name": "gdb", "path": "D:\\m\\bin\\gdb.exe", "error": ""},
    ]
    assert envcheck.toolchain_mix(same) == []
    mixed = same + [{"name": "g++", "path": "C:\\w\\bin\\g++.exe", "error": ""}]
    assert envcheck.toolchain_mix(mixed)[0]["severity"] == "warning"


def test_env_var_issues(monkeypatch, tmp_path):
    monkeypatch.setattr(envcheck.env_path, "read_user_env_var", lambda n: "")
    monkeypatch.setattr(envcheck, "_user_env_names", lambda: ["Path", "VSCODE_IPC_HOOK"])
    for var in envcheck.HOME_VARS + ("PYTHONPATH",):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GOROOT", str(tmp_path / "no-such"))
    monkeypatch.setenv("PYTHONHOME", str(tmp_path))
    texts = " ".join(i["text"] for i in envcheck.env_var_issues())
    assert "GOROOT" in texts and "PYTHONHOME" in texts and "VSCODE_IPC_HOOK" in texts


def test_format_lines_smoke():
    rep = {
        "issues": [{"severity": "error", "text": "плохо", "action": None}],
        "vscode": {"version": "1.121.0", "kind": "user"},
        "commands": [
            {
                "name": "git",
                "path": "C:\\g.exe",
                "copies": ["a", "b"],
                "version": "2.0",
                "stub": False,
                "error": "",
            },
            {"name": "go", "path": "", "copies": [], "version": "", "stub": False, "error": ""},
        ],
        "tools": [],
        "disks": [{"drive": "C:\\", "free_gb": 1.0, "total_gb": 100.0}],
    }
    text = "\n".join(envcheck.format_lines(rep))
    assert "ошибок 1" in text and "[ОШИБКА] плохо" in text and "ещё копий в PATH: 1" in text
