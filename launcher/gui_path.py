# -*- coding: utf-8 -*-
"""Окно «Починка PATH»: проблемы по группам, предпросмотр, починка, откат.

Логика — в path_doctor.py. Здесь: список проблем с галочками (по группам: кто
что перекрывает, мёртвые записи, дубли, подсказки), живой предпросмотр «что
изменится» (какие команды начнут запускать другой файл) и одна кнопка. Откат
прошлых правок — в меню «···».
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QFrame,
    QVBoxLayout,
    QWidget,
)

from . import path_doctor as pd
from .gui_cpp import Mascot
from .gui_shell import Section, menu_button
from .gui_workers import FnWorker
from .i18n import _

LEVEL_TAG = {"error": "Wheavy", "warn": "Wmedium", "info": "Woff"}

GROUPS = (
    (
        "conflict",
        ("no_system32", "toolchain_shadow", "gcc_mix", "store_alias", "shadow_system", "java_home"),
    ),
    ("dead", ("missing", "unresolved", "file", "offline")),
    ("junk", ("dup", "cross_dup", "empty", "tidy")),
    ("hint", ("length", "newer_hidden", "python_version")),
)


def _group_title(key: str) -> str:
    return {
        "conflict": _("Кто что перекрывает"),
        "dead": _("Мёртвые записи"),
        "junk": _("Дубли и мусор"),
        "hint": _("Подсказки"),
    }[key]


def _level_name(level: str) -> str:
    return {"error": _("ошибка"), "warn": _("внимание"), "info": _("к сведению")}.get(level, "-")


class PathDoctorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers: list[QThread] = []
        self._report: pd.Report | None = None
        self._boxes: dict[str, QCheckBox] = {}
        self._open = True
        self.finished.connect(lambda _=0: setattr(self, "_open", False))
        self.setWindowTitle(_("Починка PATH"))
        self.resize(860, 760)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 14)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(12)
        self.icon = Mascot("think", 60)
        head.addWidget(self.icon)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(_("Починка PATH"))
        t.setObjectName("PageTitle")
        col.addWidget(t)
        self.status = QLabel(_("Проверяю системный и ваш PATH…"))
        self.status.setObjectName("PageSub")
        self.status.setWordWrap(True)
        col.addWidget(self.status)
        head.addLayout(col, 1)
        lay.addLayout(head)
        intro = QLabel(
            _(
                "Windows ищет команду сначала в системном PATH, потом в вашем — слева направо. "
                "Здесь видно, что мешает, и что именно изменится. Каждое исправление можно "
                "снять галочкой; перед записью делается бэкап, откат — в меню «···»."
            )
        )
        intro.setObjectName("CatNote")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.holder = QWidget()
        self.holder.setObjectName("CatInner")
        self.list_lay = QVBoxLayout(self.holder)
        self.list_lay.setContentsMargins(0, 0, 6, 0)
        self.list_lay.setSpacing(8)
        sc.setWidget(self.holder)
        lay.addWidget(sc, 1)

        self.preview_sec = Section(_("Что изменится"))
        self.preview_lbl = QLabel()
        self.preview_lbl.setObjectName("CatNote")
        self.preview_lbl.setWordWrap(True)
        self.preview_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview_sec.body.addWidget(self.preview_lbl)
        lay.addWidget(self.preview_sec)

        bar = QHBoxLayout()
        self.more = menu_button(
            [(_("Показать итоговый PATH"), self._show_result)],
            tip=_("Итоговый PATH и откат прошлых правок"),
        )
        bar.addWidget(self.more)
        bar.addStretch()
        self.fix_btn = QPushButton(_("Починить"))
        self.fix_btn.setObjectName("Accent")
        self.fix_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fix_btn.clicked.connect(self._apply)
        self.fix_btn.setEnabled(False)
        bar.addWidget(self.fix_btn)
        lay.addLayout(bar)
        self._rescan()

    # --- фон -------------------------------------------------------------------

    def _bg(self, fn, done):
        w = FnWorker(fn)
        w.done.connect(lambda res: self._open and done(res))
        w.finished.connect(lambda x=w: self._workers.remove(x) if x in self._workers else None)
        self._workers.append(w)
        w.start()

    def done(self, r):
        # Потоки отдаём главному окну: объект диалога удалится, а работающий
        # QThread уничтожать нельзя.
        keep = getattr(self.parent(), "_install_threads", None)
        for w in list(self._workers):
            if w.isRunning():
                if keep is not None:
                    keep.append(w)
                else:
                    w.wait()
        super().done(r)

    def _rescan(self):
        self.icon.set("think")
        self.fix_btn.setEnabled(False)
        self.status.setText(_("Проверяю системный и ваш PATH…"))
        self._bg(pd.analyze, self._on_report)

    # --- отчёт -------------------------------------------------------------------

    def _clear(self):
        while self.list_lay.count():
            it = self.list_lay.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()

    def _on_report(self, rep):
        if not isinstance(rep, pd.Report):
            self.status.setText(_("Проверка не удалась: {e}").format(e=rep))
            return
        self._report = rep
        self._boxes = {}
        self._clear()
        s = pd.summary(rep)
        if not rep.issues:
            self.icon.set("win")
            self.status.setText(_("PATH в порядке: мусора и конфликтов нет."))
        else:
            self.icon.set("search")
            self.status.setText(
                _("Найдено: {n}. Исправить можно {f}, по умолчанию отмечено {s}.").format(
                    n=s["total"], f=s["fixable"], s=s["selected"]
                )
            )
        for gkey, kinds in GROUPS:
            items = [i for i in rep.issues if i.kind in kinds]
            if not items:
                continue
            sec = Section(
                f"{_group_title(gkey)} ({len(items)})",
                collapsible=True,
                opened=gkey != "junk" or len(items) <= 6,
            )
            for iss in items:
                sec.body.addLayout(self._issue_row(iss))
            self.list_lay.addWidget(sec)
        self.list_lay.addStretch()
        self._rebuild_menu()
        self._update_preview()

    def _issue_row(self, iss: pd.Issue) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(1)
        top = QHBoxLayout()
        top.setSpacing(8)
        if iss.fixable:
            box = QCheckBox(iss.title)
            box.setChecked(iss.selected)
            box.toggled.connect(self._update_preview)
            self._boxes[iss.id] = box
            top.addWidget(box, 1)
        else:
            lbl = QLabel(iss.title)
            lbl.setObjectName("TileTitle")
            top.addWidget(lbl, 1)
        if iss.admin:
            uac = QLabel("UAC")
            uac.setObjectName("Wmedium")
            uac.setToolTip(_("Меняется системный PATH — нужны права администратора."))
            top.addWidget(uac)
        tag = QLabel(_level_name(iss.level))
        tag.setObjectName(LEVEL_TAG.get(iss.level, "Woff"))
        top.addWidget(tag)
        col.addLayout(top)
        d = QLabel(iss.detail)
        d.setObjectName("CatNote")
        d.setWordWrap(True)
        d.setContentsMargins(26 if iss.fixable else 0, 0, 0, 4)
        d.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(d)
        return col

    def _selected(self) -> set[str]:
        return {iid for iid, b in self._boxes.items() if b.isChecked()}

    def _update_preview(self):
        if self._report is None:
            return
        ids = self._selected()
        pv = pd.preview(self._report, ids)
        lines = pd.describe_preview(pv)
        if pv["lost"]:
            lines.insert(0, _("Внимание: после починки пропадут команды — снимите лишние галочки."))
        self.preview_lbl.setText("\n".join(lines))
        n = len(ids)
        self.fix_btn.setEnabled(bool(n) and (pv["machine_changed"] or pv["user_changed"]))
        self.fix_btn.setText(_("Починить ({n})").format(n=n) if n else _("Починить"))

    def _rebuild_menu(self):
        m = self.more.menu()
        m.clear()
        m.addAction(_("Показать итоговый PATH"), self._show_result)
        backups = pd.list_backups()
        if backups:
            m.addSeparator()
            sub = m.addMenu(_("Откатить к бэкапу"))
            for b in backups:
                scope = _("системный") if b["scope"] == "machine" else _("ваш")
                sub.addAction(f"{b['time']} · {scope}", lambda f=b["file"]: self._restore(f))

    # --- действия -----------------------------------------------------------------

    def _show_result(self):
        if self._report is None:
            return
        pv = pd.preview(self._report, self._selected())
        text = (
            _("Системный PATH:")
            + "\n  "
            + "\n  ".join(pd.split_raw(pv["machine"]))
            + "\n\n"
            + _("Ваш PATH:")
            + "\n  "
            + "\n  ".join(pd.split_raw(pv["user"]))
        )
        dlg = QDialog(self)
        dlg.setWindowTitle(_("Итоговый PATH"))
        dlg.resize(760, 560)
        v = QVBoxLayout(dlg)
        box = QPlainTextEdit(text)
        box.setObjectName("Log")
        box.setReadOnly(True)
        v.addWidget(box)
        dlg.exec()

    def _apply(self):
        if self._report is None:
            return
        ids = self._selected()
        pv = pd.preview(self._report, ids)
        msg = "\n".join(pd.describe_preview(pv))
        if pv["lost"]:
            msg = _("Пропадут команды: {t}.").format(t=", ".join(pv["lost"])) + "\n\n" + msg
        r = QMessageBox.question(
            self,
            _("Починить PATH?"),
            _(
                "Будет исправлено пунктов: {n}.\n\n{msg}\n\nПеред записью сохранится бэкап. "
                "Продолжить?"
            ).format(n=len(ids), msg=msg),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return
        self.fix_btn.setEnabled(False)
        self.status.setText(_("Записываю…"))
        report = self._report
        self._bg(lambda: pd.apply(report, ids), self._on_applied)

    def _on_applied(self, res):
        ok, msg = res if isinstance(res, tuple) else (False, str(res))
        (QMessageBox.information if ok else QMessageBox.warning)(self, _("Починка PATH"), msg)
        self._rescan()

    def _restore(self, file: str):
        r = QMessageBox.question(
            self,
            _("Откатить PATH?"),
            _("Вернуть PATH из бэкапа?\n{f}\n\nТекущее значение тоже сохранится в бэкап.").format(
                f=file
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return
        self._bg(lambda: pd.restore_backup(file), self._on_applied)
