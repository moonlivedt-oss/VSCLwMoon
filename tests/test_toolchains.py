# -*- coding: utf-8 -*-
"""Тесты установки тулчейнов и управления PATH (без winget и без реестра).

Всё, что стучится наружу (winget, реестр, which), подменяется monkeypatch —
проверяем только чистую логику: валидацию id, целостность каталога,
идемпотентность PATH и ветвления install_package.

Запуск:  python -m pytest tests/test_toolchains.py
"""

import os
from pathlib import Path

import pytest

from launcher import env_path, toolchains as tc


# --- валидатор id winget ---------------------------------------------------


def test_valid_winget_id_accepts_real_ids():
    assert tc.valid_winget_id("EclipseAdoptium.Temurin.21.JDK")
    assert tc.valid_winget_id("BrechtSanders.WinLibs.POSIX.UCRT")
    assert tc.valid_winget_id("Microsoft.DotNet.SDK.8")


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "foo bar",
        "foo;calc",
        'foo"&calc',
        "foo|bar",
        "foo\ncalc",
        "-flag",
        ".leadingdot",
        "foo/bar",
    ],
)
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
    stack_keys.add("git")  # git детектится по каталогу .git, а не по маркеру файла
    EXTRA = {"deno", "bun", "zig"}  # внестековые, но устанавливаемые
    for key in tc.TOOLCHAINS:
        assert key in stack_keys or key in EXTRA, (
            f"тулчейн {key!r} не соответствует ни стеку, ни списку внестековых"
        )


def test_get_toolchain_and_keys():
    assert tc.get_toolchain("java").title == "Java (JDK)"
    assert tc.get_toolchain("nope") is None
    assert "cpp" in tc.toolchain_keys()


# --- статус пакета (which/probe подменяются) -------------------------------


def test_package_installed_uses_which(monkeypatch):
    pkg = tc.get_toolchain("go").packages[0]  # probe ("go",)
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
    pkg = tc.Package("Some.Tool", "Some", ("sometool",), path_hints=("C:/tools/bin",))
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
    pkg = tc.get_toolchain("cpp").packages[0]  # probe g++, gcc, gdb
    assert tc.find_bin_dir_for(pkg) == str(bind)


def test_repair_path_for_adds_found_dir(tmp_path, monkeypatch):
    bind = tmp_path / "bin"
    bind.mkdir()
    monkeypatch.setattr(tc, "package_installed", lambda pkg: False)
    monkeypatch.setattr(tc, "find_bin_dir_for", lambda pkg: str(bind))
    added = {}
    monkeypatch.setattr(tc.env_path, "is_on_path", lambda d: False)
    monkeypatch.setattr(
        tc.env_path, "add_to_user_path", lambda d: (added.setdefault("d", d), (True, "ok"))[1]
    )
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
    assert twice == once  # уже есть — не дублируем


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
    monkeypatch.setattr(
        tc, "_compiler_path", lambda exe: r"C:\mingw64\bin\g++.exe" if exe == "g++" else None
    )
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


# --- настройка VS Code для Python (#новое) ---------------------------------


def test_settings_for_toolchain_python(monkeypatch):
    monkeypatch.setattr(tc, "which", lambda e: r"C:\Py\python.exe" if e == "python" else None)
    s = tc.settings_for_toolchain("python")
    assert s["python.defaultInterpreterPath"].endswith("python.exe")


def test_settings_for_toolchain_python_empty_when_absent(monkeypatch):
    monkeypatch.setattr(tc, "which", lambda e: None)
    assert tc.settings_for_toolchain("python") == {}


# --- чистка PATH: дубли и мёртвые записи ------------------------------------


