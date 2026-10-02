# -*- coding: utf-8 -*-
"""C++: доктор, порядок в PATH, генерация проекта, план установки, детект."""

import json
import os

import pytest

from launcher import cpp, cpp_project as cp, cpp_setup as cs, detect
from launcher.categories import stack_conflicts
from launcher.config import migrate_config


# --- cpp.py ------------------------------------------------------------------


def test_origin_of_known_layouts():
    assert cpp.origin_of(r"D:\msys64\ucrt64\bin\g++.exe") == "MSYS2 UCRT64"
    assert cpp.origin_of(r"C:\x\g++.exe", "g++ (built by Brecht Sanders, r5) 15.2") == "WinLibs"
    assert cpp.origin_of(r"C:\Program Files\LLVM\bin\clang++.exe") == "LLVM"
    assert cpp.origin_of(r"C:\Program Files\Git\mingw64\bin\libstdc++-6.dll") == "Git for Windows"
    assert cpp.origin_of(r"C:\Strawberry\c\bin\g++.exe") == "Strawberry Perl"


def test_parse_version():
    assert cpp.parse_version("clang version 12.0.0 (x)") == (12, 0, 0)
    assert cpp.parse_version("cmake version 3.31") == (3, 31)
    assert cpp.parse_version("") == ()


def test_explain_exit_entrypoint():
    assert "0xC0000139" in cpp.explain_exit(-1073741511)
    assert "0xC0000135" in cpp.explain_exit(0xC0000135)


def _gcc_dir(root, name):
    d = root / name
    d.mkdir()
    (d / "g++.exe").write_bytes(b"")
    (d / "libstdc++-6.dll").write_bytes(b"")
    return str(d)


def test_gcc_dirs_ignores_dll_only_folders(tmp_path):
    a = _gcc_dir(tmp_path, "a")
    dll_only = tmp_path / "git"
    dll_only.mkdir()
    (dll_only / "libstdc++-6.dll").write_bytes(b"")
    assert cpp.gcc_dirs(os.pathsep.join([str(dll_only), a])) == [a]


def test_path_fix_demote_moves_conflict_to_end(tmp_path):
    a, b = _gcc_dir(tmp_path, "a"), _gcc_dir(tmp_path, "b")
    other = str(tmp_path)
    user = os.pathsep.join([b, other, a])
    plan = cpp.path_fix_plan(a, "demote", user_path=user, machine_path="")
    assert plan["user_new"].split(os.pathsep) == [a, other, b]
    assert plan["removed"] == [] and plan["demoted"] == [b]
    assert not plan["machine_changed"]


def test_path_fix_remove_reports_lost_tools(tmp_path):
    a, b = _gcc_dir(tmp_path, "a"), _gcc_dir(tmp_path, "b")
    (tmp_path / "b" / "cmake.exe").write_bytes(b"")
    plan = cpp.path_fix_plan(a, "remove", user_path=os.pathsep.join([b, a]), machine_path="")
    assert plan["user_new"].split(os.pathsep) == [a]
    assert plan["lost_tools"] == ["cmake"]


def test_path_fix_moves_primary_to_machine_when_conflict_is_there(tmp_path, monkeypatch):
    monkeypatch.setattr(cpp.env_path, "is_admin", lambda: False)
    a, b = _gcc_dir(tmp_path, "a"), _gcc_dir(tmp_path, "b")
    plan = cpp.path_fix_plan(a, "demote", user_path=a, machine_path=b)
    assert plan["machine_new"].split(os.pathsep) == [a, b]
    assert plan["user_new"] == ""
    assert plan["moved_to_machine"] and plan["needs_elevation"]


def test_path_fix_appends_primary_when_no_conflicts(tmp_path):
    # Конкурентов нет — каталог тулчейна встаёт в конец и не перекрывает чужое.
    a = _gcc_dir(tmp_path, "a")
    other = str(tmp_path / "py")
    plan = cpp.path_fix_plan(a, "demote", user_path=other, machine_path="")
    assert plan["user_new"].split(os.pathsep) == [other, a]
    assert not plan["was_on_path"]


