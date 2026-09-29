# -*- coding: utf-8 -*-
"""C++-центр: установка по ролям, проверка окружения, настройка проекта.

Три вкладки:
- «Установка» — компоненты сгруппированы по тому, за что отвечают (компилятор,
  сборка, подсказки, отладка, анализ, библиотеки, настройка). У каждого — одна
  строка «зачем» и статус. Внизу сводка: сколько ставится, сколько весит, нужны
  ли права администратора. Одна кнопка ставит всё по порядку, с прогрессом.
- «Проверка» — доктор C++: проблемы карточками, у каждой кнопка исправления.
- «Проект» — сгенерировать .vscode под компилятор или создать проект.

Логика — в cpp_setup.py, cpp.py, cpp_project.py. Здесь только окно. Всё
медленное (запуск компиляторов, winget, pacman) идёт в фоне.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import cpp
from . import cpp_project as cp
from . import cpp_setup as cs
from .detect import cpp_project_hints
from .gui_widgets import _hline, _wrap
from .gui_workers import FnWorker
from .i18n import _, get_language
from .paths import ASSETS_DIR

LEVEL_TAG = {"error": "Wheavy", "warn": "Wmedium", "info": "Woff"}


def _lang() -> str:
    return get_language()


MASCOT_DIR = ASSETS_DIR / "mascots"
_pix_cache: dict[tuple[str, int], QPixmap] = {}


def _mascot_pixmap(name: str, h: int) -> QPixmap | None:
    """Талисман из assets/mascots (тот же, что в cpp-docs-panel). Нет файла — None:
    картинки украшают, но окно без них полностью рабочее."""
    key = (name, h)
    if key not in _pix_cache:
        pm = QPixmap(str(MASCOT_DIR / f"{name}.png"))
        if pm.isNull():
            return None
        _pix_cache[key] = pm.scaledToHeight(h, Qt.TransformationMode.SmoothTransformation)
    return _pix_cache[key]


class Mascot(QLabel):
    """Картинка-состояние: думает, ищет, готово, победа, спит."""

    def __init__(self, name: str = "", h: int = 64):
        super().__init__()
        self._h = h
        self.setFixedWidth(int(h * 1.05))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set(name)

    def set(self, name: str) -> None:
        pm = _mascot_pixmap(name, self._h) if name else None
        if pm is None:
            self.clear()
            self.setVisible(False)
            return
        self.setPixmap(pm)
        self.setVisible(True)


def _tag(text: str, obj: str) -> QLabel:
    t = QLabel(text)
    t.setObjectName(obj)
    return t


def _retag(lbl: QLabel, text: str, obj: str) -> None:
    lbl.setText(text)
    lbl.setObjectName(obj)
    lbl.style().unpolish(lbl)
    lbl.style().polish(lbl)


def _btn(text: str, obj: str = "Ghost", tip: str = "") -> QPushButton:
    b = QPushButton(text)
    b.setObjectName(obj)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    return b


def _note(text: str, obj: str = "CatNote") -> QLabel:
    lbl = _wrap(QLabel(text))
    lbl.setObjectName(obj)
    return lbl


def _scroll(inner: QWidget) -> QScrollArea:
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setFrameShape(QFrame.Shape.NoFrame)
    sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    inner.setObjectName(inner.objectName() or "CatInner")
    sc.setWidget(inner)
    return sc


def _size_text(mb: int) -> str:
    if mb >= 1000:
        return _("{n} ГБ").format(n=f"{mb / 1024:.1f}".replace(".0", ""))
    return _("{n} МБ").format(n=max(1, mb))


def _adopt_threads(dlg, threads) -> None:
    """Передать ещё идущие потоки главному окну: объект диалога удалится после
    закрытия, а уничтожение работающего QThread роняет приложение."""
    keep = getattr(dlg.parent(), "_install_threads", None)
    for w in threads:
        if w is None or not w.isRunning():
            continue
        if keep is not None:
            keep.append(w)
            w.finished.connect(lambda x=w: keep.remove(x) if x in keep else None)
        else:
            w.wait()


class PlanRunner(QThread):
    """Выполнить шаги плана по очереди. Отмена — между шагами."""

    step_started = pyqtSignal(int)
    step_done = pyqtSignal(int, bool, str)
    all_done = pyqtSignal()

    def __init__(self, steps, code_cli):
        super().__init__()
        self._steps = list(steps)
        self._cli = code_cli
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        for i, step in enumerate(self._steps):
            if self._cancel:
                break
            self.step_started.emit(i)
            ok, msg = cs.execute(step, self._cli)
            self.step_done.emit(i, ok, msg or "")
        self.all_done.emit()


class CppCenter(QWidget):
    """Содержимое C++-центра: страница главного окна (или тело диалога)."""

    def __init__(
        self,
        parent,
        code_cli,
        folder: str = "",
        tab: str = "install",
        on_folder=None,
        on_installed=None,
        preselect: str = "",
        on_issues=None,
    ):
        super().__init__(parent)
        self.setObjectName("CatInner")
        self._cli = code_cli
        self._on_folder = on_folder
        self._on_installed = on_installed
        self._on_issues = on_issues
        self._after_folder = None  # диалог-обёртка закрывается после выбора папки
        self._workers: list[QThread] = []
        self._state: dict | None = None
        self._sel: dict = {}
        self._preselect = preselect
        self._runner: PlanRunner | None = None
        self._open = True
        self._scanned = False
        self._run_doctor_on_show = tab == "doctor"
        self.destroyed.connect(lambda _=None: setattr(self, "_open", False))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 18, 12)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(Mascot("hi", 58), 0, Qt.AlignmentFlag.AlignVCenter)
        htxt = QVBoxLayout()
        htxt.setSpacing(2)
        ttl = QLabel("C / C++")
        ttl.setObjectName("PageTitle")
        htxt.addWidget(ttl)
        htxt.addWidget(
            _note(
                _(
                    "Всё для C/C++ в одном месте: поставить компилятор и инструменты, "
                    "проверить, что код собирается и запускается, и настроить проект под "
                    "VS Code."
                ),
                "PageSub",
            )
        )
        head.addLayout(htxt, 1)
        lay.addLayout(head)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_install_tab(), _("Установка"))
        self.tabs.addTab(self._build_doctor_tab(), _("Проверка"))
        self.tabs.addTab(self._build_project_tab(folder), _("Проект"))
        lay.addWidget(self.tabs, 1)
        self.tabs.setCurrentIndex({"install": 0, "doctor": 1, "project": 2}.get(tab, 0))

    def showEvent(self, e):
        # Сканирование запускает компиляторы (около секунды) — только когда
        # страницу действительно открыли, а не при старте лаунчера.
        super().showEvent(e)
        if not self._scanned:
            self._scanned = True
            self._rescan()
            if self._run_doctor_on_show:
                self._run_doctor()

    def open_tab(self, tab: str = "install", preselect: str = "") -> None:
        """Переключить вкладку (и отметить нужный компонент) снаружи."""
        self.tabs.setCurrentIndex({"install": 0, "doctor": 1, "project": 2}.get(tab, 0))
        if preselect:
            if self._state is None:
                self._preselect = preselect
            else:
                self._goto_install(preselect)
        if tab == "doctor" and self._scanned:
            self._run_doctor()

    def busy(self) -> bool:
        return self._runner is not None and self._runner.isRunning()

    def threads(self) -> list:
        return self._workers + ([self._runner] if self._runner else [])

    # --- общее -----------------------------------------------------------------

    def _bg(self, fn, done):
        w = FnWorker(fn)

        def _d(res):
            if self._open:
                done(res)

        w.done.connect(_d)
        w.finished.connect(lambda x=w: self._workers.remove(x) if x in self._workers else None)
        self._workers.append(w)
        # Главное окно держит потоки до конца, чтобы их не уничтожил сборщик.
        keep = getattr(self.window(), "_install_threads", None)
        if keep is not None:
            keep.append(w)
            w.finished.connect(lambda x=w: keep.remove(x) if x in keep else None)
        w.start()
        return w

    def _rescan(self):
        self.scan_lbl.setText(_("Проверяю, что уже установлено…"))
        self.scan_box.setVisible(True)
        self.install_btn.setEnabled(False)
        self._bg(lambda: cs.scan_state(self._cli), self._on_state)

    def _on_state(self, st):
        if not isinstance(st, dict):
            self.scan_lbl.setText(_("Не удалось проверить систему: {e}").format(e=st))
            return
        self._state = st
        self.scan_box.setVisible(False)
        self._sel = cs.default_selection(st)
        if self._preselect:
            self._apply_preselect(self._preselect)
            self._preselect = ""
        self._render_options()
        self._fill_project_compilers()

    # --- вкладка «Установка» --------------------------------------------------------

    def _build_install_tab(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 10, 0, 0)
        v.setSpacing(8)
        self.install_stack = QStackedWidget()
        v.addWidget(self.install_stack, 1)

        # Страница выбора.
        choose = QWidget()
        cv = QVBoxLayout(choose)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(8)
        pre = QHBoxLayout()
        pre.setSpacing(6)
        pre.addWidget(_note(_("Готовые наборы:"), "Section"))
        for key, p in cs.PRESETS.items():
            b = _btn(cs.text(p, "title", _lang()), tip=cs.text(p, "note", _lang()))
            b.clicked.connect(lambda _c=False, k=key: self._use_preset(k))
            pre.addWidget(b)
        pre.addStretch()
        rescan = _btn(_("Проверить заново"), tip=_("Заново найти компиляторы и расширения."))
        rescan.clicked.connect(self._rescan)
        pre.addWidget(rescan)
        cv.addLayout(pre)
        cv.addWidget(
            _note(
                _(
                    "Отметьте, что нужно. Под каждым пунктом написано, за что он отвечает. "
                    "Уже установленное помечено и повторно не ставится."
                )
            )
        )
        self.scan_box = QWidget()
        self.scan_box.setObjectName("CatInner")
        sb = QHBoxLayout(self.scan_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.addWidget(Mascot("think", 56))
        self.scan_lbl = _note("", "Hint")
        sb.addWidget(self.scan_lbl, 1)
        cv.addWidget(self.scan_box)
        self.opt_holder = QWidget()
        self.opt_lay = QVBoxLayout(self.opt_holder)
        self.opt_lay.setContentsMargins(0, 0, 6, 0)
        self.opt_lay.setSpacing(8)
        cv.addWidget(_scroll(self.opt_holder), 1)
        cv.addWidget(_hline())
        bar = QHBoxLayout()
        self.summary_lbl = _note("", "Summary")
        self.sum_icon = Mascot("", 44)
        bar.addWidget(self.sum_icon)
        bar.addWidget(self.summary_lbl, 1)
        self.plan_btn = _btn(_("Что будет сделано"), tip=_("Показать шаги по порядку."))
        self.plan_btn.clicked.connect(self._show_plan)
        bar.addWidget(self.plan_btn)
        self.install_btn = _btn(_("Установить"), "Accent")
        self.install_btn.clicked.connect(self._start_install)
        bar.addWidget(self.install_btn)
        cv.addLayout(bar)
        self.install_stack.addWidget(choose)

        # Страница выполнения.
        run = QWidget()
        rv = QVBoxLayout(run)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)
        self.run_icon = Mascot("think", 72)
        rh = QHBoxLayout()
        rh.addWidget(self.run_icon)
        self.run_title = QLabel(_("Установка"))
        self.run_title.setObjectName("CatTitle")
        rh.addWidget(self.run_title, 1)
        rv.addLayout(rh)
        rv.addWidget(
            _note(
                _(
                    "Пакеты скачиваются по очереди — это может занять несколько минут. "
                    "Окно можно не трогать. После установки откройте новый терминал и "
                    "перезапустите VS Code, чтобы подхватился PATH."
                )
            )
        )
        self.step_holder = QWidget()
        self.step_lay = QVBoxLayout(self.step_holder)
        self.step_lay.setContentsMargins(0, 0, 6, 0)
        self.step_lay.setSpacing(4)
        rv.addWidget(_scroll(self.step_holder), 1)
        self.run_bar = QProgressBar()
        self.run_bar.setObjectName("InstallBar")
        self.run_bar.setTextVisible(False)
        self.run_bar.setFixedHeight(8)
        rv.addWidget(self.run_bar)
        self.run_log = QPlainTextEdit()
        self.run_log.setObjectName("Log")
        self.run_log.setReadOnly(True)
        self.run_log.setMaximumHeight(150)
        rv.addWidget(self.run_log)
        rb = QHBoxLayout()
        self.run_status = _note("")
        rb.addWidget(self.run_status, 1)
        self.cancel_btn = _btn(_("Остановить"), "Danger", _("Остановить после текущего шага."))
        self.cancel_btn.clicked.connect(self._cancel_install)
        rb.addWidget(self.cancel_btn)
        self.after_doctor = _btn(_("Проверить окружение"))
        self.after_doctor.clicked.connect(lambda: self._goto_doctor(run=True))
        self.after_project = _btn(_("Настроить проект"))
        self.after_project.clicked.connect(lambda: self.tabs.setCurrentIndex(2))
        self.after_back = _btn(_("К выбору"), "Accent")
        self.after_back.clicked.connect(self._back_to_choose)
        for b in (self.after_doctor, self.after_project, self.after_back):
            b.setVisible(False)
            rb.addWidget(b)
        rv.addLayout(rb)
        self.install_stack.addWidget(run)
        return page

    def _clear(self, lay):
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                self._clear(item.layout())

    def _render_options(self):
        st = self._state
        if st is None:
            return
        self._clear(self.opt_lay)
        self._rows: dict[str, dict] = {}
        lang = _lang()
        for g in cs.GROUPS:
            card = QFrame()
            card.setObjectName("CatCard")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 10, 12, 10)
            cl.setSpacing(4)
            head = QLabel(cs.text(g, "title", lang))
            head.setObjectName("CatTitle")
            cl.addWidget(head)
            cl.addWidget(_note(cs.text(g, "note", lang)))
            group_btns = QButtonGroup(card) if g.exclusive else None
            if g.key == "libs":
                self._render_libs(cl)
            else:
                for opt in cs.OPTIONS:
                    if opt.group != g.key:
                        continue
                    if opt.key == "keep" and not cs.other_compilers(st.get("compilers", [])):
                        continue
                    self._render_option(cl, opt, group_btns)
            self.opt_lay.addWidget(card)
            if g.key == "libs":
                self._libs_card = card
        self.opt_lay.addStretch()
        self._sync_rows()

    def _render_option(self, cl, opt, group_btns):
        st = self._state
        lang = _lang()
        installed, info = cs.status(opt.key, st)
        row = QFrame()
        row.setObjectName("OptRow")
        rl = QVBoxLayout(row)
        rl.setContentsMargins(8, 6, 8, 6)
        rl.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(8)
        title = cs.text(opt, "title", lang)
        if opt.info_only:
            ctl = QLabel(title)
            ctl.setObjectName("CatTitle")
        elif group_btns is not None:
            ctl = QRadioButton(title)
            group_btns.addButton(ctl)
            ctl.toggled.connect(lambda on, k=opt.key, g=opt.group: on and self._pick(g, k))
        else:
            ctl = QCheckBox(title)
            ctl.toggled.connect(lambda on, k=opt.key: self._toggle(k, on))
        top.addWidget(ctl)
        top.addStretch()
        if opt.admin:
            top.addWidget(_tag(_("нужен админ"), "Wmedium"))
        if opt.size_mb and not installed:
            top.addWidget(_tag(_size_text(opt.size_mb), "Woff"))
        tag = QLabel()
        top.addWidget(tag)
        rl.addLayout(top)
        what = _note(cs.text(opt, "what", lang))
        what.setContentsMargins(26, 0, 0, 0)
        rl.addWidget(what)
        extra = None
        if opt.key == "keep":
            extra = QComboBox()
            for c in cs.other_compilers(st.get("compilers", [])):
                extra.addItem(
                    f"{c['kind']} {c['version']} · {c['origin']} — {c['path']}", c["path"]
                )
            idx = extra.findData(self._sel.get("keep_path"))
            extra.setCurrentIndex(max(0, idx))
            extra.currentIndexChanged.connect(lambda _i, cb=extra: self._set_keep(cb.currentData()))
            wrap = QHBoxLayout()
            wrap.setContentsMargins(26, 2, 0, 0)
            wrap.addWidget(extra, 1)
            rl.addLayout(wrap)
        if opt.key == "path":
            dirs = st.get("gcc_dirs", [])
            if len(dirs) > 1:
                what.setText(
                    what.text() + "\n" + _("Сейчас в PATH: {dirs}").format(dirs="; ".join(dirs))
                )
        cl.addWidget(row)
        self._rows[opt.key] = {
            "row": row,
            "ctl": ctl,
            "tag": tag,
            "installed": installed,
            "info": info,
            "opt": opt,
            "extra": extra,
        }

    def _render_libs(self, cl):
        lang = _lang()
        self._lib_boxes: dict[str, QCheckBox] = {}
        self._libs_note = _note("")
        cl.addWidget(self._libs_note)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        for i, (key, ru, en) in enumerate(cs.LIBS):
            box = QCheckBox(en if lang == "en" else ru)
            box.toggled.connect(lambda on, k=key: self._toggle_lib(k, on))
            grid.addWidget(box, i // 2, i % 2)
            self._lib_boxes[key] = box
        cl.addLayout(grid)

    # Выбор пользователя -> self._sel.
    def _pick(self, group, key):
        prev = self._sel.get(group)
        self._sel[group] = key
        # clangd без cpptools: отладчик gdb (cppdbg) живёт в cpptools, поэтому
        # сразу предлагаем CodeLLDB.
        if (
            group == "intellisense"
            and key == "clangd"
            and prev != "clangd"
            and self._sel.get("compiler") != "msvc"
        ):
            self._sel["checked"].add("codelldb")
        self._sync_rows()

    def _toggle(self, key, on):
        (self._sel["checked"].add if on else self._sel["checked"].discard)(key)
        self._sync_summary()

    def _toggle_lib(self, key, on):
        (self._sel["libs"].add if on else self._sel["libs"].discard)(key)
        self._sync_summary()

    def _set_keep(self, path):
        self._sel["keep_path"] = path or ""
        self._sync_summary()

    def _use_preset(self, key):
        if self._state is None:
            return
        self._sel = cs.apply_preset(self._sel, key, self._state)
        self._sync_rows()

    def _apply_preselect(self, what: str):
        mapping = {
            "install:cpp": ("compiler", "mingw"),
            "install:cpp_msvc": ("compiler", "msvc"),
            "install:cpp_llvm": ("intellisense", "clangd"),
            "install:cpp_msys2": ("compiler", "msys2"),
        }
        if what in mapping:
            g, k = mapping[what]
            self._sel[g] = k

    def _sync_rows(self):
        """Привести виджеты к self._sel без каскада сигналов."""
        st = self._state
        for key, r in self._rows.items():
            ctl, opt = r["ctl"], r["opt"]
            installed = r["installed"]
            if isinstance(ctl, (QRadioButton, QCheckBox)):
                ctl.blockSignals(True)
                if opt.group in ("compiler", "intellisense"):
                    ctl.setChecked(self._sel.get(opt.group) == key)
                elif installed and key not in ("configure", "path"):
                    ctl.setChecked(True)
                    ctl.setEnabled(False)
                else:
                    ctl.setChecked(key in self._sel["checked"])
                ctl.blockSignals(False)
            on = (
                opt.group in ("compiler", "intellisense") and self._sel.get(opt.group) == key
            ) or (opt.group not in ("compiler", "intellisense") and key in self._sel["checked"])
            r["row"].setProperty("on", "true" if on else "false")
            r["row"].style().unpolish(r["row"])
            r["row"].style().polish(r["row"])
            if r["extra"] is not None:
                r["extra"].setEnabled(self._sel.get("compiler") == "keep")
            if opt.key in ("configure", "path"):
                _retag(r["tag"], "", "Woff")
                r["tag"].setVisible(False)
            elif installed and key == "keep":
                _retag(r["tag"], _("найдено: {n}").format(n=r["info"]), "Wlight")
                r["tag"].setVisible(True)
            elif installed:
                _retag(
                    r["tag"], (_("уже есть") + (f" · {r['info']}" if r["info"] else "")), "Wlight"
                )
                r["tag"].setVisible(True)
            else:
                label = r["info"] or (_("нет") if not opt.info_only else _("не найден"))
                _retag(r["tag"], label, "Woff")
                r["tag"].setVisible(True)
        # Библиотеки.
        avail = cs.libs_available(self._sel, st)
        if hasattr(self, "_lib_boxes"):
            for key, box in self._lib_boxes.items():
                have = bool(st.get("msys2_libs", {}).get(key))
                box.blockSignals(True)
                box.setChecked(have or key in self._sel["libs"])
                box.setEnabled(avail and not have)
                box.setToolTip(_("уже установлена") if have else "")
                box.blockSignals(False)
            self._libs_note.setText(
                ""
                if avail
                else _(
                    "Выберите компилятор MSYS2 (или оставьте свой из MSYS2), "
                    "чтобы ставить библиотеки через pacman."
                )
            )
            self._libs_note.setVisible(not avail)
        self._sync_summary()

    def _plan(self):
        return cs.build_plan(self._sel, self._state) if self._state else []

    def _sync_summary(self):
        steps = self._plan()
        s = cs.plan_summary(steps)
        if not steps:
            self.sum_icon.set("sleep")
            self.summary_lbl.setText(_("Всё выбранное уже установлено и настроено."))
            self.install_btn.setEnabled(False)
            self.install_btn.setText(_("Установить"))
            return
        self.install_btn.setEnabled(True)
        self.sum_icon.set("")
        if s["only_setup"]:
            self.summary_lbl.setText(
                _("Ставить ничего не нужно. Будет выполнено шагов настройки: {n}.").format(
                    n=len(steps)
                )
            )
            self.install_btn.setText(_("Настроить"))
            return
        txt = _("Будет установлено: {n} · около {size}").format(
            n=s["count"], size=_size_text(s["size_mb"])
        )
        if s["admin"]:
            txt += " · " + _("понадобятся права администратора")
        self.summary_lbl.setText(txt)
        self.install_btn.setText(_("Установить ({n})").format(n=s["count"]))

    def _step_title(self, step) -> str:
        return step.title_en if _lang() == "en" else step.title

    def _show_plan(self):
        steps = self._plan()
        if not steps:
            QMessageBox.information(self, _("План"), _("Делать нечего."))
            return
        lines = [f"{i}. {self._step_title(s)}" for i, s in enumerate(steps, 1)]
        QMessageBox.information(self, _("План"), "\n".join(lines))

    def _start_install(self):
        steps = self._plan()
        if not steps:
            return
        lines = "\n".join(f"  {i}. {self._step_title(s)}" for i, s in enumerate(steps, 1))
        extra = ""
        if any(s.admin for s in steps):
            extra = "\n\n" + _("Для MSVC появится запрос прав администратора (UAC).")
        if any(s.kind == "path" for s in steps):
            extra += "\n\n" + _("PATH будет изменён, старое значение сохранится в файл.")
        r = QMessageBox.question(
            self,
            _("Начать?"),
            _("Будет сделано:\n\n{steps}{extra}\n\nПродолжить?").format(steps=lines, extra=extra),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return
        self._clear(self.step_lay)
        self._step_tags = []
        for s in steps:
            row = QHBoxLayout()
            tag = _tag(_("ждёт"), "Woff")
            row.addWidget(tag)
            row.addWidget(QLabel(self._step_title(s)), 1)
            self.step_lay.addLayout(row)
            self._step_tags.append(tag)
        self.step_lay.addStretch()
        self._results = [None] * len(steps)
        self.run_bar.setRange(0, len(steps))
        self.run_bar.setValue(0)
        self.run_log.clear()
        self.run_icon.set("think")
        self.run_title.setText(_("Установка"))
        self.run_status.setText("")
        self.cancel_btn.setVisible(True)
        self.cancel_btn.setEnabled(True)
        for b in (self.after_doctor, self.after_project, self.after_back):
            b.setVisible(False)
        self.install_stack.setCurrentIndex(1)
        self._run_steps = steps
        self._runner = PlanRunner(steps, self._cli)
        self._runner.step_started.connect(self._on_step_start)
        self._runner.step_done.connect(self._on_step_done)
        self._runner.all_done.connect(self._on_all_done)
        self._runner.start()

    def _on_step_start(self, i):
        if not self._open:
            return
        _retag(self._step_tags[i], _("идёт…"), "Wmedium")
        self.run_status.setText(
            _("Шаг {i} из {n}: {title}").format(
                i=i + 1, n=len(self._run_steps), title=self._step_title(self._run_steps[i])
            )
        )

    def _on_step_done(self, i, ok, msg):
        if not self._open:
            return
        self._results[i] = ok
        _retag(self._step_tags[i], _("готово") if ok else _("ошибка"), "Wlight" if ok else "Wheavy")
        self._step_tags[i].setToolTip(msg[:800])
        self.run_bar.setValue(i + 1)
        head = self._step_title(self._run_steps[i])
        self.run_log.appendPlainText(f"== {head}: {'OK' if ok else _('ошибка')}")
        tail = [ln for ln in (msg or "").splitlines() if ln.strip()][-6:]
        for ln in tail:
            self.run_log.appendPlainText("   " + ln)

    def _on_all_done(self):
        if not self._open:
            return
        done = sum(1 for r in self._results if r)
        failed = sum(1 for r in self._results if r is False)
        skipped = sum(1 for r in self._results if r is None)
        for i, r in enumerate(self._results):
            if r is None:
                _retag(self._step_tags[i], _("пропущен"), "Woff")
        if failed or skipped:
            self.run_icon.set("think")
            self.run_title.setText(_("Готово с замечаниями"))
            self.run_status.setText(
                _(
                    "Успешно: {ok}, с ошибкой: {err}, пропущено: {skip}. Подробности — в "
                    "журнале ниже и в подсказке у шага."
                ).format(ok=done, err=failed, skip=skipped)
            )
        else:
            self.run_icon.set("done")
            self.run_title.setText(_("Готово"))
            self.run_status.setText(
                _("Всё установлено. Откройте новый терминал и перезапустите VS Code.")
            )
        self.cancel_btn.setVisible(False)
        for b in (self.after_doctor, self.after_project, self.after_back):
            b.setVisible(True)
        if any(s.kind == "ext" for s in self._run_steps) and self._on_installed:
            try:
                self._on_installed()
            except Exception:
                pass

    def _cancel_install(self):
        if self._runner is not None:
            self._runner.cancel()
            self.cancel_btn.setEnabled(False)
            self.run_status.setText(_("Остановлю после текущего шага…"))

    def _back_to_choose(self):
        self.install_stack.setCurrentIndex(0)
        self._rescan()

    # --- вкладка «Проверка» -----------------------------------------------------------

    def _build_doctor_tab(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 10, 0, 0)
        v.setSpacing(8)
        top = QHBoxLayout()
        self.doc_btn = _btn(_("Проверить"), "Accent")
        self.doc_btn.clicked.connect(self._run_doctor)
        top.addWidget(self.doc_btn)
        self.doc_smoke = QCheckBox(_("С пробной сборкой (дольше, до минуты)"))
        self.doc_smoke.setChecked(True)
        self.doc_smoke.setToolTip(
            _(
                "Собрать, запустить и отладить маленькую программу на C++20 каждым "
                "компилятором — так видны проблемы, которых не видно по версиям."
            )
        )
        top.addWidget(self.doc_smoke)
        top.addStretch()
        v.addLayout(top)
        self.doc_status = _note(
            _(
                "Найдёт все компиляторы, проверит, не смешаны ли тулчейны в PATH, и "
                "соберёт пробную программу. Ничего не меняет."
            )
        )
        dh = QHBoxLayout()
        self.doc_icon = Mascot("search", 64)
        dh.addWidget(self.doc_icon)
        dh.addWidget(self.doc_status, 1)
        v.addLayout(dh)
        self.doc_holder = QWidget()
        self.doc_lay = QVBoxLayout(self.doc_holder)
        self.doc_lay.setContentsMargins(0, 0, 6, 0)
        self.doc_lay.setSpacing(8)
        self.doc_lay.addStretch()
        v.addWidget(_scroll(self.doc_holder), 1)
        return page

    def _goto_doctor(self, run: bool = False):
        self.tabs.setCurrentIndex(1)
        if run:
            self._run_doctor()

    def _run_doctor(self):
        self.doc_btn.setEnabled(False)
        self.doc_icon.set("think")
        self.doc_status.setText(_("Проверяю… Пробная сборка может занять до минуты."))
        smoke = self.doc_smoke.isChecked()
        self._bg(lambda: cpp.cpp_report(smoke=smoke), self._on_doctor)

    def _on_doctor(self, rep):
        self.doc_btn.setEnabled(True)
        if not isinstance(rep, dict):
            self.doc_icon.set("search")
            self.doc_status.setText(_("Проверка не удалась: {e}").format(e=rep))
            return
        self._doc_rep = rep
        issues = rep.get("issues", [])
        if self._on_issues is not None:
            self._on_issues(sum(1 for i in issues if i["level"] in ("error", "warn")))
        errs = sum(1 for i in issues if i["level"] == "error")
        warns = sum(1 for i in issues if i["level"] == "warn")
        if not issues:
            self.doc_icon.set("win")
            self.doc_status.setText(_("Проблем не найдено: C++ собирается и запускается."))
        else:
            self.doc_icon.set("search")
            self.doc_status.setText(
                _(
                    "Найдено: ошибок {e}, предупреждений {w}. Ниже — что это значит и как "
                    "исправить."
                ).format(e=errs, w=warns)
            )
        self._clear(self.doc_lay)
        if issues:
            self.doc_lay.addWidget(self._issues_card(issues))
        self.doc_lay.addWidget(self._compilers_card(rep))
        if rep.get("smoke"):
            self.doc_lay.addWidget(self._smoke_card(rep["smoke"]))
        full = _btn(_("Полный отчёт текстом"), tip=_("Можно скопировать и отправить."))
        full.clicked.connect(self._show_full_report)
        row = QHBoxLayout()
        row.addWidget(full)
        row.addStretch()
        self.doc_lay.addLayout(row)
        self.doc_lay.addStretch()

    def _card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("CatCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(6)
        t = QLabel(title)
        t.setObjectName("CatTitle")
        cl.addWidget(t)
        return card, cl

    def _issues_card(self, issues) -> QFrame:
        card, cl = self._card(_("Проблемы"))
        names = {"error": _("ошибка"), "warn": _("внимание"), "info": _("к сведению")}
        order = {"error": 0, "warn": 1, "info": 2}
        for i in sorted(issues, key=lambda x: order.get(x["level"], 3)):
            row = QHBoxLayout()
            row.setSpacing(10)
            tag = _tag(names.get(i["level"], "-"), LEVEL_TAG.get(i["level"], "Woff"))
            row.addWidget(tag, 0, Qt.AlignmentFlag.AlignTop)
            txt = _note(i["text"])
            txt.setObjectName("")
            txt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(txt, 1)
            fix = i.get("fix", "")
            if fix == "path":
                b = _btn(_("Навести порядок в PATH…"))
                b.clicked.connect(self._open_path_fix)
                row.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
            elif fix.startswith("install:"):
                b = _btn(_("Подобрать установку"))
                b.clicked.connect(lambda _c=False, f=fix: self._goto_install(f))
                row.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
            cl.addLayout(row)
        return card

    def _compilers_card(self, rep) -> QFrame:
        card, cl = self._card(_("Компиляторы"))
        comps = rep.get("compilers", [])
        if not comps:
            cl.addWidget(_note(_("Не найдено ни одного компилятора C++.")))
        for c in comps:
            row = QHBoxLayout()
            row.setSpacing(8)
            name = QLabel(f"{c['kind']} {c['version']}")
            name.setMinimumWidth(110)
            row.addWidget(name)
            row.addWidget(_tag(c["origin"], "Woff"))
            if c.get("active"):
                row.addWidget(_tag(_("активный"), "Wlight"))
            elif not c.get("on_path"):
                row.addWidget(_tag(_("не в PATH"), "Wmedium"))
            p = _note(c["path"])
            p.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(p, 1)
            cl.addLayout(row)
        return card

    def _smoke_card(self, smoke) -> QFrame:
        card, cl = self._card(_("Пробная сборка C++20"))
        for s in smoke:
            c = s["compiler"]
            row = QHBoxLayout()
            row.setSpacing(6)
            lbl = QLabel(f"{c['kind']} {c['version']} · {c['origin']}")
            lbl.setMinimumWidth(220)
            row.addWidget(lbl)
            for st in s["steps"]:
                t = _tag(cpp.step_title(st["name"]), "Wlight" if st["ok"] else "Wheavy")
                t.setToolTip(st["detail"])
                row.addWidget(t)
            row.addStretch()
            cl.addLayout(row)
            failed = next((st for st in s["steps"] if not st["ok"]), None)
            if failed and failed["detail"]:
                d = _note(failed["detail"])
                d.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                cl.addWidget(d)
        return card

    def _show_full_report(self):
        rep = getattr(self, "_doc_rep", None)
        if not rep:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(_("Отчёт C++"))
        dlg.resize(760, 560)
        lay = QVBoxLayout(dlg)
        box = QPlainTextEdit("\n".join(cpp.format_report(rep)))
        box.setObjectName("Log")
        box.setReadOnly(True)
        lay.addWidget(box, 1)
        row = QHBoxLayout()
        copy = _btn(_("Скопировать"))
        copy.clicked.connect(lambda: (box.selectAll(), box.copy()))
        row.addWidget(copy)
        row.addStretch()
        close = _btn(_("Закрыть"), "Accent")
        close.clicked.connect(dlg.accept)
        row.addWidget(close)
        lay.addLayout(row)
        dlg.exec()

    def _goto_install(self, fix: str):
        self._apply_preselect(fix)
        self.tabs.setCurrentIndex(0)
        self.install_stack.setCurrentIndex(0)
        self._sync_rows()

    def _open_path_fix(self):
        rep = getattr(self, "_doc_rep", None) or {}
        dirs: list[str] = []
        for c in rep.get("compilers", []):
            if c["kind"] == "gcc" and c["bin_dir"] not in dirs:
                dirs.append(c["bin_dir"])
        if not dirs:
            QMessageBox.information(self, "PATH", _("Не найдено ни одного GCC."))
            return
        dlg = PathFixDialog(self, dirs)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._run_doctor()

    # --- вкладка «Проект» --------------------------------------------------------------

    def _build_project_tab(self, folder: str) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 10, 0, 0)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(10)
        outer.addWidget(_scroll(inner), 1)

        # Существующая папка.
        card, cl = self._card(_("Настроить папку проекта"))
        cl.addWidget(
            _note(
                _(
                    "Создаст в папке файлы для VS Code: сборка по Ctrl+Shift+B, отладка по F5 и "
                    "подсказки кода под выбранный компилятор. Ваши файлы без спроса не "
                    "перезаписываются."
                )
            )
        )
        fr = QHBoxLayout()
        self.pj_folder = QLineEdit(folder)
        self.pj_folder.setPlaceholderText(_("Папка проекта"))
        self.pj_folder.editingFinished.connect(self._refresh_project)
        fr.addWidget(self.pj_folder, 1)
        br = _btn(_("Обзор…"))
        br.clicked.connect(self._browse_project)
        fr.addWidget(br)
        cl.addLayout(fr)
        self.pj_hints = QWidget()
        self.pj_hints.setObjectName("CatInner")
        self.pj_hints_lay = QVBoxLayout(self.pj_hints)
        self.pj_hints_lay.setContentsMargins(0, 0, 0, 0)
        self.pj_hints_lay.setSpacing(4)
        cl.addWidget(self.pj_hints)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.addWidget(QLabel(_("Компилятор")), 0, 0)
        self.pj_comp = QComboBox()
        self.pj_comp.currentIndexChanged.connect(lambda _i: self._refresh_files())
        grid.addWidget(self.pj_comp, 0, 1)
        grid.addWidget(QLabel(_("Подсказки кода")), 1, 0)
        eng = QHBoxLayout()
        eng.setSpacing(18)
        self.pj_cpptools = QRadioButton("cpptools")
        self.pj_cpptools.setToolTip(_("Microsoft C/C++: привычно, отладчик gdb встроен."))
        self.pj_clangd = QRadioButton("clangd")
        self.pj_clangd.setToolTip(
            _(
                "Легче и точнее. В проекте IntelliSense cpptools будет отключён, "
                "чтобы движки не дрались."
            )
        )
        self.pj_cpptools.setChecked(True)
        for rb in (self.pj_cpptools, self.pj_clangd):
            rb.toggled.connect(lambda on: on and self._refresh_files())
            eng.addWidget(rb)
        eng.addStretch()
        grid.addLayout(eng, 1, 1)
        grid.addWidget(QLabel(_("Сборка")), 2, 0)
        self.pj_build = QComboBox()
        self.pj_build.addItem(_("Одиночные файлы (g++ текущего файла)"), "single")
        self.pj_build.addItem("CMake", "cmake")
        self.pj_build.currentIndexChanged.connect(lambda _i: self._refresh_files())
        grid.addWidget(self.pj_build, 2, 1)
        grid.addWidget(QLabel(_("Стандарт")), 3, 0)
        self.pj_std = QComboBox()
        for s in cp.STANDARDS:
            self.pj_std.addItem(s.upper(), s)
        self.pj_std.setCurrentIndex(1)
        self.pj_std.currentIndexChanged.connect(lambda _i: self._refresh_files())
        grid.addWidget(self.pj_std, 3, 1)
        grid.setColumnStretch(1, 1)
        cl.addLayout(grid)
        self.pj_olymp = QCheckBox(
            _("Олимпиадный режим: задача «собрать -O2 и запустить на input.txt»")
        )
        self.pj_olymp.toggled.connect(lambda _o: self._refresh_files())
        cl.addWidget(self.pj_olymp)
        self.pj_lint = QCheckBox(_("Файлы стиля: .clang-format и .clang-tidy"))
        self.pj_lint.setChecked(True)
        self.pj_lint.toggled.connect(lambda _o: self._refresh_files())
        cl.addWidget(self.pj_lint)
        cl.addWidget(_note(_("Файлы (снимите галочку, чтобы пропустить):"), "Section"))
        self.pj_files = QWidget()
        self.pj_files.setObjectName("CatInner")
        self.pj_files_lay = QVBoxLayout(self.pj_files)
        self.pj_files_lay.setContentsMargins(0, 0, 0, 0)
        self.pj_files_lay.setSpacing(2)
        cl.addWidget(self.pj_files)
        ar = QHBoxLayout()
        self.pj_result = _note("")
        ar.addWidget(self.pj_result, 1)
        self.pj_open = _btn(
            _("Открыть в лаунчере"), tip=_("Подставить папку в главное окно и подобрать стеки.")
        )
        self.pj_open.clicked.connect(lambda: self._send_folder(self.pj_folder.text().strip()))
        self.pj_open.setVisible(False)
        ar.addWidget(self.pj_open)
        self.pj_apply = _btn(_("Применить"), "Accent")
        self.pj_apply.clicked.connect(self._apply_project)
        ar.addWidget(self.pj_apply)
        cl.addLayout(ar)
        v.addWidget(card)

        # Новый проект.
        card2, cl2 = self._card(_("Новый проект"))
        g2 = QGridLayout()
        g2.setHorizontalSpacing(12)
        g2.setVerticalSpacing(6)
        g2.addWidget(QLabel(_("Где создать")), 0, 0)
        pr = QHBoxLayout()
        self.np_parent = QLineEdit(str(Path(folder).parent) if folder else str(Path.home()))
        pr.addWidget(self.np_parent, 1)
        b2 = _btn(_("Обзор…"))
        b2.clicked.connect(self._browse_parent)
        pr.addWidget(b2)
        g2.addLayout(pr, 0, 1)
        g2.addWidget(QLabel(_("Имя")), 1, 0)
        self.np_name = QLineEdit("hello_cpp")
        self.np_name.setPlaceholderText(_("латиница, цифры, _ . -"))
        g2.addWidget(self.np_name, 1, 1)
        g2.addWidget(QLabel(_("Шаблон")), 2, 0)
        self.np_tpl = QComboBox()
        lang = _lang()
        for key, ru, en, _dru, _den in cp.TEMPLATE_INFO:
            self.np_tpl.addItem(en if lang == "en" else ru, key)
        g2.addWidget(self.np_tpl, 2, 1)
        g2.setColumnStretch(1, 1)
        cl2.addLayout(g2)
        self.np_desc = _note("")
        cl2.addWidget(self.np_desc)
        self.np_tpl.currentIndexChanged.connect(self._sync_tpl_desc)
        self._sync_tpl_desc()
        cl2.addWidget(_note(_("Компилятор, подсказки и стандарт берутся из настроек выше.")))
        nr = QHBoxLayout()
        self.np_result = _note("")
        nr.addWidget(self.np_result, 1)
        create = _btn(_("Создать"), "Accent")
        create.clicked.connect(self._create_project)
        nr.addWidget(create)
        cl2.addLayout(nr)
        v.addWidget(card2)
        v.addStretch()
        return page

    def _sync_tpl_desc(self):
        key = self.np_tpl.currentData()
        for k, _ru, _en, dru, den in cp.TEMPLATE_INFO:
            if k == key:
                self.np_desc.setText(den if _lang() == "en" else dru)

    def _fill_project_compilers(self):
        st = self._state or {}
        self.pj_comp.blockSignals(True)
        self.pj_comp.clear()
        comps = st.get("compilers", [])
        for c in comps:
            self.pj_comp.addItem(f"{c['kind']} {c['version']} · {c['origin']}", c)
        prim = cs.primary_of(comps)
        if prim:
            self.pj_comp.setCurrentIndex(comps.index(prim))
        self.pj_comp.blockSignals(False)
        exts = set(st.get("exts", []))
        if cs.EXT_CLANGD in exts and cs.EXT_CPPTOOLS not in exts:
            self.pj_clangd.setChecked(True)
        self._refresh_project()

    def _browse_project(self):
        d = QFileDialog.getExistingDirectory(self, _("Папка проекта"), self.pj_folder.text())
        if d:
            self.pj_folder.setText(d)
            self._refresh_project()

    def _browse_parent(self):
        d = QFileDialog.getExistingDirectory(self, _("Где создать"), self.np_parent.text())
        if d:
            self.np_parent.setText(d)

    def _project_options(self) -> cp.ProjectOptions | None:
        c = self.pj_comp.currentData()
        if not c:
            return None
        o = cp.options_from_compiler(
            c, engine="clangd" if self.pj_clangd.isChecked() else "cpptools"
        )
        o.build = self.pj_build.currentData()
        o.std = self.pj_std.currentData()
        o.olympiad = self.pj_olymp.isChecked()
        o.lint_files = self.pj_lint.isChecked()
        folder = self.pj_folder.text().strip()
        o.name = Path(folder).name if folder else "app"
        o.vcpkg = bool(getattr(self, "_pj_hints", {}).get("vcpkg"))
        return o

    def _refresh_project(self):
        folder = self.pj_folder.text().strip()
        self._clear(self.pj_hints_lay)
        self._pj_hints = cpp_project_hints(folder) if folder else {}
        h = self._pj_hints
        if folder and Path(folder).is_dir():
            build = h.get("build", "none")
            self.pj_build.blockSignals(True)
            self.pj_build.setCurrentIndex(1 if build == "cmake" else 0)
            self.pj_build.blockSignals(False)
            parts = []
            if h.get("is_cpp"):
                parts.append(
                    {
                        "cmake": _("CMake-проект"),
                        "make": _("проект на Makefile"),
                        "meson": _("проект Meson"),
                    }.get(build, _("C/C++-файлы"))
                )
            else:
                parts.append(_("C/C++-файлов не найдено"))
            if h.get("vcpkg"):
                parts.append("vcpkg")
            if h.get("libs"):
                parts.append(_("библиотеки: {libs}").format(libs=", ".join(h["libs"])))
            if h.get("has_vscode_cfg"):
                parts.append(_("настройки VS Code уже есть"))
            self.pj_hints_lay.addWidget(_note(_("В папке: {what}").format(what="; ".join(parts))))
            for s in cpp.project_suggestions(h):
                if s["action"] == "setup":
                    continue  # это и есть кнопка «Применить» ниже
                row = QHBoxLayout()
                row.addWidget(_note(s["text"], "Hint"), 1)
                act = s["action"]
                if act == "vcpkg" or act.startswith("install:") or act.startswith("pacman:"):
                    b = _btn(_("Поставить"))
                    b.clicked.connect(lambda _c=False, a=act: self._suggestion_action(a))
                    row.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
                self.pj_hints_lay.addLayout(row)
        self._refresh_files()

    def _suggestion_action(self, act: str):
        if self._state is None:
            return
        if act == "vcpkg":
            self._sel["checked"].add("vcpkg")
        elif act.startswith("pacman:"):
            self._sel["libs"] |= set(act[7:].split(","))
        else:
            self._apply_preselect(act)
            if act == "install:cpp_tools":
                self._sel["checked"] |= {"conan"}
        self.tabs.setCurrentIndex(0)
        self.install_stack.setCurrentIndex(0)
        self._sync_rows()

    def _refresh_files(self):
        self._clear(self.pj_files_lay)
        self._file_boxes: dict[str, tuple[QCheckBox, dict]] = {}
        folder = self.pj_folder.text().strip()
        o = self._project_options()
        ok_folder = bool(folder) and Path(folder).is_dir()
        self.pj_apply.setEnabled(ok_folder and o is not None)
        if not ok_folder or o is None:
            self.pj_files_lay.addWidget(
                _note(
                    _("Укажите существующую папку.")
                    if o is not None
                    else _("Сначала нужен компилятор — вкладка «Установка».")
                )
            )
            return
        what = cp.FILE_WHAT_EN if _lang() == "en" else cp.FILE_WHAT
        for item in cp.plan_files(folder, o):
            rel = item["path"]
            if item["merge"]:
                n = len(item["content"])
                if not n:
                    label = _("{path} — все нужные ключи уже заданы").format(path=rel)
                else:
                    label = _("{path} — дописать ключей: {n}").format(path=rel, n=n)
            elif item["exists"]:
                label = _("{path} — уже есть, перезаписать (старый сохранится в .bak)").format(
                    path=rel
                )
            else:
                label = _("{path} — создать").format(path=rel)
            box = QCheckBox(label)
            box.setToolTip(what.get(rel, ""))
            box.setChecked(not item["exists"] or (item["merge"] and bool(item["content"])))
            if item["merge"] and not item["content"]:
                box.setEnabled(False)
                box.setChecked(False)
            self.pj_files_lay.addWidget(box)
            desc = _note(what.get(rel, ""))
            desc.setContentsMargins(26, 0, 0, 2)
            self.pj_files_lay.addWidget(desc)
            self._file_boxes[rel] = (box, item)
        self._pj_plan = [item for _b, item in self._file_boxes.values()]

    def _apply_project(self):
        folder = self.pj_folder.text().strip()
        if not getattr(self, "_file_boxes", None):
            return
        skip = {rel for rel, (b, _i) in self._file_boxes.items() if not b.isChecked()}
        overwrite = {
            rel
            for rel, (b, i) in self._file_boxes.items()
            if b.isChecked() and i["exists"] and not i["merge"]
        }
        try:
            report = cp.apply_plan(folder, self._pj_plan, overwrite=overwrite, skip=skip)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, _("Настройка проекта"), str(e))
            return
        self.pj_result.setText(
            _(
                "Готово: {n} файл(ов). Откройте папку в VS Code: Ctrl+Shift+B — сборка, "
                "F5 — отладка."
            ).format(n=len(self._pj_plan) - len(skip))
        )
        self.pj_result.setToolTip("\n".join(report))
        self.pj_open.setVisible(self._on_folder is not None)
        self._refresh_project()

    def _create_project(self):
        o = self._project_options()
        if o is None:
            QMessageBox.information(
                self, _("Новый проект"), _("Сначала нужен компилятор — вкладка «Установка».")
            )
            return
        name = self.np_name.text().strip()
        ok, msg = cp.new_project(self.np_parent.text().strip(), name, self.np_tpl.currentData(), o)
        if not ok:
            self.np_result.setText(msg)
            return
        self.np_result.setText(_("Создан: {path}").format(path=msg))
        if self._on_folder is not None:
            r = QMessageBox.question(
                self,
                _("Новый проект"),
                _(
                    "Проект создан:\n{path}\n\nПодставить его в лаунчер, чтобы открыть в VS Code?"
                ).format(path=msg),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if r == QMessageBox.StandardButton.Yes:
                self._send_folder(msg)

    def _send_folder(self, folder: str):
        if self._on_folder and folder:
            self._on_folder(folder)
            if self._after_folder is not None:
                self._after_folder()


class PathFixDialog(QDialog):
    """Выбрать основной GCC и навести порядок в PATH с предпросмотром."""

    def __init__(self, parent, dirs: list[str]):
        super().__init__(parent)
        self._workers: list[QThread] = []
        self.setWindowTitle(_("Порядок в PATH"))
        self.resize(680, 480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(8)
        t = QLabel(_("Какой компилятор сделать основным?"))
        t.setObjectName("Title")
        lay.addWidget(t)
        lay.addWidget(
            _note(
                _(
                    "Когда в PATH несколько GCC, программа может запуститься с чужой библиотекой "
                    "libstdc++ и упасть. Выберите основной — он встанет первым."
                )
            )
        )
        self.combo = QComboBox()
        for d in dirs:
            self.combo.addItem(d, d)
        lay.addWidget(self.combo)
        self.demote = QRadioButton(
            _("Остальные опустить в конец PATH (рекомендуется, ничего не удаляется)")
        )
        self.remove = QRadioButton(_("Остальные убрать из PATH совсем"))
        self.demote.setChecked(True)
        lay.addWidget(self.demote)
        lay.addWidget(self.remove)
        self.preview = QPlainTextEdit()
        self.preview.setObjectName("Log")
        self.preview.setReadOnly(True)
        lay.addWidget(self.preview, 1)
        row = QHBoxLayout()
        row.addStretch()
        cancel = _btn(_("Отмена"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.apply_btn = _btn(_("Применить"), "Accent")
        self.apply_btn.clicked.connect(self._apply)
        row.addWidget(self.apply_btn)
        lay.addLayout(row)
        self.combo.currentIndexChanged.connect(lambda _i: self._update())
        self.demote.toggled.connect(lambda _o: self._update())
        self._update()

    def _plan(self):
        return cpp.path_fix_plan(
            self.combo.currentData(), "demote" if self.demote.isChecked() else "remove"
        )

    def _update(self):
        plan = self._plan()
        self.preview.setPlainText(cpp.describe_plan(plan))
        self.apply_btn.setEnabled(plan["user_changed"] or plan["machine_changed"])

    def _apply(self):
        plan = self._plan()
        if plan["lost_tools"]:
            r = QMessageBox.question(
                self,
                _("Порядок в PATH"),
                _("Вместе с убранными каталогами пропадут: {tools}. Продолжить?").format(
                    tools=", ".join(plan["lost_tools"])
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if r != QMessageBox.StandardButton.Yes:
                return
        self.apply_btn.setEnabled(False)
        w = FnWorker(lambda: cpp.apply_path_fix(plan))
        w.done.connect(self._done)
        self._workers.append(w)
        w.start()

    def done(self, r):
        _adopt_threads(self, self._workers)
        super().done(r)

    def _done(self, res):
        ok, msg = res if isinstance(res, tuple) else (False, str(res))
        (QMessageBox.information if ok else QMessageBox.warning)(self, _("Порядок в PATH"), msg)
        if ok:
            self.accept()
        else:
            self.apply_btn.setEnabled(True)


class CppCenterDialog(QDialog):
    """C++-центр отдельным окном — тонкая обёртка вокруг CppCenter."""

    def __init__(self, parent, code_cli, **kw):
        super().__init__(parent)
        self.setWindowTitle(_("C++: установка и настройка"))
        self.resize(900, 780)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.center = CppCenter(self, code_cli, **kw)
        self.center._after_folder = self.accept
        lay.addWidget(self.center)

    def closeEvent(self, e):
        if self.center.busy():
            r = QMessageBox.question(
                self,
                _("Идёт установка"),
                _("Установка ещё идёт. Прервать после текущего шага и закрыть?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if r != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.center._runner.cancel()
        super().closeEvent(e)

    def done(self, r):
        self.center._open = False
        _adopt_threads(self, self.center.threads())
        super().done(r)