def test_compute_path_cleanup_dedups_keeping_first(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    s = os.pathsep.join([str(a), str(a), str(a)])
    plan = env_path.compute_path_cleanup(s, remove_missing=False)
    # первое вхождение сохранено, два повтора убраны
    assert plan["kept"] == [str(a)]
    assert len(plan["removed_duplicates"]) == 2
    assert plan["removed_missing"] == []


def test_compute_path_cleanup_drops_missing(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    dead = tmp_path / "ghost"  # не создаём
    s = os.pathsep.join([str(real), str(dead)])
    plan = env_path.compute_path_cleanup(s, remove_missing=True)
    assert plan["kept"] == [str(real)]
    assert plan["removed_missing"] == [str(dead)]


def test_compute_path_cleanup_keeps_reserve_dirs(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    reserve = tmp_path / "go" / "bin"  # мёртвый, но резервный
    s = os.pathsep.join([str(real), str(reserve)])
    plan = env_path.compute_path_cleanup(s, remove_missing=True, keep=(str(reserve),))
    assert str(reserve) in plan["kept"]
    assert plan["removed_missing"] == []


def test_clean_user_path_dry_run_reports_without_writing(tmp_path, monkeypatch):
    a = tmp_path / "a"
    a.mkdir()
    dead = tmp_path / "dead"
    user_path = os.pathsep.join([str(a), str(a), str(dead)])
    monkeypatch.setattr(env_path, "read_user_path", lambda: user_path)
    monkeypatch.setattr(env_path, "reserve_dirs", lambda: ())
    wrote = {}
    monkeypatch.setattr(env_path, "_write_user_path", lambda v: wrote.setdefault("v", v))
    res = env_path.clean_user_path(dry_run=True)
    assert not res["applied"]
    assert "v" not in wrote  # ничего не записали
    assert len(res["removed_duplicates"]) == 1
    assert res["removed_missing"] == [str(dead)]


def test_clean_user_path_applies_and_backs_up(tmp_path, monkeypatch):
    a = tmp_path / "a"
    a.mkdir()
    dead = tmp_path / "dead"
    user_path = os.pathsep.join([str(a), str(a), str(dead)])
    monkeypatch.setattr(env_path, "read_user_path", lambda: user_path)
    monkeypatch.setattr(env_path, "reserve_dirs", lambda: ())
    monkeypatch.setattr(env_path, "_broadcast_env_change", lambda: None)
    monkeypatch.setattr(env_path, "_backup_user_path", lambda v: "backup.txt")
    wrote = {}
    monkeypatch.setattr(env_path, "_write_user_path", lambda v: wrote.setdefault("v", v))
    monkeypatch.setenv("PATH", user_path)
    res = env_path.clean_user_path(dry_run=False)
    assert res["applied"]
    assert env_path.path_entries(wrote["v"]) == [str(a)]  # дубль и мёртвый убраны
    assert res["backup"] == "backup.txt"


# --- JAVA_HOME: поиск JDK и починка -----------------------------------------


def test_find_jdk_home_from_javac(tmp_path, monkeypatch):
    home = tmp_path / "jdk-21"
    (home / "bin").mkdir(parents=True)
    (home / "bin" / "java.exe").write_text("")
    monkeypatch.setattr(
        tc, "which", lambda e: str(home / "bin" / "javac.exe") if e == "javac" else None
    )
    assert tc.find_jdk_home() == str(home)


def test_repair_java_home_sets_var(monkeypatch):
    monkeypatch.setattr(
        tc,
        "_java_home_health",
        lambda: {"set": False, "ok": False, "path": "", "reason": "не задан"},
    )
    monkeypatch.setattr(tc, "find_jdk_home", lambda: r"C:\jdk-21")
    got = {}
    monkeypatch.setattr(
        tc.env_path, "set_user_env_var", lambda n, v: (got.update(name=n, val=v), (True, "ok"))[1]
    )
    ok, _msg = tc.repair_java_home()
    assert ok and got == {"name": "JAVA_HOME", "val": r"C:\jdk-21"}


def test_repair_java_home_noop_when_ok(monkeypatch):
    monkeypatch.setattr(
        tc, "_java_home_health", lambda: {"set": True, "ok": True, "path": r"C:\jdk", "reason": ""}
    )
    ok, msg = tc.repair_java_home()
    assert not ok and "уже" in msg.lower()


def test_verify_cmd_gates_installed(monkeypatch):
    # .NET-подобный кейс: probe (dotnet) в PATH есть, но verify_cmd решает исход.
    pkg = tc.Package(
        "Microsoft.DotNet.SDK.9", ".NET SDK 9", ("dotnet",), verify_cmd=("--list-sdks",)
    )
    monkeypatch.setattr(tc, "which", lambda e: "C:/dotnet/dotnet.exe")

    class _R:
        def __init__(self, rc, out):
            self.returncode = rc
            self.stdout = out
            self.stderr = ""

    # SDK есть → команда вернула строку, rc 0 → установлен
    monkeypatch.setattr(tc.subprocess, "run", lambda *a, **k: _R(0, "9.0.317 [C:\\...]\n"))
    assert tc.package_installed(pkg)
    assert tc.package_status(pkg)["installed"]
    # Только рантайм, SDK нет → пустой stdout → НЕ установлен
    monkeypatch.setattr(tc.subprocess, "run", lambda *a, **k: _R(0, "  \n"))
    assert not tc.package_installed(pkg)
    assert tc.package_status(pkg) == {"installed": False, "version": None}


def test_settings_for_toolchain_cpp_clang_mode(monkeypatch):
    # g++ нет, есть только clang++ → IntelliSense должен быть clang-режим.
    monkeypatch.setattr(
        tc, "_compiler_path", lambda exe: r"C:\LLVM\bin\clang++.exe" if exe == "clang++" else None
    )
    s = tc.settings_for_toolchain("cpp")
    assert s["C_Cpp.default.compilerPath"].endswith("clang++.exe")
    assert s["C_Cpp.default.intelliSenseMode"] == "windows-clang-x64"


def test_settings_for_toolchain_cpp_gcc_mode(monkeypatch):
    monkeypatch.setattr(
        tc, "_compiler_path", lambda exe: r"C:\mingw64\bin\g++.exe" if exe == "g++" else None
    )
    s = tc.settings_for_toolchain("cpp")
    assert s["C_Cpp.default.intelliSenseMode"] == "windows-gcc-x64"


def test_repair_java_home_adds_bin_to_path(monkeypatch):
    monkeypatch.setattr(
        tc,
        "_java_home_health",
        lambda: {"set": False, "ok": False, "path": "", "reason": "не задан"},
    )
    monkeypatch.setattr(tc, "find_jdk_home", lambda: r"C:\jdk-21")
    monkeypatch.setattr(tc.env_path, "set_user_env_var", lambda n, v: (True, "ok"))
    monkeypatch.setattr(tc.env_path, "is_on_path", lambda d: False)
    added = {}
    monkeypatch.setattr(
        tc.env_path, "add_to_user_path", lambda d: (added.setdefault("d", d), (True, f"+{d}"))[1]
    )
    ok, _msg = tc.repair_java_home()
    assert ok and added["d"] == r"C:\jdk-21\bin"


def test_catalog_path_hints_collects_from_packages():
    hints = tc.catalog_path_hints()
    # php в каталоге объявляет path_hints — они должны попасть в keep-список.
    assert any("php" in h.lower() for h in hints)


def test_new_toolchains_present():
    for key in ("dart", "julia", "swift"):
        chain = tc.get_toolchain(key)
        assert chain is not None, key
        assert chain.packages and tc.valid_winget_id(chain.packages[0].winget_id)


# --- чистка системного PATH -------------------------------------------------


def test_clean_machine_path_dry_run(tmp_path, monkeypatch):
    a = tmp_path / "a"
    a.mkdir()
    dead = tmp_path / "dead"
    machine_path = os.pathsep.join([str(a), str(a), str(dead)])
    monkeypatch.setattr(env_path, "read_machine_path", lambda: machine_path)
    monkeypatch.setattr(env_path, "reserve_dirs", lambda: ())
    res = env_path.clean_machine_path(dry_run=True)
    assert not res["applied"]
    assert len(res["removed_duplicates"]) == 1
    assert res["removed_missing"] == [str(dead)]


def test_clean_machine_path_applies_when_admin(tmp_path, monkeypatch):
    a = tmp_path / "a"
    a.mkdir()
    dead = tmp_path / "dead"
    machine_path = os.pathsep.join([str(a), str(a), str(dead)])
    monkeypatch.setattr(env_path, "read_machine_path", lambda: machine_path)
    monkeypatch.setattr(env_path, "reserve_dirs", lambda: ())
    monkeypatch.setattr(env_path, "is_admin", lambda: True)
    monkeypatch.setattr(env_path, "_broadcast_env_change", lambda: None)
    monkeypatch.setattr(env_path, "_backup_path", lambda v, s: "m_backup.txt")
    wrote = {}
    monkeypatch.setattr(env_path, "_write_machine_path_direct", lambda v: wrote.setdefault("v", v))
    monkeypatch.setenv("PATH", machine_path)
    res = env_path.clean_machine_path(dry_run=False)
    assert res["applied"]
    assert env_path.path_entries(wrote["v"]) == [str(a)]
    assert res["backup"] == "m_backup.txt"


def test_write_machine_path_elevated_builds_correct_script(monkeypatch):
    # Не поднимаем реальный UAC: перехватываем subprocess.run, читаем
    # сгенерированные .ps1 и файл значения ДО того, как finally их удалит.
    import re
    import subprocess as _sp

    captured: dict = {}

    def fake_run(args, **kw):
        launcher = args[4]  # ["powershell",...,"-Command", launcher]
        captured["launcher"] = launcher
        m = re.search(r"'-File',\s*'([^']+)'", launcher)
        captured["ps1"] = Path(m.group(1)).read_text(encoding="utf-8")
        m2 = re.search(r"ReadAllText\('([^']+)'\)", captured["ps1"])
        captured["value"] = Path(m2.group(1)).read_text(encoding="utf-8")

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    monkeypatch.setattr(_sp, "run", fake_run)
    ok, _msg = env_path._write_machine_path_elevated(r"C:\a;C:\b")
    assert ok
    # elevated-запуск: RunAs, ждём завершения, исполняем именно наш .ps1
    assert "-Verb RunAs" in captured["launcher"]
    assert "-Wait" in captured["launcher"]
    assert "-PassThru" in captured["launcher"]
    # скрипт пишет в системную ветку реестра значением REG_EXPAND_SZ
    assert "Session Manager\\Environment" in captured["ps1"]
    assert "ExpandString" in captured["ps1"]
    # значение передаётся файлом байт-в-байт (без экранирования длинной строки)
    assert captured["value"] == r"C:\a;C:\b"


def test_write_machine_path_elevated_reports_uac_declined(monkeypatch):
    import subprocess as _sp

    class R:
        returncode = 1223  # ERROR_CANCELLED — пользователь отклонил UAC
        stdout = ""
        stderr = ""

    monkeypatch.setattr(_sp, "run", lambda *a, **k: R())
    ok, msg = env_path._write_machine_path_elevated(r"C:\a")
    assert not ok and "UAC" in msg


def test_clean_machine_path_routes_to_elevation_when_not_admin(tmp_path, monkeypatch):
    a = tmp_path / "a"
    a.mkdir()
    dead = tmp_path / "dead"
    mp = os.pathsep.join([str(a), str(a), str(dead)])
    monkeypatch.setattr(env_path, "read_machine_path", lambda: mp)
    monkeypatch.setattr(env_path, "reserve_dirs", lambda: ())
    monkeypatch.setattr(env_path, "is_admin", lambda: False)
    monkeypatch.setattr(env_path, "_backup_path", lambda v, s: "b.txt")
    monkeypatch.setattr(env_path, "_broadcast_env_change", lambda: None)
    got: dict = {}
    monkeypatch.setattr(
        env_path,
        "_write_machine_path_elevated",
        lambda v: (got.setdefault("v", v), (True, "ok"))[1],
    )
    monkeypatch.setenv("PATH", mp)
    res = env_path.clean_machine_path(dry_run=False)
    assert res["applied"] and res["needs_elevation"]
    assert env_path.path_entries(got["v"]) == [str(a)]  # дубль и мёртвый убраны


def test_environment_report_splits_user_machine(monkeypatch):
    monkeypatch.setattr(env_path, "read_user_path", lambda: r"C:\u1;C:\u1")
    monkeypatch.setattr(env_path, "read_machine_path", lambda: r"C:\m1")
    rep = tc.environment_report()
    assert "path_user" in rep and "path_machine" in rep
    assert rep["path_user"]["duplicates"]  # C:\u1 продублирован


def test_verify_cmd_absent_means_probe_only(monkeypatch):
    # Пакет без verify_cmd — детект как раньше, лишь по наличию probe в PATH.
    pkg = tc.get_toolchain("go").packages[0]
    monkeypatch.setattr(tc, "which", lambda e: "C:/go/bin/go.exe")
    ran = {"n": 0}
    monkeypatch.setattr(tc.subprocess, "run", lambda *a, **k: ran.__setitem__("n", ran["n"] + 1))
    assert tc.package_installed(pkg)
    assert ran["n"] == 0  # без verify_cmd подпроцесс не запускаем


def test_repair_java_home_no_jdk(monkeypatch):
    monkeypatch.setattr(
        tc,
        "_java_home_health",
        lambda: {"set": False, "ok": False, "path": "", "reason": "не задан"},
    )
    monkeypatch.setattr(tc, "find_jdk_home", lambda: None)
    ok, msg = tc.repair_java_home()
    assert not ok and "jdk" in msg.lower()