def _gcc(d, active=True):
    return cpp.Compiler(
        path=os.path.join(d, "g++.exe"), kind="gcc", version="15.2.0", active=active, on_path=True
    )


def test_terminal_issues_missing_and_differs(tmp_path):
    a, b = _gcc_dir(tmp_path, "a"), _gcc_dir(tmp_path, "b")
    empty = str(tmp_path / "empty")
    os.makedirs(empty)
    assert cpp.terminal_issues([_gcc(a)], a) == []
    assert cpp.terminal_issues([_gcc(a)], "") == []  # реестра нет — проверки нет
    missing = cpp.terminal_issues([_gcc(a)], empty)
    assert len(missing) == 1 and missing[0]["fix"] == "path" and a in missing[0]["text"]
    differs = cpp.terminal_issues([_gcc(a)], os.pathsep.join([b, a]))
    assert len(differs) == 1 and b in differs[0]["text"]


def test_verify_terminal_adds_missing_dir_and_reports_shadow(tmp_path, monkeypatch):
    a, b = _gcc_dir(tmp_path, "a"), _gcc_dir(tmp_path, "b")
    reg = {"path": ""}
    monkeypatch.setattr(cs, "resolve_compiler", lambda comp, keep: _gcc(a))
    monkeypatch.setattr(cpp, "terminal_path", lambda: reg["path"] or str(tmp_path))
    monkeypatch.setattr(cpp, "terminal_smoke", lambda c, tp=None: (True, "built"))

    def fake_add(d):
        reg["path"] = d
        return True, "added"

    monkeypatch.setattr(cpp.env_path, "add_to_user_path", fake_add)
    ok, msg = cs.verify_terminal("mingw", "")
    assert ok and reg["path"] == a and "built" in msg

    reg["path"] = os.pathsep.join([b, a])
    ok, msg = cs.verify_terminal("mingw", "")
    assert not ok and b in msg


def test_winget_codes_are_matched_unsigned():
    from launcher import toolchains as tc

    # Windows отдаёт HRESULT беззнаковым: «обновлять нечего» — это успех.
    assert tc.signed_code(2316632107) == -1978335189
    assert tc.signed_code(2316632107) in tc._WINGET_OK_CODES
    assert tc.signed_code(0) == 0 and tc.signed_code(1223) == 1223
    assert "актуальная" in tc.explain_winget_code(2316632107)


def test_llvm_clang_without_stdlib_is_not_an_error(monkeypatch, tmp_path):
    a = _gcc_dir(tmp_path, "a")
    clang = cpp.Compiler(
        path=r"C:\Program Files\LLVM\bin\clang++.exe",
        kind="clang",
        version="23.1.2",
        target="x86_64-pc-windows-msvc",
        origin="LLVM",
    )
    fail = {
        "compiler": clang.to_dict(),
        "steps": [{"name": "compile", "ok": False, "detail": "'algorithm' file not found"}],
        "ok": False,
        "flags": [],
    }
    monkeypatch.setattr(cpp, "find_compilers", lambda scan_disk=True: [_gcc(a), clang])
    monkeypatch.setattr(cpp, "smoke_all", lambda comps: [fail])
    monkeypatch.setattr(cpp, "terminal_path", lambda: "")
    monkeypatch.setenv("PATH", a)
    rep = cpp.cpp_report()
    assert not any(i["level"] == "error" for i in rep["issues"])
    assert [i["level"] for i in rep["issues"] if i.get("key") == "clang_stdlib"] == ["info"]


def _configure(tmp_path, monkeypatch, engine, initial):
    import json

    from launcher import vscode

    a = _gcc_dir(tmp_path, "a")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(initial), encoding="utf-8")
    monkeypatch.setattr(cs, "resolve_compiler", lambda comp, keep: _gcc(a))
    monkeypatch.setattr(vscode, "vscode_user_settings_path", lambda cli: settings)
    monkeypatch.setattr(cs, "which", lambda name: r"C:\LLVM\bin\clangd.exe")
    monkeypatch.setattr(cs, "clangd_targets_msvc", lambda p: True)
    monkeypatch.setattr(cs, "_runner_installed", lambda cli: True)
    ok, _msg = cs.configure_vscode("msys2", "", engine, None)
    assert ok
    return a, json.loads(settings.read_text(encoding="utf-8"))


