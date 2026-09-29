# -*- coding: utf-8 -*-
"""Оболочка окна: палитры, навигация, секции, страницы главного окна."""

import logging

import pytest
from PyQt6.QtWidgets import QApplication

from launcher import gui, gui_shell, theme
from launcher.categories import build_ext_index
from launcher.config import migrate_config


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("key", list(theme.PALETTE_SETS))
@pytest.mark.parametrize("mode", ["dark", "light"])
def test_every_palette_builds_qss(key, mode):
    p = theme.make_palette(mode, key)
    for field in ("bg", "surface", "text", "accent", "accent_text", "border", "track"):
        assert p[field].startswith("#")
    assert "QPushButton#NavItem" in theme.build_qss(p)


def test_light_palette_keeps_light_background():
    p = theme.make_palette("light", "gruvbox")
    assert p["bg"] == theme.PALETTE_LIGHT["bg"]
    assert p["accent"] != theme.PALETTE_SETS["gruvbox"]["ac"]  # затемнён под контраст


def test_palette_names_bilingual():
    assert theme.palette_name("forest", "ru") == "Лес"
    assert theme.palette_name("forest", "en") == "Forest"
    assert theme.palette_name("nope", "en") == "Catppuccin"


def test_palette_images_exist():
    for key in theme.PALETTE_SETS:
        assert (gui_shell.PALETTE_DIR / f"{key}.jpg").is_file()


def test_nav_rail_select_and_badge(app):
    rail = gui_shell.NavRail()
    got = []
    rail.page_changed.connect(got.append)
    a = rail.add("a", "A", "launch")
    rail.add("b", "B", "cpp", bottom=True)
    rail.items["b"].click()
    assert got == ["b"] and rail.items["b"].isChecked() and not a.isChecked()
    a.set_badge(3)
    assert a.badge.text() == "3" and not a.badge.isHidden()
    a.set_badge(0)
    assert a.badge.isHidden()


def test_section_collapses(app):
    s = gui_shell.Section("T", collapsible=True, opened=False)
    assert s.body_w.isHidden()
    s.toggle()
    assert not s.body_w.isHidden()
    assert s.head_btn.text().endswith("T")


def test_menu_button_runs_actions(app):
    hits = []
    b = gui_shell.menu_button(
        [("one", lambda: hits.append(1)), None, ("two", lambda: hits.append(2))]
    )
    acts = [a for a in b.menu().actions() if not a.isSeparator()]
    acts[1].trigger()
    assert hits == [2]


CATS = {
    "always_on": {"extensions": []},
    "categories": {"python": {"title": "Python", "extensions": ["ms-python.python"]}},
}


def _window():
    cfg = migrate_config({})
    W = gui._launcher_factory(
        CATS, "", cfg, build_ext_index(CATS), None, {}, {}, logging.getLogger("t"), {"fn": None}
    )
    w = W(background=False)
    w.show()
    return w, cfg


def test_window_pages_and_lazy_build(app):
    w, _cfg = _window()
    try:
        assert set(w._page_of) == {"launch", "cpp", "tools", "ext", "clean", "settings"}
        assert "tools" in w._page_builders  # «Языки» собирается при первом заходе
        w._goto("tools")
        assert "tools" not in w._page_builders
        assert w.nav.items["tools"].isChecked()
        w._goto("launch")
        assert w._page == "launch"
    finally:
        w.deleteLater()


def test_palette_switch_updates_config(app, monkeypatch):
    w, cfg = _window()
    try:
        monkeypatch.setattr(gui, "save_config", lambda c: None)
        w._set_palette("sunset")
        assert cfg["palette"] == "sunset" and w._pal["accent"] == theme.PALETTE_SETS["sunset"]["ac"]
        assert w._pal_cards["sunset"].property("on") == "true"
        w._set_theme("light")
        assert cfg["theme"] == "light" and w._pal["bg"] == theme.PALETTE_LIGHT["bg"]
    finally:
        app.setStyleSheet("")
        w.deleteLater()


def test_every_stack_has_english_text():
    from launcher.categories import load_categories

    cats, err = load_categories()
    assert not err
    for key, cat in [("always_on", cats["always_on"]), *cats["categories"].items()]:
        assert cat.get("title_en") and cat.get("note_en"), key


def test_cat_title_follows_language():
    from launcher import i18n
    from launcher.categories import cat_note, cat_title

    cat = {"title": "Лес", "title_en": "Forest", "note": "н", "note_en": "n"}
    try:
        i18n.set_language("en")
        assert cat_title(cat) == "Forest" and cat_note(cat) == "n"
        assert cat_title({"title": "Только RU"}) == "Только RU"
    finally:
        i18n.set_language("ru")
    assert cat_title(cat) == "Лес" and cat_title({}, "key") == "key"


def test_extension_descriptions_have_english():
    from launcher import i18n
    from launcher.categories import load_descriptions

    d = load_descriptions()
    assert set(d) == set(d.en), "у каждого описания должен быть английский вариант"
    try:
        i18n.set_language("en")
        assert d.get("ms-vscode.cpptools").startswith("the base")
        assert d.get("no.such-ext", "x") == "x"
    finally:
        i18n.set_language("ru")
    assert d["ms-vscode.cpptools"].startswith("база")


def test_no_emoji_in_data():
    import re
    from pathlib import Path

    rx = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
    for f in Path(__file__).resolve().parents[1].joinpath("data").glob("*.json"):
        assert not rx.search(f.read_text(encoding="utf-8")), f.name
