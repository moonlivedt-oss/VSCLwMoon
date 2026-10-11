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
from .vscode import vscode_process_count

MB = 1024 * 1024


def _mb(b: int) -> str:
    if b >= 1024 * MB:
        return _("{gb} ГБ").format(gb=f"{b / (1024 * MB):.1f}")
    return _("{mb} МБ").format(mb=max(1, round(b / MB)) if b else 0)


def _age(mtime: float) -> str:
    """«сегодня», «12 дн. назад» — по дате изменения."""
    import time

    if not mtime:
        return ""
    days = int((time.time() - mtime) // 86400)
    if days <= 0:
        return _("сегодня")
    return _("{n} дн. назад").format(n=days)


class CleanupDialog(QDialog):
    def __init__(self, parent, code_cli):
        super().__init__(parent)
        self._cli = code_cli
        self._items: list[dict] = []
        self._worker = None
        self.setWindowTitle(_("Уборка VS Code"))
        self.resize(800, 600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 16)
        lay.setSpacing(12)
        ttl = QLabel(_("Уборка VS Code"))
        ttl.setObjectName("Title")
        lay.addWidget(ttl)
        note = _wrap(
            QLabel(
                _(
                    "Что VS Code накопил и сам не чистит: кэш подсказок C/C++, копии "
                    "установщиков, кэши движка, отчёты о падениях, старые логи и версии. "
                    "Отмеченное пересоздаётся само. Неотмеченные группы (данные удалённых "
                    "расширений, давно не открытые проекты, история удалённых файлов) — "
                    "отметьте сами, если не нужны. Удаление — в Корзину, при закрытом VS Code."
                )
            )
        )
        note.setObjectName("Subtitle")
        lay.addWidget(note)
        lay.addWidget(_hline())

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([_("Что"), _("Размер"), _("Изменено")])
        self.tree.setColumnWidth(0, 560)
        self.tree.setColumnWidth(1, 80)
        self.tree.itemChanged.connect(self._on_changed)
        lay.addWidget(self.tree, 1)

        self.status = _wrap(QLabel(_("Ищу…")))
        self.status.setObjectName("CatNote")
        lay.addWidget(self.status)

        bar = QHBoxLayout()
        self.safe_btn = QPushButton(_("Только безопасное"))
        self.safe_btn.setObjectName("Ghost")
        self.safe_btn.setToolTip(_("Отметить то, что VS Code и расширения создадут заново сами."))
        self.safe_btn.clicked.connect(lambda: self._check(safe_only=True))
        self.all_btn = QPushButton(_("Отметить всё"))
        self.all_btn.setObjectName("Ghost")
        self.all_btn.clicked.connect(lambda: self._check(safe_only=False))
        bar.addWidget(self.safe_btn)
        bar.addWidget(self.all_btn)
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
        cli = self._cli
        self.go_btn.setEnabled(False)
        self.rescan_btn.setEnabled(False)
        self.status.setText(_("Ищу…"))
        self._worker = FnWorker(lambda: cleanup.scan_vscode(cli))
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
            safe = kind in cleanup.SAFE_KINDS
            title = _(cleanup.KIND_TITLES.get(kind, kind))
            if not safe:
                title += "  | " + _("проверьте перед удалением")
            g = QTreeWidgetItem([f"{title}  ({n})", _mb(size), ""])
            g.setFlags(g.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            g.setCheckState(0, Qt.CheckState.Checked if safe else Qt.CheckState.Unchecked)
            g.setToolTip(0, _(cleanup.KIND_HELP.get(kind, "")))
            g.setData(0, Qt.ItemDataRole.UserRole + 1, kind)
            self.tree.addTopLevelItem(g)
            groups[kind] = g
        order = sorted(range(len(res)), key=lambda i: -res[i]["bytes"])
        for idx in order:
            it = res[idx]
            label = it["note"] or it["path"]
            child = QTreeWidgetItem([label, _mb(it["bytes"]), _age(it.get("mtime", 0))])
            child.setToolTip(0, it["path"])
            child.setData(0, Qt.ItemDataRole.UserRole, idx)
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            child.setCheckState(
                0,
                Qt.CheckState.Checked
                if it["kind"] in cleanup.SAFE_KINDS
                else Qt.CheckState.Unchecked,
            )
            groups[it["kind"]].addChild(child)
        self.tree.blockSignals(False)
        self._on_changed()

    def _check(self, safe_only: bool):
        """Отметить всё или только безопасные группы."""
        self.tree.blockSignals(True)
        for gi in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(gi)
            on = (not safe_only) or g.data(0, Qt.ItemDataRole.UserRole + 1) in cleanup.SAFE_KINDS
            state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
            for ci in range(g.childCount()):
                g.child(ci).setCheckState(0, state)
            g.setCheckState(0, state)
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
            found = sum(i["bytes"] for i in self._items)
            safe = sum(i["bytes"] for i in self._items if i["kind"] in cleanup.SAFE_KINDS)
            self.status.setText(
                _(
                    "Найдено {all} (безопасно убрать — {safe}). Выбрано: {n} | освободится {size}"
                ).format(all=_mb(found), safe=_mb(safe), n=len(sel), size=_mb(total))
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
        text = _("Переместить в Корзину {n} элементов ({size})?").format(n=len(sel), size=total)
        risky = sorted({i["kind"] for i in sel} - cleanup.SAFE_KINDS)
        if risky:
            text += "\n\n" + _("Среди них то, что само не вернётся: {kinds}.").format(
                kinds=", ".join(_(cleanup.KIND_TITLES.get(k, k)) for k in risky)
            )
        if sum(i["bytes"] for i in sel) > 2 * 1024 * MB:
            text += "\n\n" + _(
                "Объём большой: если он не помещается в Корзину, Windows удалит файлы сразу, "
                "без возможности вернуть."
            )
        ok = QMessageBox.question(self, _("Уборка VS Code"), text)
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