def test_configure_clangd_finds_mingw_headers(tmp_path, monkeypatch):
    a, data = _configure(
        tmp_path,
        monkeypatch,
        "clangd",
        {"C_Cpp.intelliSenseEngine": "default", "clangd.arguments": ["--clang-tidy"]},
    )
    assert data["C_Cpp.intelliSenseEngine"] == "disabled"
    assert data["clangd.fallbackFlags"] == ["--target=x86_64-w64-mingw32"]
    assert data["clangd.arguments"][0] == "--clang-tidy"
    assert data["clangd.arguments"][1].startswith("--query-driver=")
    assert data["clangd.arguments"][1].endswith("/a/*")


def test_configure_cpptools_turns_intellisense_back_on(tmp_path, monkeypatch):
    _a, data = _configure(
        tmp_path, monkeypatch, "cpptools", {"C_Cpp.intelliSenseEngine": "disabled"}
    )
    assert data["C_Cpp.intelliSenseEngine"] == "default"
    assert "clangd.fallbackFlags" not in data


def test_engine_follows_disabled_intellisense():
    both = [cs.EXT_CPPTOOLS, cs.EXT_CLANGD]
    assert cs.current_engine(_state(exts=both)) == "cpptools"
    st = _state(exts=both, intellisense_off=True)
    assert cs.current_engine(st) == "clangd"
    assert cs.default_selection(st)["intellisense"] == "clangd"


def test_configure_replaces_stale_query_driver_and_keeps_backup(tmp_path, monkeypatch):
    a, data = _configure(
        tmp_path,
        monkeypatch,
        "clangd",
        {"clangd.arguments": ["--query-driver=C:/old/bin/*", "--clang-tidy"]},
    )
    drivers = [x for x in data["clangd.arguments"] if x.startswith("--query-driver")]
    assert len(drivers) == 1 and drivers[0].endswith("/a/*")
    assert "--clang-tidy" in data["clangd.arguments"]
    backups = list(tmp_path.glob("settings.backup-*.json"))
    assert len(backups) == 1 and "C:/old/bin" in backups[0].read_text(encoding="utf-8")
    # Повторный запуск ничего не меняет и лишних копий не плодит.
    ok, _msg = cs.configure_vscode("msys2", "", "clangd", None)
    assert ok and len(list(tmp_path.glob("settings.backup-*.json"))) == 1


def test_clangd_settings_leave_msvc_clang_alone():
    clang = cpp.Compiler(path=r"C:\LLVM\bin\clang++.exe", kind="clang", target="x86_64-pc-windows-msvc")
    out = cs.clangd_settings(clang, r"C:\LLVM\bin\clangd.exe", True)
    assert "clangd.fallbackFlags" not in out and "clangd.arguments" not in out


def test_study_preset_reuses_msys2_gcc():
    comp = {
        "path": r"D:\msys64\ucrt64\bin\g++.exe",
        "kind": "gcc",
        "version": "15.2.0",
        "origin": "MSYS2 UCRT64",
        "active": True,
        "on_path": True,
    }
    st = _state(
        compilers=[comp],
        msys2={"root": "D:/msys64", "bin": "D:/msys64/ucrt64/bin", "has_gcc": True, "on_path": True},
    )
    sel = cs.apply_preset(cs.default_selection(st), "study", st)
    assert sel["compiler"] == "msys2"
    assert not any(s.kind == "winget" for s in cs.build_plan(sel, st))


def test_verify_terminal_skips_msvc(monkeypatch):
    cl = cpp.Compiler(path=r"C:\VS\bin\cl.exe", kind="msvc", version="19.40")
    monkeypatch.setattr(cs, "resolve_compiler", lambda comp, keep: cl)
    monkeypatch.setattr(
        cpp.env_path, "add_to_user_path", lambda d: (_ for _ in ()).throw(AssertionError(d))
    )
    assert cs.verify_terminal("keep", "")[0]


