# -*- coding: utf-8 -*-
"""Окно PyQt6: сборка Launcher-класса, диалоги, точка входа run_gui.

Дизайн модуля: чистые части вынесены отдельно, чтобы этот файл читался
как сценарий работы окна, а не как сборник всего подряд.

- gui_widgets.py — CategoryCard и микро-фабрики карточек;
- gui_workers.py — фоновые QThread'ы (ExtLoader, MemProbe, Installer);
- core.py        — вся бизнес-логика (см. фасад для навигации по подмодулям).

Здесь остаются: run_gui (входная точка), внутренние Launcher и show_details.
Они держат общее состояние сессии через замыкания (cats, cfg, code_cli,
descriptions, log, duplicates), поэтому живут вместе.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QByteArray, QTimer, QUrl
from PyQt6.QtGui import QFont, QIcon, QPixmap, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QCheckBox,
    QPushButton, QLabel, QLineEdit, QFileDialog, QComboBox,
    QMessageBox, QInputDialog, QPlainTextEdit, QScrollArea, QFrame,
    QDialog, QProgressBar,
)

from . import __version__
from .core import (
    ICON_FILE, LOGO_FILE, WEIGHT, WEIGHT_HELP, WEIGHT_LABEL, WEIGHT_MB,
    apply_settings, build_ext_index, build_launch_args, build_launch_command,
    build_dependency_map, build_shortcut_cmd, categories_present,
    code_image_name, compute_disabled,
    detect_recommended_stacks, detect_stacks, read_extension_manifests,
    disabled_by_category, estimate_saved_mb,
    find_duplicate_extensions, kill_vscode, launch_detached, list_code_installs,
    load_categories,
    load_config, load_descriptions, load_recommended,
    lookup_footprint, marketplace_url, measured_savings_mb, normalize_preset,
    preset_stacks, profile_file_content, read_installed_from_disk, recall_folder_stacks,
    recommended_for, record_baseline, record_footprint, remember_folder_stacks,
    resolve_code_cli, save_config, selection_signature, setup_logging,
    suggest_categories, vscode_process_count, vscode_user_settings_path, load_installed,
)
from .cli import _launcher_invocation
from .i18n import _, get_language, set_language
from .updates import RELEASES_URL, build_update_swap_bat
from .gui_widgets import (
    CategoryCard, FlowLayout, _card, _hline, _wrap, set_switch_palette,
)
from .gui_workers import (
    ElevatedInstaller, ExtLoader, FnWorker, Installer, MemProbe,
    ToolchainInstaller, UpdateCheck, UpdateDownloader,
)
from .theme import PALETTES, apply_titlebar, build_qss
from . import toolchains as _tc


# --- точка входа -----------------------------------------------------------

def run_gui():
    log = setup_logging()
    cats, cats_err = load_categories()
    duplicates = find_duplicate_extensions(cats)
    cfg = load_config()
    # #6: оверлей раскладки незнакомых расширений (мастер) — сливается в индекс
    # неразрушающе; сама categories.json не трогается.
    ext_index = build_ext_index(cats, cfg.get("extra_categories"))
    # #13: путь к CLI можно задать вручную в конфиге (портативная/нестандартная
    # сборка) — resolve_code_cli учитывает его, иначе ищет как раньше.
    code_cli = resolve_code_cli(cfg)
    set_language(cfg.get("lang", "ru"))   # #7: до сборки UI, чтобы _() перевёл строки
    # Заполняется в конце run_gui (см. rebuild). Метод _switch_language дёргает
    # его, чтобы пересобрать окно на новом языке. Объявляем здесь, чтобы имя
    # стало локальным run_gui и попало в замыкание методов Launcher.
    _lang_switch = {"fn": None}
    descriptions = load_descriptions()
    log.info("Старт v%s · CLI=%s · тема=%s%s", __version__, code_cli,
             cfg.get("theme", "dark"), f" · categories.json: {cats_err}" if cats_err else "")
    # Дубли в карте — тихая мина: build_ext_index молча оставляет последнее
    # назначение, и стек, куда расширение было положено раньше, теряет его.
    # Пишем в лог сразу и покажем предупреждение в окне.
    if duplicates:
        preview = ", ".join(f"{e} ({'/'.join(k)})"
                            for e, k in sorted(duplicates.items())[:3])
        more = "…" if len(duplicates) > 3 else ""
        log.warning("В categories.json дубли расширений: %d (%s%s)",
                    len(duplicates), preview, more)

    # Чистим «мёртвые» ключи категорий в пресетах/последнем выборе (например,
    # если категорию переименовали в categories.json). Только когда карта
    # загрузилась — иначе пустой набор ключей стёр бы все пресеты.
    if not cats_err:
        valid_keys = set(cats.get("categories", {}))
        dirty = False
        for name, value in list(cfg.get("presets", {}).items()):
            stacks = preset_stacks(value)   # #4: пресет может быть списком или словарём
            cleaned = [k for k in stacks if k in valid_keys]
            if cleaned != stacks:
                cfg["presets"][name] = ({**value, "stacks": cleaned}
                                        if isinstance(value, dict) else cleaned)
                dirty = True
        last = cfg.get("last_selected", [])
        cleaned_last = [k for k in last if k in valid_keys]
        if cleaned_last != last:
            cfg["last_selected"] = cleaned_last; dirty = True
        if dirty:
            save_config(cfg)
            log.info("Очищены несуществующие ключи категорий в конфиге")

    def show_details(parent, key, cat, installed):
        """Диалог со списком плагинов стека: описания + установка/удаление."""
        dlg = QDialog(parent)
        dlg.setWindowTitle(f'Стек: {cat.get("title", key)}')
        dlg.resize(820, 660)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 18, 18, 16); lay.setSpacing(12)

        title = QLabel(cat.get("title", key)); title.setObjectName("Title")
        lay.addWidget(title)
        note = _wrap(QLabel(cat.get("note", ""))); note.setObjectName("Subtitle")
        lay.addWidget(note)

        exts = cat.get("extensions", [])
        weight = WEIGHT.get(key, "light")

        # Поясняем, что вообще делает это окно и что значат кнопки: пользователь
        # должен понимать, что он ставит/удаляет и что это обратимо.
        intro = _wrap(QLabel(_(
            "Ниже — расширения этого стека и что каждое делает. "
            "«Маркетплейс» открывает страницу расширения — прочитать, что это, "
            "перед установкой. «Установить» качает его из маркетплейса VS Code, "
            "«Удалить» стирает с диска (можно поставить заново). Отключение "
            "стека галочкой в главном окне ничего не удаляет — только не грузит "
            "в этой сессии.")))
        intro.setObjectName("CatNote")
        lay.addWidget(intro)

        meta = QLabel(); meta.setObjectName("Section")
        meta.setToolTip(_(WEIGHT_HELP.get(weight, "")))
        lay.addWidget(meta)
        lay.addWidget(_hline())

        # Потоки держим на parent (главном окне), чтобы они пережили закрытие
        # диалога и не роняли приложение на уже удалённых виджетах.
        state = {"open": True}
        dlg.finished.connect(lambda _=0: state.update(open=False))
        rows: dict[str, tuple] = {}          # id -> (tag, install_btn, uninstall_btn)
        bulk_btn = None
        status_lbl = None    # строка прогресса «Устанавливаю i/n…» (создаётся в баре)
        prog_bar = None      # полоска прогресса установки/удаления
        cancel_btn = None    # кнопка отмены пакетной операции
        YES = QMessageBox.StandardButton.Yes
        NO = QMessageBox.StandardButton.No

        def refresh_meta():
            n = sum(1 for e in exts if e.lower() in installed)
            approx = WEIGHT_MB.get(weight, 30)
            meta.setText(_("{total} расширений · установлено {n} · нагрузка "
                           "{load} · выключение освобождает ~{mb} МБ").format(
                total=len(exts), n=n, load=_(WEIGHT_LABEL[weight]), mb=approx))

        def set_row_state(eid, is_inst):
            tag, ib, ub = rows.get(eid, (None, None, None))
            if tag is not None:
                tag.setText(_("установлено") if is_inst else _("нет в системе"))
                tag.setObjectName("Wlight" if is_inst else "Woff")
                tag.setToolTip(_("Расширение установлено — грузится в VS Code, "
                                 "пока стек включён.") if is_inst else
                               _("Расширения нет на диске. «Установить» скачает "
                                 "его из маркетплейса."))
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
                busy_word = _("Устанавливаю")
            else:
                body = (f"Удалить расширение:\n\n{todo[0]}\n\nОно будет удалено с диска. "
                        f"Переустановить можно кнопкой «Установить».")
                if QMessageBox.question(dlg, "Удалить расширение?",
                                        body + "\n\nПродолжить?", YES | NO, NO) != YES:
                    return
                busy = "Удаляю…"
                busy_word = _("Удаляю")
            for i in todo:
                # NB: не называть переменную `_` — это затенит функцию перевода
                # i18n._ во всей start_action и уронит вызовы _(...) выше по коду.
                _tag, ib, ub = rows.get(i.lower(), (None, None, None))
                b = ib if action == "install" else ub
                if b is not None:
                    b.setText(busy); b.setEnabled(False)
            if action == "install" and bulk_btn is not None:
                bulk_btn.setEnabled(False); bulk_btn.setText(busy)
            if prog_bar is not None:
                # Пакетная — определённый прогресс 0..N; одиночная — «бегущая»
                # неопределённая полоска (range 0,0), пока идёт единственный шаг.
                if len(todo) > 1:
                    prog_bar.setRange(0, len(todo)); prog_bar.setValue(0)
                else:
                    prog_bar.setRange(0, 0)
                prog_bar.setVisible(True)

            # Контекст одного запуска: считаем обработанные и ошибки, чтобы в
            # конце показать одну сводку вместо череды попапов на пакетной
            # операции. Одиночную ошибку показываем сразу — она про конкретный id.
            bulk = len(todo) > 1
            total = len(todo)
            processed: list[str] = []
            fails: list[tuple[str, str]] = []

            def _one(ext_id, ok, msg):
                eid = ext_id.lower()
                processed.append(eid)
                if ok:
                    installed.add(eid) if action == "install" else installed.discard(eid)
                    parent.refresh_installed()
                    if state["open"]:
                        set_row_state(eid, action == "install")
                        refresh_meta()
                else:
                    fails.append((ext_id, msg or ""))
                    if state["open"]:
                        set_row_state(eid, eid in installed)
                        if not bulk:   # пакетную ошибку копим на сводку
                            verb = _("установить") if action == "install" else _("удалить")
                            QMessageBox.warning(dlg, _("Не удалось {verb}").format(verb=verb),
                                                f"{ext_id}\n\n{(msg or '')[:600]}")

            def _progress(i, n):
                if not state["open"]:
                    return
                if status_lbl is not None:
                    status_lbl.setText(f"{busy_word} {i}/{n}…" if n > 1 else f"{busy_word}…")
                    status_lbl.setVisible(True)
                if prog_bar is not None and n > 1:
                    prog_bar.setValue(i - 1)   # столько уже завершено

            def _all():
                if not state["open"]:
                    return
                refresh_bulk()
                if cancel_btn is not None:
                    cancel_btn.setVisible(False)
                if prog_bar is not None:
                    prog_bar.setVisible(False)
                if not bulk:
                    if status_lbl is not None:
                        status_lbl.setVisible(False)
                    return
                ok_n = len(processed) - len(fails)
                rem = total - len(processed)   # не обработано (отмена)
                verb = _("Установлено") if action == "install" else _("Удалено")
                summary = _("{verb}: {ok}, ошибок: {err}").format(
                    verb=verb, ok=ok_n, err=len(fails))
                if rem:
                    summary += _(", отменено: {rem}").format(rem=rem)
                if status_lbl is not None:
                    status_lbl.setText(summary); status_lbl.setVisible(True)
                if fails:
                    preview = "\n".join(f"• {eid}: {(m or '').splitlines()[0][:120]}"
                                        for eid, m in fails[:8])
                    more = "\n…" if len(fails) > 8 else ""
                    QMessageBox.warning(dlg, _("Готово с ошибками"),
                                        summary + "\n\n" + preview + more)

            worker = Installer(code_cli, todo, action)
            worker.progress.connect(_progress)
            worker.one_done.connect(_one)
            worker.all_done.connect(_all)
            worker.finished.connect(lambda w=worker: parent._reap_installer(w))
            if bulk and cancel_btn is not None:
                cancel_btn.setVisible(True); cancel_btn.setEnabled(True)
                try:
                    cancel_btn.clicked.disconnect()
                except TypeError:
                    pass

                def _do_cancel(_checked=False, w=worker):
                    w.cancel()
                    cancel_btn.setEnabled(False)
                    if status_lbl is not None:
                        status_lbl.setText(_("Отмена…"))
                cancel_btn.clicked.connect(_do_cancel)
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

            # #9: персональный оверрайд поведения этого расширения.
            ov_box = QComboBox()
            ov_box.setToolTip(_("Поведение этого расширения независимо от галочки стека"))
            for label, mode in ((_("по стеку"), "default"),
                                (_("всегда вкл"), "enable"),
                                (_("всегда выкл"), "disable")):
                ov_box.addItem(label, mode)
            cur = parent.override_mode(ext)
            i_cur = ov_box.findData(cur)
            if i_cur >= 0:
                ov_box.setCurrentIndex(i_cur)
            ov_box.currentIndexChanged.connect(
                lambda _i, e=ext, b=ov_box: parent.set_override(e, b.currentData()))
            top.addWidget(ov_box, 0, Qt.AlignmentFlag.AlignVCenter)

            # «Маркетплейс» — прочитать, что за расширение, ПЕРЕД установкой.
            # Доступно всегда, даже без CLI (это просто ссылка в браузер).
            mkt_url = marketplace_url(ext)
            if mkt_url:
                mkt = QPushButton(_("Маркетплейс ↗")); mkt.setObjectName("Ghost")
                mkt.setCursor(Qt.CursorShape.PointingHandCursor)
                mkt.setToolTip(_("Открыть страницу расширения в маркетплейсе "
                                 "VS Code — описание, автор, рейтинг и что оно "
                                 "запрашивает — перед установкой."))
                mkt.clicked.connect(
                    lambda _=False, u=mkt_url: QDesktopServices.openUrl(QUrl(u)))
                top.addWidget(mkt, 0, Qt.AlignmentFlag.AlignVCenter)

            ib = ub = None
            if code_cli:
                ib = QPushButton(_("Установить")); ib.setObjectName("Ghost")
                ib.setCursor(Qt.CursorShape.PointingHandCursor)
                ib.setToolTip(_("Скачать и установить это расширение из "
                                "маркетплейса VS Code.") + f"\n\ncode --install-extension {ext}")
                ib.clicked.connect(lambda _=False, e=ext: start_action([e], "install"))
                top.addWidget(ib, 0, Qt.AlignmentFlag.AlignVCenter)
                ub = QPushButton(_("Удалить")); ub.setObjectName("Danger")
                ub.setCursor(Qt.CursorShape.PointingHandCursor)
                ub.setToolTip(_("Удалить расширение с диска. Переустановить можно "
                                "кнопкой «Установить».") + f"\n\ncode --uninstall-extension {ext}")
                ub.clicked.connect(lambda _=False, e=ext: start_action([e], "uninstall"))
                top.addWidget(ub, 0, Qt.AlignmentFlag.AlignVCenter)
            rows[ext.lower()] = (tag, ib, ub)
            set_row_state(ext.lower(), ext.lower() in installed)
            rl.addLayout(top)
            desc = descriptions.get(ext.lower())
            dl = _wrap(QLabel(desc or _("Описание не задано — открой «Маркетплейс», "
                                        "чтобы прочитать, что делает расширение.")))
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
            # Прогресс установки/удаления + отмена (скрыты, пока не идёт операция).
            status_lbl = QLabel(); status_lbl.setObjectName("CatNote")
            status_lbl.setVisible(False)
            bar.addWidget(status_lbl)
            prog_bar = QProgressBar(); prog_bar.setObjectName("InstallBar")
            prog_bar.setTextVisible(False); prog_bar.setFixedWidth(140)
            prog_bar.setFixedHeight(8); prog_bar.setVisible(False)
            bar.addWidget(prog_bar, 0, Qt.AlignmentFlag.AlignVCenter)
            cancel_btn = QPushButton(_("Отмена")); cancel_btn.setObjectName("Ghost")
            cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            cancel_btn.setToolTip(_("Прервать пакетную установку (текущее расширение "
                                    "доустановится, следующие — нет)"))
            cancel_btn.setVisible(False)
            bar.addWidget(cancel_btn)
        else:
            no_cli = QLabel("нет CLI VS Code — установка/удаление недоступны")
            no_cli.setObjectName("CatNote"); bar.addWidget(no_cli)
        bar.addStretch()
        close = QPushButton(_("Закрыть")); close.setObjectName("Accent")
        close.clicked.connect(dlg.accept)
        bar.addWidget(close)
        lay.addLayout(bar)
        dlg.exec()

    class Launcher(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle(f"VS Code Launcher {__version__} — переключатель нагрузки")
            self.resize(1040, 860)   # с запасом под 2 колонки карточек
            self.setMinimumSize(680, 560)
            # Стартуем из кэша (мгновенно), свежий список догружаем в фоне.
            cache = cfg.get("installed_cache", {})
            self.installed = list(cache.get("ids", []))
            self._loaded = bool(self.installed)
            self.cat_checks: dict[str, CategoryCard] = {}
            self._install_threads = []
            # #9: персональные оверрайды по одному расширению (перекрывают стек).
            ov = cfg.get("overrides", {})
            self._force_disable = {e.lower() for e in ov.get("disable", [])}
            self._force_enable = {e.lower() for e in ov.get("enable", [])}
            self._dep_map = None              # #1: карта зависимостей (ленивая, кэш)
            self._pending_record_sig = None   # #6: подпись выбора для замера после запуска
            self._pending_is_baseline = False # #2: следующий замер — базлайн «всё вкл»
            self._suggested_keys: set[str] = set()   # #1: что предложил автодетект
            self._auto_suggested = False      # #1: авто-подсказку при старте делаем один раз
            self._theme = cfg.get("theme", "dark")
            if self._theme not in PALETTES:
                self._theme = "dark"
            self._pal = PALETTES[self._theme]
            set_switch_palette(self._pal)   # цвета тумблеров под тему
            self._build_ui()
            self._restore()
            self._maybe_auto_suggest()   # #1: если папка подставилась из «недавних»
            self._update_summary()
            # Первая раскладка карточек-сетки, когда окно получит реальную ширину.
            QTimer.singleShot(0, self._relayout_cards)
            self._start_ext_load()
            self._probe_memory()
            self._start_update_check()   # #8
            geo = cfg.get("geometry")
            if geo:   # запоминаем размер и позицию окна между запусками
                try:
                    self.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))
                except Exception:
                    pass

        def _update_theme_btn(self):
            # Показываем текущую тему; действие поясняет tooltip.
            self.theme_btn.setText(_("Светлая") if self._theme == "light" else _("Тёмная"))

        def _toggle_theme(self):
            self._theme = "light" if self._theme == "dark" else "dark"
            self._pal = PALETTES[self._theme]
            set_switch_palette(self._pal)   # тумблеры перекрашиваем под новую тему
            QApplication.instance().setStyleSheet(build_qss(self._pal))
            apply_titlebar(self, self._theme == "dark")
            self._update_theme_btn()
            for card in self.cat_checks.values():   # перерисовать тумблеры
                card.cb.update()
            cfg["theme"] = self._theme
            save_config(cfg)

        def _probe_memory(self):
            # Не плодим второй поток, пока прошлый замер не закончился: иначе
            # ссылка на живой QThread терялась бы и Qt ронял приложение.
            if getattr(self, "_mem", None) is not None and self._mem.isRunning():
                return
            self.mem_lbl.setText(_("VS Code сейчас: замеряю…"))
            self._mem = MemProbe(code_cli)
            self._mem.measured.connect(self._on_memory)
            self._mem.start()

        def _on_memory(self, mb: int, n: int):
            if n:
                self.mem_lbl.setText(
                    _("VS Code сейчас: {mb} МБ, {n} процессов").format(mb=mb, n=n))
                self.mem_lbl.setToolTip(_("Private working set всех процессов VS Code "
                                          "(неразделяемая, реально освобождаемая память)"))
            else:
                self.mem_lbl.setText(_("VS Code сейчас не запущен"))
                self.mem_lbl.setToolTip("")
            # #6: после запуска записываем фактический footprint под подпись выбора.
            # #2: если это был запуск без единого выключенного стека — это базлайн
            # «всё включено», от которого считается реальная экономия.
            dirty = False
            if self._pending_record_sig and n:
                record_footprint(cfg, self._pending_record_sig, mb, n)
                self._pending_record_sig = None
                dirty = True
            if self._pending_is_baseline and n:
                record_baseline(cfg, mb, n)
                self._pending_is_baseline = False
                dirty = True
            if dirty:
                save_config(cfg)
                self._update_summary()

        # --- выбор установки VS Code (#18) --------------------------------
        def _choose_code_cli(self):
            """#18: выбрать, какой VS Code запускать — стабильную/Insiders/
            портативную. Показываем найденные установки + «Обзор…» (указать
            code.cmd/Code.exe вручную) + «Авто» (сбросить на автопоиск). Выбор
            сохраняется в cfg['code_cli'] и применяется НА ЛЕТУ: переопределяем
            замыкание code_cli и перечитываем расширения/память — без
            перезапуска окна."""
            nonlocal code_cli
            installs = list_code_installs()
            AUTO = _("Авто (автопоиск)")
            BROWSE = _("Обзор… (указать путь вручную)")
            items = [f"{label}  —  {path}" for label, path in installs]
            items += [AUTO, BROWSE]
            cur = code_cli or _("не найден")
            choice, ok = QInputDialog.getItem(
                self, _("Установка VS Code"),
                _("Сейчас: {cur}\n\nВыбери установку:").format(cur=cur),
                items, 0, False)
            if not ok:
                return
            new_path = None            # None -> авто (сброс)
            if choice == BROWSE:
                picked, _filt = QFileDialog.getOpenFileName(
                    self, _("Выбери code.cmd или Code.exe"), "",
                    "VS Code CLI (code.cmd code-insiders.cmd Code.exe);;Все файлы (*.*)")
                if not picked:
                    return
                new_path = picked
            elif choice == AUTO:
                new_path = None
            else:
                idx = items.index(choice)
                new_path = installs[idx][1]

            if new_path:
                cfg["code_cli"] = new_path
            else:
                cfg.pop("code_cli", None)
            save_config(cfg)

            code_cli = resolve_code_cli(cfg)   # переопределяем замыкание
            self._dep_map = None               # #1: другой VS Code — другой набор
            self.b_run.setEnabled(bool(code_cli))
            self.log.appendPlainText(
                _("VS Code CLI: {cli}").format(cli=code_cli or _("не найден")))
            self._loaded = False
            self._start_ext_load()             # перечитать расширения нового VS Code
            self._probe_memory()               # и его память

        # --- проверка обновлений (#8) -------------------------------------
        def _start_update_check(self):
            if not cfg.get("check_updates", True):
                return
            self._upd = UpdateCheck(__version__)
            self._upd.done.connect(self._on_update)
            self._upd.start()

        def _on_update(self, ver: str):
            if not ver:
                return
            self._update_tag = ver
            # #10: у собранного exe предлагаем скачать и обновиться на месте;
            # из исходников — просто открыть страницу релизов (обновляться нечему).
            if getattr(sys, "frozen", False):
                self.update_bar.setText(
                    _("Доступна новая версия {ver} — скачать и установить").format(ver=ver))
            else:
                self.update_bar.setText(
                    _("Доступна новая версия {ver} — открыть страницу релизов").format(ver=ver))
            self.update_bar.setVisible(True)

        def _on_update_clicked(self):
            """#10: клик по баннеру. Из исходников открываем страницу релизов.
            Для собранного exe — скачиваем новую версию, сверяем SHA256 и
            применяем через .bat-своп (запущенный exe заменить нельзя, поэтому
            своп ждёт закрытия, меняет файл и перезапускает)."""
            if not getattr(sys, "frozen", False):
                QDesktopServices.openUrl(QUrl(RELEASES_URL))
                return
            tag = getattr(self, "_update_tag", "")
            if getattr(self, "_dl", None) is not None and self._dl.isRunning():
                return
            if QMessageBox.question(
                    self, _("Обновление"),
                    _("Скачать и установить {ver}? Лаунчер закроется и "
                      "обновится сам.").format(ver=tag),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            exe = Path(sys.executable)
            dest = exe.with_name(f"{exe.stem}-{tag}.new.exe")
            self.update_bar.setEnabled(False)
            self.update_bar.setText(_("Скачиваю обновление…"))
            self._dl = UpdateDownloader(dest)
            self._dl.progress.connect(self._on_dl_progress)
            self._dl.done.connect(self._on_dl_done)
            self._dl.start()

        def _on_dl_progress(self, got: int, total: int):
            if total > 0:
                pct = int(got * 100 / total)
                self.update_bar.setText(_("Скачиваю обновление… {pct}%").format(pct=pct))
            else:
                self.update_bar.setText(
                    _("Скачиваю обновление… {mb} МБ").format(mb=got // (1024 * 1024)))

        def _on_dl_done(self, ok: bool, msg: str, dest: str):
            self.update_bar.setEnabled(True)
            tag = getattr(self, "_update_tag", "")
            self.update_bar.setText(
                _("Доступна новая версия {ver} — скачать и установить").format(ver=tag))
            if not ok:
                QMessageBox.warning(self, _("Обновление"), msg)
                return
            try:
                old_exe = sys.executable
                image = Path(old_exe).name
                bat = build_update_swap_bat(old_exe, dest, image)
                bat_path = Path(dest).with_name(Path(dest).stem + ".swap.bat")
                bat_path.write_text(bat, encoding="utf-8")
            except Exception as e:
                QMessageBox.warning(self, _("Обновление"),
                                    _("Не удалось подготовить обновление: {e}").format(e=e))
                return
            if QMessageBox.question(
                    self, _("Готово"),
                    msg + "\n\n" + _("Перезапустить сейчас, чтобы применить обновление?"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes) != QMessageBox.StandardButton.Yes:
                return
            DETACHED = 0x00000008 | 0x00000200
            try:
                subprocess.Popen([os.environ.get("COMSPEC", "cmd.exe"), "/c",
                                  str(bat_path)], creationflags=DETACHED, close_fds=True)
            except Exception as e:
                QMessageBox.critical(self, _("Обновление"), str(e))
                return
            QApplication.quit()

        # --- автоопределение стеков по папке (#1) -------------------------
        def _suggest_for_folder(self, folder: str):
            """Определить тип проекта и, если есть что предложить, показать
            строку-подсказку. Предлагаем только стеки с установленными
            расширениями, которые ещё не отмечены."""
            self._suggested_keys = set()
            self.suggest_bar.setVisible(False)
            self._suggest_toolchains(folder)
            if not folder:
                return
            available = set(cats.get("categories", {}))
            detected = detect_stacks(folder, available=available)
            # #3: рекомендации воркспейса (.vscode/extensions.json) точно называют
            # нужные инструменты — добавляем стеки, на которые они указывают.
            detected |= detect_recommended_stacks(folder, ext_index) & available
            # #1: если для этой папки уже выбирали набор — предложим его снова.
            remembered = recall_folder_stacks(cfg, folder)
            if remembered is not None:
                detected |= set(remembered) & available
            inst_set = set(self.installed)
            selected = self._selected()
            useful = set()
            for key in detected:
                if key in selected:
                    continue
                exts = cats["categories"].get(key, {}).get("extensions", [])
                if any(e.lower() in inst_set for e in exts):
                    useful.add(key)
            if not useful:
                return
            self._suggested_keys = useful
            titles = ", ".join(sorted(
                cats["categories"][k].get("title", k) for k in useful))
            self.suggest_lbl.setText(
                _("Похоже на проект: {stacks}. Включить эти стеки?").format(stacks=titles))
            self.suggest_bar.setVisible(True)

        def _suggest_toolchains(self, folder):
            """Показать подсказку, если у проекта есть язык, но его тулчейн
            (компилятор/SDK) не установлен. Тихо гасим при любой ошибке —
            подсказка вспомогательна и не должна ронять окно."""
            if not hasattr(self, "tool_bar"):
                return
            self._tool_target = None
            self.tool_bar.setVisible(False)
            if not folder:
                return
            try:
                missing = _tc.missing_toolchains_for(folder)
            except Exception:
                return
            if not missing:
                return
            self._tool_target = missing[0]
            titles = ", ".join(_tc.get_toolchain(k).title for k in missing
                               if _tc.get_toolchain(k))
            self.tool_lbl.setText(_(
                "Для этого проекта не хватает инструментов: {tools}. "
                "Установить компилятор/SDK?").format(tools=titles))
            self.tool_bar.setVisible(True)

        def _maybe_auto_suggest(self):
            """#1: один раз при старте показать подсказку для уже подставленной
            папки (из «недавних»). Ждём список расширений — без него detect
            отфильтрует всё в ноль; поэтому вызываем и из __init__ (если список
            уже в кэше), и после фоновой загрузки."""
            if self._auto_suggested or not self.installed:
                return
            folder = self.folder_edit.text().strip()
            if folder:
                self._auto_suggested = True
                self._suggest_for_folder(folder)

        def _apply_suggestion(self):
            for k in self._suggested_keys:
                card = self.cat_checks.get(k)
                if card is not None:
                    card.setChecked(True)
            titles = ", ".join(sorted(
                cats["categories"][k].get("title", k) for k in self._suggested_keys))
            self.log.appendPlainText(
                _("Включены стеки по типу проекта: {stacks}").format(stacks=titles))
            self.suggest_bar.setVisible(False)
            self._suggested_keys = set()

        def _dismiss_suggestion(self):
            self.suggest_bar.setVisible(False)
            self._suggested_keys = set()

        # --- оверрайды по одному расширению (#9) --------------------------
        def override_mode(self, ext_id: str) -> str:
            eid = ext_id.lower()
            if eid in self._force_enable:
                return "enable"
            if eid in self._force_disable:
                return "disable"
            return "default"

        def set_override(self, ext_id: str, mode: str):
            """mode: 'default' | 'enable' | 'disable'. Сохраняет в конфиг и
            пересчитывает сводку."""
            eid = ext_id.lower()
            self._force_enable.discard(eid)
            self._force_disable.discard(eid)
            if mode == "enable":
                self._force_enable.add(eid)
            elif mode == "disable":
                self._force_disable.add(eid)
            cfg["overrides"] = {"disable": sorted(self._force_disable),
                                "enable": sorted(self._force_enable)}
            save_config(cfg)
            self._update_summary()

        # --- переключение языка (#7) --------------------------------------
        def _switch_language(self):
            self._persist()   # сохранить выбор/опции/папку перед пересборкой окна
            new = "ru" if get_language() == "en" else "en"
            set_language(new)
            cfg["lang"] = new
            save_config(cfg)
            _lang_switch["fn"]()   # пересобрать окно (замыкание из run_gui)

        def _start_ext_load(self):
            if getattr(self, "_loader", None) is not None and self._loader.isRunning():
                return
            if not self._loaded:
                self._set_hero("…", "", _("считаю расширения…"), "")
            self.b_run.setEnabled(False)
            self._loader = ExtLoader(code_cli)
            self._loader.loaded.connect(self._on_installed)
            self._loader.start()

        def _apply_installed(self, ids: list):
            self.installed = ids
            self._dep_map = None   # #1: набор расширений сменился — перечитать граф
            for key, card in self.cat_checks.items():
                # Считаем через ext_index — так в счётчик карточки попадают и
                # расширения, разложенные мастером (#6, оверлей), а не только
                # перечисленные в categories.json напрямую.
                card.set_installed(sum(1 for e in ids
                                       if ext_index.get(e.lower()) == key))
            self._refresh_unknown()
            # Список установленных мог измениться — обновим счётчики сегментов и
            # перечитаем фильтр (карточка могла перейти в другую группу).
            self._update_seg_counts()
            if hasattr(self, "seg_btns"):
                self._filter_cards(self.search_edit.text())

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
            self._maybe_auto_suggest()   # #1: кэш был пуст — подсказка после загрузки

        def refresh_installed(self):
            ids = read_installed_from_disk(code_cli)
            if not ids:
                ids, _src = load_installed(code_cli)
            if ids and ids != self.installed:
                self._apply_installed(ids)
                cfg["installed_cache"] = {"ids": ids, "source": "extensions.json"}
                save_config(cfg)
                self._update_summary()

        def _build_ui(self):
            root = QVBoxLayout(self)
            root.setContentsMargins(18, 18, 18, 14)
            root.setSpacing(14)

            header = QFrame(); header.setObjectName("Header")
            hl = QHBoxLayout(header); hl.setContentsMargins(22, 18, 22, 18); hl.setSpacing(16)
            if LOGO_FILE.exists():
                logo = QLabel()
                logo.setPixmap(QPixmap(str(LOGO_FILE)).scaled(
                    54, 54, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
                hl.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)
            htext = QVBoxLayout(); htext.setSpacing(4)
            title = QLabel("VS Code Launcher"); title.setObjectName("Title")
            sub = _wrap(QLabel(_("Открой редактор только с нужными стеками — остальные "
                                 "тяжёлые серверы не грузятся, память свободна.")))
            sub.setObjectName("Subtitle")
            htext.addWidget(title); htext.addWidget(sub)
            hl.addLayout(htext, 1)
            root.addWidget(header)

            # #8: баннер новой версии (скрыт, пока фоновая проверка не найдёт обновление).
            self.update_bar = QPushButton()
            self.update_bar.setObjectName("Accent")
            self.update_bar.setCursor(Qt.CursorShape.PointingHandCursor)
            self.update_bar.setVisible(False)
            self.update_bar.clicked.connect(self._on_update_clicked)
            root.addWidget(self.update_bar)

            if not code_cli:
                warn = _wrap(QLabel(_("Не найден CLI VS Code (code.cmd). Добавь его в PATH.")))
                warn.setObjectName("Warn")
                root.addWidget(warn)

            if cats_err:
                cwarn = _wrap(QLabel(cats_err)); cwarn.setObjectName("Warn")
                root.addWidget(cwarn)

            if duplicates:
                dup_row = QHBoxLayout(); dup_row.setSpacing(8)
                dup_lbl = _wrap(QLabel(
                    f"В categories.json дубли расширений: {len(duplicates)}. "
                    "Расширение попадёт только в один стек — последний по порядку."))
                dup_lbl.setObjectName("Warn")
                dup_row.addWidget(dup_lbl, 1)
                dup_btn = QPushButton("Показать"); dup_btn.setObjectName("Ghost")
                dup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                dup_btn.clicked.connect(self._show_duplicates)
                dup_row.addWidget(dup_btn, 0, Qt.AlignmentFlag.AlignVCenter)
                root.addLayout(dup_row)

            mem_row = QHBoxLayout(); mem_row.setSpacing(8)
            self.mem_lbl = QLabel(_("VS Code сейчас: замеряю…")); self.mem_lbl.setObjectName("Section")
            self.lang_btn = QPushButton("EN" if get_language() == "ru" else "RU")
            self.lang_btn.setObjectName("Ghost")
            self.lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.lang_btn.setFixedWidth(52)
            self.lang_btn.setToolTip(_("Переключить язык интерфейса (RU/EN)"))
            self.lang_btn.clicked.connect(self._switch_language)
            self.theme_btn = QPushButton(); self.theme_btn.setObjectName("Ghost")
            self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.theme_btn.setFixedWidth(104)
            self.theme_btn.setToolTip(_("Переключить светлую/тёмную тему"))
            self.theme_btn.clicked.connect(self._toggle_theme)
            self._update_theme_btn()
            mem_ref = QPushButton(_("Обновить")); mem_ref.setObjectName("Ghost")
            mem_ref.setToolTip(_("Обновить замер памяти запущенного VS Code"))
            mem_ref.clicked.connect(self._probe_memory)
            code_btn = QPushButton(_("VS Code…")); code_btn.setObjectName("Ghost")
            code_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            code_btn.setToolTip(_("Выбрать установку VS Code (стабильная/Insiders/"
                                  "портативная) — если автопоиск нашёл не ту или "
                                  "не нашёл вовсе."))
            code_btn.clicked.connect(self._choose_code_cli)
            mem_row.addWidget(self.mem_lbl); mem_row.addStretch()
            mem_row.addWidget(code_btn)
            mem_row.addWidget(self.lang_btn)
            mem_row.addWidget(self.theme_btn); mem_row.addWidget(mem_ref)
            root.addLayout(mem_row)

            # Середина (пресеты → параметры) — в одном скролле, чтобы шапка и
            # нижняя панель «Запустить» всегда были видны, а окно оставалось
            # адаптивным при любой высоте.
            scroll = QScrollArea(); scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            self._scroll = scroll
            content = QWidget(); cv = QVBoxLayout(content)
            cv.setContentsMargins(0, 0, 6, 0); cv.setSpacing(12)

            pre_card = _card()
            pre = QHBoxLayout(pre_card); pre.setContentsMargins(14, 10, 14, 10); pre.setSpacing(8)
            plbl = QLabel(_("Пресет")); plbl.setObjectName("Section")
            pre.addWidget(plbl)
            self.preset_box = QComboBox(); self.preset_box.setMinimumWidth(180)
            self._reload_presets()
            self.preset_box.activated.connect(self._apply_preset)
            pre.addWidget(self.preset_box, 1)
            b_save = QPushButton(_("Сохранить…")); b_save.clicked.connect(self._save_preset)
            b_del = QPushButton(_("Удалить")); b_del.setObjectName("Ghost"); b_del.clicked.connect(self._delete_preset)
            b_exp = QPushButton(_("Экспорт")); b_exp.setObjectName("Ghost")
            b_exp.setToolTip(_("Экспортировать все пресеты в файл"))
            b_exp.clicked.connect(self._export_presets)
            b_imp = QPushButton(_("Импорт")); b_imp.setObjectName("Ghost")
            b_imp.setToolTip(_("Импортировать пресеты из файла (объединяются с текущими)"))
            b_imp.clicked.connect(self._import_presets)
            b_short = QPushButton(_("Ярлык")); b_short.setObjectName("Ghost")
            b_short.setToolTip(_("Создать .cmd-файл, открывающий VS Code с выбранным "
                                 "пресетом одним двойным кликом (без окна лаунчера)"))
            b_short.clicked.connect(self._make_shortcut)
            b_prof = QPushButton(_("Профиль…")); b_prof.setObjectName("Ghost")
            b_prof.setToolTip(_("Экспортировать текущий выбор стеков как нативный "
                                "профиль VS Code (.code-profile). Импортируется через "
                                "«Profiles: Import Profile…» — постоянный профиль "
                                "ровно с включёнными расширениями."))
            b_prof.clicked.connect(self._export_profile)
            pre.addWidget(b_save); pre.addWidget(b_del)
            pre.addWidget(b_exp); pre.addWidget(b_imp); pre.addWidget(b_short)
            pre.addWidget(b_prof)
            cv.addWidget(pre_card)

            sec_row = QHBoxLayout(); sec_row.setSpacing(8)
            sec = QLabel(_("СТЕКИ РАСШИРЕНИЙ"))
            sec.setObjectName("Section")
            sec_row.addWidget(sec)
            self.sel_count = QLabel(); self.sel_count.setObjectName("SelCount")
            self.sel_count.setToolTip(_("Сколько стеков сейчас отмечено из всех."))
            sec_row.addWidget(self.sel_count)
            sec_row.addStretch()
            b_tools = QPushButton(_("Языки и инструменты…")); b_tools.setObjectName("Ghost")
            b_tools.setCursor(Qt.CursorShape.PointingHandCursor)
            b_tools.setToolTip(_("Установить компиляторы и SDK (C/C++, Java, Go, Rust…) "
                                 "через winget и прописать их в PATH."))
            b_tools.clicked.connect(lambda: self._show_toolchains())
            sec_row.addWidget(b_tools)
            b_all = QPushButton(_("Всё вкл")); b_all.setObjectName("Ghost")
            b_all.clicked.connect(lambda: self._set_all(True))
            b_none = QPushButton(_("Минимум")); b_none.setObjectName("Ghost")
            b_none.clicked.connect(lambda: self._set_all(False))
            b_all.setToolTip(_("Отметить все стеки (с учётом фильтра поиска)"))
            b_none.setToolTip(_("Снять все галочки — останется только ядро "
                                "(always_on) и незамапленные расширения"))
            sec_row.addWidget(b_all); sec_row.addWidget(b_none)
            cv.addLayout(sec_row)

            # Легенда-подсказка: как читать карточки — снимает вопрос «а что тут
            # вообще делать» у нового пользователя.
            legend = _wrap(QLabel(_(
                "Отметь стеки, нужные сегодня. Полоска слева — нагрузка на память: "
                "красная тяжёлый, жёлтая средний, зелёная лёгкий; чем тяжелее "
                "выключенный стек, тем больше экономия. Снятые галочки не удаляют "
                "расширения — они просто не грузятся в этот запуск. «Подробнее» — "
                "что внутри стека и установка/удаление.")))
            legend.setObjectName("CatNote")
            cv.addWidget(legend)

            self.search_edit = QLineEdit()
            self.search_edit.setPlaceholderText(_("Поиск стека или расширения…"))
            self.search_edit.setClearButtonEnabled(True)
            self.search_edit.setToolTip(_("Фильтрует карточки по названию, заметке "
                                          "и id расширений. На выбор не влияет."))
            self.search_edit.textChanged.connect(self._filter_cards)
            cv.addWidget(self.search_edit)

            # Сегментированный фильтр: разделяем установленные и неустановленные
            # стеки. Установленные — то, чем реально управляешь память в этой
            # сессии; неустановленные — что можно доставить. Работает вместе с
            # поиском (пересечение условий).
            filt_row = QHBoxLayout(); filt_row.setSpacing(8)
            seg = QFrame(); seg.setObjectName("Segmented")
            sl = QHBoxLayout(seg); sl.setContentsMargins(3, 3, 3, 3); sl.setSpacing(3)
            self._inst_filter = "all"
            self.seg_btns = {}
            for fkey, flabel in (("all", _("Все")),
                                 ("installed", _("Установленные")),
                                 ("missing", _("Не установленные"))):
                sb = QPushButton(flabel); sb.setObjectName("SegBtn")
                sb.setCheckable(True); sb.setCursor(Qt.CursorShape.PointingHandCursor)
                sb.clicked.connect(lambda _=False, k=fkey: self._set_inst_filter(k))
                sl.addWidget(sb)
                self.seg_btns[fkey] = sb
            self.seg_btns["all"].setChecked(True)
            filt_row.addWidget(seg)
            filt_row.addStretch()
            self.search_status = QLabel(); self.search_status.setObjectName("CatNote")
            filt_row.addWidget(self.search_status)
            cv.addLayout(filt_row)

            installed_set = set(self.installed)
            # Сначала установленные стеки (по ним и есть что выключать), внутри —
            # тяжёлые вверх (максимум экономии). Неустановленные сборки — ниже.
            weight_rank = {"heavy": 0, "medium": 1, "light": 2}
            ordered = sorted(
                cats.get("categories", {}).items(),
                key=lambda kv: (
                    0 if any(e.lower() in installed_set for e in kv[1]["extensions"]) else 1,
                    weight_rank.get(WEIGHT.get(kv[0], "light"), 2),
                    kv[1].get("title", kv[0]).lower()))
            # Карточки — в отзывчивую сетку-флоу: на широком окне 2–3 колонки,
            # на узком — одна. Меньше скролла, горизонталь не пустует.
            self.cards_host = QWidget()
            self._cards_flow = FlowLayout(self.cards_host, margin=0, spacing=10)
            for key, cat in ordered:
                exts = cat["extensions"]
                inst = sum(1 for e in exts if e.lower() in installed_set)
                card = CategoryCard(
                    key, cat, inst, len(exts), self._update_summary,
                    lambda _=False, k=key, c=cat: show_details(self, k, c, set(self.installed)))
                self.cat_checks[key] = card
                self._cards_flow.addWidget(card)
            cv.addWidget(self.cards_host)
            self._update_seg_counts()

            self.unknown_btn = QPushButton(); self.unknown_btn.setObjectName("Ghost")
            self.unknown_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.unknown_btn.setToolTip("Установленные расширения, которых нет в "
                                        "data/categories.json — лаунчер всегда оставляет "
                                        "их включёнными")
            self.unknown_btn.clicked.connect(self._show_unknown)
            # #6: мастер авто-раскладки незнакомых расширений по стекам.
            self.classify_btn = QPushButton(); self.classify_btn.setObjectName("Ghost")
            self.classify_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.classify_btn.setToolTip(_("Автоматически разложить незнакомые "
                                           "расширения по стекам (по их манифесту). "
                                           "Ничего не навязывается — ты подтверждаешь "
                                           "раскладку; categories.json не меняется."))
            self.classify_btn.clicked.connect(self._classify_wizard)
            self.classify_btn.setVisible(False)
            urow = QHBoxLayout(); urow.addWidget(self.unknown_btn)
            urow.addWidget(self.classify_btn); urow.addStretch()
            cv.addLayout(urow)
            self._refresh_unknown()

            fold_card = _card()
            fv = QVBoxLayout(fold_card); fv.setContentsMargins(14, 12, 14, 12); fv.setSpacing(8)
            flbl = QLabel(_("ПАПКА ПРОЕКТА (НЕОБЯЗАТЕЛЬНО)")); flbl.setObjectName("Section")
            fv.addWidget(flbl)
            fbox = QHBoxLayout(); fbox.setSpacing(8)
            self.folder_edit = QLineEdit()
            self.folder_edit.setPlaceholderText(_("путь к проекту, который открыть"))
            self.folder_edit.editingFinished.connect(
                lambda: self._suggest_for_folder(self.folder_edit.text().strip()))
            fbox.addWidget(self.folder_edit)
            b_browse = QPushButton(_("Обзор…")); b_browse.clicked.connect(self._browse)
            fbox.addWidget(b_browse)
            fv.addLayout(fbox)
            self.recent_box = QComboBox()
            self.recent_box.addItem(_("— недавние папки —"), "")
            for p in cfg.get("recent_folders", []):
                self.recent_box.addItem(p, p)
            self.recent_box.activated.connect(self._pick_recent)
            fv.addWidget(self.recent_box)

            # #1: строка-подсказка автодетекта стеков (скрыта, пока нет папки).
            self.suggest_bar = QFrame(); self.suggest_bar.setObjectName("CatCard")
            sbl = QHBoxLayout(self.suggest_bar)
            sbl.setContentsMargins(12, 8, 12, 8); sbl.setSpacing(8)
            self.suggest_lbl = _wrap(QLabel()); self.suggest_lbl.setObjectName("CatNote")
            sbl.addWidget(self.suggest_lbl, 1)
            sug_apply = QPushButton(_("Включить")); sug_apply.setObjectName("Accent")
            sug_apply.setCursor(Qt.CursorShape.PointingHandCursor)
            sug_apply.clicked.connect(self._apply_suggestion)
            sug_hide = QPushButton(_("Скрыть")); sug_hide.setObjectName("Ghost")
            sug_hide.clicked.connect(self._dismiss_suggestion)
            sbl.addWidget(sug_apply); sbl.addWidget(sug_hide)
            self.suggest_bar.setVisible(False)
            fv.addWidget(self.suggest_bar)

            # Подсказка: у проекта есть язык, но его тулчейн (компилятор/SDK) не
            # установлен — предложить поставить прямо из окна «Языки и инструменты».
            self.tool_bar = QFrame(); self.tool_bar.setObjectName("CatCard")
            tbl = QHBoxLayout(self.tool_bar)
            tbl.setContentsMargins(12, 8, 12, 8); tbl.setSpacing(8)
            self.tool_lbl = _wrap(QLabel()); self.tool_lbl.setObjectName("CatNote")
            tbl.addWidget(self.tool_lbl, 1)
            self._tool_target = None
            tool_open = QPushButton(_("Поставить")); tool_open.setObjectName("Accent")
            tool_open.setCursor(Qt.CursorShape.PointingHandCursor)
            tool_open.clicked.connect(
                lambda: self._show_toolchains(target=self._tool_target))
            tool_hide = QPushButton(_("Скрыть")); tool_hide.setObjectName("Ghost")
            tool_hide.clicked.connect(lambda: self.tool_bar.setVisible(False))
            tbl.addWidget(tool_open); tbl.addWidget(tool_hide)
            self.tool_bar.setVisible(False)
            fv.addWidget(self.tool_bar)
            cv.addWidget(fold_card)

            opt_card = _card()
            ov = QVBoxLayout(opt_card); ov.setContentsMargins(14, 12, 14, 12); ov.setSpacing(8)
            olbl = QLabel(_("ПАРАМЕТРЫ ЗАПУСКА")); olbl.setObjectName("Section")
            ov.addWidget(olbl)
            self.kill_cb = QCheckBox(_("Закрыть VS Code перед стартом (чтобы память освободилась)"))
            self.kill_cb.setChecked(cfg.get("kill_first", True))
            self.kill_cb.setToolTip(
                f"Закроет все окна VS Code ({code_image_name(code_cli)}) перед стартом. "
                "Запускай этот тул НЕ из терминала VS Code.")
            ov.addWidget(self.kill_cb)
            self.soft_cb = QCheckBox(_("   Мягко: дать VS Code сохранить (иначе принудительно)"))
            self.soft_cb.setChecked(cfg.get("soft_close", False))
            self.soft_cb.setToolTip(
                "Пошлёт окну обычный запрос на закрытие — VS Code сам спросит про "
                "несохранённые файлы. Лаунчер подождёт, пока редактор закроется, и "
                "только потом стартует новый. Если оставить открытым диалог сохранения, "
                "запуск отменится (ничего не потеряется). Выкл — жёсткое закрытие (/F): "
                "быстро и надёжно освобождает память, но несохранённое теряется.")
            self.kill_cb.stateChanged.connect(
                lambda: self.soft_cb.setEnabled(self.kill_cb.isChecked()))
            self.soft_cb.setEnabled(self.kill_cb.isChecked())
            ov.addWidget(self.soft_cb)
            self.newwin_cb = QCheckBox(_("Открыть в новом окне (--new-window)"))
            self.newwin_cb.setChecked(cfg.get("new_window", True))
            ov.addWidget(self.newwin_cb)
            self.gpu_cb = QCheckBox(_("Без GPU-ускорения (--disable-gpu) — для слабых видеокарт"))
            self.gpu_cb.setChecked(cfg.get("disable_gpu", False))
            self.gpu_cb.setToolTip("Отключает аппаратное ускорение отрисовки. "
                                   "Иногда лечит артефакты/лаги на старых GPU и экономит немного памяти.")
            ov.addWidget(self.gpu_cb)
            self.bare_cb = QCheckBox(_("Голый режим: полностью без расширений (--disable-extensions)"))
            self.bare_cb.setToolTip("Отключит ВСЕ расширения, включая ядро — максимальная скорость. "
                                    "Галочки стеков при этом игнорируются.")
            self.bare_cb.stateChanged.connect(self._update_summary)
            ov.addWidget(self.bare_cb)

            prof_row = QHBoxLayout(); prof_row.setSpacing(8)
            prof_lbl = QLabel(_("Профиль")); prof_lbl.setObjectName("Section")
            self.profile_edit = QLineEdit(); self.profile_edit.setText(cfg.get("profile", ""))
            self.profile_edit.setPlaceholderText(_("имя существующего профиля VS Code (необязательно)"))
            self.profile_edit.setToolTip(
                "Откроет окно с этим профилем (--profile). Профиль нужно заранее создать "
                "в VS Code (шестерёнка → Profiles). Пусто — профиль по умолчанию.")
            prof_row.addWidget(prof_lbl); prof_row.addWidget(self.profile_edit, 1)
            ov.addLayout(prof_row)
            cv.addWidget(opt_card)

            cfg_card = _card()
            cvv = QVBoxLayout(cfg_card); cvv.setContentsMargins(14, 12, 14, 12); cvv.setSpacing(8)
            aclbl = QLabel(_("НАСТРОЙКА VS CODE")); aclbl.setObjectName("Section")
            cvv.addWidget(aclbl)
            ac_row = QHBoxLayout()
            self.autoconf_btn = QPushButton(_("Автонастройка settings.json"))
            self.autoconf_btn.setObjectName("Ghost")
            self.autoconf_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.autoconf_btn.setToolTip(_("Добавить рекомендованные настройки для "
                                           "установленных стеков"))
            self.autoconf_btn.clicked.connect(self._show_autoconfig)
            ac_row.addWidget(self.autoconf_btn); ac_row.addStretch()
            cvv.addLayout(ac_row)
            ac_hint = _wrap(QLabel(
                "Пропишет базовые настройки для установленных стеков (формат при "
                "сохранении и т.п.). Существующие настройки не трогаются, перед "
                "записью делается бэкап settings.json."))
            ac_hint.setObjectName("CatNote"); cvv.addWidget(ac_hint)
            cv.addWidget(cfg_card)

            cv.addStretch()
            scroll.setWidget(content)
            root.addWidget(scroll, 1)

            # Hero-панель экономии: слева крупное число сэкономленных МБ, справа
            # чипы (включено/выключено/замер) и действия. Ключевая ценность —
            # экономия памяти — теперь читается с одного взгляда.
            action_card = QFrame(); action_card.setObjectName("SavingsCard")
            acv = QVBoxLayout(action_card)
            acv.setContentsMargins(18, 12, 16, 12); acv.setSpacing(10)

            # Ряд 1: крупное число экономии + подпись + чипы статистики.
            row1 = QHBoxLayout(); row1.setSpacing(14)
            hero = QHBoxLayout(); hero.setSpacing(4)
            self.savings_num = QLabel("—"); self.savings_num.setObjectName("SavingsNumber")
            self.savings_unit = QLabel(_("МБ")); self.savings_unit.setObjectName("SavingsUnit")
            self.savings_unit.setAlignment(Qt.AlignmentFlag.AlignBottom)
            hero.addWidget(self.savings_num)
            hero.addWidget(self.savings_unit, 0, Qt.AlignmentFlag.AlignBottom)
            hero_box = QVBoxLayout(); hero_box.setSpacing(0)
            cap = QLabel(_("ЭКОНОМИЯ ПАМЯТИ")); cap.setObjectName("SavingsCaption")
            hero_box.addLayout(hero); hero_box.addWidget(cap)
            row1.addLayout(hero_box)
            vsep = QFrame(); vsep.setObjectName("HLine"); vsep.setFixedWidth(1)
            vsep.setFixedHeight(44)
            row1.addWidget(vsep)
            self.stat_en = QLabel(); self.stat_en.setObjectName("Stat")
            self.stat_dis = QLabel(); self.stat_dis.setObjectName("StatAccent")
            self.stat_extra = QLabel(); self.stat_extra.setObjectName("Stat")
            self.stat_extra.setVisible(False)
            row1.addWidget(self.stat_en); row1.addWidget(self.stat_dis)
            row1.addWidget(self.stat_extra)
            row1.addStretch()
            acv.addLayout(row1)

            # Ряд 2: действия справа — вторичные «призрачные», основная акцентная.
            row2 = QHBoxLayout(); row2.setSpacing(10)
            row2.addStretch()
            b_diff = QPushButton(_("Что выключится")); b_diff.setObjectName("Ghost")
            b_diff.setToolTip(_("Показать список расширений, которые будут выключены"))
            b_diff.clicked.connect(self._show_diff)
            b_cmd = QPushButton(_("Показать команду")); b_cmd.setObjectName("Ghost")
            b_cmd.clicked.connect(self._show_cmd)
            self.b_run = QPushButton(_("Запустить VS Code")); self.b_run.setObjectName("Accent")
            self.b_run.clicked.connect(self._run)
            row2.addWidget(b_diff); row2.addWidget(b_cmd); row2.addWidget(self.b_run)
            acv.addLayout(row2)
            root.addWidget(action_card)
            # Держим скрытый self.summary для обратной совместимости (код, что
            # писал в него текст статуса, продолжает работать без падений).
            self.summary = QLabel(); self.summary.setVisible(False)

            self.log = QPlainTextEdit(); self.log.setObjectName("Log")
            self.log.setReadOnly(True); self.log.setMaximumHeight(90)
            self.log.setPlaceholderText(_("Здесь появится итоговая команда и статус запуска."))
            root.addWidget(self.log)

        def _selected(self) -> set[str]:
            return {k for k, cb in self.cat_checks.items() if cb.isChecked()}

        def _set_all(self, state: bool):
            # Применяем только к видимым (после фильтра) карточкам — чтобы «Всё вкл»
            # при активном поиске не трогал скрытые стеки неожиданно.
            for cb in self.cat_checks.values():
                if cb.isVisible():
                    cb.setChecked(state)

        def _set_inst_filter(self, key: str):
            """Переключить сегмент Все/Установленные/Не установленные."""
            self._inst_filter = key
            for k, b in self.seg_btns.items():
                b.setChecked(k == key)
            self._filter_cards(self.search_edit.text())

        def _update_seg_counts(self):
            """Показать в подписях сегментов, сколько стеков установлено/нет."""
            if not hasattr(self, "seg_btns"):
                return
            total = len(self.cat_checks)
            inst = sum(1 for c in self.cat_checks.values() if c.is_installed())
            self.seg_btns["all"].setText(_("Все ({n})").format(n=total))
            self.seg_btns["installed"].setText(_("Установленные ({n})").format(n=inst))
            self.seg_btns["missing"].setText(
                _("Не установленные ({n})").format(n=total - inst))

        def _card_passes_filter(self, card) -> bool:
            f = getattr(self, "_inst_filter", "all")
            if f == "installed":
                return card.is_installed()
            if f == "missing":
                return not card.is_installed()
            return True

        def _filter_cards(self, text: str = ""):
            q = (text or "").strip().lower()
            shown = 0
            for card in self.cat_checks.values():
                vis = (q in card.search_text) and self._card_passes_filter(card)
                card.setVisible(vis)
                shown += 1 if vis else 0
            # Пересобрать сетку без «дыр» от скрытых карточек.
            if hasattr(self, "_cards_flow"):
                self._cards_flow.invalidate()
                self.cards_host.updateGeometry()
            # Счётчик результатов: видно, что фильтр/поиск реально сработали.
            if hasattr(self, "search_status"):
                total = len(self.cat_checks)
                filtered = q or getattr(self, "_inst_filter", "all") != "all"
                if not filtered:
                    self.search_status.setText("")
                elif shown:
                    self.search_status.setText(
                        _("показано {n} из {total}").format(n=shown, total=total))
                else:
                    self.search_status.setText(_("ничего не найдено"))

        def _relayout_cards(self):
            """Подобрать ширину карточек под окно: 1–3 колонки по порогам ширины,
            карточки в строке равной ширины и заполняют её без рваного края."""
            if not hasattr(self, "cards_host"):
                return
            avail = self.cards_host.width()
            if avail <= 0:
                return
            spacing = 10
            cols = 3 if avail >= 1080 else 2 if avail >= 720 else 1
            # −2 на колонку: гарантия, что ряд действительно вмещает cols карточек
            # (иначе округление/скроллбар роняют последнюю на новую строку, и
            # половина ширины пустует). Ширину не опускаем ниже разумного минимума.
            w = max(280, (avail - spacing * (cols - 1)) // cols - 2)
            for card in self.cat_checks.values():
                card.setFixedWidth(w)
            self._cards_flow.invalidate()
            self.cards_host.updateGeometry()

        def resizeEvent(self, e):
            super().resizeEvent(e)
            self._relayout_cards()

        def _get_dep_map(self) -> dict:
            """Карта зависимостей расширений для #1. Строится один раз (читает
            ~100 небольших package.json, десятки мс) и кэшируется до смены
            набора установленных расширений. Ошибку чтения глушим в пустую
            карту — защита по зависимостям тогда просто выключена, поведение
            откатывается к прежнему."""
            if self._dep_map is None:
                try:
                    self._dep_map = build_dependency_map(
                        read_extension_manifests(code_cli))
                except Exception:
                    self._dep_map = {}
            return self._dep_map

        def _disabled_list(self) -> list[str]:
            return compute_disabled(self.installed, ext_index, self._selected(),
                                    self._force_disable, self._force_enable,
                                    dep_map=self._get_dep_map())

        def _bare(self) -> bool:
            return getattr(self, "bare_cb", None) is not None and self.bare_cb.isChecked()

        def _unknown(self) -> list[str]:
            """Установленные расширения, которых нет в карте категорий."""
            return sorted(e for e in self.installed if e not in ext_index)

        def _refresh_unknown(self):
            unk = self._unknown()
            self.unknown_btn.setText(f"Не в карте: {len(unk)} — показать")
            self.unknown_btn.setVisible(bool(unk))
            # #6: кнопку мастера показываем, когда есть что раскладывать; сами
            # предложения считаем лениво (при клике), чтобы не читать манифесты
            # на каждый refresh.
            if getattr(self, "classify_btn", None) is not None:
                self.classify_btn.setText(_("Разложить по стекам (авто)"))
                self.classify_btn.setVisible(bool(unk))

        def _classify_wizard(self):
            """#6: мастер авто-раскладки незнакомых расширений по стекам.

            Угадывает стек по манифесту (classify), показывает диалог с
            чекбоксами и выбором стека. Принятое пишется в оверлей
            cfg['extra_categories'] и сливается в ext_index — categories.json
            не трогается, всё обратимо. Ничего не навязывается: по умолчанию
            галочки стоят, но пользователь решает."""
            nonlocal ext_index
            if not self._unknown():
                QMessageBox.information(self, _("Раскладка"),
                                        _("Незнакомых расширений нет."))
                return
            valid_keys = set(cats.get("categories", {}))
            try:
                manifests = read_extension_manifests(code_cli)
            except Exception:
                manifests = {}
            suggestions = suggest_categories(self.installed, ext_index, manifests,
                                             available=valid_keys)
            if not suggestions:
                QMessageBox.information(
                    self, _("Раскладка"),
                    _("Не удалось уверенно определить стек ни для одного "
                      "незнакомого расширения. Разложи вручную в "
                      "data/categories.json."))
                return

            dlg = QDialog(self); dlg.setWindowTitle(_("Разложить по стекам"))
            dlg.resize(580, 540)
            lay = QVBoxLayout(dlg)
            lay.addWidget(_wrap(QLabel(_(
                "Предлагаю раскладку {n} расширений. Сними галочку, чтобы "
                "пропустить; стек можно поменять. Твоя categories.json не "
                "меняется — раскладка хранится отдельно и обратима.").format(
                    n=len(suggestions)))))
            key_titles = [(k, cats["categories"][k].get("title", k))
                          for k in sorted(valid_keys)]
            keys_order = [k for k, _t in key_titles]
            scroll = QScrollArea(); scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            host = QWidget(); hv = QVBoxLayout(host); hv.setSpacing(6)
            rows = []
            for ext_id, key in sorted(suggestions.items()):
                line = QHBoxLayout()
                cb = QCheckBox(ext_id); cb.setChecked(True)
                combo = QComboBox()
                for k, title in key_titles:
                    combo.addItem(title, k)
                if key in keys_order:
                    combo.setCurrentIndex(keys_order.index(key))
                line.addWidget(cb, 1); line.addWidget(combo, 0)
                holder = QWidget(); holder.setLayout(line); hv.addWidget(holder)
                rows.append((cb, combo))
            hv.addStretch()
            scroll.setWidget(host); lay.addWidget(scroll, 1)
            bar = QHBoxLayout(); bar.addStretch()
            cancel = QPushButton(_("Отмена")); cancel.setObjectName("Ghost")
            cancel.clicked.connect(dlg.reject)
            accept = QPushButton(_("Принять отмеченные")); accept.setObjectName("Accent")
            accept.clicked.connect(dlg.accept)
            bar.addWidget(cancel); bar.addWidget(accept); lay.addLayout(bar)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return

            approved = {cb.text(): combo.currentData() for cb, combo in rows
                        if cb.isChecked() and combo.currentData()}
            if not approved:
                return
            overlay = cfg.setdefault("extra_categories", {})
            overlay.update(approved)
            save_config(cfg)
            ext_index = build_ext_index(cats, overlay)   # переопределяем замыкание
            self._dep_map = None
            self._apply_installed(self.installed)   # пересчитать счётчики/фильтр/unknown
            self._update_summary()
            self.log.appendPlainText(
                _("Разложено расширений: {n}").format(n=len(approved)))

        def _show_toolchains(self, target=None):
            """Диалог языковых тулчейнов: установка, обновление, удаление, проверка.

            По карточке на тулчейн; у каждого пакета — статус и действия (winget).
            Операции идут в фоне (ToolchainInstaller), прогресс/отмена общие внизу.
            `target` — ключ тулчейна, к которому проскроллить (из подсказки в окне).
            Пока идёт winget-операция, кнопки действий заблокированы (одна за раз)."""
            dlg = QDialog(self)
            dlg.setWindowTitle(_("Языки и инструменты"))
            dlg.resize(720, 700)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(18, 18, 18, 16); lay.setSpacing(10)

            title = QLabel(_("Языки и инструменты")); title.setObjectName("Title")
            lay.addWidget(title)
            intro = _wrap(QLabel(_(
                "Расширения VS Code добавляют подсветку и подсказки, но собирать и "
                "запускать код им нечем без самого тулчейна: компилятора C++, JDK, "
                "Go и т.д. Здесь можно поставить недостающее через winget — он сам "
                "скачает пакет и, где нужно, лаунчер пропишет его в PATH. После "
                "установки откройте новый терминал, чтобы PATH подхватился.")))
            intro.setObjectName("CatNote")
            lay.addWidget(intro)

            wg_ok = _tc.winget_available()
            if not wg_ok:
                warn = _wrap(QLabel(_(
                    "winget не найден. Установите «App Installer» из Microsoft Store "
                    "(входит в состав Windows 10/11) — без него автоматическая "
                    "установка недоступна.")))
                warn.setObjectName("Warn")
                lay.addWidget(warn)
            lay.addWidget(_hline())

            state = {"open": True, "busy": False}
            dlg.finished.connect(lambda _=0: state.update(open=False))
            rows: dict[str, dict] = {}          # winget_id -> {widgets...}
            action_btns: list = []              # все кнопки действий (для блокировки)
            card_of: dict[str, QWidget] = {}    # key -> карточка (для скролла к target)
            status_lbl = QLabel(); status_lbl.setObjectName("CatNote"); status_lbl.setVisible(False)
            prog_bar = QProgressBar(); prog_bar.setObjectName("InstallBar")
            prog_bar.setTextVisible(False); prog_bar.setFixedHeight(8); prog_bar.setVisible(False)
            cancel_btn = QPushButton(_("Отмена")); cancel_btn.setObjectName("Ghost")
            cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor); cancel_btn.setVisible(False)

            def lock_actions(busy):
                state["busy"] = busy
                for b in action_btns:
                    b.setEnabled(not busy)

            def refresh_pkg_row(pkg, installed, version, just=False):
                """Обновить строку пакета: тег статуса и видимость кнопок."""
                r = rows.get(pkg.winget_id)
                if not r:
                    return
                tag = r["tag"]
                if installed and just:
                    tag.setText(_("установлено ✓ — перезапустите терминал")); tag.setObjectName("Wlight")
                elif installed:
                    tag.setText(_("установлено{ver}").format(ver=f" · {version}" if version else ""))
                    tag.setObjectName("Wlight")
                else:
                    tag.setText(_("нет в системе")); tag.setObjectName("Woff")
                tag.style().unpolish(tag); tag.style().polish(tag)
                on_disk = (not installed) and bool(_tc.find_tool_on_disk(pkg))
                r["install"].setVisible(not installed and wg_ok)
                r["addpath"].setVisible(not installed and on_disk)
                r["verify"].setVisible(installed)
                r["upgrade"].setVisible(installed and wg_ok)
                r["uninstall"].setVisible(installed and wg_ok)

            def do_add_existing(pkg):
                bindir = _tc.find_tool_on_disk(pkg)
                if not bindir:
                    return
                ok, msg = _tc.env_path.add_to_user_path(bindir)
                status_lbl.setText(msg); status_lbl.setVisible(True)
                if ok:
                    refresh_pkg_row(pkg, True, None, just=True)

            def do_verify(pkg):
                ok, info = _tc.verify_package(pkg)
                QMessageBox.information(
                    dlg, _("Проверка инструмента"),
                    (f"✓ {info}" if ok else f"✗ {info}"))

            def do_configure_vscode(key):
                ok, msg = _tc.configure_vscode_for(key, code_cli)
                (QMessageBox.information if ok else QMessageBox.warning)(
                    dlg, _("Настройка VS Code"), msg)

            def _resolve_version(pkg):
                """#4: подставить выбранную в комбобоксе версию пакета."""
                r = rows.get(pkg.winget_id)
                combo = r.get("ver_combo") if r else None
                if combo is not None and combo.currentData():
                    return pkg.with_version(combo.currentData())
                return pkg

            def _start_elevated(resolved_pkg, orig_pkg):
                """#10: повторить установку с правами администратора (в фоне —
                elevated winget ждёт UAC и может идти минуты)."""
                if state["busy"]:
                    return
                lock_actions(True)
                status_lbl.setText(_("Установка с правами администратора…"))
                status_lbl.setVisible(True)
                prog_bar.setRange(0, 0); prog_bar.setValue(0); prog_bar.setVisible(True)

                def _edone(ok, m):
                    if not state["open"]:
                        return
                    prog_bar.setVisible(False); lock_actions(False)
                    status_lbl.setText((m or "").splitlines()[0] if m
                                       else (_("Готово") if ok else _("Ошибка")))
                    if ok and orig_pkg is not None:
                        refresh_pkg_row(orig_pkg, True, None, just=True)
                    elif not ok:
                        QMessageBox.warning(dlg, _("Не удалось выполнить"),
                                            (m or "")[:600])
                w = ElevatedInstaller(resolved_pkg)
                w.done.connect(_edone)
                w.finished.connect(lambda x=w: self._reap_installer(x))
                self._install_threads.append(w)
                w.start()

            def start_winget(pkgs, action):
                """action: install | upgrade | uninstall. Один воркер за раз."""
                if state["busy"] or not wg_ok:
                    return
                if action == "install":
                    pkgs = [p for p in pkgs if not _tc.package_installed(p)]
                    q_title, q_verb = _("Установить через winget?"), _("Устанавливаю")
                elif action == "uninstall":
                    pkgs = [p for p in pkgs if _tc.package_installed(p)]
                    q_title, q_verb = _("Удалить через winget?"), _("Удаляю")
                else:
                    pkgs = [p for p in pkgs if _tc.package_installed(p)]
                    q_title, q_verb = _("Обновить через winget?"), _("Обновляю")
                if not pkgs:
                    return
                # #4: применяем выбранную версию (только install — upgrade/uninstall
                # работают с уже установленным). orig_by_rid ведёт от id, с которым
                # реально пошли в winget, к исходному пакету (для обновления строки).
                if action == "install":
                    resolved = [_resolve_version(p) for p in pkgs]
                    orig_by_rid = {rp.winget_id: op
                                   for op, rp in zip(pkgs, resolved, strict=True)}
                    pkgs = resolved
                else:
                    orig_by_rid = {p.winget_id: p for p in pkgs}
                names = ", ".join(p.title for p in pkgs)
                # #7: предупреждение, если для языка стоит менеджер версий.
                warn_txt = ""
                if action == "install":
                    orig_ids = {op.winget_id for op in orig_by_rid.values()}
                    keys = {k for k in _tc.toolchain_keys()
                            for pp in _tc.get_toolchain(k).packages
                            if pp.winget_id in orig_ids}
                    warns = [w for w in (_tc.manager_warning_for(k) for k in keys) if w]
                    if warns:
                        warn_txt = "\n\n⚠ " + "\n⚠ ".join(warns)
                if QMessageBox.question(
                        dlg, q_title,
                        _("Пакеты:\n\n{names}\n\nЭто может занять несколько минут. "
                          "Продолжить?").format(names=names) + warn_txt,
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                    return
                lock_actions(True)
                bulk = len(pkgs) > 1
                prog_bar.setRange(0, len(pkgs) if bulk else 0)
                prog_bar.setValue(0); prog_bar.setVisible(True)
                fails: list[tuple[str, str]] = []; done = [0]

                def _one(wid, ok, msg):
                    if not state["open"]:
                        return
                    done[0] += 1
                    resolved_pkg = next((p for p in pkgs if p.winget_id == wid), None)
                    orig_pkg = orig_by_rid.get(wid, resolved_pkg)   # #4: строку по исходному
                    if ok:
                        if orig_pkg is not None:
                            refresh_pkg_row(orig_pkg, action != "uninstall", None, just=True)
                    else:
                        fails.append((wid, msg or ""))
                        if not bulk:
                            # #10: ошибка из-за прав администратора — предложить повтор elevated.
                            need_admin = "администратор" in (msg or "").lower()
                            if (need_admin and action == "install"
                                    and resolved_pkg is not None
                                    and QMessageBox.question(
                                        dlg, _("Нужны права администратора"),
                                        (msg or "")[:400] + "\n\n"
                                        + _("Повторить установку с правами "
                                            "администратора?"),
                                        QMessageBox.StandardButton.Yes
                                        | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.Yes)
                                    == QMessageBox.StandardButton.Yes):
                                QTimer.singleShot(
                                    0, lambda rp=resolved_pkg, op=orig_pkg:
                                    _start_elevated(rp, op))
                                return
                            QMessageBox.warning(dlg, _("Не удалось выполнить"),
                                                f"{wid}\n\n{(msg or '')[:600]}")

                def _progress(i, n):
                    if not state["open"]:
                        return
                    status_lbl.setText(f"{q_verb} {i}/{n}…" if n > 1 else f"{q_verb}…")
                    status_lbl.setVisible(True)
                    if n > 1:
                        prog_bar.setValue(i - 1)

                def _all():
                    if not state["open"]:
                        return
                    prog_bar.setVisible(False); cancel_btn.setVisible(False)
                    lock_actions(False)
                    ok_n = done[0] - len(fails)
                    status_lbl.setText(_("Готово: {ok}, ошибок: {err}").format(
                        ok=ok_n, err=len(fails)))
                    status_lbl.setVisible(True)
                    if fails and bulk:
                        preview = "\n".join(f"• {wid}: {(m or '').splitlines()[0][:120]}"
                                            for wid, m in fails[:8])
                        QMessageBox.warning(dlg, _("Готово с ошибками"),
                                            status_lbl.text() + "\n\n" + preview)

                worker = ToolchainInstaller(pkgs, action=action)
                worker.progress.connect(_progress)
                worker.one_done.connect(_one)
                worker.all_done.connect(_all)
                worker.finished.connect(lambda w=worker: self._reap_installer(w))
                if bulk:
                    cancel_btn.setVisible(True); cancel_btn.setEnabled(True)
                    try:
                        cancel_btn.clicked.disconnect()
                    except TypeError:
                        pass

                    def _do_cancel(_checked=False, w=worker):
                        w.cancel(); cancel_btn.setEnabled(False)
                        status_lbl.setText(_("Отмена…"))
                    cancel_btn.clicked.connect(_do_cancel)
                self._install_threads.append(worker)
                worker.start()

            def mk_btn(text, obj, slot, tip=""):
                b = QPushButton(text); b.setObjectName(obj)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                if tip:
                    b.setToolTip(tip)
                b.clicked.connect(slot)
                action_btns.append(b)
                return b

            scroll = QScrollArea(); scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            holder = QWidget(); vb = QVBoxLayout(holder)
            vb.setContentsMargins(0, 0, 6, 0); vb.setSpacing(8)
            for key in _tc.toolchain_keys():
                tc = _tc.get_toolchain(key)
                statuses = _tc.toolchain_status(key)
                card = QFrame(); card.setObjectName("CatCard")
                card_of[key] = card
                cl = QVBoxLayout(card); cl.setContentsMargins(12, 10, 12, 10); cl.setSpacing(4)
                head = QHBoxLayout(); head.setSpacing(8)
                nm = QLabel(f"{tc.title}  ·  {key}"); nm.setObjectName("CatTitle")
                head.addWidget(nm, 1)
                if key == "cpp":
                    cfgbtn = mk_btn(_("Настроить VS Code"), "Ghost",
                                    lambda _=False, k=key: do_configure_vscode(k),
                                    _("Прописать путь к компилятору в settings.json "
                                      "VS Code, чтобы IntelliSense и сборка заработали."))
                    head.addWidget(cfgbtn, 0, Qt.AlignmentFlag.AlignVCenter)
                req_missing = [p for p in tc.packages
                               if not p.optional and not _tc.package_installed(p)]
                if wg_ok and req_missing:
                    allbtn = mk_btn(_("Установить всё ({n})").format(n=len(req_missing)),
                                    "Ghost",
                                    lambda _=False, ps=list(req_missing): start_winget(ps, "install"))
                    head.addWidget(allbtn, 0, Qt.AlignmentFlag.AlignVCenter)
                cl.addLayout(head)
                note = _wrap(QLabel(tc.note)); note.setObjectName("CatNote")
                cl.addWidget(note)
                for st in statuses:
                    pkg = st["package"]
                    prow = QHBoxLayout(); prow.setSpacing(6)
                    label = pkg.title + (_(" · доп.") if pkg.optional else "")
                    pn = QLabel(label)
                    pn.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                    if pkg.provides:
                        pn.setToolTip(_("Даёт: {tools}").format(tools=", ".join(pkg.provides)))
                    prow.addWidget(pn, 1)
                    tag = QLabel(); tag.setObjectName("Woff")
                    prow.addWidget(tag, 0, Qt.AlignmentFlag.AlignVCenter)
                    # #4: выбор версии для пакетов, у которых есть варианты.
                    ver_combo = None
                    if pkg.versions:
                        ver_combo = QComboBox()
                        for vid, vtitle in pkg.versions:
                            ver_combo.addItem(vtitle, vid)
                        # по умолчанию — winget_id пакета (первый подходящий).
                        idx = next((i for i, (vid, _t) in enumerate(pkg.versions)
                                    if vid == pkg.winget_id), 0)
                        ver_combo.setCurrentIndex(idx)
                        ver_combo.setToolTip(_("Версия для установки/обновления"))
                        prow.addWidget(ver_combo, 0, Qt.AlignmentFlag.AlignVCenter)
                    ib = mk_btn(_("Установить"), "Ghost",
                                lambda _=False, p=pkg: start_winget([p], "install"),
                                _("winget install --id {id}").format(id=pkg.winget_id)
                                + (f"\n\n{pkg.note}" if pkg.note else ""))
                    ap = mk_btn(_("Добавить в PATH"), "Ghost",
                                lambda _=False, p=pkg: do_add_existing(p),
                                _("Компилятор найден на диске — добавить его каталог "
                                  "в PATH без повторной загрузки."))
                    vf = mk_btn(_("Проверить"), "Ghost",
                                lambda _=False, p=pkg: do_verify(p),
                                _("Запустить инструмент и показать его версию."))
                    up = mk_btn(_("Обновить"), "Ghost",
                                lambda _=False, p=pkg: start_winget([p], "upgrade"),
                                _("winget upgrade --id {id}").format(id=pkg.winget_id))
                    un = mk_btn(_("Удалить"), "Danger",
                                lambda _=False, p=pkg: start_winget([p], "uninstall"),
                                _("winget uninstall --id {id}").format(id=pkg.winget_id))
                    for b in (ib, ap, vf, up, un):
                        prow.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
                    rows[pkg.winget_id] = {"tag": tag, "install": ib, "addpath": ap,
                                           "verify": vf, "upgrade": up, "uninstall": un,
                                           "ver_combo": ver_combo, "pkg": pkg}
                    refresh_pkg_row(pkg, st["installed"], st["version"])
                    cl.addLayout(prow)
                vb.addWidget(card)
            vb.addStretch()
            scroll.setWidget(holder)
            lay.addWidget(scroll, 1)

            def do_check_updates():
                """#5: спросить winget, что из наших тулчейнов можно обновить, и
                отметить такие пакеты в списке."""
                if state["busy"] or not wg_ok:
                    return
                lock_actions(True)
                status_lbl.setText(_("Проверяю обновления…")); status_lbl.setVisible(True)
                w = FnWorker(_tc.list_upgradable_ids)

                def _d(res):
                    if not state["open"]:
                        return
                    lock_actions(False)
                    if not isinstance(res, set):
                        status_lbl.setText(_("Не удалось проверить обновления"))
                        return
                    n = 0
                    for _wid, r in rows.items():
                        pkg = r.get("pkg")
                        ids = {pkg.winget_id, *(v for v, _t in pkg.versions)} if pkg else set()
                        if ids & res and _tc.package_installed(pkg):
                            r["tag"].setText(_("доступно обновление ↑"))
                            r["tag"].setObjectName("Wmedium")
                            r["tag"].style().unpolish(r["tag"]); r["tag"].style().polish(r["tag"])
                            n += 1
                    status_lbl.setText(_("Доступно обновлений: {n}").format(n=n))
                    status_lbl.setVisible(True)
                w.done.connect(_d)
                w.finished.connect(lambda x=w: self._reap_installer(x))
                self._install_threads.append(w); w.start()

            def do_doctor():
                """#8: собрать отчёт об окружении в фоне и показать его."""
                if state["busy"]:
                    return
                lock_actions(True)
                status_lbl.setText(_("Проверяю окружение…")); status_lbl.setVisible(True)
                w = FnWorker(_tc.environment_report)

                def _d(res):
                    if not state["open"]:
                        return
                    lock_actions(False); status_lbl.setVisible(False)
                    if not isinstance(res, dict):
                        QMessageBox.warning(dlg, _("Проверка окружения"),
                                            _("Не удалось собрать отчёт."))
                        return
                    self._show_doctor_report(res)
                w.done.connect(_d)
                w.finished.connect(lambda x=w: self._reap_installer(x))
                self._install_threads.append(w); w.start()

            bar = QHBoxLayout()
            bar.addWidget(status_lbl)
            bar.addWidget(prog_bar, 0, Qt.AlignmentFlag.AlignVCenter)
            bar.addWidget(cancel_btn)
            bar.addStretch()
            doctor_btn = mk_btn(_("Проверить окружение"), "Ghost", do_doctor,
                                _("Отчёт: установленные тулчейны и версии, здоровье "
                                  "PATH (дубли/мёртвые записи), JAVA_HOME."))
            bar.addWidget(doctor_btn)
            if wg_ok:
                upd_btn = mk_btn(_("Проверить обновления"), "Ghost", do_check_updates,
                                 _("Спросить winget, для каких тулчейнов доступно "
                                   "обновление, и отметить их."))
                bar.addWidget(upd_btn)
            close = QPushButton(_("Закрыть")); close.setObjectName("Accent")
            close.clicked.connect(dlg.accept)
            bar.addWidget(close)
            lay.addLayout(bar)

            # Прокрутка к нужному тулчейну (из подсказки в главном окне).
            if target and target in card_of:
                QTimer.singleShot(0, lambda: scroll.ensureWidgetVisible(card_of[target]))
            dlg.exec()

        def _show_doctor_report(self, rep: dict):
            """#8: показать отчёт environment_report в читаемом виде."""
            dlg = QDialog(self); dlg.setWindowTitle(_("Проверка окружения"))
            dlg.resize(640, 620)
            lay = QVBoxLayout(dlg); lay.setContentsMargins(18, 18, 18, 16); lay.setSpacing(10)
            title = QLabel(_("Проверка окружения")); title.setObjectName("Title")
            lay.addWidget(title)

            lines: list[str] = []
            lines.append(_("winget: {v}").format(v=rep.get("winget") or _("не найден")))
            lines.append("")
            tools = rep.get("tools", [])
            lines.append(_("Установленные тулчейны ({n}):").format(n=len(tools)))
            for t in tools:
                lines.append(f"  ✓ {t['title']}  —  {t.get('version') or ''}")
            if not tools:
                lines.append("  —")
            lines.append("")
            jh = rep.get("java_home", {})
            if jh.get("set"):
                mark = "✓ " if jh.get("ok") else "✗ "
                extra = f"  ({jh.get('reason')})" if not jh.get("ok") else ""
                lines.append(f"{mark}JAVA_HOME: {jh.get('path')}{extra}")
            else:
                lines.append(_("JAVA_HOME не задан."))
            lines.append("")
            ph = rep.get("path", {})
            lines.append(_("PATH: {n} записей, длина {l} символов").format(
                n=ph.get("count", 0), l=ph.get("length", 0)))
            dups = ph.get("duplicates", [])
            miss = ph.get("missing", [])
            if dups:
                lines.append(_("  Дубликаты ({n}):").format(n=len(dups)))
                lines += [f"    • {d}" for d in dups[:12]]
            if miss:
                lines.append(_("  Несуществующие каталоги ({n}):").format(n=len(miss)))
                lines += [f"    • {d}" for d in miss[:12]]
            if not dups and not miss:
                lines.append(_("  PATH в порядке: дублей и мёртвых записей не найдено."))

            box = QPlainTextEdit("\n".join(lines)); box.setReadOnly(True)
            lay.addWidget(box, 1)
            b = QHBoxLayout(); b.addStretch()
            close = QPushButton(_("Закрыть")); close.setObjectName("Accent")
            close.clicked.connect(dlg.accept)
            b.addWidget(close); lay.addLayout(b)
            dlg.exec()

        def _show_duplicates(self):
            if not duplicates:
                return
            dlg = QDialog(self)
            dlg.setWindowTitle("Дубли в categories.json")
            dlg.resize(600, 500)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(18, 18, 18, 16); lay.setSpacing(12)
            title = QLabel("Расширения в нескольких стеках"); title.setObjectName("Title")
            lay.addWidget(title)
            note = _wrap(QLabel(
                "Каждое расширение попадёт только в один стек — тот, что стоит "
                "последним в data/categories.json. Убери дубли, чтобы галочка "
                "работала предсказуемо."))
            note.setObjectName("Subtitle")
            lay.addWidget(note)
            lay.addWidget(_hline())
            box = QPlainTextEdit(); box.setObjectName("Log"); box.setReadOnly(True)
            box.setMaximumHeight(16777215)
            text = "\n".join(f"{ext}  ->  {' + '.join(keys)}"
                             for ext, keys in sorted(duplicates.items()))
            box.setPlainText(text)
            lay.addWidget(box, 1)
            bar = QHBoxLayout()
            copy = QPushButton("Копировать"); copy.setObjectName("Ghost")
            copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
            bar.addWidget(copy); bar.addStretch()
            close = QPushButton("Закрыть"); close.setObjectName("Accent")
            close.clicked.connect(dlg.accept)
            bar.addWidget(close)
            lay.addLayout(bar)
            dlg.exec()

        def _show_unknown(self):
            unk = self._unknown()
            if not unk:
                return
            dlg = QDialog(self)
            dlg.setWindowTitle("Расширения не в карте")
            dlg.resize(560, 560)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(18, 18, 18, 16); lay.setSpacing(12)
            title = QLabel("Не в data/categories.json"); title.setObjectName("Title")
            lay.addWidget(title)
            note = _wrap(QLabel(
                f"{len(unk)} расширений нет в карте категорий, поэтому лаунчер всегда "
                "оставляет их включёнными. Добавь их в нужную категорию в "
                "data/categories.json, чтобы управлять ими из окна."))
            note.setObjectName("Subtitle")
            lay.addWidget(note)
            lay.addWidget(_hline())
            box = QPlainTextEdit(); box.setObjectName("Log"); box.setReadOnly(True)
            box.setMaximumHeight(16777215)
            box.setPlainText("\n".join(unk))
            lay.addWidget(box, 1)
            bar = QHBoxLayout()
            copy = QPushButton("Копировать список"); copy.setObjectName("Ghost")
            copy.clicked.connect(lambda: QApplication.clipboard().setText("\n".join(unk)))
            bar.addWidget(copy); bar.addStretch()
            close = QPushButton("Закрыть"); close.setObjectName("Accent")
            close.clicked.connect(dlg.accept)
            bar.addWidget(close)
            lay.addLayout(bar)
            dlg.exec()

        def _show_autoconfig(self):
            recommended = load_recommended()
            present = categories_present(self.installed, ext_index)
            to_add = {k: v for k, v in recommended_for(present, recommended).items()
                      if k != "_comment"}
            path = vscode_user_settings_path(code_cli)
            text = (json.dumps(to_add, ensure_ascii=False, indent=2) if to_add
                    else "Нет рекомендаций для установленных стеков.")

            dlg = QDialog(self); dlg.setWindowTitle("Автонастройка VS Code")
            dlg.resize(600, 560)
            lay = QVBoxLayout(dlg); lay.setContentsMargins(18, 18, 18, 16); lay.setSpacing(12)
            title = QLabel("Рекомендованные настройки"); title.setObjectName("Title")
            lay.addWidget(title)
            stacks = ", ".join(sorted(present)) or "—"
            info = _wrap(QLabel(
                f"Стеки: {stacks}. «Применить» добавит только НЕДОСТАЮЩИЕ ключи в "
                f"settings.json и сделает бэкап; существующие настройки не меняются.\n"
                f"Файл: {path if path else 'не найден'}"))
            info.setObjectName("Subtitle"); lay.addWidget(info)
            lay.addWidget(_hline())
            box = QPlainTextEdit(); box.setObjectName("Log"); box.setReadOnly(True)
            box.setMaximumHeight(16777215); box.setPlainText(text)
            lay.addWidget(box, 1)

            bar = QHBoxLayout()
            copy = QPushButton("Копировать"); copy.setObjectName("Ghost")
            copy.setEnabled(bool(to_add))
            copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
            bar.addWidget(copy)
            apply_btn = QPushButton("Применить (бэкап)"); apply_btn.setObjectName("Accent")
            apply_btn.setEnabled(bool(to_add and path))

            def do_apply():
                if QMessageBox.question(
                        dlg, "Применить настройки?",
                        "Добавить недостающие рекомендованные ключи в settings.json?\n"
                        "Существующие настройки не изменятся, будет сделан бэкап.",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                    return
                ok, msg = apply_settings(path, to_add)
                log.info("Автонастройка: %s", msg.replace("\n", " | "))
                (QMessageBox.information if ok else QMessageBox.warning)(
                    dlg, "Автонастройка", msg)
            apply_btn.clicked.connect(do_apply)
            bar.addWidget(apply_btn); bar.addStretch()
            close = QPushButton("Закрыть"); close.setObjectName("Ghost")
            close.clicked.connect(dlg.accept)
            bar.addWidget(close)
            lay.addLayout(bar)
            dlg.exec()

        def _update_selcount(self):
            """Чип «выбрано N / M» в шапке секции стеков."""
            if hasattr(self, "sel_count"):
                self.sel_count.setText(_("выбрано {n} / {m}").format(
                    n=len(self._selected()), m=len(self.cat_checks)))

        def _set_hero(self, number, unit, en_txt, dis_txt, extra_txt=""):
            self.savings_num.setText(str(number))
            self.savings_unit.setText(unit)
            self.stat_en.setText(en_txt); self.stat_en.setVisible(bool(en_txt))
            self.stat_dis.setText(dis_txt); self.stat_dis.setVisible(bool(dis_txt))
            self.stat_extra.setText(extra_txt); self.stat_extra.setVisible(bool(extra_txt))

        def _update_summary(self):
            self._update_selcount()
            if self._bare():
                self._set_hero("MAX", "", _("голый режим"),
                               _("все расширения выключены"))
                self.b_run.setText(_("Запустить (голый режим)"))
                return
            if not self.installed:
                self._set_hero("—", "", _("нет списка расширений"), "")
                self.b_run.setText(_("Запустить VS Code"))
                return
            dis = self._disabled_list()
            en = len(self.installed) - len(dis)
            saved = estimate_saved_mb(dis, ext_index)
            # Фактические замеры, если этот набор уже запускали (#6/#2).
            sig = selection_signature(self._selected(), self._bare())
            extra = ""
            sav = measured_savings_mb(cfg, sig)
            fp = lookup_footprint(cfg, sig)
            if sav:
                self._set_hero(sav, _("МБ"),
                               _("включено {en}").format(en=en),
                               _("выключится {dis}").format(dis=len(dis)),
                               _("реально · оценка ~{saved}").format(saved=saved))
            else:
                extra = _("замерено {mb} МБ").format(mb=fp["mb"]) if fp else ""
                self._set_hero(saved, _("МБ"),
                               _("включено {en}").format(en=en),
                               _("выключится {dis}").format(dis=len(dis)), extra)
            self.b_run.setText(_("Запустить · −{dis}").format(dis=len(dis))
                               if dis else _("Запустить VS Code"))

        def _cmd_kwargs(self) -> dict:
            return {
                "profile": self.profile_edit.text().strip(),
                "disable_gpu": self.gpu_cb.isChecked(),
                "bare": self._bare(),
            }

        def _browse(self):
            d = QFileDialog.getExistingDirectory(self, _("Выбери папку проекта"))
            if d:
                self.folder_edit.setText(d.replace("/", "\\"))
                self._suggest_for_folder(self.folder_edit.text().strip())

        def _pick_recent(self):
            path = self.recent_box.currentData() or ""
            self.folder_edit.setText(path)
            self._suggest_for_folder(path)

        def _show_diff(self):
            """#5: показать точный список расширений, которые будут выключены,
            сгруппированный по стеку — доверие к «что именно уйдёт»."""
            if self._bare():
                body = _("Голый режим: все расширения выключены (--disable-extensions).")
                groups = []
            else:
                dis = self._disabled_list()
                groups = disabled_by_category(dis, ext_index)
                if dis:
                    body = _("Выключается {n} расширений из невыбранных стеков. always_on "
                             "и всё, чего нет в карте, останется включённым.").format(n=len(dis))
                else:
                    body = _("Ничего не выключается — всё установленное останется включённым.")

            lines = []
            for cat, exts in groups:
                title = cats.get("categories", {}).get(cat, {}).get("title", cat)
                lines.append(f"— {title} ({len(exts)}) —")
                lines.extend(f"    {e}" for e in exts)
                lines.append("")
            text = "\n".join(lines).strip()

            dlg = QDialog(self); dlg.setWindowTitle(_("Что будет выключено"))
            dlg.resize(560, 560)
            lay = QVBoxLayout(dlg); lay.setContentsMargins(18, 18, 18, 16); lay.setSpacing(12)
            ttl = QLabel(_("Что будет выключено")); ttl.setObjectName("Title")
            lay.addWidget(ttl)
            note = _wrap(QLabel(body)); note.setObjectName("Subtitle")
            lay.addWidget(note)
            lay.addWidget(_hline())
            box = QPlainTextEdit(); box.setObjectName("Log"); box.setReadOnly(True)
            box.setMaximumHeight(16777215); box.setPlainText(text)
            lay.addWidget(box, 1)
            bar = QHBoxLayout()
            copy = QPushButton(_("Копировать список")); copy.setObjectName("Ghost")
            copy.setEnabled(bool(text))
            copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
            bar.addWidget(copy); bar.addStretch()
            close = QPushButton(_("Закрыть")); close.setObjectName("Accent")
            close.clicked.connect(dlg.accept)
            bar.addWidget(close)
            lay.addLayout(bar)
            dlg.exec()

        def _show_cmd(self):
            # Сам лаунчер запускает Code.exe напрямую (без оболочки), но здесь
            # показываем эквивалентную команду для cmd — её удобно скопировать
            # в скрипт/ярлык. Помечаем это явно, чтобы не вводить в заблуждение.
            cmd = build_launch_command(code_cli or "code", self._disabled_list(),
                                       self.folder_edit.text().strip(),
                                       self.newwin_cb.isChecked(), self.kill_cb.isChecked(),
                                       **self._cmd_kwargs())
            self.log.setPlainText("Эквивалент для cmd (сам лаунчер запускает "
                                  "Code.exe напрямую, без оболочки):\n" + cmd)

        def _run(self):
            if not code_cli:
                QMessageBox.critical(self, "Ошибка", "Не найден CLI VS Code (code.cmd).")
                return
            folder = self.folder_edit.text().strip()
            if folder and not Path(folder).exists():
                # Не открываем молча несуществующий путь — легче заметить опечатку
                # и это отсекает попытку подсунуть в поле что-то, что не является путём.
                r = QMessageBox.question(
                    self, "Папка не найдена",
                    f"Путь не существует:\n{folder}\n\nОткрыть VS Code без папки?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if r != QMessageBox.StandardButton.Yes:
                    return
                self.folder_edit.clear()
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
            bare = self._bare()
            args = build_launch_args(dis, self.folder_edit.text().strip(),
                                     self.newwin_cb.isChecked(), self.kill_cb.isChecked(),
                                     **self._cmd_kwargs())

            def do_launch():
                try:
                    launch_detached(code_cli, args)   # без оболочки, напрямую Code.exe
                except Exception as e:
                    log.exception("Ошибка запуска")
                    QMessageBox.critical(self, "Ошибка запуска", str(e))
                    return
                log.info("Запуск: %s", "голый режим" if bare
                         else f"выключено {len(dis)} расширений")
                self.log.appendPlainText("Запуск: голый режим (все расширения выкл). OK."
                                         if bare else
                                         f"Запуск: выключено {len(dis)} расширений. OK.")
                # #6: замерить фактический footprint этого набора чуть погодя.
                self._pending_record_sig = selection_signature(self._selected(), bare)
                # #2: запуск без выключенных стеков (и не голый) — это базлайн
                # «всё включено», от которого считается реальная экономия.
                self._pending_is_baseline = (not bare) and len(dis) == 0
                QTimer.singleShot(6000, self._probe_memory)   # новый footprint

            if self.kill_cb.isChecked():
                if self.soft_cb.isChecked():
                    self._graceful_close_then(do_launch)   # дать сохранить, дождаться
                else:
                    kill_vscode(code_cli)   # жёстко (/F), затем стартуем с паузой
                    self.log.appendPlainText("Закрываю VS Code…")
                    QTimer.singleShot(1800, do_launch)   # не блокируем интерфейс
            else:
                do_launch()
            self._persist()

        def _graceful_close_then(self, cont):
            """Мягко закрыть VS Code (с запросом на сохранение) и дождаться выхода,
            затем cont(). Если через ~15 с редактор ещё открыт (скорее всего висит
            диалог сохранения) — отменяем запуск, ничего не потеряв."""
            kill_vscode(code_cli, graceful=True)
            self.log.appendPlainText("Прошу VS Code закрыться (ответь на запрос сохранения)…")
            self._soft_tries = 0

            def check():
                self._soft_tries += 1
                if vscode_process_count(code_cli) == 0:
                    self.log.appendPlainText("VS Code закрыт. Запускаю…")
                    cont()
                    return
                if self._soft_tries >= 20:   # ~15 секунд
                    self.log.appendPlainText(
                        "VS Code всё ещё открыт — запуск отменён. Закрой окна "
                        "(или ответь на запрос сохранения) и нажми «Запустить» снова.")
                    return
                QTimer.singleShot(750, check)

            QTimer.singleShot(750, check)

        def _reload_presets(self):
            self.preset_box.blockSignals(True)
            self.preset_box.clear()
            self.preset_box.addItem(_("— выбрать пресет —"), None)
            for name in cfg.get("presets", {}):
                self.preset_box.addItem(name, name)
            self.preset_box.blockSignals(False)

        def _apply_preset(self):
            name = self.preset_box.currentData()
            if not name:
                return
            value = cfg.get("presets", {}).get(name)
            if value is None:
                return
            p = normalize_preset(value)
            keys = set(p["stacks"])
            for k, cb in self.cat_checks.items():
                cb.setChecked(k in keys)
            # #4: словарная форма пресета несёт опции запуска — применяем их тоже,
            # чтобы пресет был полноценным лаунч-профилем, а не только набором стеков.
            if isinstance(value, dict):
                self.kill_cb.setChecked(p["kill"])
                self.soft_cb.setEnabled(self.kill_cb.isChecked())
                self.gpu_cb.setChecked(p["gpu_off"])
                self.bare_cb.setChecked(p["bare"])
                self.newwin_cb.setChecked(p["new_window"])
                self.profile_edit.setText(p["profile"])
                if p["folder"]:
                    self.folder_edit.setText(p["folder"])
            self._update_summary()

        def _save_preset(self):
            name, ok = QInputDialog.getText(self, "Сохранить пресет", "Имя пресета:")
            if not ok or not name.strip():
                return
            # #4: сохраняем не только стеки, но и текущие опции запуска —
            # пресет становится полноценным лаунч-профилем. Форма — словарь;
            # normalize_preset и preset_stacks читают её везде, где нужно.
            cfg.setdefault("presets", {})[name.strip()] = {
                "stacks": sorted(self._selected()),
                "folder": self.folder_edit.text().strip(),
                "kill": self.kill_cb.isChecked(),
                "gpu_off": self.gpu_cb.isChecked(),
                "bare": self._bare(),
                "new_window": self.newwin_cb.isChecked(),
                "profile": self.profile_edit.text().strip(),
            }
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
            path, _filt = QFileDialog.getSaveFileName(
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
            path, _filt = QFileDialog.getOpenFileName(self, "Импорт пресетов", "", "JSON (*.json)")
            if not path:
                return
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("ожидается объект {имя: [категории]}")
                # #4: значение пресета — список ключей ИЛИ словарь-профиль.
                raw = {str(k): v for k, v in data.items()
                       if isinstance(v, (list, dict))}
            except Exception as e:
                QMessageBox.critical(self, "Ошибка импорта", str(e))
                return
            # Пропускаем несуществующие ключи категорий: чужой пресет мог
            # ссылаться на переименованный/удалённый стек — молчаливо оставлять
            # такие ключи в конфиге плохо, а падать на них — ещё хуже.
            valid_keys = set(cats.get("categories", {}))
            incoming: dict = {}
            dropped_keys: set[str] = set()
            for name, value in raw.items():
                stacks = preset_stacks(value)
                cleaned = [k for k in stacks if k in valid_keys]
                dropped_keys.update(k for k in stacks if k not in valid_keys)
                # Сохраняем исходную форму: словарь-профиль остаётся профилем.
                incoming[name] = ({**value, "stacks": cleaned}
                                  if isinstance(value, dict) else cleaned)
            if not incoming:
                self.log.appendPlainText("Импорт: в файле нет пресетов.")
                return
            cfg.setdefault("presets", {}).update(incoming)
            save_config(cfg)
            self._reload_presets()
            msg = f"Импортировано пресетов: {len(incoming)}"
            if dropped_keys:
                sample = ", ".join(sorted(dropped_keys)[:6])
                tail = "…" if len(dropped_keys) > 6 else ""
                msg += (f" (пропущено неизвестных ключей категорий: "
                        f"{len(dropped_keys)} — {sample}{tail})")
            self.log.appendPlainText(msg)

        def _make_shortcut(self):
            """#5: сохранить .cmd-ярлык, открывающий VS Code с выбранным пресетом
            через тихий CLI-режим — один клик, без окна лаунчера."""
            name = self.preset_box.currentData()
            if not name:
                QMessageBox.information(
                    self, _("Ярлык"),
                    _("Сначала выбери пресет в списке — ярлык открывает VS Code "
                      "с ним."))
                return
            path, _filt = QFileDialog.getSaveFileName(
                self, _("Сохранить ярлык"), f"{name}.cmd", "CMD (*.cmd)")
            if not path:
                return
            try:
                body = build_shortcut_cmd(_launcher_invocation(), name)
                if not path.lower().endswith(".cmd"):
                    path += ".cmd"
                Path(path).write_text(body, encoding="utf-8")
                self.log.appendPlainText(
                    _("Ярлык создан: {path}").format(path=path))
            except Exception as e:
                QMessageBox.critical(self, _("Ошибка"), str(e))

        def _export_profile(self):
            """#4: сохранить текущий выбор как нативный профиль VS Code
            (.code-profile). В профиль кладём ВКЛючённые расширения — тот же
            набор, что остался бы включённым при запуске через лаунчер, только
            в виде постоянного профиля, а не флагов --disable-extension."""
            if not self.installed:
                QMessageBox.information(self, _("Профиль VS Code"),
                                        _("Список расширений ещё не загружен."))
                return
            disabled = set(self._disabled_list())
            enabled = [e for e in self.installed if e not in disabled]
            keys = sorted(self._selected())
            default_name = "stacks-" + ("-".join(keys) if keys else "core")
            path, _filt = QFileDialog.getSaveFileName(
                self, _("Экспорт профиля VS Code"),
                f"{default_name}.code-profile",
                "VS Code Profile (*.code-profile)")
            if not path:
                return
            if not path.lower().endswith(".code-profile"):
                path += ".code-profile"
            try:
                manifests = read_extension_manifests(code_cli)
                content = profile_file_content(Path(path).stem, enabled, manifests)
                Path(path).write_text(content, encoding="utf-8")
                self.log.appendPlainText(
                    _("Профиль VS Code сохранён ({n} расш.): {path}").format(
                        n=len(enabled), path=path))
                QMessageBox.information(
                    self, _("Профиль VS Code"),
                    _("Готово. В VS Code открой палитру команд и выполни "
                      "«Profiles: Import Profile…», затем выбери этот файл.\n\n"
                      "Расширений в профиле: {n}").format(n=len(enabled)))
            except Exception as e:
                QMessageBox.critical(self, _("Ошибка экспорта профиля"), str(e))

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
            cfg["soft_close"] = self.soft_cb.isChecked()
            cfg["new_window"] = self.newwin_cb.isChecked()
            cfg["disable_gpu"] = self.gpu_cb.isChecked()
            cfg["profile"] = self.profile_edit.text().strip()
            folder = self.folder_edit.text().strip()
            if folder:
                rec = [folder] + [p for p in cfg.get("recent_folders", []) if p != folder]
                cfg["recent_folders"] = rec[:8]
                # #1: запоминаем выбор стеков под этой папкой (без голого режима —
                # он не отражает набор стеков).
                if not self._bare():
                    remember_folder_stacks(cfg, folder, self._selected())
            save_config(cfg)

        def keyPressEvent(self, e):
            # Enter — запустить (если кнопка активна), Esc — закрыть окно,
            # Ctrl+F — фокус в поле поиска стеков (полезно, когда карточек много).
            # Опасный путь (закрыть VS Code) всё равно спрашивает подтверждение в _run.
            if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self.b_run.isEnabled():
                    self._run()
                return
            if e.key() == Qt.Key.Key_Escape:
                self.close()
                return
            if (e.key() == Qt.Key.Key_F
                    and e.modifiers() & Qt.KeyboardModifier.ControlModifier):
                self.search_edit.setFocus()
                self.search_edit.selectAll()
                return
            super().keyPressEvent(e)

        def _reap_installer(self, worker):
            # Убираем завершившийся поток установки/удаления, чтобы список не рос.
            if worker in self._install_threads:
                self._install_threads.remove(worker)

        def closeEvent(self, e):
            try:   # запоминаем геометрию окна
                cfg["geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
                save_config(cfg)
            except Exception:
                pass
            # Дождёмся фоновых потоков, иначе Qt ругается «QThread destroyed while
            # running». Ждём с потолком, чтобы окно не зависало на сетевой установке.
            threads = [getattr(self, "_mem", None), getattr(self, "_loader", None),
                       getattr(self, "_upd", None)]
            threads += list(self._install_threads)
            for t in threads:
                if t is not None and t.isRunning():
                    t.wait(2000)
            super().closeEvent(e)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    font = QFont(); font.setPointSize(10); app.setFont(font)
    theme_name = cfg.get("theme", "dark")
    if theme_name not in PALETTES:
        theme_name = "dark"
    app.setStyleSheet(build_qss(PALETTES[theme_name]))

    def build_window():
        win = Launcher()
        if ICON_FILE.exists():
            win.setWindowIcon(QIcon(str(ICON_FILE)))
        win.show()
        apply_titlebar(win, win._theme == "dark")   # после show(), когда есть нативный hwnd
        return win

    # #7: смена языка пересобирает окно (текст виджетов задаётся при сборке).
    # Держим текущее окно в holder, чтобы кнопка языка могла заменить его,
    # перенеся геометрию и сохранённый выбор.
    holder = {"w": None}

    def rebuild():
        old = holder["w"]
        geo = old.saveGeometry() if old is not None else None
        nw = build_window()
        if geo is not None:
            nw.restoreGeometry(geo)
        holder["w"] = nw
        if old is not None:
            old.close()
            old.deleteLater()

    _lang_switch["fn"] = rebuild

    w = build_window()
    holder["w"] = w
    _shot = os.environ.get("LAUNCHER_SHOT")   # dev-хук: снять окно в PNG и выйти
    if _shot:
        sw, sh = os.environ.get("LAUNCHER_W"), os.environ.get("LAUNCHER_H")
        if sw and sh:
            w.resize(int(sw), int(sh))

        def _grab():
            holder["w"].grab().save(_shot)
            app.quit()
        QTimer.singleShot(1800, _grab)
    sys.exit(app.exec())
