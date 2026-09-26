# -*- coding: utf-8 -*-
"""Окно «Уборка»: предпросмотр мусора VS Code и удаление в Корзину.

Логика поиска — в cleanup.py (без GUI). Здесь только список с галочками по
группам, сводка и кнопка. Поиск и удаление идут в фоне: обход кэшей — это
десятки тысяч файлов.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from . import cleanup
from .gui_widgets import _hline, _wrap
from .gui_workers import FnWorker
from .i18n import _
from .vscode import code_gui_exe, extensions_dir, vscode_process_count, vscode_user_settings_path

MB = 1024 * 1024


def _mb(b: int) -> str:
    return _("{mb} МБ").format(mb=max(1, round(b / MB)) if b else 0)


class CleanupDialog(QDialog):
    def __init__(self, parent, code_cli):
        super().__init__(parent)
        self._cli = code_cli
        self._items: list[dict] = []
        self._worker = None
        self.setWindowTitle(_("Уборка VS Code"))
        self.resize(720, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 16)
        lay.setSpacing(12)
        ttl = QLabel(_("Уборка VS Code"))
        ttl.setObjectName("Title")
        lay.addWidget(ttl)
        note = _wrap(
            QLabel(
                _(
                    "Что VS Code накопил и сам не чистит: копии установщиков, данные "
                    "удалённых проектов, кэши движка, старые логи и версии расширений. "
                    "Всё это пересоздаётся при необходимости. Удаление — в Корзину, "
                    "только при закрытом VS Code."
                )
            )
        )
        note.setObjectName("Subtitle")
        lay.addWidget(note)
        lay.addWidget(_hline())

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([_("Что"), _("Размер")])
        self.tree.setColumnWidth(0, 520)
        self.tree.itemChanged.connect(self._on_changed)
        lay.addWidget(self.tree, 1)

        self.status = _wrap(QLabel(_("Ищу…")))
        self.status.setObjectName("CatNote")
        lay.addWidget(self.status)

        bar = QHBoxLayout()
        self.rescan_btn = QPushButton(_("Пересканировать"))
        self.rescan_btn.setObjectName("Ghost")
        self.rescan_btn.clicked.connect(self._scan)
        self.go_btn = QPushButton(_("В Корзину"))
        self.go_btn.setObjectName("Accent")
        self.go_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.go_btn.clicked.connect(self._apply)
        close = QPushButton(_("Закрыть"))
        close.setObjectName("Ghost")
        close.clicked.connect(self.reject)
        bar.addWidget(self.rescan_btn)
        bar.addStretch()
        bar.addWidget(self.go_btn)
        bar.addWidget(close)
        lay.addLayout(bar)
        self._scan()

    # --- поиск ---------------------------------------------------------
    def _scan(self):
        if self._worker is not None and self._worker.isRunning():
            return
        settings = vscode_user_settings_path(self._cli)
        if settings is None:
            self.status.setText(_("Не найдена папка данных VS Code (%APPDATA%)."))
            return
        user_data = settings.parent.parent
        ext_dir = extensions_dir(self._cli)
        exe = code_gui_exe(self._cli)
        self.go_btn.setEnabled(False)
        self.rescan_btn.setEnabled(False)
        self.status.setText(_("Ищу…"))
        self._worker = FnWorker(lambda: cleanup.scan(user_data, ext_dir, exe))
        self._worker.done.connect(self._on_scanned)
        self._worker.start()

    def _on_scanned(self, res):
        self.rescan_btn.setEnabled(True)
        if isinstance(res, Exception):
            self.status.setText(_("Ошибка поиска: {err}").format(err=res))
            return
        self._items = res
        self.tree.blockSignals(True)
        self.tree.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        for kind, size, n in cleanup.summarize(res):
            g = QTreeWidgetItem([f"{_(cleanup.KIND_TITLES.get(kind, kind))}  ({n})", _mb(size)])
            g.setFlags(g.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            g.setCheckState(0, Qt.CheckState.Checked)
            self.tree.addTopLevelItem(g)
            groups[kind] = g
        for idx, it in enumerate(res):
            label = it["note"] or it["path"]
            child = QTreeWidgetItem([label, _mb(it["bytes"])])
            child.setToolTip(0, it["path"])
            child.setData(0, Qt.ItemDataRole.UserRole, idx)
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            child.setCheckState(0, Qt.CheckState.Checked)
            groups[it["kind"]].addChild(child)
        self.tree.blockSignals(False)
        self._on_changed()

    def _selected(self) -> list[dict]:
        out = []
        for gi in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(gi)
            for ci in range(g.childCount()):
                c = g.child(ci)
                if c.checkState(0) == Qt.CheckState.Checked:
                    out.append(self._items[c.data(0, Qt.ItemDataRole.UserRole)])
        return out

    def _on_changed(self, *_args):
        sel = self._selected()
        total = sum(i["bytes"] for i in sel)
        if not self._items:
            self.status.setText(_("Убирать нечего — всё чисто."))
        else:
            self.status.setText(
                _("Выбрано: {n} · освободится {size}").format(n=len(sel), size=_mb(total))
            )
        self.go_btn.setEnabled(bool(sel))

    # --- удаление ------------------------------------------------------
    def _apply(self):
        sel = self._selected()
        if not sel:
            return
        if vscode_process_count(self._cli) > 0:
            QMessageBox.warning(
                self,
                _("Уборка VS Code"),
                _(
                    "VS Code запущен. Закройте его: кэши открытого редактора заняты "
                    "и удалятся не полностью."
                ),
            )
            return
        total = _mb(sum(i["bytes"] for i in sel))
        ok = QMessageBox.question(
            self,
            _("Уборка VS Code"),
            _("Переместить в Корзину {n} элементов ({size})?").format(n=len(sel), size=total),
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        paths = [i["path"] for i in sel]
        self.go_btn.setEnabled(False)
        self.rescan_btn.setEnabled(False)
        self.status.setText(_("Перемещаю в Корзину…"))
        self._worker = FnWorker(lambda: cleanup.send_to_trash(paths))
        self._worker.done.connect(lambda res: self._on_trashed(res, total))
        self._worker.start()

    def _on_trashed(self, res, total: str):
        if isinstance(res, Exception):
            res = (False, str(res))
        ok, err = res
        if ok:
            QMessageBox.information(
                self, _("Уборка VS Code"), _("Готово: {size} в Корзине.").format(size=total)
            )
        else:
            QMessageBox.warning(
                self, _("Уборка VS Code"), _("Не всё удалось убрать: {err}").format(err=err)
            )
        self._worker = None
        self._scan()
