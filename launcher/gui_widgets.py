# -*- coding: utf-8 -*-
"""GUI-виджеты и мелкие хелперы лейаута.

CategoryCard — кликабельная карточка стека, самая заметная сущность окна.
Три _card/_hline/_wrap — микро-фабрики, чтобы не повторять
setObjectName и setSizePolicy повсюду.
"""
from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QCheckBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLayout,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .categories import WEIGHT, WEIGHT_HELP, WEIGHT_LABEL
from .i18n import _


# Цвета переключателя берём из активной палитры (обновляется при смене темы).
_SWITCH = {"track": "#45475a", "accent": "#cba6f7", "knob": "#11111b",
           "knob_off": "#cdd6f4"}


def set_switch_palette(p: dict) -> None:
    """Синхронизировать цвета ToggleSwitch с текущей палитрой темы."""
    _SWITCH.update(track=p["track"], accent=p["accent"],
                   knob=p["accent_text"], knob_off=p["subtext"])


class ToggleSwitch(QCheckBox):
    """Переключатель-«тумблер»: рисуем дорожку и бегунок вместо квадратной
    галочки. Для семантики вкл/выкл стека это яснее — форма сразу читается как
    рычажок. Ведёт себя как обычный QCheckBox (isChecked/toggle/stateChanged),
    поэтому карточка и остальной код не меняются."""

    _W, _H = 42, 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self._W, self._H)

    def sizeHint(self):
        return QSize(self._W, self._H)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        r = self.rect().adjusted(1, 1, -1, -1)
        track = QColor(_SWITCH["accent"] if on else _SWITCH["track"])
        if not self.isEnabled():
            track.setAlpha(90)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.right() - d - 2 if on else r.left() + 3
        p.setBrush(QColor(_SWITCH["knob"] if on else _SWITCH["knob_off"]))
        p.drawEllipse(x, r.top() + 3, d, d)


# --- микро-фабрики виджетов ------------------------------------------------

def _card() -> QFrame:
    """QFrame с закруглённой рамкой (QSS: #Card)."""
    f = QFrame(); f.setObjectName("Card")
    return f


class FlowLayout(QLayout):
    """Лейаут, раскладывающий карточки слева-направо с переносом по ширине —
    как строки текста. На широком окне стеки идут в 2–3 колонки, на узком — в
    одну; scroll становится короче, а горизонтальное место не пустует.

    Скрытые виджеты (фильтр поиска) пропускаются — без «дыр» в сетке. Высота
    строки = максимум по её элементам, поэтому карточки разной высоты не ломают
    раскладку. Классический паттерн Qt FlowLayout + пропуск невидимых."""

    def __init__(self, parent=None, margin=0, spacing=10):
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            w = item.widget()
            if w is not None and not w.isVisible():
                continue
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        x0 = rect.x() + m.left()
        right = rect.right() - m.right()
        x = x0
        y = rect.y() + m.top()
        row: list = []          # элементы текущего ряда: (item, x, width)
        line_height = 0

        def flush():
            # Все карточки ряда — одной высоты (по самой высокой): ровная сетка,
            # без рваного низа. Содержимое карточек прижато кверху (stretch),
            # поэтому лишняя высота не «размазывает» элементы по центру.
            nonlocal x, y, row, line_height
            if not test_only:
                for it, ix, iw in row:
                    it.setGeometry(QRect(ix, y, iw, line_height))
            y += line_height + self._spacing
            row = []; line_height = 0; x = x0

        for item in self._items:
            w = item.widget()
            if w is not None and not w.isVisible():
                continue   # скрытые фильтром — не занимают место
            hint = item.sizeHint()
            iw = hint.width()
            # heightForWidth даёт корректную высоту при фактической ширине.
            ih = item.heightForWidth(iw) if item.hasHeightForWidth() else hint.height()
            if x + iw > right and row:
                flush()
            row.append((item, x, iw))
            x += iw + self._spacing
            line_height = max(line_height, ih)
        if row:
            flush()
        return y - self._spacing - rect.y() + m.bottom()


def _hline() -> QFrame:
    """Тонкая горизонтальная линия-разделитель (QSS: #HLine)."""
    ln = QFrame(); ln.setObjectName("HLine"); ln.setFixedHeight(1)
    return ln


def _wrap(lbl: QLabel) -> QLabel:
    """Ignored по горизонтали разрешает лейблу переносить текст,
    а не тянуть окно."""
    lbl.setWordWrap(True)
    lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return lbl


# --- CategoryCard ----------------------------------------------------------

