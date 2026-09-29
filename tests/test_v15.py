# -*- coding: utf-8 -*-
"""v1.5: дерево процессов по стекам, уборка, раскладка стеков, eager-метка."""

import json
from pathlib import Path

import pytest

from launcher import categories, cleanup, proctree
from launcher.detect import detect_stacks
from launcher.manifests import _parse_manifest

EXT = r"C:\Users\u\.vscode\extensions"
MB = 1024 * 1024


def _p(pid, ppid, name, cmd="", image="", mb=0):
    return {"pid": pid, "ppid": ppid, "name": name, "cmd": cmd, "image": image, "private": mb * MB}


# --- proctree ---------------------------------------------------------------


def test_ext_folder_in_cmd_and_image():
    cmd = f'"C:\\Code\\Code.exe" "{EXT}\\ms-python.vscode-pylance-2025.1.1\\dist\\server.js"'
    assert proctree.ext_folder_in(cmd, EXT) == "ms-python.vscode-pylance-2025.1.1"
    img = EXT.replace("\\", "/") + "/ms-vscode.cpptools-1.2.3-win32-x64/bin/cpptools.exe"
    assert proctree.ext_folder_in(img, EXT) == "ms-vscode.cpptools-1.2.3-win32-x64"
    assert proctree.ext_folder_in(r"C:\Windows\System32\conhost.exe", EXT) == ""
    assert proctree.ext_folder_in("anything", "") == ""


def test_attribute_tree_splits_editor_extensions_and_terminal():
    procs = [
        _p(1, 999, "Code.exe", mb=300),  # главный
        _p(2, 1, "Code.exe", mb=500),  # хост расширений
        _p(3, 2, "Code.exe", cmd=f"{EXT}\\ms-python.vscode-pylance-1.0.0\\server.js", mb=320),
        _p(
            4,
            2,
            "cpptools.exe",
            image=f"{EXT}\\ms-vscode.cpptools-1.2.3-win32-x64\\bin\\cpptools.exe",
            mb=200,
        ),
        _p(5, 4, "cpptools-srv.exe", mb=100),  # наследует cpptools
        _p(6, 1, "powershell.exe", mb=80),  # терминал
        _p(7, 6, "python.exe", mb=900),  # запущено в терминале
        _p(8, 999, "explorer.exe", mb=50),  # вне дерева
    ]
    idx = {"ms-python.vscode-pylance": "python", "ms-vscode.cpptools": "cpp"}
    r = proctree.attribute_tree(procs, "Code.exe", EXT, idx)
    assert r["editor_mb"] == 800
    assert r["ext"] == {"ms-vscode.cpptools": 300, "ms-python.vscode-pylance": 320}
    assert r["stacks"] == {"python": 320, "cpp": 300}
    assert r["ext_mb"] == 620
    assert r["total_mb"] == 1420  # терминал не входит
    assert dict(r["other"]) == {"python.exe": 900, "powershell.exe": 80}
    assert r["n"] == 7


def test_attribute_tree_unmapped_and_cycle_safe():
    procs = [
        _p(1, 999, "Code.exe", mb=10),
        _p(2, 1, "x.exe", image=f"{EXT}\\pub.thing-0.1.0\\x.exe", mb=5),
        _p(3, 3, "loop.exe", mb=1),  # сам себе родитель — не в дереве
    ]
    r = proctree.attribute_tree(procs, "Code.exe", EXT, {})
    assert r["stacks"] == {proctree.UNMAPPED: 5}
    assert r["n"] == 2


def test_attribute_tree_no_editor():
    r = proctree.attribute_tree([_p(1, 0, "explorer.exe", mb=5)], "Code.exe", EXT, {})
    assert r["n"] == 0 and r["total_mb"] == 0


# --- cleanup ----------------------------------------------------------------


def test_uri_to_local_path():
    assert str(cleanup.uri_to_local_path("file:///d%3A/proj/x")).replace("\\", "/") == "d:/proj/x"
    assert cleanup.uri_to_local_path("vscode-remote://wsl+Ubuntu/home/u") is None