def test_configure_points_runner_at_the_compiler(tmp_path, monkeypatch):
    a, data = _configure(
        tmp_path, monkeypatch, "cpptools", {"C_Cpp_Runner.cppCompilerPath": "C:/old/g++.exe"}
    )
    assert data["C_Cpp_Runner.cppCompilerPath"] == os.path.join(a, "g++.exe").replace("\\", "/")
    # gdb.exe рядом нет — путь к отладчику не выдумываем.
    assert "C_Cpp_Runner.debuggerPath" not in data


def test_llvm_lldb_failure_does_not_claim_build_failed(monkeypatch, tmp_path):
    a = _gcc_dir(tmp_path, "a")
    clang = cpp.Compiler(
        path=r"C:\LLVM\bin\clang++.exe", kind="clang", target="x86_64-pc-windows-msvc"
    )
    res = {
        "compiler": clang.to_dict(),
        "steps": [
            {"name": "compile", "ok": True, "detail": ""},
            {"name": "link", "ok": True, "detail": ""},
            {"name": "run", "ok": True, "detail": ""},
            {"name": "debug", "ok": False, "detail": "lldb: No module named 'encodings'"},
        ],
        "ok": False,
        "flags": ["--target=x86_64-w64-mingw32"],
    }
    monkeypatch.setattr(cpp, "find_compilers", lambda scan_disk=True: [_gcc(a), clang])
    monkeypatch.setattr(cpp, "smoke_all", lambda comps: [res])
    monkeypatch.setattr(cpp, "terminal_path", lambda: "")
    monkeypatch.setenv("PATH", a)
    issues = [i for i in cpp.cpp_report()["issues"] if i.get("key") == "clang_stdlib"]
    assert len(issues) == 1 and issues[0]["level"] == "info"
    assert "encodings" in issues[0]["text"] and "CodeLLDB" in issues[0]["text"]
    assert "тоже не прошла" not in issues[0]["text"]


def test_plan_ends_with_verify_except_msvc():
    st = _state()
    steps = cs.build_plan(cs.default_selection(st), st)
    assert steps[-1].kind == "verify"
    sel = cs.default_selection(st)
    sel["compiler"] = "msvc"
    assert not any(s.kind == "verify" for s in cs.build_plan(sel, st))


def test_analyze_flags_foreign_libstdcxx(tmp_path, monkeypatch):
    a, b = _gcc_dir(tmp_path, "a"), _gcc_dir(tmp_path, "b")
    monkeypatch.setenv("PATH", os.pathsep.join([b, a]))
    comp = cpp.Compiler(
        path=os.path.join(a, "g++.exe"), kind="gcc", version="15.2.0", active=True, on_path=True
    )
    issues = cpp.analyze([comp], {"gdb": os.path.join(a, "gdb.exe")})
    assert any(i["level"] == "error" and "libstdc++" in i["text"] for i in issues)
    assert any(i["fix"] == "path" for i in issues)


def test_analyze_no_compiler_suggests_install():
    issues = cpp.analyze([], {})
    assert issues[0]["level"] == "error" and issues[0]["fix"] == "install:cpp"


def test_analyze_old_clang_targeting_msvc():
    c = cpp.Compiler(
        path=r"C:\LLVM\clang++.exe",
        kind="clang",
        version="12.0.0",
        target="x86_64-pc-windows-msvc",
        active=True,
        on_path=True,
    )
    fixes = {i["fix"] for i in cpp.analyze([c], {})}
    assert {"install:cpp_llvm", "install:cpp_msvc"} <= fixes


def test_pacman_packages_filter():
    assert cpp.pacman_packages("ucrt64", ("toolchain", "bad name", "x;rm")) == [
        "mingw-w64-ucrt-x86_64-toolchain"
    ]
    assert cpp.pacman_packages("nope", ("toolchain",)) == []