class CategoryCard(QFrame):
    """Кликабельная карточка стека: галочка + название + бейджи."""

    def __init__(self, key: str, cat: dict, inst: int, total: int,
                 on_toggle, on_details):
        super().__init__()
        self.setObjectName("CatCard")
        self.setProperty("on", "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Минимальная ширина под сетку-флоу; фактическую задаёт окно по колонкам.
        self.setMinimumWidth(320)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._on_toggle = on_toggle
        weight = WEIGHT.get(key, "light")
        # Текст для поиска: ключ, название, заметка и id расширений стека.
        self.search_text = " ".join([
            key, cat.get("title", ""), cat.get("note", ""),
            " ".join(cat.get("extensions", [])),
        ]).lower()

        # Внешний контейнер: цветная полоска нагрузки слева (flush) + контент.
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        strip = QFrame(); strip.setObjectName(f"Strip_{weight}")
        strip.setFixedWidth(4)
        strip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        outer.addWidget(strip)
        inner = QWidget(); inner.setObjectName("CatInner")
        # Вертикальная структура: верхний ряд (тумблер + название + бейджи +
        # «Подробнее») и заметка под ним на всю ширину. Прижим кверху (stretch)
        # держит содержимое сверху, когда карточку растягивают до высоты ряда —
        # тогда карточки в ряду ровные, а элементы не «плавают» по центру.
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(7)
        outer.addWidget(inner, 1)

        # Ряд 1: тумблер + название (растягивается) + счётчик установленных.
        # Название держим на своей строке почти во всю ширину — не обрезается.
        top = QHBoxLayout(); top.setSpacing(10)
        self.cb = ToggleSwitch()
        note_txt = cat.get("note", "")
        check_help = _("Галочка ВКЛючает этот стек в запускаемом VS Code. "
                       "Снятая — расширения стека уйдут в --disable-extension "
                       "(не удалятся, только не загрузятся в этой сессии).")
        self.cb.setToolTip(check_help + (f"\n\n{note_txt}" if note_txt else ""))
        self.cb.stateChanged.connect(self._changed)
        top.addWidget(self.cb, 0, Qt.AlignmentFlag.AlignVCenter)

        title = QLabel(cat.get("title", key)); title.setObjectName("CatTitle")
        title.setToolTip(cat.get("title", key))
        top.addWidget(title, 1, Qt.AlignmentFlag.AlignVCenter)

        self._total = total
        self.cnt = QLabel(); self.cnt.setObjectName("Count")
        top.addWidget(self.cnt, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(top)

        # Ряд 2: метка нагрузки + заметка (растягивается) + «Подробнее».
        bottom = QHBoxLayout(); bottom.setSpacing(10)
        wl = QLabel(_(WEIGHT_LABEL[weight])); wl.setObjectName(f"W{weight}")
        wl.setToolTip(_(WEIGHT_HELP.get(weight, "")))
        bottom.addWidget(wl, 0, Qt.AlignmentFlag.AlignTop)

        note = QLabel(cat.get("note", "")); note.setObjectName("CatNote")
        note.setWordWrap(True)
        # Preferred/Minimum + wordWrap: высота считается по фактической ширине
        # карточки (heightForWidth), без раздувания, как было с Ignored.
        note.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        note.setAlignment(Qt.AlignmentFlag.AlignTop)
        bottom.addWidget(note, 1)

        info = QPushButton(_("Подробнее")); info.setObjectName("Ghost")
        info.setCursor(Qt.CursorShape.PointingHandCursor)
        info.setToolTip(_("Что за расширения в стеке и зачем они: описание "
                          "каждого, ссылка на маркетплейс, установка и удаление."))
        info.clicked.connect(on_details)
        bottom.addWidget(info, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(bottom)
        lay.addStretch(1)

        self.set_installed(inst)

    def is_installed(self) -> bool:
        """Есть ли у стека хоть одно установленное расширение — для фильтра
        «Установленные / Не установленные»."""
        return getattr(self, "_inst", 0) > 0

    def set_installed(self, inst: int):
        self._inst = inst
        total = self._total
        if inst:
            self.cnt.setText(f"{inst}/{total}"); self.cnt.setObjectName("Count")
            self.cnt.setToolTip(_("Установлено {inst} из {total} расширений стека. "
                                  "Выключение стека коснётся только этих "
                                  "установленных.").format(inst=inst, total=total))
            self.setToolTip("")
        else:
            self.cnt.setText(_("нет")); self.cnt.setObjectName("Woff")
            self.cnt.setToolTip(_("Ни одно из {total} расширений стека не "
                                  "установлено.").format(total=total))
            self.setToolTip(_("Расширения этого стека не установлены — галочка "
                              "ни на что не влияет. Поставить их можно в "
                              "«Подробнее» → «Установить недостающие»."))
        self.cnt.style().unpolish(self.cnt); self.cnt.style().polish(self.cnt)

    def _changed(self):
        self.setProperty("on", "true" if self.cb.isChecked() else "false")
        self.style().unpolish(self); self.style().polish(self)
        self._on_toggle()

    def mousePressEvent(self, e):
        self.cb.toggle()
        super().mousePressEvent(e)

    def enterEvent(self, e):
        # Приподнимаем карточку тенью при наведении.
        eff = QGraphicsDropShadowEffect(self)
        eff.setBlurRadius(26); eff.setXOffset(0); eff.setYOffset(6)
        # Тонированная под акцент мягкая тень — карточка «приподнимается»
        # заметно, но без грубого чёрного пятна.
        c = QColor(_SWITCH["accent"]); c.setAlpha(70)
        eff.setColor(c)
        self.setGraphicsEffect(eff)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.setGraphicsEffect(None)
        super().leaveEvent(e)

    def isChecked(self):
        return self.cb.isChecked()

    def setChecked(self, v):
        self.cb.setChecked(v)
