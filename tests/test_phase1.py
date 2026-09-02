# -*- coding: utf-8 -*-
"""Тесты Фазы 1: зависимости расширений (#1), честный замер (#2),
автоклассификация (#3), JSON Schema карты (#16).

Запуск:  python -m pytest tests/test_phase1.py
"""

import json

from launcher import core
from launcher.classify import classify_extension, suggest_categories
from launcher.launch import compute_disabled, required_by_enabled
from launcher.manifests import (
    build_dependency_map,
    read_extension_manifests,
)
from launcher.paths import CATEGORIES_FILE, DATA_DIR

# --- #1: граф зависимостей и защита при выключении -------------------------


def test_build_dependency_map_merges_deps_and_pack():
    manifests = {
        "pub.pack": {"depends": [], "pack": ["pub.a", "pub.b"]},
        "pub.a": {"depends": ["pub.lib"], "pack": []},
        "pub.self": {"depends": ["pub.self"], "pack": []},  # self-ref опускаем
        "pub.empty": {"depends": [], "pack": []},  # пустое — не в карте
    }
    dep = build_dependency_map(manifests)
    assert dep["pub.pack"] == {"pub.a", "pub.b"}
    assert dep["pub.a"] == {"pub.lib"}
    assert "pub.self" not in dep  # ссылка сама на себя выкинута -> пусто
    assert "pub.empty" not in dep


def test_required_by_enabled_transitive_and_cycle_safe():
    dep = {"a": {"b"}, "b": {"c"}, "c": {"a"}}  # цикл a->b->c->a
    got = required_by_enabled({"a"}, dep)
    assert got == {"a", "b", "c"}  # обход не зацикливается


def test_compute_disabled_keeps_dependency_of_enabled():
    # web зависит от общей библиотеки, лежащей в стеке python; python выключен,
    # но библиотека нужна включённому web — её нельзя гасить.
    idx = {"pub.web": "web", "pub.lib": "python"}
    installed = ["pub.web", "pub.lib"]
    dep = {"pub.web": {"pub.lib"}}
    disabled = compute_disabled(installed, idx, {"web"}, dep_map=dep)
    assert "pub.lib" not in disabled  # зависимость спасена
    assert disabled == []


def test_compute_disabled_without_depmap_disables_lib():
    # Без карты зависимостей поведение прежнее — библиотека гаснет.
    idx = {"pub.web": "web", "pub.lib": "python"}
    installed = ["pub.web", "pub.lib"]
    disabled = compute_disabled(installed, idx, {"web"})
    assert "pub.lib" in disabled


def test_compute_disabled_force_disable_beats_dependency():
    # Явный force_disable сильнее защиты по зависимости — осознанный выбор.
    idx = {"pub.web": "web", "pub.lib": "python"}
    installed = ["pub.web", "pub.lib"]
    dep = {"pub.web": {"pub.lib"}}
    disabled = compute_disabled(installed, idx, {"web"}, force_disable={"pub.lib"}, dep_map=dep)
    assert "pub.lib" in disabled


def test_compute_disabled_transitive_rescue():
    # a(вкл, web) -> b(python) -> c(python); оба b и c должны остаться вкл.
    idx = {"pub.a": "web", "pub.b": "python", "pub.c": "python"}
    installed = ["pub.a", "pub.b", "pub.c"]
    dep = {"pub.a": {"pub.b"}, "pub.b": {"pub.c"}}
    disabled = compute_disabled(installed, idx, {"web"}, dep_map=dep)
    assert disabled == []


# --- #3: автоклассификация по манифесту -------------------------------------


def test_classify_by_language():
    assert classify_extension({"languages": ["python"], "categories": []}) == "python"
    assert classify_extension({"languages": ["go"], "categories": []}) == "go"
    assert classify_extension({"languages": ["typescript"], "categories": []}) == "web"


def test_classify_multilang_returns_none():
    # Плагин для нескольких разных стеков не приписываем одному.
    assert classify_extension({"languages": ["python", "go"], "categories": []}) is None


def test_classify_by_category_fallback():
    assert classify_extension({"languages": [], "categories": ["Data Science"]}) == "data"
    assert classify_extension({"languages": [], "categories": ["Notebooks"]}) == "data"


def test_classify_unknown_returns_none():
    assert classify_extension({"languages": [], "categories": ["Other"]}) is None
    assert classify_extension({}) is None
    assert classify_extension("nonsense") is None


