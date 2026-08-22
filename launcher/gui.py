# -*- coding: utf-8 -*-
"""Окно PyQt6: карточки стеков, пресеты, замер памяти, установка/удаление."""
import json
import sys
from pathlib import Path

from .core import (
    ROOT, WEIGHT, WEIGHT_LABEL,
    build_ext_index, build_launch_command, code_image_name, code_memory_mb,
    compute_disabled, estimate_saved_mb, find_code_cli, install_extension,
    launch, load_categories, load_config, load_descriptions, load_installed,
    read_installed_from_disk, save_config, uninstall_extension,
)
from .theme import PALETTE, apply_dark_titlebar, build_qss


def run_gui():
    from PyQt6.QtCore import Qt, QRectF, QThread, pyqtSignal, QTimer
    from PyQt6.QtGui import QFont, QPixmap, QPainter, QPainterPath, QColor, QPen
    from PyQt6.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout, QCheckBox,
        QPushButton, QLabel, QLineEdit, QFileDialog, QComboBox,
        QMessageBox, QInputDialog, QPlainTextEdit, QScrollArea, QFrame,
        QSizePolicy, QDialog,
    )

    cats = load_categories()
    ext_index = build_ext_index(cats)
    code_cli = find_code_cli()
    cfg = load_config()
    descriptions = load_descriptions()

    def _card() -> QFrame:
        f = QFrame(); f.setObjectName("Card")
        return f

    def _hline() -> QFrame:
        ln = QFrame(); ln.setObjectName("HLine"); ln.setFixedHeight(1)
        return ln

    def _wrap(lbl: QLabel) -> QLabel:
        # Ignored по горизонтали разрешает лейблу переносить текст, а не тянуть окно
        lbl.setWordWrap(True)
        lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return lbl

    def show_details(parent, key, cat, installed):
        """Диалог со списком плагинов стека: описания + установка/удаление."""
        dlg = QDialog(parent)
        dlg.setWindowTitle(f'Стек: {cat.get("title", key)}')
        dlg.resize(620, 640)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 18, 18, 16); lay.setSpacing(12)

        title = QLabel(cat.get("title", key)); title.setObjectName("Title")
        lay.addWidget(title)
        note = _wrap(QLabel(cat.get("note", ""))); note.setObjectName("Subtitle")
        lay.addWidget(note)

        exts = cat.get("extensions", [])
        weight = WEIGHT.get(key, "light")
        meta = QLabel(); meta.setObjectName("Section")
        lay.addWidget(meta)
        lay.addWidget(_hline())

        # Потоки держим на parent (главном окне), чтобы они пережили закрытие
        # диалога и не роняли приложение на уже удалённых виджетах.
        state = {"open": True}
        dlg.finished.connect(lambda _=0: state.update(open=False))
        rows: dict[str, tuple] = {}          # id -> (tag, install_btn, uninstall_btn)
        bulk_btn = None
        YES = QMessageBox.StandardButton.Yes
        NO = QMessageBox.StandardButton.No

        def refresh_meta():
            n = sum(1 for e in exts if e.lower() in installed)
            meta.setText(f"{len(exts)} расширений · установлено {n} · "
                         f"нагрузка: {WEIGHT_LABEL[weight]}")

        def set_row_state(eid, is_inst):
            tag, ib, ub = rows.get(eid, (None, None, None))
            if tag is not None:
                tag.setText("установлено" if is_inst else "нет в системе")
                tag.setObjectName("Wlight" if is_inst else "Woff")
                tag.style().unpolish(tag); tag.style().polish(tag)
            if ib is not None:
                ib.setVisible(not is_inst); ib.setEnabled(True); ib.setText("Установить")
            if ub is not None:
                ub.setVisible(is_inst); ub.setEnabled(True); ub.setText("Удалить")

        def refresh_bulk():
            if bulk_btn is None:
                return
            left = [e for e in exts if e.lower() not in installed]
            bulk_btn.setEnabled(True)
            bulk_btn.setText(f"Установить недостающие ({len(left)})")
            bulk_btn.setVisible(bool(left))

        def on_done(ext_id, ok, msg, action):
            eid = ext_id.lower()
            if ok:
                installed.add(eid) if action == "install" else installed.discard(eid)
                parent.refresh_installed()
                if state["open"]:
                    set_row_state(eid, action == "install")
                    refresh_meta()
            elif state["open"]:
                set_row_state(eid, eid in installed)
                verb = "установить" if action == "install" else "удалить"
                QMessageBox.warning(dlg, f"Не удалось {verb}",
                                    f"{ext_id}\n\n{(msg or '')[:600]}")

        def on_all_done(action):
            if state["open"]:
                refresh_bulk()

        def start_action(ids, action):
            if action == "install":
                todo = [i for i in ids if i.lower() not in installed]
            else:
                todo = [i for i in ids if i.lower() in installed]
            if not todo or not code_cli:
                return
            if action == "install":
                body = (f"Установить расширение:\n\n{todo[0]}\n\nОно будет скачано "
                        f"из маркетплейса VS Code." if len(todo) == 1 else
                        f"Установить {len(todo)} недостающих расширений стека "
                        f"«{cat.get('title', key)}»?\n\nВсе они будут скачаны из маркетплейса.")
                if QMessageBox.question(dlg, "Скачать и установить?",
                                        body + "\n\nПродолжить?", YES | NO, NO) != YES:
                    return
                busy = "Устанавливаю…"
            else:
                body = (f"Удалить расширение:\n\n{todo[0]}\n\nОно будет удалено с диска. "
                        f"Переустановить можно кнопкой «Установить».")
                if QMessageBox.question(dlg, "Удалить расширение?",
                                        body + "\n\nПродолжить?", YES | NO, NO) != YES:
                    return
                busy = "Удаляю…"
            for i in todo:
                _, ib, ub = rows.get(i.lower(), (None, None, None))
                b = ib if action == "install" else ub
                if b is not None:
                    b.setText(busy); b.setEnabled(False)
            if action == "install" and bulk_btn is not None:
                bulk_btn.setEnabled(False); bulk_btn.setText(busy)
            worker = Installer(code_cli, todo, action)
            worker.one_done.connect(lambda e, ok, m, a=action: on_done(e, ok, m, a))
            worker.all_done.connect(lambda a=action: on_all_done(a))
            parent._install_threads.append(worker)
            worker.start()

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        holder = QWidget(); vb = QVBoxLayout(holder)
        vb.setContentsMargins(0, 0, 6, 0); vb.setSpacing(8)
        for ext in exts:
            row = QFrame(); row.setObjectName("CatCard")
            rl = QVBoxLayout(row); rl.setContentsMargins(12, 9, 12, 9); rl.setSpacing(3)
            top = QHBoxLayout(); top.setSpacing(8)
            name = QLabel(ext); name.setObjectName("CatTitle")
            name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            top.addWidget(name, 1)
            tag = QLabel(); tag.setObjectName("Woff")
            top.addWidget(tag, 0, Qt.AlignmentFlag.AlignVCenter)
            ib = ub = None
            if code_cli:
                ib = QPushButton("Установить"); ib.setObjectName("Ghost")
                ib.setCursor(Qt.CursorShape.PointingHandCursor)
                ib.setToolTip(f"code --install-extension {ext}")
                ib.clicked.connect(lambda _=False, e=ext: start_action([e], "install"))
                top.addWidget(ib, 0, Qt.AlignmentFlag.AlignVCenter)
                ub = QPushButton("Удалить"); ub.setObjectName("Danger")
                ub.setCursor(Qt.CursorShape.PointingHandCursor)
                ub.setToolTip(f"code --uninstall-extension {ext}")
                ub.clicked.connect(lambda _=False, e=ext: start_action([e], "uninstall"))
                top.addWidget(ub, 0, Qt.AlignmentFlag.AlignVCenter)
            rows[ext.lower()] = (tag, ib, ub)
            set_row_state(ext.lower(), ext.lower() in installed)
            rl.addLayout(top)
            dl = _wrap(QLabel(descriptions.get(ext.lower(), "нет описания")))
            dl.setObjectName("CatNote")
            rl.addWidget(dl)
            vb.addWidget(row)
        vb.addStretch()
        scroll.setWidget(holder)
        lay.addWidget(scroll, 1)
        refresh_meta()

        bar = QHBoxLayout()
        if code_cli:
            missing = [e for e in exts if e.lower() not in installed]
            bulk_btn = QPushButton(f"Установить недостающие ({len(missing)})")
            bulk_btn.clicked.connect(
                lambda: start_action([e for e in exts if e.lower() not in installed], "install"))
            bulk_btn.setVisible(bool(missing))
            bar.addWidget(bulk_btn)
        else:
            no_cli = QLabel("нет CLI VS Code — установка/удаление недоступны")
            no_cli.setObjectName("CatNote"); bar.addWidget(no_cli)
        bar.addStretch()
        close = QPushButton("Закрыть"); close.setObjectName("Accent")
        close.clicked.connect(dlg.accept)
        bar.addWidget(close)
        lay.addLayout(bar)
        dlg.exec()

    class ExtLoader(QThread):
        """Фоновая загрузка списка расширений, чтобы окно не подмерзало на старте."""
        loaded = pyqtSignal(list, str)

        def __init__(self, cli):
            super().__init__()
            self._cli = cli

        def run(self):
            ids, source = load_installed(self._cli)
            self.loaded.emit(ids, source)

    class MemProbe(QThread):
        """Фоновый замер памяти запущенного VS Code."""
        measured = pyqtSignal(int, int)

        def __init__(self, cli):
            super().__init__()
            self._cli = cli

        def run(self):
            mb, n = code_memory_mb(self._cli)
            self.measured.emit(mb, n)

    class Installer(QThread):
        """Последовательная установка/удаление в фоне. action: install | uninstall."""
        one_done = pyqtSignal(str, bool, str)
        all_done = pyqtSignal()

        def __init__(self, cli, ids, action="install"):
            super().__init__()
            self._cli = cli
            self._ids = list(ids)
            self._action = action

        def run(self):
            fn = install_extension if self._action == "install" else uninstall_extension
            for i in self._ids:
                ok, msg = fn(self._cli, i)
                self.one_done.emit(i, ok, msg)
            self.all_done.emit()

    class BannerHeader(QFrame):
        """Шапка: PNG-баннер «cover» со скруглёнными углами, иначе ровный фон."""
        RADIUS = 16

        def __init__(self):
            super().__init__()
            self.setObjectName("Header")
            self._pm = QPixmap(str(ROOT / "banner.png"))

        def paintEvent(self, _e):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = QRectF(self.rect())
            path = QPainterPath()
            path.addRoundedRect(rect, self.RADIUS, self.RADIUS)
            p.setClipPath(path)
            if not self._pm.isNull():
                scaled = self._pm.scaled(
                    self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)
                x = (scaled.width() - self.width()) // 2
                y = (scaled.height() - self.height()) // 2
                p.drawPixmap(-x, -y, scaled)
            else:
                p.fillRect(rect, QColor(PALETTE["surface"]))
            p.setClipping(False)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(PALETTE["border"]), 1))
            p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self.RADIUS, self.RADIUS)
            p.end()

    class CategoryCard(QFrame):
        """Кликабельная карточка стека: галочка + название + бейджи."""

        def __init__(self, key: str, cat: dict, inst: int, total: int, on_toggle, on_details):
            super().__init__()
            self.setObjectName("CatCard")
            self.setProperty("on", "false")
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self._on_toggle = on_toggle

            lay = QHBoxLayout(self)
            lay.setContentsMargins(12, 10, 12, 10)
            lay.setSpacing(12)

            self.cb = QCheckBox()
            self.cb.setToolTip(cat.get("note", ""))
            self.cb.stateChanged.connect(self._changed)
            lay.addWidget(self.cb, 0, Qt.AlignmentFlag.AlignVCenter)

            mid = QVBoxLayout(); mid.setSpacing(2)
            title = QLabel(cat.get("title", key)); title.setObjectName("CatTitle")
            note = QLabel(cat.get("note", "")); note.setObjectName("CatNote")
            note.setWordWrap(True)
            note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            mid.addWidget(title); mid.addWidget(note)
            lay.addLayout(mid, 1)

            weight = WEIGHT.get(key, "light")
            wl = QLabel(WEIGHT_LABEL[weight]); wl.setObjectName(f"W{weight}")
            wl.setToolTip("Ориентировочная нагрузка на память при включении")
            lay.addWidget(wl, 0, Qt.AlignmentFlag.AlignVCenter)

            self._total = total
            self.cnt = QLabel(); self.cnt.setObjectName("Count")
            lay.addWidget(self.cnt, 0, Qt.AlignmentFlag.AlignVCenter)
            self.set_installed(inst)

            info = QPushButton("Подробнее"); info.setObjectName("Ghost")
            info.setCursor(Qt.CursorShape.PointingHandCursor)
            info.setToolTip("Показать плагины стека и для чего они")
            info.clicked.connect(on_details)
            lay.addWidget(info, 0, Qt.AlignmentFlag.AlignVCenter)

        def set_installed(self, inst: int):
            total = self._total
            if inst:
                self.cnt.setText(f"{inst}/{total}"); self.cnt.setObjectName("Count")
                self.cnt.setToolTip(f"установлено {inst} из {total} расширений стека")
                self.setToolTip("")
            else:
                self.cnt.setText("нет"); self.cnt.setObjectName("Woff")
                self.cnt.setToolTip(f"ни одно из {total} расширений стека не установлено")
                self.setToolTip("Расширения этого стека не установлены — "
                                "галочка ни на что не влияет")
            self.cnt.style().unpolish(self.cnt); self.cnt.style().polish(self.cnt)

        def _changed(self):
            self.setProperty("on", "true" if self.cb.isChecked() else "false")
            self.style().unpolish(self); self.style().polish(self)
            self._on_toggle()

        def mousePressEvent(self, e):
            self.cb.toggle()
            super().mousePressEvent(e)

        def isChecked(self): return self.cb.isChecked()
        def setChecked(self, v): self.cb.setChecked(v)

    class Launcher(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("VS Code Launcher — переключатель нагрузки")
            self.resize(760, 820)
            self.setMinimumSize(680, 560)
            # Стартуем из кэша (мгновенно), свежий список догружаем в фоне.
            cache = cfg.get("installed_cache", {})
            self.installed = list(cache.get("ids", []))
            self._loaded = bool(self.installed)
            self.cat_checks: dict[str, CategoryCard] = {}
            self._install_threads = []
            self._build_ui()
            self._restore()
            self._update_summary()
            self._start_ext_load()
            self._probe_memory()

        def _probe_memory(self):
            self.mem_lbl.setText("VS Code сейчас: замеряю…")
            self._mem = MemProbe(code_cli)
            self._mem.measured.connect(self._on_memory)
            self._mem.start()

        def _on_memory(self, mb: int, n: int):
            if n:
                self.mem_lbl.setText(f"VS Code сейчас: {mb} МБ · {n} проц.")
                self.mem_lbl.setToolTip("Суммарный working set всех процессов VS Code")
            else:
                self.mem_lbl.setText("VS Code сейчас не запущен")
                self.mem_lbl.setToolTip("")

        def _start_ext_load(self):
            if not self._loaded:
                self.summary.setText("Считаю расширения…")
            self.b_run.setEnabled(False)
            self._loader = ExtLoader(code_cli)
            self._loader.loaded.connect(self._on_installed)
            self._loader.start()

        def _apply_installed(self, ids: list):
            self.installed = ids
            inst_set = set(ids)
            for key, card in self.cat_checks.items():
                exts = cats["categories"][key]["extensions"]
                card.set_installed(sum(1 for e in exts if e.lower() in inst_set))

        def _on_installed(self, ids: list, source: str):
            self.b_run.setEnabled(bool(code_cli))
            self._loaded = True
            if ids and ids != self.installed:
                self._apply_installed(ids)
            elif not ids and not self.installed:
                self.log.appendPlainText("Не удалось получить список расширений.")
            if ids:
                cfg["installed_cache"] = {"ids": ids, "source": source}
                save_config(cfg)
                self.log.appendPlainText(f"Расширений: {len(ids)} (источник: {source}).")
            self._update_summary()

        def refresh_installed(self):
            ids = read_installed_from_disk(code_cli)
            if not ids:
                ids, _ = load_installed(code_cli)
            if ids and ids != self.installed:
                self._apply_installed(ids)
                cfg["installed_cache"] = {"ids": ids, "source": "extensions.json"}
                save_config(cfg)
                self._update_summary()

        def _build_ui(self):
            root = QVBoxLayout(self)
            root.setContentsMargins(18, 18, 18, 14)
            root.setSpacing(14)

            header = BannerHeader()
            header.setFixedHeight(112)
            hl = QHBoxLayout(header); hl.setContentsMargins(24, 16, 24, 16)
            htext = QVBoxLayout(); htext.setSpacing(3)
            title = QLabel("VS Code Launcher"); title.setObjectName("Title")
            sub = _wrap(QLabel("Открой редактор только с нужными стеками — остальные "
                               "тяжёлые серверы не грузятся, память свободна."))
            sub.setObjectName("Subtitle")
            htext.addWidget(title); htext.addWidget(sub)
            hl.addLayout(htext, 1)
            root.addWidget(header)

            if not code_cli:
                warn = _wrap(QLabel("Не найден CLI VS Code (code.cmd). Добавь его в PATH."))
                warn.setObjectName("Warn")
                root.addWidget(warn)

            mem_row = QHBoxLayout(); mem_row.setSpacing(8)
            self.mem_lbl = QLabel("VS Code сейчас: замеряю…"); self.mem_lbl.setObjectName("Section")
            mem_ref = QPushButton("⟳"); mem_ref.setObjectName("Ghost"); mem_ref.setFixedWidth(34)
            mem_ref.setToolTip("Обновить замер памяти запущенного VS Code")
            mem_ref.clicked.connect(self._probe_memory)
            mem_row.addWidget(self.mem_lbl); mem_row.addStretch(); mem_row.addWidget(mem_ref)
            root.addLayout(mem_row)

            pre_card = _card()
            pre = QHBoxLayout(pre_card); pre.setContentsMargins(14, 10, 14, 10); pre.setSpacing(8)
            plbl = QLabel("Пресет"); plbl.setObjectName("Section")
            pre.addWidget(plbl)
            self.preset_box = QComboBox(); self.preset_box.setMinimumWidth(200)
            self._reload_presets()
            self.preset_box.activated.connect(self._apply_preset)
            pre.addWidget(self.preset_box)
            b_save = QPushButton("Сохранить…"); b_save.clicked.connect(self._save_preset)
            b_del = QPushButton("Удалить"); b_del.setObjectName("Ghost"); b_del.clicked.connect(self._delete_preset)
            b_exp = QPushButton("⭱"); b_exp.setObjectName("Ghost"); b_exp.setFixedWidth(34)
            b_exp.setToolTip("Экспортировать все пресеты в файл")
            b_exp.clicked.connect(self._export_presets)
            b_imp = QPushButton("⭳"); b_imp.setObjectName("Ghost"); b_imp.setFixedWidth(34)
            b_imp.setToolTip("Импортировать пресеты из файла (объединяются с текущими)")
            b_imp.clicked.connect(self._import_presets)
            pre.addWidget(b_save); pre.addWidget(b_del)
            pre.addWidget(b_exp); pre.addWidget(b_imp); pre.addStretch()
            b_all = QPushButton("Всё вкл"); b_all.setObjectName("Ghost"); b_all.clicked.connect(lambda: self._set_all(True))
            b_none = QPushButton("Минимум"); b_none.setObjectName("Ghost"); b_none.clicked.connect(lambda: self._set_all(False))
            pre.addWidget(b_all); pre.addWidget(b_none)
            root.addWidget(pre_card)

            sec = QLabel("СТЕКИ  ·  ОТМЕТЬ, ЧТО НУЖНО В ЭТОЙ СЕССИИ")
            sec.setObjectName("Section")
            root.addWidget(sec)

            scroll = QScrollArea(); scroll.setWidgetResizable(True)
            holder = QWidget(); vb = QVBoxLayout(holder)
            vb.setContentsMargins(0, 0, 6, 0); vb.setSpacing(8)
            installed_set = set(self.installed)
            for key, cat in cats.get("categories", {}).items():
                exts = cat["extensions"]
                inst = sum(1 for e in exts if e.lower() in installed_set)
                card = CategoryCard(
                    key, cat, inst, len(exts), self._update_summary,
                    lambda _=False, k=key, c=cat: show_details(self, k, c, set(self.installed)))
                self.cat_checks[key] = card
                vb.addWidget(card)
            vb.addStretch()
            scroll.setWidget(holder)
            root.addWidget(scroll, 1)

            ao = cats.get("always_on", {})
            ao_lbl = QLabel(f'{ao.get("title","Ядро")}: {len(ao.get("extensions",[]))} шт. '
                            f'— грузятся всегда. {ao.get("note","")}')
            ao_lbl.setObjectName("Core"); _wrap(ao_lbl)
            root.addWidget(ao_lbl)

            fold_card = _card()
            fv = QVBoxLayout(fold_card); fv.setContentsMargins(14, 12, 14, 12); fv.setSpacing(8)
            flbl = QLabel("ПАПКА ПРОЕКТА (НЕОБЯЗАТЕЛЬНО)"); flbl.setObjectName("Section")
            fv.addWidget(flbl)
            fbox = QHBoxLayout(); fbox.setSpacing(8)
            self.folder_edit = QLineEdit()
            self.folder_edit.setPlaceholderText("путь к проекту, который открыть")
            fbox.addWidget(self.folder_edit)
            b_browse = QPushButton("Обзор…"); b_browse.clicked.connect(self._browse)
            fbox.addWidget(b_browse)
            fv.addLayout(fbox)
            self.recent_box = QComboBox()
            self.recent_box.addItem("— недавние папки —", "")
            for p in cfg.get("recent_folders", []):
                self.recent_box.addItem(p, p)
            self.recent_box.activated.connect(
                lambda: self.folder_edit.setText(self.recent_box.currentData() or ""))
            fv.addWidget(self.recent_box)
            root.addWidget(fold_card)

            self.kill_cb = QCheckBox("Закрыть VS Code перед стартом (чтобы память освободилась)")
            self.kill_cb.setChecked(cfg.get("kill_first", True))
            self.kill_cb.setToolTip(
                f"Принудительно закроет все окна VS Code ({code_image_name(code_cli)}). "
                "Сохрани файлы заранее! Запускай этот тул НЕ из терминала VS Code.")
            root.addWidget(self.kill_cb)
            self.newwin_cb = QCheckBox("Открыть в новом окне (--new-window)")
            self.newwin_cb.setChecked(cfg.get("new_window", True))
            root.addWidget(self.newwin_cb)
            self.gpu_cb = QCheckBox("Без GPU-ускорения (--disable-gpu) — для слабых видеокарт")
            self.gpu_cb.setChecked(cfg.get("disable_gpu", False))
            self.gpu_cb.setToolTip("Отключает аппаратное ускорение отрисовки. "
                                   "Иногда лечит артефакты/лаги на старых GPU и экономит немного памяти.")
            root.addWidget(self.gpu_cb)
            self.bare_cb = QCheckBox("Голый режим: полностью без расширений (--disable-extensions)")
            self.bare_cb.setToolTip("Отключит ВСЕ расширения, включая ядро — максимальная скорость. "
                                    "Галочки стеков при этом игнорируются.")
            self.bare_cb.stateChanged.connect(self._update_summary)
            root.addWidget(self.bare_cb)

            prof_row = QHBoxLayout(); prof_row.setSpacing(8)
            prof_lbl = QLabel("Профиль"); prof_lbl.setObjectName("Section")
            self.profile_edit = QLineEdit(); self.profile_edit.setText(cfg.get("profile", ""))
            self.profile_edit.setPlaceholderText("имя существующего профиля VS Code (необязательно)")
            self.profile_edit.setToolTip(
                "Откроет окно с этим профилем (--profile). Профиль нужно заранее создать "
                "в VS Code (шестерёнка → Profiles). Пусто — профиль по умолчанию.")
            prof_row.addWidget(prof_lbl); prof_row.addWidget(self.profile_edit, 1)
            root.addLayout(prof_row)

            root.addWidget(_hline())
            bar = QHBoxLayout(); bar.setSpacing(10)
            self.summary = QLabel(); self.summary.setObjectName("Summary")
            bar.addWidget(self.summary, 1)
            b_cmd = QPushButton("Показать команду"); b_cmd.setObjectName("Ghost")
            b_cmd.clicked.connect(self._show_cmd)
            self.b_run = QPushButton("Запустить VS Code"); self.b_run.setObjectName("Accent")
            self.b_run.clicked.connect(self._run)
            bar.addWidget(b_cmd); bar.addWidget(self.b_run)
            root.addLayout(bar)

            self.log = QPlainTextEdit(); self.log.setObjectName("Log")
            self.log.setReadOnly(True); self.log.setMaximumHeight(90)
            self.log.setPlaceholderText("Здесь появится итоговая команда и статус запуска.")
            root.addWidget(self.log)

        def _selected(self) -> set[str]:
            return {k for k, cb in self.cat_checks.items() if cb.isChecked()}

        def _set_all(self, state: bool):
            for cb in self.cat_checks.values():
                cb.setChecked(state)

        def _disabled_list(self) -> list[str]:
            return compute_disabled(self.installed, ext_index, self._selected())

        def _bare(self) -> bool:
            return getattr(self, "bare_cb", None) is not None and self.bare_cb.isChecked()

        def _update_summary(self):
            if self._bare():
                self.summary.setText("Голый режим: все расширения выключены "
                                     "(--disable-extensions).")
                return
            if not self.installed:
                self.summary.setText("Список расширений не получен (нет CLI?).")
                return
            dis = self._disabled_list()
            en = len(self.installed) - len(dis)
            saved = estimate_saved_mb(dis, ext_index)
            self.summary.setText(f"Вкл {en} · выкл {len(dis)} · ~{saved} МБ экономии")

        def _cmd_kwargs(self) -> dict:
            return {
                "profile": self.profile_edit.text().strip(),
                "disable_gpu": self.gpu_cb.isChecked(),
                "bare": self._bare(),
            }

        def _browse(self):
            d = QFileDialog.getExistingDirectory(self, "Выбери папку проекта")
            if d:
                self.folder_edit.setText(d.replace("/", "\\"))

        def _show_cmd(self):
            cmd = build_launch_command(code_cli or "code", self._disabled_list(),
                                       self.folder_edit.text().strip(),
                                       self.newwin_cb.isChecked(), self.kill_cb.isChecked(),
                                       **self._cmd_kwargs())
            self.log.setPlainText(cmd)

        def _run(self):
            if not code_cli:
                QMessageBox.critical(self, "Ошибка", "Не найден CLI VS Code (code.cmd).")
                return
            if self.kill_cb.isChecked():
                r = QMessageBox.question(
                    self, "Закрыть VS Code?",
                    "Сейчас будут ПРИНУДИТЕЛЬНО закрыты все окна VS Code, "
                    "затем откроется новое с выбранным набором.\n\n"
                    "Сохранил несохранённые файлы? Продолжить?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if r != QMessageBox.StandardButton.Yes:
                    return
            dis = self._disabled_list()
            cmd = build_launch_command(code_cli, dis, self.folder_edit.text().strip(),
                                       self.newwin_cb.isChecked(), self.kill_cb.isChecked(),
                                       **self._cmd_kwargs())
            try:
                launch(cmd)
                if self._bare():
                    self.log.appendPlainText("Запуск: голый режим (все расширения выкл). OK.")
                else:
                    self.log.appendPlainText(f"Запуск: выключено {len(dis)} расширений. OK.")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка запуска", str(e))
                return
            self._persist()
            QTimer.singleShot(6000, self._probe_memory)   # покажем новый footprint

        def _reload_presets(self):
            self.preset_box.blockSignals(True)
            self.preset_box.clear()
            self.preset_box.addItem("— выбрать пресет —", None)
            for name in cfg.get("presets", {}):
                self.preset_box.addItem(name, name)
            self.preset_box.blockSignals(False)

        def _apply_preset(self):
            name = self.preset_box.currentData()
            if not name:
                return
            keys = set(cfg["presets"].get(name, []))
            for k, cb in self.cat_checks.items():
                cb.setChecked(k in keys)

        def _save_preset(self):
            name, ok = QInputDialog.getText(self, "Сохранить пресет", "Имя пресета:")
            if not ok or not name.strip():
                return
            cfg.setdefault("presets", {})[name.strip()] = sorted(self._selected())
            save_config(cfg)
            self._reload_presets()
            i = self.preset_box.findData(name.strip())
            if i >= 0:
                self.preset_box.setCurrentIndex(i)

        def _delete_preset(self):
            name = self.preset_box.currentData()
            if name and name in cfg.get("presets", {}):
                del cfg["presets"][name]
                save_config(cfg)
                self._reload_presets()

        def _export_presets(self):
            presets = cfg.get("presets", {})
            if not presets:
                QMessageBox.information(self, "Экспорт", "Пресетов пока нет.")
                return
            path, _ = QFileDialog.getSaveFileName(
                self, "Экспорт пресетов", "vscode_launcher_presets.json", "JSON (*.json)")
            if not path:
                return
            try:
                Path(path).write_text(
                    json.dumps(presets, ensure_ascii=False, indent=2), encoding="utf-8")
                self.log.appendPlainText(f"Экспортировано пресетов: {len(presets)} → {path}")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка экспорта", str(e))

        def _import_presets(self):
            path, _ = QFileDialog.getOpenFileName(self, "Импорт пресетов", "", "JSON (*.json)")
            if not path:
                return
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("ожидается объект {имя: [категории]}")
                incoming = {str(k): [str(x) for x in v]
                            for k, v in data.items() if isinstance(v, list)}
            except Exception as e:
                QMessageBox.critical(self, "Ошибка импорта", str(e))
                return
            cfg.setdefault("presets", {}).update(incoming)
            save_config(cfg)
            self._reload_presets()
            self.log.appendPlainText(f"Импортировано пресетов: {len(incoming)}")

        def _restore(self):
            last = set(cfg.get("last_selected", []))
            if last:
                for k, cb in self.cat_checks.items():
                    cb.setChecked(k in last)
            recent = cfg.get("recent_folders", [])
            if recent and not self.folder_edit.text().strip():
                self.folder_edit.setText(recent[0])

        def _persist(self):
            cfg["last_selected"] = sorted(self._selected())
            cfg["kill_first"] = self.kill_cb.isChecked()
            cfg["new_window"] = self.newwin_cb.isChecked()
            cfg["disable_gpu"] = self.gpu_cb.isChecked()
            cfg["profile"] = self.profile_edit.text().strip()
            folder = self.folder_edit.text().strip()
            if folder:
                rec = [folder] + [p for p in cfg.get("recent_folders", []) if p != folder]
                cfg["recent_folders"] = rec[:8]
            save_config(cfg)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    font = QFont(); font.setPointSize(10); app.setFont(font)
    app.setStyleSheet(build_qss(PALETTE))
    w = Launcher()
    icon_path = ROOT / "banner.png"
    if icon_path.exists():
        from PyQt6.QtGui import QIcon
        w.setWindowIcon(QIcon(str(icon_path)))
    w.show()
    apply_dark_titlebar(w)   # после show(), когда есть нативный hwnd
    sys.exit(app.exec())
