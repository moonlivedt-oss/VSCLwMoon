# -*- coding: utf-8 -*-
"""Оболочка окна: навигация слева, страницы, секции, плитки, баннер с пейзажем.

Язык оформления взят из панелей vscode-bg и cpp-docs-panel: слева колонка
вкладок с иконками-стикерами и счётчиками, справа страница с крупным заголовком
и подписью, содержимое — в секциях-карточках (сворачиваемых), редкие действия
спрятаны в меню «⋯», а не выставлены рядами кнопок. Здесь только виджеты без
логики лаунчера: их собирает gui.py.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .paths import ASSETS_DIR

ICON_DIR = ASSETS_DIR / "icons"
PALETTE_DIR = ASSETS_DIR / "palettes"
_cache: dict[tuple, QPixmap] = {}


def pixmap(path, w: int = 0, h: int = 0) -> QPixmap | None:
    """Картинка из assets с масштабом и кэшем. Нет файла — None (оформление
    не должно ломать окно)."""
    key = (str(path), w, h)
    if key in _cache:
        return _cache[key]
    pm = QPixmap(str(path))
    if pm.isNull():
        return None
    if w and h:
        pm = pm.scaled(
            w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
    elif h:
        pm = pm.scaledToHeight(h, Qt.TransformationMode.SmoothTransformation)
    elif w:
        pm = pm.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)
    _cache[key] = pm
    return pm


def icon(name: str, size: int = 22) -> QPixmap | None:
    return pixmap(ICON_DIR / f"{name}.png", size, size)


def _repolish(w: QWidget) -> None:
    st = w.style()
    if st is not None:
        st.unpolish(w)
        st.polish(w)


# --- навигация ------------------------------------------------------------------


class NavItem(QPushButton):
    """Вкладка слева: плитка-иконка, подпись, счётчик."""

    def __init__(self, key: str, text: str, icon_name: str, tip: str = ""):
        super().__init__()
        self.key = key
        self.setObjectName("NavItem")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(40)
        if tip:
            self.setToolTip(tip)
        self.setAccessibleName(text)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 5, 8, 5)
        lay.setSpacing(9)
        self.ic = QLabel()
        self.ic.setObjectName("NavIcon")
        self.ic.setFixedSize(30, 30)
        self.ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = icon(icon_name, 23)
        if pm is not None:
            self.ic.setPixmap(pm)
        self.txt = QLabel(text)
        self.txt.setObjectName("NavText")
        self.badge = QLabel()
        self.badge.setObjectName("NavBadge")
        self.badge.setVisible(False)
        self.badge.setFixedHeight(18)
        for w in (self.ic, self.txt, self.badge):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self.ic)
        lay.addWidget(self.txt, 1)
        lay.addWidget(self.badge)
        self.toggled.connect(self._sync)

    def _sync(self, on: bool):
        for w in (self.ic, self.txt):
            w.setProperty("on", "true" if on else "false")
            _repolish(w)

    def set_badge(self, value) -> None:
        text = "" if value in (None, 0, "", "0") else str(value)
        self.badge.setText(text)
        self.badge.setVisible(bool(text))


class NavRail(QWidget):
    """Колонка вкладок. page_changed(key) — при выборе вкладки."""

    page_changed = pyqtSignal(str)

    def __init__(self, width: int = 190):
        super().__init__()
        self.setObjectName("Nav")
        self.setFixedWidth(width)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(10, 12, 10, 12)
        self._lay.setSpacing(4)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.items: dict[str, NavItem] = {}
        self._tail = QVBoxLayout()
        self._tail.setSpacing(4)
        self._lay.addStretch(1)
        self._lay.addLayout(self._tail)

    def add(self, key: str, text: str, icon_name: str, tip: str = "", bottom: bool = False):
        it = NavItem(key, text, icon_name, tip)
        self._group.addButton(it)
        it.clicked.connect(lambda _c=False, k=key: self.page_changed.emit(k))
        if bottom:
            self._tail.addWidget(it)
        else:
            self._lay.insertWidget(self._lay.count() - 2, it)
        self.items[key] = it
        return it

    def select(self, key: str) -> None:
        it = self.items.get(key)
        if it is not None:
            it.setChecked(True)


# --- страницы и секции -------------------------------------------------------------


def page_header(title: str, sub: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(2, 0, 2, 4)
    lay.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("PageTitle")
    lay.addWidget(t)
    if sub:
        s = QLabel(sub)
        s.setObjectName("PageSub")
        s.setWordWrap(True)
        lay.addWidget(s)
    return w


class Section(QFrame):
    """Секция-карточка с заголовком. collapsible — заголовок сворачивает тело."""

    def __init__(
        self,
        title: str,
        collapsible: bool = False,
        opened: bool = True,
        trailing: QWidget | None = None,
    ):
        super().__init__()
        self.setObjectName("Sec")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 10, 0)
        self._title = title
        self._collapsible = collapsible
        if collapsible:
            self.head_btn = QPushButton()
            self.head_btn.setObjectName("SecHead")
            self.head_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.head_btn.clicked.connect(self.toggle)
            head.addWidget(self.head_btn, 1)
        else:
            lbl = QLabel(title)
            lbl.setObjectName("SecTitle")
            lbl.setContentsMargins(14, 11, 0, 4)
            head.addWidget(lbl, 1)
        if trailing is not None:
            head.addWidget(trailing, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(head)
        self.body_w = QWidget()
        self.body_w.setObjectName("CatInner")
        self.body = QVBoxLayout(self.body_w)
        self.body.setContentsMargins(14, 2, 14, 12)
        self.body.setSpacing(8)
        outer.addWidget(self.body_w)
        self._open = opened
        self._apply()

    def _apply(self):
        self.body_w.setVisible(self._open)
        if self._collapsible:
            # ▸/▾ — геометрические символы, а не эмодзи.
            self.head_btn.setText(("▾  " if self._open else "▸  ") + self._title)

    def toggle(self):
        self._open = not self._open
        self._apply()

    def set_open(self, on: bool):
        self._open = on
        self._apply()


class Pill(QFrame):
    """Переключатель-пилюля: тумблер + подпись («Фон и эффекты включены»)."""

    def __init__(self, switch, text: str, tip: str = ""):
        super().__init__()
        self.setObjectName("Pill")
        self.switch = switch
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 12, 6)
        lay.setSpacing(8)
        lay.addWidget(switch)
        self.lbl = QLabel(text)
        self.lbl.setObjectName("PillText")
        lay.addWidget(self.lbl)
        if tip:
            self.setToolTip(tip)
            switch.setToolTip(tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        switch.toggled.connect(self._sync)
        self._sync(switch.isChecked())

    def _sync(self, on: bool):
        self.setProperty("on", "true" if on else "false")
        _repolish(self)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.switch.toggle()
        super().mousePressEvent(e)


class Tile(QFrame):
    """Плитка-действие: иконка, заголовок, пояснение, крупное число справа.
    Вся плитка кликабельна — отдельная кнопка не нужна."""

    clicked = pyqtSignal()

    def __init__(self, icon_name: str, title: str, text: str = "", num: str = ""):
        super().__init__()
        self.setObjectName("Tile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 14, 10)
        lay.setSpacing(12)
        ic = QLabel()
        ic.setObjectName("NavIcon")
        ic.setFixedSize(40, 40)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = icon(icon_name, 30)
        if pm is not None:
            ic.setPixmap(pm)
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("TileTitle")
        col.addWidget(self.title_lbl)
        self.text_lbl = QLabel(text)
        self.text_lbl.setObjectName("CatNote")
        self.text_lbl.setWordWrap(True)
        col.addWidget(self.text_lbl)
        lay.addLayout(col, 1)
        self.num_lbl = QLabel(num)
        self.num_lbl.setObjectName("TileNum")
        self.num_lbl.setVisible(bool(num))
        lay.addWidget(self.num_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_num(self, num) -> None:
        text = "" if num in (None, "") else str(num)
        self.num_lbl.setText(text)
        self.num_lbl.setVisible(bool(text))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clicked.emit()
            return
        super().keyPressEvent(e)


def menu_button(items, tip: str = "", text: str = "···", obj: str = "Round") -> QPushButton:
    """Кнопка «⋯» с меню: items — [(текст, слот) | None для разделителя].
    Редкие действия живут здесь, а не рядом кнопок."""
    b = QPushButton(text)
    b.setObjectName(obj)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    m = QMenu(b)
    for it in items:
        if it is None:
            m.addSeparator()
            continue
        label, slot = it[0], it[1]
        act = m.addAction(label)
        if len(it) > 2 and it[2]:
            act.setToolTip(it[2])
        act.triggered.connect(lambda _c=False, f=slot: f())
    m.setToolTipsVisible(True)
    b.setMenu(m)
    return b


# --- баннер с пейзажем ----------------------------------------------------------


class Banner(QFrame):
    """Карточка с пейзажем палитры на фоне и затемнением к краю, как главная
    cpp-docs-panel. Содержимое — обычная раскладка поверх картинки."""

    def __init__(self, palette_key: str = "mocha", radius: int = 16):
        super().__init__()
        self.setObjectName("CatInner")
        self._radius = radius
        self._bg = QColor("#181825")
        self._accent = QColor("#cba6f7")
        self._pm = None
        self.set_palette(palette_key)

    def set_palette(self, key: str, bg: str = "", accent: str = "") -> None:
        self._pm = pixmap(PALETTE_DIR / f"{key}.jpg") or pixmap(PALETTE_DIR / "default.jpg")
        if bg:
            self._bg = QColor(bg)
        if accent:
            self._accent = QColor(accent)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self._radius, self._radius)
        p.setClipPath(path)
        if self._pm is not None:
            # «cover»: заполнить без искажений, лишнее обрезать по центру.
            src = self._pm.size()
            scale = max(r.width() / src.width(), r.height() / src.height())
            w, h = src.width() * scale, src.height() * scale
            target = QRectF(r.center().x() - w / 2, r.center().y() - h * 0.62, w, h)
            p.drawPixmap(target, self._pm, QRectF(self._pm.rect()))
        grad = QLinearGradient(r.topLeft(), r.topRight())
        c0 = QColor(self._bg)
        c0.setAlpha(238)
        c1 = QColor(self._bg)
        c1.setAlpha(150)
        c2 = QColor(self._bg)
        c2.setAlpha(60)
        grad.setColorAt(0.0, c0)
        grad.setColorAt(0.55, c1)
        grad.setColorAt(1.0, c2)
        p.fillRect(r, grad)
        edge = QColor(self._accent)
        edge.setAlpha(90)
        p.setClipping(False)
        p.setPen(edge)
        p.drawPath(path)
        p.end()


class PaletteCard(QFrame):
    """Превью палитры: пейзаж, точки цветов, название. Клик — выбрать."""

    picked = pyqtSignal(str)

    def __init__(self, key: str, name: str, colors: list[str], selected: bool = False):
        super().__init__()
        self.key = key
        self.setObjectName("PalCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(QSize(172, 124))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 8)
        lay.setSpacing(5)
        img = QLabel()
        img.setFixedSize(162, 74)
        pm = pixmap(PALETTE_DIR / f"{key}.jpg")
        if pm is not None:
            pm = pm.scaled(
                162,
                74,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            rounded = QPixmap(162, 74)
            rounded.fill(Qt.GlobalColor.transparent)
            pp = QPainter(rounded)
            pp.setRenderHint(QPainter.RenderHint.Antialiasing)
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(0, 0, 162, 74), 9, 9)
            pp.setClipPath(clip)
            pp.drawPixmap(0, 0, pm, (pm.width() - 162) // 2, (pm.height() - 74) // 2, 162, 74)
            pp.end()
            img.setPixmap(rounded)
        lay.addWidget(img)
        row = QHBoxLayout()
        row.setContentsMargins(6, 0, 6, 0)
        row.setSpacing(4)
        for c in colors[:4]:
            dot = QLabel()
            dot.setFixedSize(12, 12)
            dot.setStyleSheet(f"background:{c}; border-radius:6px;")
            row.addWidget(dot)
        row.addSpacing(6)
        nm = QLabel(name)
        nm.setObjectName("TileTitle")
        row.addWidget(nm, 1)
        lay.addLayout(row)
        self.set_selected(selected)

    def set_selected(self, on: bool) -> None:
        self.setProperty("on", "true" if on else "false")
        _repolish(self)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self.key)
        super().mousePressEvent(e)


def segmented(options, current, on_pick) -> QFrame:
    """Сегменты вместо короткого выпадающего списка: [(ключ, подпись)]."""
    seg = QFrame()
    seg.setObjectName("Segmented")
    lay = QHBoxLayout(seg)
    lay.setContentsMargins(3, 3, 3, 3)
    lay.setSpacing(3)
    group = QButtonGroup(seg)
    group.setExclusive(True)
    seg.buttons = {}
    for key, label in options:
        b = QPushButton(label)
        b.setObjectName("SegBtn")
        b.setCheckable(True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setChecked(key == current)
        b.clicked.connect(lambda _c=False, k=key: on_pick(k))
        group.addButton(b)
        lay.addWidget(b)
        seg.buttons[key] = b
    seg._group = group
    return seg