def test_suggest_categories_only_unknown_and_available():
    installed = ["known.python", "guess.go", "guess.rust"]
    ext_index = {"known.python": "python"}  # known уже в карте
    manifests = {
        "guess.go": {"languages": ["go"], "categories": []},
        "guess.rust": {"languages": ["rust"], "categories": []},
    }
    # rust нет в доступных ключах карты — предложение по нему отбрасываем.
    out = suggest_categories(installed, ext_index, manifests, available={"go", "python"})
    assert out == {"guess.go": "go"}


# --- #1/#3: чтение манифестов с диска ---------------------------------------


def _write_ext(ext_dir, folder, pkg):
    d = ext_dir / folder
    d.mkdir(parents=True)
    (d / "package.json").write_text(json.dumps(pkg), encoding="utf-8")


def test_read_extension_manifests_from_extensions_json(tmp_path, monkeypatch):
    ext_dir = tmp_path / "extensions"
    ext_dir.mkdir()
    _write_ext(
        ext_dir,
        "ms-python.python-1.0",
        {
            "publisher": "ms-python",
            "name": "python",
            "extensionDependencies": ["ms-python.debugpy"],
            "contributes": {"languages": [{"id": "python"}]},
            "categories": ["Programming Languages"],
        },
    )
    _write_ext(
        ext_dir,
        "redhat.java-2.0",
        {
            "publisher": "redhat",
            "name": "java",
            "extensionPack": ["redhat.dep1", "redhat.dep2"],
            "activationEvents": ["onLanguage:java"],
        },
    )
    index = [
        {"identifier": {"id": "ms-python.python"}, "relativeLocation": "ms-python.python-1.0"},
        {"identifier": {"id": "redhat.java"}, "relativeLocation": "redhat.java-2.0"},
    ]
    (ext_dir / "extensions.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setenv("VSCODE_EXTENSIONS", str(ext_dir))

    manifests = read_extension_manifests("code")
    assert set(manifests) == {"ms-python.python", "redhat.java"}
    assert manifests["ms-python.python"]["depends"] == ["ms-python.debugpy"]
    assert manifests["ms-python.python"]["languages"] == ["python"]
    assert manifests["redhat.java"]["pack"] == ["redhat.dep1", "redhat.dep2"]
    assert manifests["redhat.java"]["languages"] == ["java"]

    dep = build_dependency_map(manifests)
    assert dep["ms-python.python"] == {"ms-python.debugpy"}
    assert dep["redhat.java"] == {"redhat.dep1", "redhat.dep2"}


def test_read_extension_manifests_missing_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("VSCODE_EXTENSIONS", str(tmp_path / "nope"))
    assert read_extension_manifests("code") == {}


# --- #2: честный замер с фолбэком -------------------------------------------


def test_footprint_prefers_private_ws(monkeypatch):
    monkeypatch.setattr(core.vscode, "code_private_ws_mb", lambda cli: (321, 7))
    monkeypatch.setattr(
        core.vscode,
        "code_memory_mb",
        lambda cli: (_ for _ in ()).throw(AssertionError("не должно вызваться")),
    )
    assert core.vscode.code_footprint_mb("code") == (321, 7)


def test_footprint_falls_back_to_tasklist(monkeypatch):
    monkeypatch.setattr(core.vscode, "code_private_ws_mb", lambda cli: (0, 0))
    monkeypatch.setattr(core.vscode, "code_memory_mb", lambda cli: (999, 12))
    assert core.vscode.code_footprint_mb("code") == (999, 12)


# --- #16: JSON Schema карты категорий ---------------------------------------


def test_schema_file_is_valid_json():
    schema = json.loads((DATA_DIR / "categories.schema.json").read_text(encoding="utf-8"))
    assert schema["type"] == "object"
    assert "always_on" in schema["required"]
    assert "categories" in schema["required"]


def test_shipped_categories_conform_to_schema_structure():
    """Лёгкая проверка без jsonschema-зависимости: реальный categories.json
    удовлетворяет ключевым инвариантам схемы (форма и валидные id)."""
    data = json.loads(CATEGORIES_FILE.read_text(encoding="utf-8-sig"))
    assert data.get("$schema") == "./categories.schema.json"
    assert isinstance(data["always_on"]["extensions"], list)
    for ext in data["always_on"]["extensions"]:
        assert core.valid_ext_id(ext), ext
    for key, cat in data["categories"].items():
        assert key == key.lower() and key.replace("_", "").isalnum()
        assert cat["title"]
        for ext in cat["extensions"]:
            assert core.valid_ext_id(ext), ext