def test_stale_workspaces(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    st = tmp_path / "ws"
    for name, uri in (
        ("a", live.as_uri()),
        ("b", (tmp_path / "gone").as_uri()),
        ("c", "vscode-remote://ssh-remote+h/home"),
    ):
        d = st / name
        d.mkdir(parents=True)
        (d / "workspace.json").write_text(json.dumps({"folder": uri}), encoding="utf-8")
    (st / "d").mkdir()  # без workspace.json — не трогаем
    assert [p.name for p in cleanup.stale_workspaces(st)] == ["b"]


def _ext(ext_dir, folder, ext_id):
    d = ext_dir / folder
    d.mkdir(parents=True)
    pub, name = ext_id.split(".", 1)
    (d / "package.json").write_text(json.dumps({"publisher": pub, "name": name}), encoding="utf-8")
    (d / "f.bin").write_bytes(b"x" * 10)


def test_old_extension_folders_only_superseded(tmp_path):
    ed = tmp_path / "extensions"
    _ext(ed, "pub.a-1.0.0", "pub.a")
    _ext(ed, "pub.a-2.0.0", "pub.a")  # зарегистрирована эта
    _ext(ed, "local.dev-3.5.0", "local.dev")  # не зарегистрирована — не трогаем
    (ed / "pub.a_data").mkdir()  # данные без package.json
    (ed / "extensions.json").write_text(
        json.dumps([{"identifier": {"id": "pub.a"}, "relativeLocation": "pub.a-2.0.0"}]),
        encoding="utf-8",
    )
    assert [p.name for p in cleanup.old_extension_folders(ed)] == ["pub.a-1.0.0"]


def test_scan_and_summarize(tmp_path):
    ud = tmp_path / "Code"
    (ud / "CachedExtensionVSIXs").mkdir(parents=True)
    (ud / "CachedExtensionVSIXs" / "pub.a-1.0.0").write_bytes(b"x" * 100)
    (ud / "GPUCache").mkdir()
    (ud / "GPUCache" / "data").write_bytes(b"x" * 50)
    (ud / "Cache").mkdir()  # пустой — не показываем
    for s in ("20260101T1", "20260102T1"):
        (ud / "logs" / s).mkdir(parents=True)
        (ud / "logs" / s / "main.log").write_bytes(b"x" * 5)
    items = cleanup.scan(ud, tmp_path / "noext", None)
    kinds = {i["kind"] for i in items}
    assert kinds == {"vsix", "engine", "logs"}
    assert [i["path"] for i in items if i["kind"] == "logs"] == [str(ud / "logs" / "20260101T1")]
    assert cleanup.summarize(items)[0] == ("vsix", 100, 1)


# --- раскладка стеков -------------------------------------------------------


def test_categories_have_no_duplicates_and_weights():
    cats, err = categories.load_categories()
    assert not err
    assert categories.find_duplicate_extensions(cats) == {}
    for key in cats["categories"]:
        assert key in categories.WEIGHT, key


def test_eager_heavy_extensions_left_core():
    cats, _err = categories.load_categories()
    core = set(cats["always_on"]["extensions"])
    for moved in (
        "streetsidesoftware.code-spell-checker",
        "seyyedkhandon.qpack",
        "formulahendry.code-runner",
        "brandonkirbyson.vscode-animations",
    ):
        assert moved not in core


def test_dev_extensions_stay_unmapped():
    # Расширения, которые пользователь сам разрабатывает, в карту не заносим.
    idx = categories.build_ext_index(categories.load_categories()[0])
    for dev in (
        "moonlivedt.cpp-docs-panel",
        "moonlivedt.moon-core",
        "subframe7536.custom-ui-style",
    ):
        assert dev not in idx


def test_detect_markdown_suggests_spell_and_sqlite(tmp_path):
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    (tmp_path / "data.sqlite").write_bytes(b"")
    found = detect_stacks(tmp_path)
    assert {"markdown", "spell", "sqlite"} <= found


# --- eager ------------------------------------------------------------------


def test_manifest_eager_flag(tmp_path):
    def mk(acts, main=True):
        f = tmp_path / "package.json"
        data = {"publisher": "p", "name": "n", "activationEvents": acts}
        if main:
            data["main"] = "./out.js"
        f.write_text(json.dumps(data), encoding="utf-8")
        return _parse_manifest(f)

    assert mk(["onStartupFinished"])["eager"] is True
    assert mk(["*"])["eager"] is True
    assert mk(["onLanguage:python"])["eager"] is False
    assert mk(["*"], main=False)["eager"] is False  # без кода — нечего активировать


def test_stale_workspaces_skips_disconnected_drive(tmp_path):
    """Проект на отключённом диске — не «удалённый»: диск вернётся."""
    import string
    free = next((c for c in reversed(string.ascii_uppercase)
                 if not Path(f"{c}:\\").exists()), None)
    if free is None:
        pytest.skip("все буквы дисков заняты")
    st = tmp_path / "ws"
    d = st / "usb"
    d.mkdir(parents=True)
    uri = f"file:///{free.lower()}%3A/proj"
    (d / "workspace.json").write_text(json.dumps({"folder": uri}), encoding="utf-8")
    assert cleanup.stale_workspaces(st) == []
