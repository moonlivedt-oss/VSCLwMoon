# -*- coding: utf-8 -*-
"""GUI-виджеты и мелкие хелперы лейаута.

CategoryCard — кликабельная карточка стека, самая заметная сущность окна.
Три _card/_hline/_wrap — микро-фабрики, чтобы не повторять
setObjectName и setSizePolicy повсюду.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .categories import WEIGHT, WEIGHT_HELP, WEIGHT_LABEL
from .i18n import _


# --- микро-фабрики виджетов ------------------------------------------------

def _card() -> QFrame:
    """QFrame с закруглённой рамкой (QSS: #Card)."""
    f = QFrame(); f.setObjectName("Card")
    return f


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
        lay = QHBoxLayout(inner)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(12)
        outer.addWidget(inner, 1)

        self.cb = QCheckBox()
        # Тултип галочки: сначала что делает галочка, затем заметка стека.
        note_txt = cat.get("note", "")
        check_help = _("Галочка ВКЛючает этот стек в запускаемом VS Code. "
                       "Снятая — расширения стека уйдут в --disable-extension "
                       "(не удалятся, только не загрузятся в этой сессии).")
        self.cb.setToolTip(check_help + (f"\n\n{note_txt}" if note_txt else ""))
        self.cb.stateChanged.connect(self._changed)
        lay.addWidget(self.cb, 0, Qt.AlignmentFlag.AlignVCenter)

        mid = QVBoxLayout(); mid.setSpacing(2)
        title = QLabel(cat.get("title", key)); title.setObjectName("CatTitle")
        note = QLabel(cat.get("note", "")); note.setObjectName("CatNote")
        note.setWordWrap(True)
        note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        mid.addWidget(title); mid.addWidget(note)
        lay.addLayout(mid, 1)

        wl = QLabel(_(WEIGHT_LABEL[weight])); wl.setObjectName(f"W{weight}")
        # Тултип нагрузки объясняет смысл цвета и выгоду держать стек выключенным.
        wl.setToolTip(_(WEIGHT_HELP.get(weight, "")))
        lay.addWidget(wl, 0, Qt.AlignmentFlag.AlignVCenter)

        self._total = total
        self.cnt = QLabel(); self.cnt.setObjectName("Count")
        lay.addWidget(self.cnt, 0, Qt.AlignmentFlag.AlignVCenter)
        self.set_installed(inst)

        info = QPushButton(_("Подробнее")); info.setObjectName("Ghost")
        info.setCursor(Qt.CursorShape.PointingHandCursor)
        info.setToolTip(_("Что за расширения в стеке и зачем они: описание "
                          "каждого, ссылка на маркетплейс, установка и удаление."))
        info.clicked.connect(on_details)
        lay.addWidget(info, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_installed(self, inst: int):
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
        eff.setBlurRadius(22); eff.setXOffset(0); eff.setYOffset(4)
        eff.setColor(QColor(0, 0, 0, 120))
        self.setGraphicsEffect(eff)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.setGraphicsEffect(None)
        super().leaveEvent(e)

    def isChecked(self):
        return self.cb.isChecked()

    def setChecked(self, v):
        self.cb.setChecked(v)