def test_format_report_smoke():
    rep = {"compilers": [], "tools": {}, "issues": cpp.analyze([], {}), "smoke": []}
    text = "\n".join(cpp.format_report(rep))
    assert "не найдено" in text and "[ошибка]" in text


# --- cpp_project.py -------------------------------------------------------------


def _opts(**kw):
    o = cp.ProjectOptions(compiler_path=r"D:\m\bin\g++.exe", compiler_kind="gcc")
    for k, v in kw.items():
        setattr(o, k, v)
    return o


def test_debugger_auto_pairs():
    assert _opts().resolved_debugger() == "gdb"
    assert _opts(engine="clangd").resolved_debugger() == "lldb"
    # cpptools установлен — GCC отлаживаем gdb, даже когда подсказки даёт clangd.
    assert _opts(engine="clangd", has_cpptools=True).resolved_debugger() == "gdb"
    single = cp.launch_json(_opts(engine="clangd", has_cpptools=True))["configurations"][0]
    assert single["type"] == "cppdbg" and single["cwd"] == "${fileDirname}"
    assert _opts(compiler_kind="msvc").resolved_debugger() == "cppvsdbg"


def test_clangd_settings_disable_cpptools_and_query_driver():
    s = cp.workspace_settings(_opts(engine="clangd"))
    assert s["C_Cpp.intelliSenseEngine"] == "disabled"
    assert any(a.startswith("--query-driver=D:/m/bin/") for a in s["clangd.arguments"])


def test_tasks_single_uses_compiler_and_std():
    t = cp.tasks_json(_opts(std="c++23"))["tasks"][0]
    assert t["command"] == r"D:\m\bin\g++.exe" and "-std=c++23" in t["args"]


def test_olympiad_task_does_not_start_with_quote():
    # cmd /c срезает кавычки, если строка начинается с них — ломается путь.
    run = cp.tasks_json(_opts(olympiad=True))["tasks"][1]["command"]
    assert run.startswith("call ") and "input.txt" in run


def test_cmake_presets_msvc_multiconfig():
    p = cp.cmake_presets(_opts(compiler_kind="msvc", compiler_path=""))
    assert p["configurePresets"][0]["generator"].startswith("Visual Studio")
    assert all("configuration" in b for b in p["buildPresets"])


def test_vcpkg_triplet_for_mingw():
    p = cp.cmake_presets(_opts(vcpkg=True))
    assert p["configurePresets"][0]["cacheVariables"]["VCPKG_TARGET_TRIPLET"] == "x64-mingw-static"


def test_apply_plan_keeps_existing_files(tmp_path):
    (tmp_path / ".clang-format").write_text("mine", encoding="utf-8")
    plan = cp.plan_files(str(tmp_path), _opts())
    report = cp.apply_plan(str(tmp_path), plan)
    assert (tmp_path / ".clang-format").read_text(encoding="utf-8") == "mine"
    assert any("пропущен" in r for r in report)
    assert json.loads((tmp_path / ".vscode" / "tasks.json").read_text(encoding="utf-8"))


def test_apply_plan_overwrite_makes_backup(tmp_path):
    (tmp_path / ".clang-format").write_text("mine", encoding="utf-8")
    plan = cp.plan_files(str(tmp_path), _opts())
    cp.apply_plan(str(tmp_path), plan, overwrite={".clang-format"})
    assert list(tmp_path.glob(".clang-format.bak-*"))


def test_new_project_validates_name(tmp_path):
    ok, msg = cp.new_project(str(tmp_path), "bad name", "single", _opts())
    assert not ok


def test_new_project_cmake(tmp_path):
    ok, path = cp.new_project(str(tmp_path), "demo", "cmake_vcpkg", _opts())
    assert ok
    root = tmp_path / "demo"
    assert (root / "src" / "main.cpp").is_file()
    assert "find_package(fmt" in (root / "CMakeLists.txt").read_text(encoding="utf-8")
    assert json.loads((root / "vcpkg.json").read_text(encoding="utf-8"))["name"] == "demo"


# --- detect.py ----------------------------------------------------------------------


def test_detect_cpp_parts(tmp_path):
    (tmp_path / "main.cpp").write_text("#include <SFML/Graphics.hpp>\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text("all:\n", encoding="utf-8")
    found = detect.detect_stacks(str(tmp_path))
    assert {"cpp", "cpp_cpptools", "cpp_make", "cpp_extras"} <= found


def test_detect_clangd_and_cmake(tmp_path):
    (tmp_path / "CMakeLists.txt").write_text("", encoding="utf-8")
    (tmp_path / ".clangd").write_text("", encoding="utf-8")
    found = detect.detect_stacks(str(tmp_path))
    assert {"cpp", "cpp_cmake", "cpp_clangd"} <= found
    assert "cpp_cpptools" not in found and "cpp_make" not in found


def test_makefile_alone_is_not_cpp(tmp_path):
    (tmp_path / "Makefile").write_text("all:\n", encoding="utf-8")
    assert "cpp_make" not in detect.detect_stacks(str(tmp_path))


def test_cpp_project_hints(tmp_path):
    (tmp_path / "CMakeLists.txt").write_text("", encoding="utf-8")
    (tmp_path / "vcpkg.json").write_text("{}", encoding="utf-8")
    (tmp_path / "a.cpp").write_text("#include <fmt/core.h>\n#include <QWidget>\n", "utf-8")
    h = detect.cpp_project_hints(str(tmp_path))
    assert h["is_cpp"] and h["build"] == "cmake" and h["vcpkg"]
    assert h["libs"] == ["fmt", "qt6"] and not h["has_vscode_cfg"]


# --- категории и конфиг --------------------------------------------------------------


def test_stack_conflicts():
    cats = {"categories": {"a": {"conflicts": ["b"]}, "b": {"conflicts": ["a"]}, "c": {}}}
    assert stack_conflicts({"a", "b", "c"}, cats) == [("a", "b")]
    assert stack_conflicts({"a", "c"}, cats) == []


def test_config_v5_splits_cpp():
    cfg = migrate_config(
        {"config_version": 4, "last_selected": ["cpp", "python"], "presets": {"p": ["cpp"]}}
    )
    assert {"cpp_cpptools", "cpp_cmake", "cpp_make", "cpp_lldb", "cpp_extras"} <= set(
        cfg["last_selected"]
    )
    assert "cpp_clangd" not in cfg["last_selected"]
    assert "cpp_cpptools" in cfg["presets"]["p"]


# --- cpp_setup.py -------------------------------------------------------------------


def _state(**kw):
    st = {
        "compilers": [],
        "tools": {},
        "gcc_dirs": [],
        "exts": [],
        "msys2": {"root": "", "bin": "", "has_gcc": False, "on_path": False},
        "msys2_libs": {},
        "vcpkg": "",
        "clangd": "",
        "clangd_version": [],
        "git": "git",
        "code_cli": "code",
    }
    st.update(kw)
    return st


def _kinds(steps):
    return [(s.kind, s.ref) for s in steps]


def test_fresh_machine_defaults_to_mingw():
    st = _state()
    sel = cs.default_selection(st)
    assert sel["compiler"] == "mingw"
    kinds = _kinds(cs.build_plan(sel, st))
    assert ("winget", "cpp/BrechtSanders.WinLibs.POSIX.UCRT") in kinds
    assert ("ext", cs.EXT_CPPTOOLS) in kinds


def test_msys2_brings_cmake_and_ninja():
    st = _state()
    sel = cs.apply_preset(cs.default_selection(st), "projects", st)
    kinds = _kinds(cs.build_plan(sel, st))
    assert ("winget", "cpp_msys2/MSYS2.MSYS2") in kinds
    assert not any(ref.endswith("Kitware.CMake") for _k, ref in kinds)
    assert ("ext", cs.EXT_CMAKE) in kinds


def test_clangd_upgrades_old_llvm_and_adds_codelldb():
    st = _state(clangd="clangd", clangd_version=[12, 0, 0])
    sel = cs.apply_preset(cs.default_selection(st), "pro", st)
    kinds = _kinds(cs.build_plan(sel, st))
    assert ("winget_upgrade", "cpp_llvm/LLVM.LLVM") in kinds
    assert ("ext", cs.EXT_CLANGD) in kinds and ("ext", cs.EXT_CODELLDB) in kinds


def test_vcpkg_pulls_git_when_missing():
    st = _state(git="")
    sel = cs.default_selection(st)
    sel["checked"].add("vcpkg")
    kinds = [s.kind for s in cs.build_plan(sel, st)]
    assert kinds.index("winget") < kinds.index("vcpkg")
    assert any(s.ref == "git/Git.Git" for s in cs.build_plan(sel, st))


def test_installed_things_are_not_planned():
    comp = {
        "path": r"D:\msys64\ucrt64\bin\g++.exe",
        "kind": "gcc",
        "version": "15",
        "origin": "MSYS2 UCRT64",
        "active": True,
        "on_path": True,
    }
    st = _state(
        compilers=[comp],
        tools={"cmake": "c", "ninja": "n"},
        exts=[cs.EXT_CPPTOOLS, cs.EXT_CMAKE],
        msys2={
            "root": "D:/msys64",
            "bin": "D:/msys64/ucrt64/bin",
            "has_gcc": True,
            "on_path": True,
        },
    )
    sel = cs.default_selection(st)
    assert sel["compiler"] == "msys2"
    sel["checked"] |= {"cmake", "ninja"}
    steps = cs.build_plan(sel, st)
    assert [s.kind for s in steps] == ["configure", "verify"]
    assert cs.plan_summary(steps)["only_setup"]


def test_libs_need_msys2():
    st = _state()
    sel = cs.default_selection(st)
    sel["libs"] = {"sfml"}
    assert not any(s.kind == "pacman" for s in cs.build_plan(sel, st))
    sel["compiler"] = "msys2"
    assert any(s.kind == "pacman" and "sfml" in s.args for s in cs.build_plan(sel, st))


def test_msvc_step_needs_admin():
    st = _state()
    sel = cs.default_selection(st)
    sel["compiler"] = "msvc"
    steps = cs.build_plan(sel, st)
    assert cs.plan_summary(steps)["admin"]
    assert not any(s.kind == "path" for s in steps)


def test_set_string_keys_keeps_comments(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text('{\n  // comment\n  "C_Cpp.default.compilerPath": "old",\n  "x": 1\n}\n', "utf-8")
    assert cs._set_string_keys(f, {"C_Cpp.default.compilerPath": "C:\\new\\g++.exe"}) == [
        "C_Cpp.default.compilerPath"
    ]
    text = f.read_text(encoding="utf-8")
    assert "// comment" in text and '"C:\\\\new\\\\g++.exe"' in text


def test_option_texts_both_languages():
    for o in cs.OPTIONS:
        assert cs.text(o, "title", "ru") and cs.text(o, "title", "en")
        assert cs.text(o, "what", "en")


@pytest.mark.parametrize("key", list(cs.PRESETS))
def test_presets_build(key):
    st = _state()
    cs.build_plan(cs.apply_preset(cs.default_selection(st), key, st), st)


# --- окно ------------------------------------------------------------------------------


def test_cpp_center_dialog_builds(monkeypatch):
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from launcher import gui_cpp

    st = _state()
    monkeypatch.setattr(cs, "scan_state", lambda cli: st)
    dlg = gui_cpp.CppCenter(None, None)
    dlg._on_state(st)  # без фонового потока
    try:
        # Чистая машина: в простом режиме сразу выбран набор для новичков.
        assert dlg._preset_key == "study"
        assert dlg.install_btn.isEnabled()
        dlg._use_preset("pro")
        assert dlg.install_btn.isEnabled()
        assert dlg._sel["intellisense"] == "clangd"
        assert dlg._preset_cards["pro"].property("on") == "true"
        dlg._set_mode("detail")
        dlg._toggle("doxygen", True)
        assert dlg._preset_key == ""
        dlg.tabs.setCurrentIndex(2)
        dlg.tabs.setCurrentIndex(1)
    finally:
        dlg._open = False
        dlg.deleteLater()
        app.processEvents()
