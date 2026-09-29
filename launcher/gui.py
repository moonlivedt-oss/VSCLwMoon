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
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QPushButton,
    QLabel,
    QLineEdit,
    QFileDialog,
    QComboBox,
    QMessageBox,
    QInputDialog,
    QPlainTextEdit,
    QScrollArea,
    QFrame,
    QDialog,
    QProgressBar,
    QSystemTrayIcon,
    QGridLayout,
    QStackedWidget,
)

from . import __version__
from .core import (
    ICON_FILE,
    LOGO_FILE,
    WEIGHT,
    WEIGHT_HELP,
    WEIGHT_LABEL,
    WEIGHT_MB,
    apply_settings,
    build_ext_index,
    build_launch_command,
    build_dependency_map,
    build_shortcut_cmd,
    categories_present,
    code_image_name,
    compute_disabled,
    detect_recommended_stacks,
    detect_stacks,
    read_extension_manifests,
    disabled_by_category,
    find_duplicate_extensions,
    kill_vscode,
    launch_detached,
    list_code_installs,
    load_categories,
    load_config,
    load_descriptions,
    load_recommended,
    lookup_footprint,
    marketplace_url,
    measured_savings_mb,
    normalize_preset,
    plan_launch,
    preset_stacks,
    profile_file_content,
    read_installed_from_disk,
    recall_folder_stacks,
    folder_auto_stacks,
    set_folder_auto,
    is_folder_auto,
    recommended_for,
    record_baseline,
    record_footprint,
    remember_folder_stacks,
    resolve_code_cli,
    save_config,
    selection_signature,
    setup_logging,
    suggest_categories,
    vscode_process_count,
    vscode_user_settings_path,
    load_installed,
)
from .categories import cat_note, cat_title
from .cli import _launcher_invocation
from .i18n import _, get_language, set_language
from .settings_apply import missing_settings as _missing_settings
from .updates import RELEASES_URL, build_update_swap_bat
from .gui_widgets import (
    CategoryCard,
    FlowLayout,
    ToggleSwitch,
    _hline,
    _wrap,
    set_switch_palette,
)
from .gui_shell import (
    Banner,
    NavRail,
    PaletteCard,
    Pill,
    Section,
    Tile,
    menu_button,
    page_header,
    segmented,
)
from .gui_shell import icon as shell_icon
from .gui_workers import (
    ElevatedInstaller,
    ExtLoader,
    FnWorker,
    Installer,
    MemProbe,
    SizeProbe,
    StatusProbe,
    ToolchainInstaller,
    UpdateCheck,
    UpdateDownloader,
)
from . import weights as _w
from .theme import PALETTE_SETS, PALETTES, apply_titlebar, build_qss, make_palette, palette_name
from . import toolchains as _tc


# --- окно: фабрика класса Launcher --------------------------------------
# Класс замыкает состояние сессии (карта, конфиг, CLI, логгер, ...). Фабрика
# делает его модульным и импортируемым: run_gui зовёт её для приложения,
# тесты — с подставленным состоянием (см. tests/test_gui_smoke.py).


def _note_lbl(text: str) -> QLabel:
    lbl = _wrap(QLabel(text))
    lbl.setObjectName("CatNote")
    return lbl


def _switch_row(switch, title: str, desc: str = "") -> QHBoxLayout:
    """Строка настройки: тумблер, название, пояснение под ним (как в vscode-bg)."""
    row = QHBoxLayout()
    row.setSpacing(12)
    row.addWidget(switch, 0, Qt.AlignmentFlag.AlignTop)
    col = QVBoxLayout()
    col.setSpacing(1)
    t = QLabel(title)
    t.setObjectName("TileTitle")
    col.addWidget(t)
    if desc:
        col.addWidget(_note_lbl(desc))
    row.addLayout(col, 1)
    return row


def _launcher_factory(
    cats, cats_err, cfg, ext_index, code_cli, descriptions, duplicates, log, _lang_switch
):
    def show_details(parent, key, cat, installed):
        """Диалог со списком плагинов стека: описания + установка/удаление."""
        dlg = QDialog(parent)
        dlg.setWindowTitle(_("Стек: {title}").format(title=cat_title(cat, key)))
        dlg.resize(820, 660)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 18, 18, 16)
        lay.setSpacing(12)

        title = QLabel(cat_title(cat, key))
        title.setObjectName("Title")
        lay.addWidget(title)
        note = _wrap(QLabel(cat_note(cat)))
        note.setObjectName("Subtitle")
        lay.addWidget(note)

        exts = cat.get("extensions", [])
        weight = WEIGHT.get(key, "light")
        try:
            manifests = read_extension_manifests(code_cli)
        except Exception:
            manifests = {}

        # Поясняем, что вообще делает это окно и что значат кнопки: пользователь
        # должен понимать, что он ставит/удаляет и что это обратимо.
        intro = _wrap(
            QLabel(
                _(
                    "Ниже — расширения этого стека и что каждое делает. "
                    "«Маркетплейс» открывает страницу расширения — прочитать, что это, "
                    "перед установкой. «Установить» качает его из маркетплейса VS Code, "
                    "«Удалить» стирает с диска (можно поставить заново). Отключение "
                    "стека галочкой в главном окне ничего не удаляет — только не грузит "
                    "в этой сессии."
                )
            )
        )
        intro.setObjectName("CatNote")
        lay.addWidget(intro)

        meta = QLabel()
        meta.setObjectName("Section")
        meta.setToolTip(_(WEIGHT_HELP.get(weight, "")))
        lay.addWidget(meta)
        lay.addWidget(_hline())

        # Потоки держим на parent (главном окне), чтобы они пережили закрытие
        # диалога и не роняли приложение на уже удалённых виджетах.
        state = {"open": True}
        dlg.finished.connect(lambda _=0: state.update(open=False))
        rows: dict[str, tuple] = {}  # id -> (tag, install_btn, uninstall_btn)
        bulk_btn = None
        status_lbl = None  # строка прогресса «Устанавливаю i/n…» (создаётся в баре)
        prog_bar = None  # полоска прогресса установки/удаления
        cancel_btn = None  # кнопка отмены пакетной операции
        YES = QMessageBox.StandardButton.Yes
        NO = QMessageBox.StandardButton.No

        def refresh_meta():
            n = sum(1 for e in exts if e.lower() in installed)
            approx = WEIGHT_MB.get(weight, 30)
            meta.setText(
                _(
                    "{total} расширений · установлено {n} · нагрузка "
                    "{load} · выключение освобождает ~{mb} МБ"
                ).format(total=len(exts), n=n, load=_(WEIGHT_LABEL[weight]), mb=approx)
            )

        def set_row_state(eid, is_inst):
            tag, ib, ub = rows.get(eid, (None, None, None))
            if tag is not None:
                tag.setText(_("установлено") if is_inst else _("нет в системе"))
                tag.setObjectName("Wlight" if is_inst else "Woff")
                tag.setToolTip(
                    _("Расширение установлено — грузится в VS Code, пока стек включён.")
                    if is_inst
                    else _("Расширения нет на диске. «Установить» скачает его из маркетплейса.")
                )
                tag.style().unpolish(tag)
                tag.style().polish(tag)
            if ib is not None:
                ib.setVisible(not is_inst)
                ib.setEnabled(True)
                ib.setText(_("Установить"))
            if ub is not None:
                ub.setVisible(is_inst)
                ub.setEnabled(True)
                ub.setText(_("Удалить"))

        def refresh_bulk():
            if bulk_btn is None:
                return
            left = [e for e in exts if e.lower() not in installed]
            bulk_btn.setEnabled(True)
            bulk_btn.setText(_("Установить недостающие ({n})").format(n=len(left)))
            bulk_btn.setVisible(bool(left))

        def start_action(ids, action):
            if action == "install":
                todo = [i for i in ids if i.lower() not in installed]
            else:
                todo = [i for i in ids if i.lower() in installed]
            if not todo or not code_cli:
                return
            if action == "install":
                body = (
                    _(
                        "Установить расширение:\n\n{ext}\n\nОно будет скачано "
                        "из маркетплейса VS Code."
                    ).format(ext=todo[0])
                    if len(todo) == 1
                    else _(
                        "Установить {n} недостающих расширений стека «{title}»?"
                        "\n\nВсе они будут скачаны из маркетплейса."
                    ).format(n=len(todo), title=cat_title(cat, key))
                )
                if (
                    QMessageBox.question(
                        dlg,
                        _("Скачать и установить?"),
                        body + "\n\n" + _("Продолжить?"),
                        YES | NO,
                        NO,
                    )
                    != YES
                ):
                    return
                busy = _("Устанавливаю…")
                busy_word = _("Устанавливаю")
            else:
                body = _(
                    "Удалить расширение:\n\n{ext}\n\nОно будет удалено с диска. "
                    "Переустановить можно кнопкой «Установить»."
                ).format(ext=todo[0])
                if (
                    QMessageBox.question(
                        dlg,
                        _("Удалить расширение?"),
                        body + "\n\n" + _("Продолжить?"),
                        YES | NO,
                        NO,
                    )
                    != YES
                ):
                    return
                busy = _("Удаляю…")
                busy_word = _("Удаляю")
            for i in todo:
                # NB: не называть переменную `_` — это затенит функцию перевода
                # i18n._ во всей start_action и уронит вызовы _(...) выше по коду.
                _tag, ib, ub = rows.get(i.lower(), (None, None, None))
                b = ib if action == "install" else ub
                if b is not None:
                    b.setText(busy)
                    b.setEnabled(False)
            if action == "install" and bulk_btn is not None:
                bulk_btn.setEnabled(False)
                bulk_btn.setText(busy)
            if prog_bar is not None:
                # Пакетная — определённый прогресс 0..N; одиночная — «бегущая»
                # неопределённая полоска (range 0,0), пока идёт единственный шаг.
                if len(todo) > 1:
                    prog_bar.setRange(0, len(todo))
                    prog_bar.setValue(0)
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
                        if not bulk:  # пакетную ошибку копим на сводку
                            verb = _("установить") if action == "install" else _("удалить")
                            QMessageBox.warning(
                                dlg,
                                _("Не удалось {verb}").format(verb=verb),
                                f"{ext_id}\n\n{(msg or '')[:600]}",
                            )

            def _progress(i, n):
                if not state["open"]:
                    return
                if status_lbl is not None:
                    status_lbl.setText(f"{busy_word} {i}/{n}…" if n > 1 else f"{busy_word}…")
                    status_lbl.setVisible(True)
                if prog_bar is not None and n > 1:
                    prog_bar.setValue(i - 1)  # столько уже завершено

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
                rem = total - len(processed)  # не обработано (отмена)
                verb = _("Установлено") if action == "install" else _("Удалено")
                summary = _("{verb}: {ok}, ошибок: {err}").format(
                    verb=verb, ok=ok_n, err=len(fails)
                )
                if rem:
                    summary += _(", отменено: {rem}").format(rem=rem)
                if status_lbl is not None:
                    status_lbl.setText(summary)
                    status_lbl.setVisible(True)
                if fails:
                    preview = "\n".join(
                        f"• {eid}: {(m or '').splitlines()[0][:120]}" for eid, m in fails[:8]
                    )
                    more = "\n…" if len(fails) > 8 else ""
                    QMessageBox.warning(
                        dlg, _("Готово с ошибками"), summary + "\n\n" + preview + more
                    )

            worker = Installer(code_cli, todo, action)
            worker.progress.connect(_progress)
            worker.one_done.connect(_one)
            worker.all_done.connect(_all)
            worker.finished.connect(lambda w=worker: parent._reap_installer(w))
            if bulk and cancel_btn is not None:
                cancel_btn.setVisible(True)
                cancel_btn.setEnabled(True)
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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        vb = QVBoxLayout(holder)
        vb.setContentsMargins(0, 0, 6, 0)
        vb.setSpacing(8)
        for ext in exts:
            row = QFrame()
            row.setObjectName("CatCard")
            rl = QVBoxLayout(row)
            rl.setContentsMargins(12, 9, 12, 9)
            rl.setSpacing(3)
            top = QHBoxLayout()
            top.setSpacing(8)
            name = QLabel(ext)
            name.setObjectName("CatTitle")
            name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            top.addWidget(name, 1)
            tag = QLabel()
            tag.setObjectName("Woff")
            top.addWidget(tag, 0, Qt.AlignmentFlag.AlignVCenter)
            if manifests.get(ext.lower(), {}).get("eager"):
                eager = QLabel(_("стартует сразу"))
                eager.setObjectName("Wmedium")
                eager.setToolTip(
                    _(
                        "Расширение активируется при каждом запуске VS Code "
                        "(«*» или onStartupFinished), а не когда открыт файл его "
                        "языка. Такие держат память даже там, где не нужны, — "
                        "их выгоднее всего выключать стеком."
                    )
                )
                top.addWidget(eager, 0, Qt.AlignmentFlag.AlignVCenter)

            # #9: персональный оверрайд поведения этого расширения.
            ov_box = QComboBox()
            ov_box.setToolTip(_("Поведение этого расширения независимо от галочки стека"))
            for label, mode in (
                (_("по стеку"), "default"),
                (_("всегда вкл"), "enable"),
                (_("всегда выкл"), "disable"),
            ):
                ov_box.addItem(label, mode)
            cur = parent.override_mode(ext)
            i_cur = ov_box.findData(cur)
            if i_cur >= 0:
                ov_box.setCurrentIndex(i_cur)
            ov_box.currentIndexChanged.connect(
                lambda _i, e=ext, b=ov_box: parent.set_override(e, b.currentData())
            )
            top.addWidget(ov_box, 0, Qt.AlignmentFlag.AlignVCenter)

            # «Маркетплейс» — прочитать, что за расширение, ПЕРЕД установкой.
            # Доступно всегда, даже без CLI (это просто ссылка в браузер).
            mkt_url = marketplace_url(ext)
            if mkt_url:
                mkt = QPushButton(_("Маркетплейс ↗"))
                mkt.setObjectName("Ghost")
                mkt.setCursor(Qt.CursorShape.PointingHandCursor)
                mkt.setToolTip(
                    _(
                        "Открыть страницу расширения в маркетплейсе "
                        "VS Code — описание, автор, рейтинг и что оно "
                        "запрашивает — перед установкой."
                    )
                )
                mkt.clicked.connect(lambda _=False, u=mkt_url: QDesktopServices.openUrl(QUrl(u)))
                top.addWidget(mkt, 0, Qt.AlignmentFlag.AlignVCenter)

            ib = ub = None
            if code_cli:
                ib = QPushButton(_("Установить"))
                ib.setObjectName("Ghost")
                ib.setCursor(Qt.CursorShape.PointingHandCursor)
                ib.setToolTip(
                    _("Скачать и установить это расширение из маркетплейса VS Code.")
                    + f"\n\ncode --install-extension {ext}"
                )
                ib.clicked.connect(lambda _=False, e=ext: start_action([e], "install"))
                top.addWidget(ib, 0, Qt.AlignmentFlag.AlignVCenter)
                ub = QPushButton(_("Удалить"))
                ub.setObjectName("Danger")
                ub.setCursor(Qt.CursorShape.PointingHandCursor)
                ub.setToolTip(
                    _("Удалить расширение с диска. Переустановить можно кнопкой «Установить».")
                    + f"\n\ncode --uninstall-extension {ext}"
                )
                ub.clicked.connect(lambda _=False, e=ext: start_action([e], "uninstall"))
                top.addWidget(ub, 0, Qt.AlignmentFlag.AlignVCenter)
            rows[ext.lower()] = (tag, ib, ub)
            set_row_state(ext.lower(), ext.lower() in installed)
            rl.addLayout(top)
            desc = descriptions.get(ext.lower())
            dl = _wrap(
                QLabel(
                    desc
                    or _(
                        "Описание не задано — открой «Маркетплейс», "
                        "чтобы прочитать, что делает расширение."
                    )
                )
            )
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
            bulk_btn = QPushButton(_("Установить недостающие ({n})").format(n=len(missing)))
            bulk_btn.clicked.connect(
                lambda: start_action([e for e in exts if e.lower() not in installed], "install")
            )
            bulk_btn.setVisible(bool(missing))
            bar.addWidget(bulk_btn)
            # Прогресс установки/удаления + отмена (скрыты, пока не идёт операция).
            status_lbl = QLabel()
            status_lbl.setObjectName("CatNote")
            status_lbl.setVisible(False)
            bar.addWidget(status_lbl)
            prog_bar = QProgressBar()
            prog_bar.setObjectName("InstallBar")
            prog_bar.setTextVisible(False)
            prog_bar.setFixedWidth(140)
            prog_bar.setFixedHeight(8)
            prog_bar.setVisible(False)
            bar.addWidget(prog_bar, 0, Qt.AlignmentFlag.AlignVCenter)
            cancel_btn = QPushButton(_("Отмена"))
            cancel_btn.setObjectName("Ghost")
            cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            cancel_btn.setToolTip(
                _("Прервать пакетную установку (текущее расширение доустановится, следующие — нет)")
            )
            cancel_btn.setVisible(False)
            bar.addWidget(cancel_btn)
        else:
            no_cli = QLabel(_("нет CLI VS Code — установка/удаление недоступны"))
            no_cli.setObjectName("CatNote")
            bar.addWidget(no_cli)
        bar.addStretch()
        close = QPushButton(_("Закрыть"))
        close.setObjectName("Accent")
        close.clicked.connect(dlg.accept)
        bar.addWidget(close)
        lay.addLayout(bar)
        dlg.exec()

    class Launcher(QWidget):
        def __init__(self, background=True):
            super().__init__()
            self.setWindowTitle(
                _("VS Code Launcher {ver} — переключатель нагрузки").format(ver=__version__)
            )
            self.resize(1040, 860)  # с запасом под 2 колонки карточек
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
            self._dep_map = None  # #1: карта зависимостей (ленивая, кэш)
            self._pending_record_sig = None  # #6: подпись выбора для замера после запуска
            self._pending_is_baseline = False  # #2: следующий замер — базлайн «всё вкл»
            self._suggested_keys: set[str] = set()  # #1: что предложил автодетект
            self._auto_suggested = False  # #1: авто-подсказку при старте делаем один раз
            # Реальные размеры расширений на диске: из кэша мгновенно, свежие
            # догружаем в фоне (обход папки расширений стоит 1-2 с).
            cached_sizes = cfg.get("ext_sizes", {})
            self._ext_sizes = (
                dict(cached_sizes.get("sizes", {})) if isinstance(cached_sizes, dict) else {}
            )
            self._tray = None  # ставится извне (run_gui), если трей включён
            self._quit_requested = False  # закрытие «по-настоящему», а не в трей
            self._theme = cfg.get("theme", "dark")
            if self._theme not in PALETTES:
                self._theme = "dark"
            self._palette_key = cfg.get("palette", "mocha")
            if self._palette_key not in PALETTE_SETS:
                self._palette_key = "mocha"
            self._pal = make_palette(self._theme, self._palette_key)
            self._page = "launch"
            set_switch_palette(self._pal)  # цвета тумблеров под тему
            self.setAcceptDrops(True)  # папку проекта можно просто перетащить в окно
            self._build_ui()
            self._apply_sizes(self._ext_sizes, persist=False)
            self._restore()
            self._apply_folder_auto()  # #5: молча включить набор для авто-папки
            self._maybe_auto_suggest()  # #1: если папка подставилась из «недавних»
            self._update_summary()
            # Первая раскладка карточек-сетки, когда окно получит реальную ширину.
            QTimer.singleShot(0, self._relayout_cards)
            if background:  # тесты создают окно без фоновых потоков и сети
                self._start_ext_load()
                self._probe_memory()
                self._start_size_probe()
                self._start_update_check()  # #8
                self._scan_path_badge()
            geo = cfg.get("geometry")
            if geo:  # запоминаем размер и позицию окна между запусками
                try:
                    self.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))
                except Exception:
                    pass

        def _update_theme_btn(self):
            # Показываем текущую тему; действие поясняет tooltip.
            self.theme_btn.setText(_("Светлая") if self._theme == "light" else _("Тёмная"))

        def _toggle_theme(self):
            self._set_theme("light" if self._theme == "dark" else "dark")

        def _set_theme(self, theme: str):
            if theme not in PALETTES or theme == self._theme:
                return
            self._theme = theme
            cfg["theme"] = theme
            self._apply_look()

        def _set_palette(self, key: str):
            if key not in PALETTE_SETS:
                return
            self._palette_key = key
            cfg["palette"] = key
            self._apply_look()

        def _apply_look(self):
            """Перекрасить окно под тему и палитру без пересборки."""
            self._pal = make_palette(self._theme, self._palette_key)
            set_switch_palette(self._pal)  # тумблеры перекрашиваем под новую тему
            app = QApplication.instance()
            if app is not None:
                app.setStyleSheet(build_qss(self._pal))
            apply_titlebar(self, self._theme == "dark")
            self._update_theme_btn()
            if hasattr(self, "banner"):
                self.banner.set_palette(self._palette_key, self._pal["bg"], self._pal["accent"])
            for key, card in getattr(self, "_pal_cards", {}).items():
                card.set_selected(key == self._palette_key)
            seg = getattr(self, "theme_seg", None)
            if seg is not None and self._theme in seg.buttons:
                seg.buttons[self._theme].setChecked(True)
            for w in self.findChildren(ToggleSwitch):  # перерисовать тумблеры
                w.update()
            save_config(cfg)

        # --- реальный вес стеков: размер на диске -------------------------
        def _start_size_probe(self):
            """Посчитать, сколько занимают расширения на диске. В фоне: обход
            папки расширений (десятки тысяч файлов) стоит 1-2 с."""
            if getattr(self, "_sizes", None) is not None and self._sizes.isRunning():
                return
            self._sizes = SizeProbe(code_cli)
            self._sizes.measured.connect(lambda d: self._apply_sizes(d))
            self._sizes.start()

        def _apply_sizes(self, sizes: dict, persist: bool = True):
            """Показать размер стека на карточках и запомнить в конфиге.

            Число твёрдое (это байты на диске, а не прикидка), поэтому его видно
            сразу и без единого запуска редактора: заметно, какие стеки дорогие."""
            if not sizes:
                return
            self._ext_sizes = dict(sizes)
            per_stack = _w.stack_disk_mb(ext_index, self._ext_sizes, self.installed)
            for key, card in self.cat_checks.items():
                card.set_disk_mb(per_stack.get(key, 0))
            # Бейдж нагрузки стал длиннее (к «тяжёлый» дописался размер) — заметка
            # рядом переносится на лишнюю строку. Без пересчёта ряды остаются
            # прежней высоты, и текст обрезается до первого resize окна.
            if hasattr(self, "_cards_flow"):
                self._cards_flow.invalidate()
                self.cards_host.updateGeometry()
            if persist:
                cfg["ext_sizes"] = {"n": len(self.installed), "sizes": self._ext_sizes}
                save_config(cfg)

        # --- честная стоимость расширений: code --status ------------------
        def _measure_extensions(self):
            """Спросить у самого VS Code, сколько сейчас едят его процессы, и
            показать разбор «редактор против расширений».

            Это единственный способ увидеть цену расширений отдельно от цены
            редактора: VS Code сам подписывает свой extensionHost, а мы просто
            читаем его ответ. Остальные числа в окне — оценки, это — факт."""
            if getattr(self, "_status", None) is not None and self._status.isRunning():
                return
            self.ext_measure_btn.setEnabled(False)
            self.ext_measure_btn.setText(_("Замеряю…"))
            self._status = StatusProbe(code_cli, ext_index)
            self._status.measured.connect(self._on_ext_status)
            self._status.start()

        def _on_ext_status(self, data: dict):
            self.ext_measure_btn.setEnabled(True)
            self.ext_measure_btn.setText(_("Замерить расширения"))
            if not data or not (data.get("processes") or data.get("tree")):
                QMessageBox.information(
                    self,
                    _("Замер расширений"),
                    _(
                        "VS Code не отвечает на --status. Он запущен? Замер работает "
                        "только при открытом редакторе."
                    ),
                )
                return
            self._show_ext_report(data)

        def _show_ext_report(self, data: dict):
            unit = _("МБ")
            lines: list[str] = []
            tree = data.get("tree") or {}
            titles = {k: cat_title(c, k) for k, c in cats.get("categories", {}).items()}
            titles["always_on"] = cat_title(cats.get("always_on", {}), _("Ядро"))
            if tree:
                lines += [
                    _("Дерево процессов VS Code: {mb} МБ").format(mb=tree["total_mb"]),
                    _("  расширения и их языковые серверы: {mb} МБ").format(mb=tree["ext_mb"]),
                    _("  сам редактор (окно, хост расширений, GPU): {mb} МБ").format(
                        mb=tree["editor_mb"]
                    ),
                    "",
                    _("Память по стекам (отдельные процессы расширений):"),
                ]
                for key, mb in tree["stacks"].items():
                    lines.append(f"  {mb:>6} {unit}  {titles.get(key, key)}")
                lines += ["", _("По расширениям:")]
                for ext_id, mb in tree["ext"].items():
                    lines.append(f"  {mb:>6} {unit}  {ext_id}")
                if tree["other"]:
                    lines += ["", _("Не входит в замер (терминал и запущенное в нём):")]
                    for name, mb in tree["other"]:
                        lines.append(f"  {mb:>6} {unit}  {name}")
                lines.append("")
            if data.get("processes"):
                total = data["total_mb"]
                ext_mb = data["extension_mb"]
                share = round(ext_mb * 100 / total) if total else 0
                lines += [
                    _("Ответ code --status: всего {mb} МБ").format(mb=total),
                    _(
                        "  из них расширения (extensionHost и языковые серверы): {mb} МБ ({share}%)"
                    ).format(mb=ext_mb, share=share),
                    _("  сам редактор (окно, GPU, терминал, поиск): {mb} МБ").format(
                        mb=data["editor_mb"]
                    ),
                    "",
                    _("Процессы:"),
                ]
                for r in data["processes"]:
                    lines.append(f"  {r['mb']:>6} {unit}  {' ' * r['depth']}{r['name']}")
            per_stack = _w.stack_disk_mb(ext_index, self._ext_sizes, self.installed)
            if per_stack:
                lines += ["", _("Размер стеков на диске (установленное):")]
                for key, mb in sorted(per_stack.items(), key=lambda kv: -kv[1]):
                    lines.append(f"  {mb:>6} {unit}  {titles.get(key, key)}")
            if tree and tree["stacks"]:
                top_key, top_mb = next(iter(tree["stacks"].items()))
                subtitle = _(
                    "Больше всех в отдельных процессах держит «{title}»: "
                    "{mb} МБ. Эта память уходит, когда стек выключен."
                ).format(title=titles.get(top_key, top_key), mb=top_mb)
            elif data.get("processes"):
                subtitle = _(
                    "Расширения занимают {mb} МБ — это {share}% памяти VS Code. "
                    "Именно эта часть и уходит, когда стек выключен."
                ).format(
                    mb=data["extension_mb"],
                    share=round(data["extension_mb"] * 100 / data["total_mb"])
                    if data["total_mb"]
                    else 0,
                )
            else:
                subtitle = ""
            self._text_dialog(_("Замер расширений"), subtitle, "\n".join(lines))

        def _open_cleanup(self):
            from .gui_cleanup import CleanupDialog

            CleanupDialog(self, code_cli).exec()

        def _open_cpp(self, tab: str = "install", preselect: str = ""):
            """Открыть страницу C / C++ (установка, проверка, проект)."""
            self._goto("cpp")
            center = getattr(self, "cpp_center", None)
            if center is not None:
                center.open_tab(tab, preselect)

        def _text_dialog(self, title: str, subtitle: str, text: str):
            """Диалог «заголовок + пояснение + текстовый блок + копировать».
            Три диалога окна отличались только текстом, теперь у них одна
            реализация — и одинаковое поведение кнопок."""
            dlg = QDialog(self)
            dlg.setWindowTitle(title)
            dlg.resize(620, 600)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(18, 18, 18, 16)
            lay.setSpacing(12)
            ttl = QLabel(title)
            ttl.setObjectName("Title")
            lay.addWidget(ttl)
            if subtitle:
                note = _wrap(QLabel(subtitle))
                note.setObjectName("Subtitle")
                lay.addWidget(note)
            lay.addWidget(_hline())
            box = QPlainTextEdit()
            box.setObjectName("Log")
            box.setReadOnly(True)
            box.setMaximumHeight(16777215)
            box.setPlainText(text)
            lay.addWidget(box, 1)
            bar = QHBoxLayout()
            copy = QPushButton(_("Копировать"))
            copy.setObjectName("Ghost")
            copy.setEnabled(bool(text))
            copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
            bar.addWidget(copy)
            bar.addStretch()
            close = QPushButton(_("Закрыть"))
            close.setObjectName("Accent")
            close.clicked.connect(dlg.accept)
            bar.addWidget(close)
            lay.addLayout(bar)
            dlg.exec()

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
                self.mem_lbl.setText(_("VS Code сейчас: {mb} МБ, {n} процессов").format(mb=mb, n=n))
                self.mem_lbl.setToolTip(
                    _(
                        "Приватная память всех процессов VS Code "
                        "(неразделяемая — именно она освобождается при закрытии). "
                        "Замер нативный, без запуска PowerShell."
                    )
                )
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
                self,
                _("Установка VS Code"),
                _("Сейчас: {cur}\n\nВыбери установку:").format(cur=cur),
                items,
                0,
                False,
            )
            if not ok:
                return
            new_path = None  # None -> авто (сброс)
            if choice == BROWSE:
                picked, _filt = QFileDialog.getOpenFileName(
                    self,
                    _("Выбери code.cmd или Code.exe"),
                    "",
                    _("VS Code CLI (code.cmd code-insiders.cmd Code.exe);;Все файлы (*.*)"),
                )
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

            code_cli = resolve_code_cli(cfg)  # переопределяем замыкание
            self._dep_map = None  # #1: другой VS Code — другой набор
            self.b_run.setEnabled(bool(code_cli))
            self.log.appendPlainText(_("VS Code CLI: {cli}").format(cli=code_cli or _("не найден")))
            self._loaded = False
            self._start_ext_load()  # перечитать расширения нового VS Code
            self._probe_memory()  # и его память

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
                    _("Доступна новая версия {ver} — скачать и установить").format(ver=ver)
                )
            else:
                self.update_bar.setText(
                    _("Доступна новая версия {ver} — открыть страницу релизов").format(ver=ver)
                )
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
            if (
                QMessageBox.question(
                    self,
                    _("Обновление"),
                    _("Скачать и установить {ver}? Лаунчер закроется и обновится сам.").format(
                        ver=tag
                    ),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                != QMessageBox.StandardButton.Yes
            ):
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
                    _("Скачиваю обновление… {mb} МБ").format(mb=got // (1024 * 1024))
                )

        def _on_dl_done(self, ok: bool, msg: str, dest: str):
            self.update_bar.setEnabled(True)
            tag = getattr(self, "_update_tag", "")
            self.update_bar.setText(
                _("Доступна новая версия {ver} — скачать и установить").format(ver=tag)
            )
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
                QMessageBox.warning(
                    self, _("Обновление"), _("Не удалось подготовить обновление: {e}").format(e=e)
                )
                return
            if (
                QMessageBox.question(
                    self,
                    _("Готово"),
                    msg + "\n\n" + _("Перезапустить сейчас, чтобы применить обновление?"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                != QMessageBox.StandardButton.Yes
            ):
                return
            DETACHED = 0x00000008 | 0x00000200
            try:
                subprocess.Popen(
                    [os.environ.get("COMSPEC", "cmd.exe"), "/c", str(bat_path)],
                    creationflags=DETACHED,
                    close_fds=True,
                )
            except Exception as e:
                QMessageBox.critical(self, _("Обновление"), str(e))
                return
            QApplication.quit()

        # --- автоопределение стеков по папке (#1) -------------------------
        def _sync_auto_cb(self, on: bool):
            """Отразить авто-статус папки в чекбоксе, не дёргая обработчик."""
            if not hasattr(self, "auto_cb"):
                return
            self.auto_cb.blockSignals(True)
            self.auto_cb.setChecked(on)
            self.auto_cb.blockSignals(False)

        def _apply_folder_auto(self) -> bool:
            """#5: если текущая папка помечена авто и для неё есть набор —
            включить эти стеки молча. True, если что-то применили."""
            folder = self.folder_edit.text().strip()
            auto = folder_auto_stacks(cfg, folder)
            if not auto:
                return False
            available = set(cats.get("categories", {}))
            keys = sorted(set(auto) & available)
            for k in keys:
                card = self.cat_checks.get(k)
                if card is not None:
                    card.setChecked(True)
            if keys:
                self.log.appendPlainText(
                    _("Авто-набор для папки: {stacks}").format(
                        stacks=", ".join(cat_title(cats["categories"][k], k) for k in keys)
                    )
                )
            self._sync_auto_cb(True)
            return True

        def _toggle_folder_auto(self, on: bool):
            """Пользователь сам переключил «всегда для этой папки»."""
            folder = self.folder_edit.text().strip()
            if not folder:
                return
            set_folder_auto(cfg, folder, on)
            if on and not self._bare():
                remember_folder_stacks(cfg, folder, self._selected())
            save_config(cfg)

        @staticmethod
        def _scan_root(target: str) -> str:
            """Что сканировать автодетектом. Для .code-workspace — папку, где
            лежит сам файл: VS Code открывает такой файл как проект, а детект
            по файлу дал бы пусто и подсказка молча не появлялась бы."""
            t = (target or "").strip()
            if not t:
                return ""
            try:
                path = Path(t)
                return str(path.parent) if path.is_file() else t
            except Exception:
                return t

        def _suggest_for_folder(self, folder: str):
            """Определить тип проекта и, если есть что предложить, показать
            строку-подсказку. Предлагаем только стеки с установленными
            расширениями, которые ещё не отмечены."""
            folder = self._scan_root(folder) if folder else folder
            self._suggested_keys = set()
            self.suggest_bar.setVisible(False)
            self._suggest_toolchains(folder)
            if not folder:
                self._sync_auto_cb(False)
                return
            # #5: авто-папка — включаем набор молча и показываем инфо-строку
            # (без кнопки «Включить»), где можно снять авто-режим.
            if folder_auto_stacks(cfg, folder) is not None:
                self._apply_folder_auto()
                self.suggest_lbl.setText(_("Авто-набор для этой папки включён."))
                self._sug_apply.setVisible(False)
                self.suggest_bar.setVisible(True)
                return
            self._sug_apply.setVisible(True)
            self._sync_auto_cb(False)
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
            titles = ", ".join(sorted(cat_title(cats["categories"][k], k) for k in useful))
            self.suggest_lbl.setText(
                _("Похоже на проект: {stacks}. Включить эти стеки?").format(stacks=titles)
            )
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
            cpp_missing = [k for k in missing if k == "cpp" or k.startswith("cpp_")]
            if cpp_missing:
                self._tool_action = lambda: self._open_cpp(preselect="install:" + cpp_missing[0])
                self.tool_open.setText(_("Выбрать и поставить"))
                self.tool_lbl.setText(
                    _(
                        "Это C/C++-проект, а подходящего инструмента нет: {tools}. "
                        "Открыть C++-центр?"
                    ).format(
                        tools=", ".join(
                            _tc.get_toolchain(k).title for k in cpp_missing if _tc.get_toolchain(k)
                        )
                    )
                )
                self.tool_bar.setVisible(True)
                return
            if not missing:
                self._suggest_cpp_setup(folder)
                return
            self._tool_action = None
            self.tool_open.setText(_("Поставить"))
            self._tool_target = missing[0]
            titles = ", ".join(_tc.get_toolchain(k).title for k in missing if _tc.get_toolchain(k))
            self.tool_lbl.setText(
                _(
                    "Для этого проекта не хватает инструментов: {tools}. Установить компилятор/SDK?"
                ).format(tools=titles)
            )
            self.tool_bar.setVisible(True)

        def _suggest_cpp_setup(self, folder):
            """C/C++-проект без настроек VS Code — предложить настроить."""
            try:
                from .detect import cpp_project_hints

                h = cpp_project_hints(folder)
            except Exception:
                return
            if not h.get("is_cpp") or h.get("has_vscode_cfg") or h.get("has_clangd_cfg"):
                return
            self._tool_action = lambda: self._open_cpp(tab="project")
            self.tool_open.setText(_("Настроить"))
            self.tool_lbl.setText(
                _(
                    "C/C++-проект без настроек VS Code: сборка (Ctrl+Shift+B), отладка (F5) "
                    "и подсказки не настроены. Сгенерировать их под ваш компилятор?"
                )
            )
            self.tool_bar.setVisible(True)

        def _tool_bar_clicked(self):
            if getattr(self, "_tool_action", None):
                self.tool_bar.setVisible(False)
                self._tool_action()
            else:
                self._show_toolchains(target=self._tool_target)

        def _open_tools_page(self, target=None):
            self._goto("tools")
            scroll_to = getattr(self, "_tools_scroll_to", None)
            if target and scroll_to is not None:
                QTimer.singleShot(0, lambda: scroll_to(target))

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
            titles = ", ".join(
                sorted(cat_title(cats["categories"][k], k) for k in self._suggested_keys)
            )
            self.log.appendPlainText(
                _("Включены стеки по типу проекта: {stacks}").format(stacks=titles)
            )
            folder = self.folder_edit.text().strip()
            if folder and is_folder_auto(cfg, folder) and not self._bare():
                remember_folder_stacks(cfg, folder, self._selected())
                save_config(cfg)
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
            cfg["overrides"] = {
                "disable": sorted(self._force_disable),
                "enable": sorted(self._force_enable),
            }
            save_config(cfg)
            self._refresh_override_chip()
            self._update_summary()

        # --- переключение языка (#7) --------------------------------------
        def ui_state(self) -> dict:
            """Снимок того, что человек НАБРАЛ в окне, но ещё не запускал.

            Текст виджетов задаётся при сборке, поэтому смена языка пересобирает
            окно — и раньше при этом терялось всё несохранённое: галочки стеков
            откатывались к последнему ЗАПУЩЕННОМУ набору, поиск и фильтр
            сбрасывались. Снимок переносит состояние в новое окно."""
            return {
                "selected": sorted(self._selected()),
                "folder": self.folder_edit.text(),
                "profile": self.profile_edit.text(),
                "search": self.search_edit.text(),
                "inst_filter": getattr(self, "_inst_filter", "all"),
                "kill": self.kill_cb.isChecked(),
                "soft": self.soft_cb.isChecked(),
                "new_window": self.newwin_cb.isChecked(),
                "gpu_off": self.gpu_cb.isChecked(),
                "bare": self.bare_cb.isChecked(),
                "scroll": (
                    self._scroll.verticalScrollBar().value() if hasattr(self, "_scroll") else 0
                ),
            }

        def apply_ui_state(self, st: dict):
            """Вернуть снимок ui_state в свежесобранное окно."""
            if not st:
                return
            keys = set(st.get("selected", []))
            for k, card in self.cat_checks.items():
                card.setChecked(k in keys)
            self.folder_edit.setText(st.get("folder", ""))
            self.profile_edit.setText(st.get("profile", ""))
            self.kill_cb.setChecked(bool(st.get("kill", True)))
            self.soft_cb.setChecked(bool(st.get("soft", False)))
            self.newwin_cb.setChecked(bool(st.get("new_window", True)))
            self.gpu_cb.setChecked(bool(st.get("gpu_off", False)))
            self.bare_cb.setChecked(bool(st.get("bare", False)))
            self._set_inst_filter(st.get("inst_filter", "all"))
            self.search_edit.setText(st.get("search", ""))
            self._update_summary()
            if st.get("scroll") and hasattr(self, "_scroll"):
                QTimer.singleShot(
                    0, lambda: self._scroll.verticalScrollBar().setValue(st["scroll"])
                )

        def _switch_language(self):
            self._persist()  # сохранить выбор/опции/папку перед пересборкой окна
            new = "ru" if get_language() == "en" else "en"
            set_language(new)
            cfg["lang"] = new
            save_config(cfg)
            # Пересобрать окно на новом языке, перенеся в него всё несохранённое.
            _lang_switch["fn"](self.ui_state())

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
            self._dep_map = None  # #1: набор расширений сменился — перечитать граф
            for key, card in self.cat_checks.items():
                # Считаем через ext_index — так в счётчик карточки попадают и
                # расширения, разложенные мастером (#6, оверлей), а не только
                # перечисленные в categories.json напрямую.
                card.set_installed(sum(1 for e in ids if ext_index.get(e.lower()) == key))
            self._refresh_unknown()
            # Размеры считаны для прежнего набора — пересчитаем по стекам с
            # новым списком установленного (свежий замер придёт из SizeProbe).
            if self._ext_sizes:
                self._apply_sizes(self._ext_sizes, persist=False)
            # Набор расширений изменился (что-то поставили/удалили) — размеры
            # на диске устарели, перечитываем их в фоне.
            cached = cfg.get("ext_sizes", {})
            if not isinstance(cached, dict) or cached.get("n") != len(ids):
                if getattr(self, "_sizes", None) is not None or self._ext_sizes:
                    self._start_size_probe()
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
                self.log.appendPlainText(_("Не удалось получить список расширений."))
            if ids:
                cfg["installed_cache"] = {"ids": ids, "source": source}
                save_config(cfg)
                self.log.appendPlainText(
                    _("Расширений: {n} (источник: {src}).").format(n=len(ids), src=source)
                )
            self._update_summary()
            self._maybe_auto_suggest()  # #1: кэш был пуст — подсказка после загрузки

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
            """Окно-оболочка: шапка, навигация слева, страницы справа.

            Раньше всё жило одной длинной лентой с рядами кнопок. Теперь каждое
            дело — своя страница: «Запуск» (стеки и кнопка запуска), «C / C++»,
            «Языки», «Расширения», «Обслуживание», «Настройки». Редкие действия
            убраны в меню «⋯»."""
            root = QVBoxLayout(self)
            root.setContentsMargins(0, 0, 0, 0)
            root.setSpacing(0)
            self._build_topbar(root)
            body = QHBoxLayout()
            body.setContentsMargins(0, 0, 0, 0)
            body.setSpacing(0)
            self.nav = NavRail()
            self.pages = QStackedWidget()
            self._page_of: dict[str, QWidget] = {}
            self._page_builders = {}
            nav_items = (
                (
                    "launch",
                    _("Запуск"),
                    "launch",
                    _("Стеки расширений, папка проекта и запуск VS Code"),
                ),
                (
                    "cpp",
                    "C / C++",
                    "cpp",
                    _("Компилятор, подсказки, отладка, проверка и настройка проекта"),
                ),
                ("tools", _("Языки"), "tools", _("Компиляторы и SDK других языков через winget")),
                (
                    "ext",
                    _("Расширения"),
                    "ext",
                    _("Замер памяти, незнакомые расширения, исключения, settings.json"),
                ),
                (
                    "clean",
                    _("Обслуживание"),
                    "clean",
                    _("Уборка мусора VS Code, проверка PATH, журнал"),
                ),
            )
            for key, text, ic, tip in nav_items:
                self.nav.add(key, text, ic, tip)
            self.nav.add(
                "settings",
                _("Настройки"),
                "settings",
                _("Вид, палитра, язык и параметры запуска"),
                bottom=True,
            )
            self.nav.page_changed.connect(self._goto)
            body.addWidget(self.nav)
            body.addWidget(self.pages, 1)
            root.addLayout(body, 1)

            # Страницы: «Запуск», «Расширения», «Обслуживание» и «Настройки»
            # собираем сразу (на них живут виджеты, с которыми работает остальной
            # код), C++ и «Языки» — лениво, при первом открытии: они медленные.
            self._add_page("launch", self._build_launch_page())
            self._add_page("cpp", None, self._build_cpp_page)
            self._add_page("tools", None, self._build_tools_page)
            self._add_page("ext", self._build_ext_page())
            self._add_page("clean", self._build_maint_page())
            self._add_page("settings", self._build_settings_page())
            self._goto("launch")

        def _add_page(self, key, widget, builder=None):
            holder = QWidget()
            lay = QVBoxLayout(holder)
            lay.setContentsMargins(0, 0, 0, 0)
            if widget is not None:
                lay.addWidget(widget)
            else:
                self._page_builders[key] = builder
            self._page_of[key] = holder
            self.pages.addWidget(holder)

        def _goto(self, key: str):
            """Открыть страницу; медленные собираются при первом заходе."""
            holder = self._page_of.get(key)
            if holder is None:
                return
            builder = self._page_builders.pop(key, None)
            if builder is not None:
                try:
                    holder.layout().addWidget(builder())
                except Exception:
                    log.exception("Страница %s не собралась", key)
            self.pages.setCurrentWidget(holder)
            if key == "launch":
                QTimer.singleShot(0, self._relayout_cards)
            self.nav.select(key)
            self._page = key

        def _page_scroll(self, header: QWidget) -> tuple[QScrollArea, QVBoxLayout]:
            """Прокручиваемая страница с заголовком; возвращает (скролл, раскладку)."""
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.Shape.NoFrame)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            inner = QWidget()
            inner.setObjectName("CatInner")
            v = QVBoxLayout(inner)
            v.setContentsMargins(20, 16, 18, 16)
            v.setSpacing(12)
            v.addWidget(header)
            sc.setWidget(inner)
            return sc, v

        # --- шапка -------------------------------------------------------
        def _build_topbar(self, root):
            """Шапка: значок, название, живой замер памяти и три маленькие
            кнопки (обновить замер, язык, тема). Всё остальное — в навигации."""
            top = QWidget()
            top.setObjectName("TopBar")
            top.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            hl = QHBoxLayout(top)
            hl.setContentsMargins(14, 12, 14, 12)
            hl.setSpacing(10)
            tile = QLabel()
            tile.setObjectName("AppTile")
            tile.setFixedSize(42, 42)
            tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if LOGO_FILE.exists():
                tile.setPixmap(
                    QPixmap(str(LOGO_FILE)).scaled(
                        30,
                        30,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            hl.addWidget(tile)
            htext = QVBoxLayout()
            htext.setSpacing(0)
            title = QLabel("VS Code Launcher")
            title.setObjectName("AppTitle")
            self.mem_lbl = QLabel(_("VS Code сейчас: замеряю…"))
            self.mem_lbl.setObjectName("AppSub")
            htext.addWidget(title)
            htext.addWidget(self.mem_lbl)
            hl.addLayout(htext, 1)
            mem_ref = QPushButton(_("Обновить"))
            mem_ref.setObjectName("HBtn")
            mem_ref.setCursor(Qt.CursorShape.PointingHandCursor)
            mem_ref.setToolTip(_("Обновить замер памяти запущенного VS Code"))
            mem_ref.clicked.connect(self._probe_memory)
            self.lang_btn = QPushButton("EN" if get_language() == "ru" else "RU")
            self.lang_btn.setObjectName("HBtn")
            self.lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.lang_btn.setToolTip(_("Переключить язык интерфейса (RU/EN)"))
            self.lang_btn.clicked.connect(self._switch_language)
            self.theme_btn = QPushButton()
            self.theme_btn.setObjectName("HBtn")
            self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.theme_btn.setToolTip(_("Переключить светлую/тёмную тему"))
            self.theme_btn.clicked.connect(self._toggle_theme)
            self._update_theme_btn()
            for b in (mem_ref, self.lang_btn, self.theme_btn):
                hl.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
            root.addWidget(top)

            # Баннер новой версии и предупреждения — под шапкой, на всю ширину.
            warn_box = QWidget()
            wl = QVBoxLayout(warn_box)
            wl.setContentsMargins(14, 0, 14, 0)
            wl.setSpacing(6)
            self.update_bar = QPushButton()
            self.update_bar.setObjectName("Accent")
            self.update_bar.setCursor(Qt.CursorShape.PointingHandCursor)
            self.update_bar.setVisible(False)
            self.update_bar.clicked.connect(self._on_update_clicked)
            wl.addWidget(self.update_bar)
            has_warn = False
            if not code_cli:
                warn = _wrap(QLabel(_("Не найден CLI VS Code (code.cmd). Добавь его в PATH.")))
                warn.setObjectName("Warn")
                wl.addWidget(warn)
                has_warn = True
            if cats_err:
                cwarn = _wrap(QLabel(cats_err))
                cwarn.setObjectName("Warn")
                wl.addWidget(cwarn)
                has_warn = True
            if has_warn:
                wl.setContentsMargins(14, 10, 14, 4)
            root.addWidget(warn_box)

        # --- страница «Запуск» ---------------------------------------------
        def _build_launch_page(self) -> QWidget:
            page = QWidget()
            pv = QVBoxLayout(page)
            pv.setContentsMargins(0, 0, 0, 0)
            pv.setSpacing(0)
            scroll, cv = self._page_scroll(
                page_header(
                    _("Запуск"),
                    _(
                        "Отметь стеки на сегодня — остальные расширения не загрузятся, и "
                        "память останется свободной. Ничего не удаляется."
                    ),
                )
            )
            self._scroll = scroll

            # Проект и пресет — одна секция, по строке на каждое.
            sec = Section(_("Проект и пресет"))
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(8)
            lbl_f = QLabel(_("Папка"))
            lbl_f.setObjectName("CatNote")
            grid.addWidget(lbl_f, 0, 0)
            self.folder_edit = QLineEdit()
            self.folder_edit.setPlaceholderText(
                _("путь к проекту или .code-workspace — можно перетащить сюда")
            )
            self.folder_edit.editingFinished.connect(
                lambda: self._suggest_for_folder(self.folder_edit.text().strip())
            )
            grid.addWidget(self.folder_edit, 0, 1)
            # Недавние папки: скрытый список для совместимости (_pick_recent) и
            # меню у кнопки «Обзор».
            self.recent_box = QComboBox()
            self.recent_box.addItem(_("— недавние папки —"), "")
            for p in cfg.get("recent_folders", []):
                self.recent_box.addItem(p, p)
            self.recent_box.activated.connect(self._pick_recent)
            self.recent_box.setVisible(False)
            browse_items = [
                (_("Выбрать папку…"), self._browse),
                (_("Открыть рабочую область (.code-workspace)…"), self._browse_workspace),
            ]
            recent = cfg.get("recent_folders", [])
            if recent:
                browse_items.append(None)
                for p in recent[:8]:
                    browse_items.append((p, lambda p=p: self._use_recent(p)))
            b_browse = menu_button(
                browse_items,
                tip=_(
                    "Выбрать папку, рабочую область или недавний проект. Папку можно и "
                    "просто перетащить в окно."
                ),
                text=_("Обзор…"),
                obj="HBtn",
            )
            grid.addWidget(b_browse, 0, 2)
            lbl_p = QLabel(_("Пресет"))
            lbl_p.setObjectName("CatNote")
            grid.addWidget(lbl_p, 1, 0)
            self.preset_box = QComboBox()
            self.preset_box.setMinimumWidth(180)
            self._reload_presets()
            self.preset_box.activated.connect(self._apply_preset)
            grid.addWidget(self.preset_box, 1, 1)
            preset_menu = menu_button(
                [
                    (_("Сохранить текущий выбор как пресет…"), self._save_preset),
                    (_("Удалить выбранный пресет"), self._delete_preset),
                    None,
                    (_("Экспорт пресетов в файл…"), self._export_presets),
                    (_("Импорт пресетов из файла…"), self._import_presets),
                    None,
                    (
                        _("Ярлык .cmd для пресета…"),
                        self._make_shortcut,
                        _("Файл, открывающий VS Code с пресетом двойным кликом"),
                    ),
                    (
                        _("Экспорт профиля VS Code…"),
                        self._export_profile,
                        _("Нативный профиль .code-profile ровно с включёнными расширениями"),
                    ),
                ],
                tip=_("Пресеты: сохранить, удалить, экспорт, ярлык, профиль"),
                text=_("Пресеты ▾"),
                obj="HBtn",
            )
            grid.addWidget(preset_menu, 1, 2)
            grid.setColumnStretch(1, 1)
            sec.body.addLayout(grid)
            sec.body.addWidget(self.recent_box)

            # Подсказки по папке: автодетект стеков и недостающие инструменты.
            self.suggest_bar = QFrame()
            self.suggest_bar.setObjectName("CatCard")
            sbl = QHBoxLayout(self.suggest_bar)
            sbl.setContentsMargins(12, 8, 12, 8)
            sbl.setSpacing(8)
            hint_ic = QLabel()
            pm = shell_icon("hint", 24)
            if pm is not None:
                hint_ic.setPixmap(pm)
            sbl.addWidget(hint_ic)
            self.suggest_lbl = _wrap(QLabel())
            self.suggest_lbl.setObjectName("CatNote")
            sbl.addWidget(self.suggest_lbl, 1)
            self.auto_cb = QCheckBox(_("всегда для этой папки"))
            self.auto_cb.setToolTip(
                _("Запоминать набор для этой папки и включать его при выборе без подсказки")
            )
            self.auto_cb.toggled.connect(self._toggle_folder_auto)
            sbl.addWidget(self.auto_cb)
            self._sug_apply = QPushButton(_("Включить"))
            self._sug_apply.setObjectName("HBtn")
            self._sug_apply.setCursor(Qt.CursorShape.PointingHandCursor)
            self._sug_apply.clicked.connect(self._apply_suggestion)
            sug_hide = QPushButton("×")
            sug_hide.setObjectName("Round")
            sug_hide.setToolTip(_("Скрыть"))
            sug_hide.clicked.connect(self._dismiss_suggestion)
            sbl.addWidget(self._sug_apply)
            sbl.addWidget(sug_hide)
            self.suggest_bar.setVisible(False)
            sec.body.addWidget(self.suggest_bar)

            self.tool_bar = QFrame()
            self.tool_bar.setObjectName("CatCard")
            tbl = QHBoxLayout(self.tool_bar)
            tbl.setContentsMargins(12, 8, 12, 8)
            tbl.setSpacing(8)
            tool_ic = QLabel()
            pm = shell_icon("steps", 24)
            if pm is not None:
                tool_ic.setPixmap(pm)
            tbl.addWidget(tool_ic)
            self.tool_lbl = _wrap(QLabel())
            self.tool_lbl.setObjectName("CatNote")
            tbl.addWidget(self.tool_lbl, 1)
            self._tool_target = None
            tool_open = QPushButton(_("Поставить"))
            tool_open.setObjectName("HBtn")
            tool_open.setCursor(Qt.CursorShape.PointingHandCursor)
            tool_open.clicked.connect(self._tool_bar_clicked)
            self.tool_open = tool_open
            self._tool_action = None
            tool_hide = QPushButton("×")
            tool_hide.setObjectName("Round")
            tool_hide.setToolTip(_("Скрыть"))
            tool_hide.clicked.connect(lambda: self.tool_bar.setVisible(False))
            tbl.addWidget(tool_open)
            tbl.addWidget(tool_hide)
            self.tool_bar.setVisible(False)
            sec.body.addWidget(self.tool_bar)
            cv.addWidget(sec)

            # Стеки.
            self.sel_count = QLabel()
            self.sel_count.setObjectName("SelCount")
            self.sel_count.setToolTip(_("Сколько стеков сейчас отмечено из всех."))
            trail = QWidget()
            tl = QHBoxLayout(trail)
            tl.setContentsMargins(0, 0, 0, 0)
            tl.setSpacing(6)
            tl.addWidget(self.sel_count)
            tl.addWidget(
                menu_button(
                    [
                        (_("Включить все (с учётом поиска)"), lambda: self._set_all(True)),
                        (_("Оставить минимум (только ядро)"), lambda: self._set_all(False)),
                    ],
                    tip=_("Быстрый выбор стеков"),
                )
            )
            stacks = Section(_("Стеки расширений"), trailing=trail)
            stacks.setToolTip(
                _(
                    "Полоска слева у карточки — нагрузка на память: красная тяжёлый, "
                    "жёлтая средний, зелёная лёгкий. Снятые галочки не удаляют расширения — "
                    "они просто не грузятся в этот запуск. Кнопка «›» — что внутри стека."
                )
            )
            srow = QHBoxLayout()
            srow.setSpacing(8)
            self.search_edit = QLineEdit()
            self.search_edit.setPlaceholderText(_("Поиск стека или расширения…"))
            self.search_edit.setClearButtonEnabled(True)
            self.search_edit.setToolTip(
                _("Фильтрует карточки по названию, заметке и id расширений. На выбор не влияет.")
            )
            self.search_edit.textChanged.connect(self._filter_cards)
            srow.addWidget(self.search_edit, 1)
            seg = QFrame()
            seg.setObjectName("Segmented")
            sl = QHBoxLayout(seg)
            sl.setContentsMargins(3, 3, 3, 3)
            sl.setSpacing(3)
            self._inst_filter = "all"
            self.seg_btns = {}
            for fkey, flabel in (
                ("all", _("Все")),
                ("installed", _("Установленные")),
                ("missing", _("Не установленные")),
            ):
                sb = QPushButton(flabel)
                sb.setObjectName("SegBtn")
                sb.setCheckable(True)
                sb.setCursor(Qt.CursorShape.PointingHandCursor)
                sb.clicked.connect(lambda _=False, k=fkey: self._set_inst_filter(k))
                sl.addWidget(sb)
                self.seg_btns[fkey] = sb
            self.seg_btns["all"].setChecked(True)
            srow.addWidget(seg)
            stacks.body.addLayout(srow)
            self.search_status = QLabel()
            self.search_status.setObjectName("CatNote")
            stacks.body.addWidget(self.search_status)

            installed_set = set(self.installed)
            weight_rank = {"heavy": 0, "medium": 1, "light": 2}
            ordered = sorted(
                cats.get("categories", {}).items(),
                key=lambda kv: (
                    0 if any(e.lower() in installed_set for e in kv[1]["extensions"]) else 1,
                    weight_rank.get(WEIGHT.get(kv[0], "light"), 2),
                    cat_title(kv[1], kv[0]).lower(),
                ),
            )
            self.cards_host = QWidget()
            self.cards_host.setObjectName("CatInner")
            self._cards_flow = FlowLayout(self.cards_host, margin=0, spacing=10)
            for key, cat in ordered:
                exts = cat["extensions"]
                inst = sum(1 for e in exts if e.lower() in installed_set)
                card = CategoryCard(
                    key,
                    cat,
                    inst,
                    len(exts),
                    self._update_summary,
                    lambda _=False, k=key, c=cat: show_details(self, k, c, set(self.installed)),
                )
                self.cat_checks[key] = card
                self._cards_flow.addWidget(card)
            stacks.body.addWidget(self.cards_host)
            self._update_seg_counts()
            cv.addWidget(stacks)
            cv.addStretch()
            pv.addWidget(scroll, 1)
            pv.addWidget(self._build_launch_footer())
            return page

        def _build_launch_footer(self) -> QWidget:
            """Низ «Запуска»: баннер с пейзажем палитры — экономия, два главных
            переключателя и кнопка запуска. Остальное — в меню «⋯»."""
            wrap = QWidget()
            wv = QVBoxLayout(wrap)
            wv.setContentsMargins(16, 6, 16, 12)
            wv.setSpacing(4)
            self.banner = Banner(self._palette_key)
            self.banner.set_palette(self._palette_key, self._pal["bg"], self._pal["accent"])
            bl = QHBoxLayout(self.banner)
            bl.setContentsMargins(20, 14, 16, 14)
            bl.setSpacing(16)
            left = QVBoxLayout()
            left.setSpacing(6)
            hero = QHBoxLayout()
            hero.setSpacing(4)
            self.savings_num = QLabel("—")
            self.savings_num.setObjectName("SavingsNumber")
            self.savings_unit = QLabel(_("МБ"))
            self.savings_unit.setObjectName("SavingsUnit")
            hero.addWidget(self.savings_num)
            hero.addWidget(self.savings_unit, 0, Qt.AlignmentFlag.AlignBottom)
            cap = QLabel(_("ЭКОНОМИЯ ПАМЯТИ"))
            cap.setObjectName("SavingsCaption")
            hero.addSpacing(10)
            hero.addWidget(cap, 0, Qt.AlignmentFlag.AlignBottom)
            hero.addStretch()
            left.addLayout(hero)
            chips = QHBoxLayout()
            chips.setSpacing(6)
            self.stat_en = QLabel()
            self.stat_en.setObjectName("Stat")
            self.stat_dis = QLabel()
            self.stat_dis.setObjectName("StatAccent")
            self.stat_extra = QLabel()
            self.stat_extra.setObjectName("Stat")
            self.stat_extra.setVisible(False)
            for w in (self.stat_en, self.stat_dis, self.stat_extra):
                chips.addWidget(w)
            chips.addStretch()
            left.addLayout(chips)
            pills = QHBoxLayout()
            pills.setSpacing(8)
            self.kill_cb = ToggleSwitch()
            self.kill_cb.setChecked(cfg.get("kill_first", True))
            pills.addWidget(
                Pill(
                    self.kill_cb,
                    _("Закрыть VS Code перед стартом"),
                    _(
                        "Закроет все окна VS Code ({exe}) перед стартом, чтобы память "
                        "освободилась. Запускай этот тул НЕ из терминала VS Code. Как "
                        "закрывать (мягко или принудительно) — в «Настройках»."
                    ).format(exe=code_image_name(code_cli)),
                )
            )
            self.bare_cb = ToggleSwitch()
            self.bare_cb.stateChanged.connect(self._update_summary)
            pills.addWidget(
                Pill(
                    self.bare_cb,
                    _("Голый режим"),
                    _(
                        "Отключит ВСЕ расширения, включая ядро — максимальная скорость. "
                        "Галочки стеков при этом игнорируются."
                    ),
                )
            )
            pills.addStretch()
            left.addLayout(pills)
            bl.addLayout(left, 1)
            right = QVBoxLayout()
            right.setSpacing(8)
            right.addStretch()
            rrow = QHBoxLayout()
            rrow.setSpacing(8)
            rrow.addWidget(
                menu_button(
                    [
                        (
                            _("Что выключится"),
                            self._show_diff,
                            _("Список расширений, которые будут выключены"),
                        ),
                        (
                            _("Показать команду"),
                            self._show_cmd,
                            _("Эквивалентная команда для cmd/ярлыка"),
                        ),
                    ],
                    tip=_("Что выключится, команда запуска"),
                ),
                0,
                Qt.AlignmentFlag.AlignVCenter,
            )
            self.b_run = QPushButton(_("Запустить VS Code"))
            self.b_run.setObjectName("Accent")
            self.b_run.setCursor(Qt.CursorShape.PointingHandCursor)
            self.b_run.clicked.connect(self._run)
            rrow.addWidget(self.b_run)
            right.addLayout(rrow)
            right.addStretch()
            bl.addLayout(right)
            wv.addWidget(self.banner)
            self.status_lbl = QLabel()
            self.status_lbl.setObjectName("Status")
            self.status_lbl.setContentsMargins(6, 0, 0, 0)
            wv.addWidget(self.status_lbl)
            # Скрытый summary — совместимость со старым кодом статуса.
            self.summary = QLabel()
            self.summary.setVisible(False)
            return wrap

        # --- страница «C / C++» ------------------------------------------------
        def _build_cpp_page(self) -> QWidget:
            from .gui_cpp import CppCenter

            def use_folder(folder):
                self.folder_edit.setText(folder.replace("/", "\\"))
                self._suggest_for_folder(folder)
                self.log.appendPlainText(_("Папка проекта: {folder}").format(folder=folder))
                self._goto("launch")

            self.cpp_center = CppCenter(
                self,
                code_cli,
                folder=self.folder_edit.text().strip(),
                on_folder=use_folder,
                on_installed=self.refresh_installed,
                on_issues=lambda n: self.nav.items["cpp"].set_badge(n),
            )
            return self.cpp_center

        # --- страница «Языки» ----------------------------------------------------
        def _build_tools_page(self) -> QWidget:
            host = QWidget()
            host.setObjectName("CatInner")
            self._show_toolchains(host=host)
            return host

        # --- страница «Расширения» ----------------------------------------------
        def _build_ext_page(self) -> QWidget:
            scroll, v = self._page_scroll(
                page_header(
                    _("Расширения"),
                    _(
                        "Сколько на самом деле весит каждое расширение, что делать с "
                        "незнакомыми и какие настройки VS Code снимают фоновую нагрузку."
                    ),
                )
            )
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(10)
            t_measure = Tile(
                "ext",
                _("Замерить расширения"),
                _(
                    "Спросить у запущенного VS Code, сколько памяти держит каждое "
                    "расширение и каждый стек. Это факт, а не оценка."
                ),
            )
            t_measure.clicked.connect(self._measure_extensions)
            t_auto = Tile(
                "hint",
                _("Автонастройка settings.json"),
                _(
                    "Рекомендованные настройки для установленных стеков и против фоновой "
                    "нагрузки. Только недостающие ключи, с бэкапом."
                ),
            )
            t_auto.clicked.connect(self._show_autoconfig)
            grid.addWidget(t_measure, 0, 0)
            grid.addWidget(t_auto, 0, 1)
            v.addLayout(grid)
            # Кнопка замера живёт здесь (её текст меняется на «Замеряю…»).
            self.ext_measure_btn = QPushButton(_("Замерить расширения"))
            self.ext_measure_btn.setObjectName("Ghost")
            self.ext_measure_btn.setVisible(False)
            self.ext_measure_btn.clicked.connect(self._measure_extensions)
            v.addWidget(self.ext_measure_btn)
            self.autoconf_btn = QPushButton(_("Автонастройка settings.json"))
            self.autoconf_btn.setVisible(False)
            self.autoconf_btn.clicked.connect(self._show_autoconfig)
            v.addWidget(self.autoconf_btn)

            unk = Section(_("Незнакомые расширения"))
            unk.body.addWidget(
                _note_lbl(
                    _(
                        "Расширения, которых нет в data/categories.json, лаунчер всегда "
                        "оставляет включёнными. Их можно разложить по стекам автоматически — "
                        "по манифесту; сама карта при этом не меняется."
                    )
                )
            )
            urow = QHBoxLayout()
            self.unknown_btn = QPushButton()
            self.unknown_btn.setObjectName("HBtn")
            self.unknown_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.unknown_btn.clicked.connect(self._show_unknown)
            self.classify_btn = QPushButton()
            self.classify_btn.setObjectName("HBtn")
            self.classify_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.classify_btn.clicked.connect(self._classify_wizard)
            self.classify_btn.setVisible(False)
            self.unknown_none = _note_lbl(_("Все установленные расширения уже в карте."))
            urow.addWidget(self.unknown_btn)
            urow.addWidget(self.classify_btn)
            urow.addWidget(self.unknown_none)
            urow.addStretch()
            unk.body.addLayout(urow)
            v.addWidget(unk)

            ovr = Section(_("Личные исключения"))
            ovr.body.addWidget(
                _note_lbl(
                    _(
                        "Режим «всегда включать / всегда выключать» для отдельных "
                        "расширений задаётся в «›» у стека и сильнее галочек."
                    )
                )
            )
            orow = QHBoxLayout()
            self.overrides_btn = QPushButton()
            self.overrides_btn.setObjectName("HBtn")
            self.overrides_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.overrides_btn.clicked.connect(self._show_overrides)
            self.overrides_btn.setVisible(False)
            orow.addWidget(self.overrides_btn)
            orow.addStretch()
            ovr.body.addLayout(orow)
            v.addWidget(ovr)

            if duplicates:
                dup = Section(_("Дубли в карте"))
                dup.body.addWidget(
                    _note_lbl(
                        _(
                            "В categories.json дубли расширений: {n}. Расширение "
                            "попадёт только в один стек — последний по порядку."
                        ).format(n=len(duplicates))
                    )
                )
                drow = QHBoxLayout()
                dup_btn = QPushButton(_("Показать"))
                dup_btn.setObjectName("HBtn")
                dup_btn.clicked.connect(self._show_duplicates)
                drow.addWidget(dup_btn)
                drow.addStretch()
                dup.body.addLayout(drow)
                v.addWidget(dup)
            v.addStretch()
            self._refresh_unknown()
            self._refresh_override_chip()
            return scroll

        # --- страница «Обслуживание» ---------------------------------------
        def _build_maint_page(self) -> QWidget:
            scroll, v = self._page_scroll(
                page_header(
                    _("Обслуживание"),
                    _("Уборка того, что VS Code копит на диске, проверка PATH и журнал."),
                )
            )
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(10)
            t_clean = Tile(
                "clean",
                _("Уборка VS Code"),
                _(
                    "Копии установщиков, данные удалённых проектов, кэши, старые логи и "
                    "версии расширений. Предпросмотр, удаление в Корзину."
                ),
            )
            t_clean.clicked.connect(self._open_cleanup)
            t_env = Tile(
                "steps",
                _("Проверить окружение"),
                _("Тулчейны и версии, дубли и мёртвые записи в PATH, JAVA_HOME."),
            )
            t_env.clicked.connect(self._run_env_doctor)
            self.t_path = Tile(
                "steps",
                _("Починить PATH"),
                _(
                    "Мусор, мёртвые записи и главное — кто кого перекрывает: заглушка Microsoft "
                    "Store вместо Python, компилятор вместо ваших python/cmake, чужой java. "
                    "С предпросмотром и откатом."
                ),
            )
            self.t_path.clicked.connect(self._open_path_doctor)
            t_code = Tile(
                "settings",
                _("Установка VS Code"),
                _("Выбрать, какой VS Code запускать: стабильный, Insiders или портативный."),
            )
            t_code.clicked.connect(self._choose_code_cli)
            grid.addWidget(self.t_path, 0, 0)
            grid.addWidget(t_clean, 0, 1)
            grid.addWidget(t_env, 1, 0)
            grid.addWidget(t_code, 1, 1)
            v.addLayout(grid)
            jr = Section(_("Журнал"))
            self.log = QPlainTextEdit()
            self.log.setObjectName("Log")
            self.log.setReadOnly(True)
            self.log.setMinimumHeight(220)
            self.log.setPlaceholderText(_("Здесь появится итоговая команда и статус запуска."))
            # Последняя строка журнала видна на «Запуске» под баннером.
            self.log.textChanged.connect(self._mirror_log)
            jr.body.addWidget(self.log)
            v.addWidget(jr)
            v.addStretch()
            return scroll

        def _open_path_doctor(self):
            from .gui_path import PathDoctorDialog

            PathDoctorDialog(self).exec()
            self._scan_path_badge()

        def _scan_path_badge(self):
            """Быстрая проверка PATH в фоне (без запуска программ) — счётчик на
            вкладке «Обслуживание» и на плитке «Починить PATH»."""
            from . import path_doctor as _pd

            w = FnWorker(lambda: _pd.analyze(probe_versions=False))

            def _d(rep):
                if not isinstance(rep, _pd.Report):
                    return
                n = sum(1 for i in rep.issues if i.level in ("error", "warn") and i.fixable)
                self.nav.items["clean"].set_badge(n)
                self.t_path.set_num(n or "")

            w.done.connect(_d)
            w.finished.connect(lambda x=w: self._reap_installer(x))
            self._install_threads.append(w)
            w.start()

        def _mirror_log(self):
            lines = [ln for ln in self.log.toPlainText().splitlines() if ln.strip()]
            if hasattr(self, "status_lbl"):
                self.status_lbl.setText(lines[-1][:160] if lines else "")

        def _run_env_doctor(self):
            """Проверка окружения (тулчейны, PATH, JAVA_HOME) в фоне."""
            w = FnWorker(_tc.environment_report)

            def _d(res):
                if isinstance(res, dict):
                    self._show_doctor_report(res)
                else:
                    QMessageBox.warning(
                        self, _("Проверка окружения"), _("Не удалось собрать отчёт.")
                    )

            w.done.connect(_d)
            w.finished.connect(lambda x=w: self._reap_installer(x))
            self._install_threads.append(w)
            w.start()

        # --- страница «Настройки» ------------------------------------------
        def _build_settings_page(self) -> QWidget:
            scroll, v = self._page_scroll(
                page_header(_("Настройки"), _("Вид и поведение — всё меняется сразу."))
            )
            view = Section(_("Вид"))
            row = QHBoxLayout()
            row.addWidget(QLabel(_("Тема")))
            row.addStretch()
            self.theme_seg = segmented(
                [("dark", _("Тёмная")), ("light", _("Светлая"))],
                self._theme,
                self._set_theme,
            )
            row.addWidget(self.theme_seg)
            view.body.addLayout(row)
            row2 = QHBoxLayout()
            row2.addWidget(QLabel(_("Язык")))
            row2.addStretch()
            row2.addWidget(
                segmented(
                    [("ru", _("Русский")), ("en", "English")],
                    get_language(),
                    lambda k: k != get_language() and self._switch_language(),
                )
            )
            view.body.addLayout(row2)
            view.body.addWidget(_note_lbl(_("Палитра — цвета окна и пейзаж на баннере запуска.")))
            pal_host = QWidget()
            pal_host.setObjectName("CatInner")
            flow = FlowLayout(pal_host, margin=0, spacing=10)
            self._pal_cards = {}
            lang = get_language()
            for key, ps in PALETTE_SETS.items():
                card = PaletteCard(
                    key,
                    palette_name(key, lang),
                    [ps["ac"], ps["glow"], ps["ok"], ps["warn"]],
                    key == self._palette_key,
                )
                card.picked.connect(self._set_palette)
                flow.addWidget(card)
                self._pal_cards[key] = card
            view.body.addWidget(pal_host)
            view.body.addWidget(_note_lbl(_("В светлой теме палитра меняет только акцент.")))
            v.addWidget(view)

            run = Section(_("Запуск VS Code"))
            self.soft_cb = ToggleSwitch()
            self.soft_cb.setChecked(cfg.get("soft_close", False))
            run.body.addLayout(
                _switch_row(
                    self.soft_cb,
                    _("Закрывать мягко"),
                    _(
                        "VS Code получит обычный запрос на закрытие и сам спросит про "
                        "несохранённое; лаунчер дождётся выхода. Выключено — "
                        "принудительно (/F): быстро, но несохранённое теряется."
                    ),
                )
            )
            self.kill_cb.stateChanged.connect(
                lambda: self.soft_cb.setEnabled(self.kill_cb.isChecked())
            )
            self.soft_cb.setEnabled(self.kill_cb.isChecked())
            self.newwin_cb = ToggleSwitch()
            self.newwin_cb.setChecked(cfg.get("new_window", True))
            run.body.addLayout(
                _switch_row(self.newwin_cb, _("Открывать в новом окне"), "--new-window")
            )
            self.gpu_cb = ToggleSwitch()
            self.gpu_cb.setChecked(cfg.get("disable_gpu", False))
            run.body.addLayout(
                _switch_row(
                    self.gpu_cb,
                    _("Без GPU-ускорения"),
                    _(
                        "--disable-gpu: лечит артефакты на старых видеокартах, "
                        "экономит немного памяти."
                    ),
                )
            )
            prow = QHBoxLayout()
            prow.setSpacing(10)
            plbl = QLabel(_("Профиль"))
            self.profile_edit = QLineEdit()
            self.profile_edit.setText(cfg.get("profile", ""))
            self.profile_edit.setPlaceholderText(
                _("имя существующего профиля VS Code (необязательно)")
            )
            self.profile_edit.setToolTip(
                _(
                    "Откроет окно с этим профилем (--profile). Профиль нужно заранее создать "
                    "в VS Code (шестерёнка → Profiles). Пусто — профиль по умолчанию."
                )
            )
            prow.addWidget(plbl)
            prow.addWidget(self.profile_edit, 1)
            run.body.addLayout(prow)
            v.addWidget(run)

            tray = Section(_("Трей"))
            self.tray_cb = ToggleSwitch()
            self.tray_cb.setChecked(cfg.get("tray", True))
            self.tray_cb.stateChanged.connect(self._toggle_tray_setting)
            tray.body.addLayout(
                _switch_row(
                    self.tray_cb,
                    _("Значок в трее"),
                    _(
                        "Правый клик по значку — список пресетов: VS Code открывается "
                        "нужным набором без окна. Применится после перезапуска."
                    ),
                )
            )
            self.close_tray_cb = ToggleSwitch()
            self.close_tray_cb.setChecked(cfg.get("close_to_tray", False))
            self.close_tray_cb.setEnabled(self.tray_cb.isChecked())
            self.close_tray_cb.stateChanged.connect(self._toggle_tray_setting)
            tray.body.addLayout(
                _switch_row(
                    self.close_tray_cb,
                    _("Крестик сворачивает в трей"),
                    _("Лаунчер останется в трее; выйти совсем — «Выход» в меню значка."),
                )
            )
            v.addWidget(tray)
            v.addStretch()
            return scroll

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
            self.seg_btns["missing"].setText(_("Не установленные ({n})").format(n=total - inst))

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
                        _("показано {n} из {total}").format(n=shown, total=total)
                    )
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
            # Ширина области карточек становится известна только после того,
            # как раскладка страницы пересчитается, — повторяем на следующем такте.
            QTimer.singleShot(0, self._relayout_cards)

        def _get_dep_map(self) -> dict:
            """Карта зависимостей расширений для #1. Строится один раз (читает
            ~100 небольших package.json, десятки мс) и кэшируется до смены
            набора установленных расширений. Ошибку чтения глушим в пустую
            карту — защита по зависимостям тогда просто выключена, поведение
            откатывается к прежнему."""
            if self._dep_map is None:
                try:
                    self._dep_map = build_dependency_map(read_extension_manifests(code_cli))
                except Exception:
                    self._dep_map = {}
            return self._dep_map

        def _disabled_list(self) -> list[str]:
            return compute_disabled(
                self.installed,
                ext_index,
                self._selected(),
                self._force_disable,
                self._force_enable,
                dep_map=self._get_dep_map(),
            )

        def _bare(self) -> bool:
            return getattr(self, "bare_cb", None) is not None and self.bare_cb.isChecked()

        def _unknown(self) -> list[str]:
            """Установленные расширения, которых нет в карте категорий."""
            return sorted(e for e in self.installed if e not in ext_index)

        def _refresh_unknown(self):
            unk = self._unknown()
            self.unknown_btn.setText(_("Не в карте: {n} — показать").format(n=len(unk)))
            self.unknown_btn.setVisible(bool(unk))
            if getattr(self, "unknown_none", None) is not None:
                self.unknown_none.setVisible(not unk)
            if getattr(self, "nav", None) is not None:
                self.nav.items["ext"].set_badge(len(unk))
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
                QMessageBox.information(self, _("Раскладка"), _("Незнакомых расширений нет."))
                return
            valid_keys = set(cats.get("categories", {}))
            try:
                manifests = read_extension_manifests(code_cli)
            except Exception:
                manifests = {}
            suggestions = suggest_categories(
                self.installed, ext_index, manifests, available=valid_keys
            )
            if not suggestions:
                QMessageBox.information(
                    self,
                    _("Раскладка"),
                    _(
                        "Не удалось уверенно определить стек ни для одного "
                        "незнакомого расширения. Разложи вручную в "
                        "data/categories.json."
                    ),
                )
                return

            dlg = QDialog(self)
            dlg.setWindowTitle(_("Разложить по стекам"))
            dlg.resize(580, 540)
            lay = QVBoxLayout(dlg)
            lay.addWidget(
                _wrap(
                    QLabel(
                        _(
                            "Предлагаю раскладку {n} расширений. Сними галочку, чтобы "
                            "пропустить; стек можно поменять. Твоя categories.json не "
                            "меняется — раскладка хранится отдельно и обратима."
                        ).format(n=len(suggestions))
                    )
                )
            )
            key_titles = [(k, cat_title(cats["categories"][k], k)) for k in sorted(valid_keys)]
            keys_order = [k for k, _t in key_titles]
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            host = QWidget()
            hv = QVBoxLayout(host)
            hv.setSpacing(6)
            rows = []
            for ext_id, key in sorted(suggestions.items()):
                line = QHBoxLayout()
                cb = QCheckBox(ext_id)
                cb.setChecked(True)
                combo = QComboBox()
                for k, title in key_titles:
                    combo.addItem(title, k)
                if key in keys_order:
                    combo.setCurrentIndex(keys_order.index(key))
                line.addWidget(cb, 1)
                line.addWidget(combo, 0)
                holder = QWidget()
                holder.setLayout(line)
                hv.addWidget(holder)
                rows.append((cb, combo))
            hv.addStretch()
            scroll.setWidget(host)
            lay.addWidget(scroll, 1)
            bar = QHBoxLayout()
            bar.addStretch()
            cancel = QPushButton(_("Отмена"))
            cancel.setObjectName("Ghost")
            cancel.clicked.connect(dlg.reject)
            accept = QPushButton(_("Принять отмеченные"))
            accept.setObjectName("Accent")
            accept.clicked.connect(dlg.accept)
            bar.addWidget(cancel)
            bar.addWidget(accept)
            lay.addLayout(bar)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return

            approved = {
                cb.text(): combo.currentData()
                for cb, combo in rows
                if cb.isChecked() and combo.currentData()
            }
            if not approved:
                return
            overlay = cfg.setdefault("extra_categories", {})
            overlay.update(approved)
            save_config(cfg)
            ext_index = build_ext_index(cats, overlay)  # переопределяем замыкание
            self._dep_map = None
            self._apply_installed(self.installed)  # пересчитать счётчики/фильтр/unknown
            self._update_summary()
            self.log.appendPlainText(_("Разложено расширений: {n}").format(n=len(approved)))

        def _show_toolchains(self, target=None, host=None):
            """Диалог языковых тулчейнов: установка, обновление, удаление, проверка.

            По карточке на тулчейн; у каждого пакета — статус и действия (winget).
            Операции идут в фоне (ToolchainInstaller), прогресс/отмена общие внизу.
            `target` — ключ тулчейна, к которому проскроллить (из подсказки в окне).
            Пока идёт winget-операция, кнопки действий заблокированы (одна за раз)."""
            if host is None and getattr(self, "_page_of", None) is not None:
                # В окне с навигацией «Языки» — страница, а не отдельный диалог.
                self._open_tools_page(target)
                return
            embedded = host is not None
            dlg = host if embedded else QDialog(self)
            if not embedded:
                dlg.setWindowTitle(_("Языки и инструменты"))
                dlg.resize(720, 700)
            lay = QVBoxLayout(dlg)
            if embedded:
                lay.setContentsMargins(20, 16, 18, 14)
            else:
                lay.setContentsMargins(18, 18, 18, 16)
            lay.setSpacing(10)

            if embedded:
                lay.addWidget(page_header(_("Языки"), ""))
            else:
                title = QLabel(_("Языки и инструменты"))
                title.setObjectName("Title")
                lay.addWidget(title)
            intro = _wrap(
                QLabel(
                    _(
                        "Расширения VS Code добавляют подсветку и подсказки, но собирать и "
                        "запускать код им нечем без самого тулчейна: компилятора C++, JDK, "
                        "Go и т.д. Здесь можно поставить недостающее через winget — он сам "
                        "скачает пакет и, где нужно, лаунчер пропишет его в PATH. После "
                        "установки откройте новый терминал, чтобы PATH подхватился."
                    )
                )
            )
            intro.setObjectName("CatNote")
            lay.addWidget(intro)

            wg_ok = _tc.winget_available()
            if not wg_ok:
                warn = _wrap(
                    QLabel(
                        _(
                            "winget не найден. Установите «App Installer» из Microsoft Store "
                            "(входит в состав Windows 10/11) — без него автоматическая "
                            "установка недоступна."
                        )
                    )
                )
                warn.setObjectName("Warn")
                lay.addWidget(warn)
            lay.addWidget(_hline())

            state = {"open": True, "busy": False}
            if embedded:
                dlg.destroyed.connect(lambda _=None: state.update(open=False))
            else:
                dlg.finished.connect(lambda _=0: state.update(open=False))
            rows: dict[str, dict] = {}  # winget_id -> {widgets...}
            action_btns: list = []  # все кнопки действий (для блокировки)
            card_of: dict[str, QWidget] = {}  # key -> карточка (для скролла к target)
            status_lbl = QLabel()
            status_lbl.setObjectName("CatNote")
            status_lbl.setVisible(False)
            prog_bar = QProgressBar()
            prog_bar.setObjectName("InstallBar")
            prog_bar.setTextVisible(False)
            prog_bar.setFixedHeight(8)
            prog_bar.setVisible(False)
            cancel_btn = QPushButton(_("Отмена"))
            cancel_btn.setObjectName("Ghost")
            cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            cancel_btn.setVisible(False)

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
                    tag.setText(_("установлено ✓ — перезапустите терминал"))
                    tag.setObjectName("Wlight")
                elif installed:
                    tag.setText(
                        _("установлено{ver}").format(ver=f" · {version}" if version else "")
                    )
                    tag.setObjectName("Wlight")
                else:
                    tag.setText(_("нет в системе"))
                    tag.setObjectName("Woff")
                tag.style().unpolish(tag)
                tag.style().polish(tag)
                on_disk = (not installed) and bool(_tc.find_tool_on_disk(pkg))
                r["install"].setVisible(not installed and wg_ok)
                r["addpath"].setVisible(not installed and on_disk)
                # Установленному пакету — одно меню «⋯» (проверить, обновить,
                # удалить) вместо трёх кнопок; выбор версии нужен только до установки.
                r["more"].setVisible(installed)
                if r.get("ver_combo") is not None:
                    r["ver_combo"].setVisible(not installed)

            def do_add_existing(pkg):
                bindir = _tc.find_tool_on_disk(pkg)
                if not bindir:
                    return
                ok, msg = _tc.env_path.add_to_user_path(bindir)
                status_lbl.setText(msg)
                status_lbl.setVisible(True)
                if ok:
                    refresh_pkg_row(pkg, True, None, just=True)

            def do_verify(pkg):
                ok, info = _tc.verify_package(pkg)
                QMessageBox.information(
                    dlg, _("Проверка инструмента"), (f"✓ {info}" if ok else f"✗ {info}")
                )

            def do_configure_vscode(key):
                ok, msg = _tc.configure_vscode_for(key, code_cli)
                (QMessageBox.information if ok else QMessageBox.warning)(
                    dlg, _("Настройка VS Code"), msg
                )

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
                prog_bar.setRange(0, 0)
                prog_bar.setValue(0)
                prog_bar.setVisible(True)

                def _edone(ok, m):
                    if not state["open"]:
                        return
                    prog_bar.setVisible(False)
                    lock_actions(False)
                    status_lbl.setText(
                        (m or "").splitlines()[0] if m else (_("Готово") if ok else _("Ошибка"))
                    )
                    if ok and orig_pkg is not None:
                        refresh_pkg_row(orig_pkg, True, None, just=True)
                    elif not ok:
                        QMessageBox.warning(dlg, _("Не удалось выполнить"), (m or "")[:600])

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
                    orig_by_rid = {rp.winget_id: op for op, rp in zip(pkgs, resolved, strict=True)}
                    pkgs = resolved
                else:
                    orig_by_rid = {p.winget_id: p for p in pkgs}
                names = ", ".join(p.title for p in pkgs)
                # #7: предупреждение, если для языка стоит менеджер версий.
                warn_txt = ""
                if action == "install":
                    orig_ids = {op.winget_id for op in orig_by_rid.values()}
                    keys = {
                        k
                        for k in _tc.toolchain_keys()
                        for pp in _tc.get_toolchain(k).packages
                        if pp.winget_id in orig_ids
                    }
                    warns = [w for w in (_tc.manager_warning_for(k) for k in keys) if w]
                    if warns:
                        warn_txt = "\n\n⚠ " + "\n⚠ ".join(warns)
                if (
                    QMessageBox.question(
                        dlg,
                        q_title,
                        _(
                            "Пакеты:\n\n{names}\n\nЭто может занять несколько минут. Продолжить?"
                        ).format(names=names)
                        + warn_txt,
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    != QMessageBox.StandardButton.Yes
                ):
                    return
                lock_actions(True)
                bulk = len(pkgs) > 1
                prog_bar.setRange(0, len(pkgs) if bulk else 0)
                prog_bar.setValue(0)
                prog_bar.setVisible(True)
                fails: list[tuple[str, str]] = []
                done = [0]

                def _one(wid, ok, msg):
                    if not state["open"]:
                        return
                    done[0] += 1
                    resolved_pkg = next((p for p in pkgs if p.winget_id == wid), None)
                    orig_pkg = orig_by_rid.get(wid, resolved_pkg)  # #4: строку по исходному
                    if ok:
                        if orig_pkg is not None:
                            refresh_pkg_row(orig_pkg, action != "uninstall", None, just=True)
                        # После установки JDK — сразу прописать JAVA_HOME, если он
                        # ещё не настроен (многим Java-инструментам нужен именно он).
                        if (
                            action == "install"
                            and orig_pkg is not None
                            and "javac" in orig_pkg.probe
                        ):
                            jok, jmsg = _tc.repair_java_home()
                            if jok:
                                status_lbl.setText(jmsg)
                                status_lbl.setVisible(True)
                    else:
                        fails.append((wid, msg or ""))
                        if not bulk:
                            # #10: ошибка из-за прав администратора — предложить повтор elevated.
                            need_admin = "администратор" in (msg or "").lower()
                            if (
                                need_admin
                                and action == "install"
                                and resolved_pkg is not None
                                and QMessageBox.question(
                                    dlg,
                                    _("Нужны права администратора"),
                                    (msg or "")[:400]
                                    + "\n\n"
                                    + _("Повторить установку с правами администратора?"),
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.Yes,
                                )
                                == QMessageBox.StandardButton.Yes
                            ):
                                QTimer.singleShot(
                                    0, lambda rp=resolved_pkg, op=orig_pkg: _start_elevated(rp, op)
                                )
                                return
                            QMessageBox.warning(
                                dlg, _("Не удалось выполнить"), f"{wid}\n\n{(msg or '')[:600]}"
                            )

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
                    prog_bar.setVisible(False)
                    cancel_btn.setVisible(False)
                    lock_actions(False)
                    ok_n = done[0] - len(fails)
                    status_lbl.setText(
                        _("Готово: {ok}, ошибок: {err}").format(ok=ok_n, err=len(fails))
                    )
                    status_lbl.setVisible(True)
                    if fails and bulk:
                        preview = "\n".join(
                            f"• {wid}: {(m or '').splitlines()[0][:120]}" for wid, m in fails[:8]
                        )
                        QMessageBox.warning(
                            dlg, _("Готово с ошибками"), status_lbl.text() + "\n\n" + preview
                        )

                worker = ToolchainInstaller(pkgs, action=action)
                worker.progress.connect(_progress)
                worker.one_done.connect(_one)
                worker.all_done.connect(_all)
                worker.finished.connect(lambda w=worker: self._reap_installer(w))
                if bulk:
                    cancel_btn.setVisible(True)
                    cancel_btn.setEnabled(True)
                    try:
                        cancel_btn.clicked.disconnect()
                    except TypeError:
                        pass

                    def _do_cancel(_checked=False, w=worker):
                        w.cancel()
                        cancel_btn.setEnabled(False)
                        status_lbl.setText(_("Отмена…"))

                    cancel_btn.clicked.connect(_do_cancel)
                self._install_threads.append(worker)
                worker.start()

            def mk_btn(text, obj, slot, tip=""):
                b = QPushButton(text)
                b.setObjectName(obj)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                if tip:
                    b.setToolTip(tip)
                b.clicked.connect(slot)
                action_btns.append(b)
                return b

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            holder = QWidget()
            vb = QVBoxLayout(holder)
            vb.setContentsMargins(0, 0, 6, 0)
            vb.setSpacing(8)
            cpp_card_done = False
            for key in _tc.toolchain_keys():
                if key == "cpp" or key.startswith("cpp_"):
                    if cpp_card_done:
                        continue
                    cpp_card_done = True
                    card = self._cpp_toolchain_card(dlg)
                    card_of["cpp"] = card
                    for k in _tc.toolchain_keys():
                        if k.startswith("cpp_"):
                            card_of[k] = card
                    vb.addWidget(card)
                    continue
                tc = _tc.get_toolchain(key)
                statuses = _tc.toolchain_status(key)
                card = QFrame()
                card.setObjectName("CatCard")
                card_of[key] = card
                cl = QVBoxLayout(card)
                cl.setContentsMargins(12, 10, 12, 10)
                cl.setSpacing(4)
                head = QHBoxLayout()
                head.setSpacing(8)
                nm = QLabel(f"{tc.title}  ·  {key}")
                nm.setObjectName("CatTitle")
                head.addWidget(nm, 1)
                req_missing = [
                    p for p in tc.packages if not p.optional and not _tc.package_installed(p)
                ]
                if wg_ok and len(req_missing) > 1:
                    allbtn = mk_btn(
                        _("Установить всё ({n})").format(n=len(req_missing)),
                        "Ghost",
                        lambda _=False, ps=list(req_missing): start_winget(ps, "install"),
                    )
                    head.addWidget(allbtn, 0, Qt.AlignmentFlag.AlignVCenter)
                cl.addLayout(head)
                note = _wrap(QLabel(tc.note))
                note.setObjectName("CatNote")
                cl.addWidget(note)
                for st in statuses:
                    pkg = st["package"]
                    prow = QHBoxLayout()
                    prow.setSpacing(6)
                    label = pkg.title + (_(" · доп.") if pkg.optional else "")
                    pn = QLabel(label)
                    pn.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                    if pkg.provides:
                        pn.setToolTip(_("Даёт: {tools}").format(tools=", ".join(pkg.provides)))
                    prow.addWidget(pn, 1)
                    tag = QLabel()
                    tag.setObjectName("Woff")
                    prow.addWidget(tag, 0, Qt.AlignmentFlag.AlignVCenter)
                    # #4: выбор версии для пакетов, у которых есть варианты.
                    ver_combo = None
                    if pkg.versions:
                        ver_combo = QComboBox()
                        for vid, vtitle in pkg.versions:
                            ver_combo.addItem(vtitle, vid)
                        # по умолчанию — winget_id пакета (первый подходящий).
                        idx = next(
                            (i for i, (vid, _t) in enumerate(pkg.versions) if vid == pkg.winget_id),
                            0,
                        )
                        ver_combo.setCurrentIndex(idx)
                        ver_combo.setToolTip(_("Версия для установки/обновления"))
                        prow.addWidget(ver_combo, 0, Qt.AlignmentFlag.AlignVCenter)
                    ib = mk_btn(
                        _("Установить"),
                        "Ghost",
                        lambda _=False, p=pkg: start_winget([p], "install"),
                        _("winget install --id {id}").format(id=pkg.winget_id)
                        + (f"\n\n{pkg.note}" if pkg.note else ""),
                    )
                    ap = mk_btn(
                        _("Добавить в PATH"),
                        "Ghost",
                        lambda _=False, p=pkg: do_add_existing(p),
                        _(
                            "Компилятор найден на диске — добавить его каталог "
                            "в PATH без повторной загрузки."
                        ),
                    )
                    items = [
                        (
                            _("Проверить"),
                            lambda p=pkg: do_verify(p),
                            _("Запустить инструмент и показать его версию."),
                        ),
                    ]
                    if key == "python":
                        items.append(
                            (
                                _("Настроить VS Code"),
                                lambda k=key: do_configure_vscode(k),
                                _("Прописать путь к интерпретатору в settings.json VS Code."),
                            )
                        )
                    if wg_ok:
                        items += [
                            (
                                _("Обновить"),
                                lambda p=pkg: start_winget([p], "upgrade"),
                                _("winget upgrade --id {id}").format(id=pkg.winget_id),
                            ),
                            None,
                            (
                                _("Удалить"),
                                lambda p=pkg: start_winget([p], "uninstall"),
                                _("winget uninstall --id {id}").format(id=pkg.winget_id),
                            ),
                        ]
                    more = menu_button(items, tip=_("Проверить, обновить или удалить"))
                    action_btns.append(more)
                    for b in (ib, ap, more):
                        prow.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
                    rows[pkg.winget_id] = {
                        "tag": tag,
                        "install": ib,
                        "addpath": ap,
                        "more": more,
                        "ver_combo": ver_combo,
                        "pkg": pkg,
                    }
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
                status_lbl.setText(_("Проверяю обновления…"))
                status_lbl.setVisible(True)
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
                            r["tag"].style().unpolish(r["tag"])
                            r["tag"].style().polish(r["tag"])
                            n += 1
                    status_lbl.setText(_("Доступно обновлений: {n}").format(n=n))
                    status_lbl.setVisible(True)

                w.done.connect(_d)
                w.finished.connect(lambda x=w: self._reap_installer(x))
                self._install_threads.append(w)
                w.start()

            def do_doctor():
                """#8: собрать отчёт об окружении в фоне и показать его."""
                if state["busy"]:
                    return
                lock_actions(True)
                status_lbl.setText(_("Проверяю окружение…"))
                status_lbl.setVisible(True)
                w = FnWorker(_tc.environment_report)

                def _d(res):
                    if not state["open"]:
                        return
                    lock_actions(False)
                    status_lbl.setVisible(False)
                    if not isinstance(res, dict):
                        QMessageBox.warning(
                            dlg, _("Проверка окружения"), _("Не удалось собрать отчёт.")
                        )
                        return
                    self._show_doctor_report(res)

                w.done.connect(_d)
                w.finished.connect(lambda x=w: self._reap_installer(x))
                self._install_threads.append(w)
                w.start()

            bar = QHBoxLayout()
            bar.addWidget(status_lbl)
            bar.addWidget(prog_bar, 0, Qt.AlignmentFlag.AlignVCenter)
            bar.addWidget(cancel_btn)
            bar.addStretch()
            doctor_btn = mk_btn(
                _("Проверить окружение"),
                "Ghost",
                do_doctor,
                _(
                    "Отчёт: установленные тулчейны и версии, здоровье "
                    "PATH (дубли/мёртвые записи), JAVA_HOME."
                ),
            )
            bar.addWidget(doctor_btn)
            if wg_ok:
                upd_btn = mk_btn(
                    _("Проверить обновления"),
                    "Ghost",
                    do_check_updates,
                    _("Спросить winget, для каких тулчейнов доступно обновление, и отметить их."),
                )
                bar.addWidget(upd_btn)
            if not embedded:
                close = QPushButton(_("Закрыть"))
                close.setObjectName("Accent")
                close.clicked.connect(dlg.accept)
                bar.addWidget(close)
            lay.addLayout(bar)

            def _scroll_to(key):
                if key in card_of:
                    scroll.ensureWidgetVisible(card_of[key])

            # Прокрутка к нужному тулчейну (из подсказки в главном окне).
            if embedded:
                self._tools_scroll_to = _scroll_to
                if target:
                    QTimer.singleShot(0, lambda: _scroll_to(target))
                return
            if target and target in card_of:
                QTimer.singleShot(0, lambda: _scroll_to(target))
            dlg.exec()

        def _cpp_toolchain_card(self, dlg):
            """Карточка C/C++ в окне тулчейнов: коротко что стоит и кнопка в
            C++-центр, где всё ставится одним списком по ролям."""
            from shutil import which

            card = QFrame()
            card.setObjectName("CatCard")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 10, 12, 10)
            cl.setSpacing(4)
            head = QHBoxLayout()
            nm = QLabel("C / C++")
            nm.setObjectName("CatTitle")
            head.addWidget(nm, 1)
            go = QPushButton(_("Открыть C++-центр"))
            go.setObjectName("Accent")
            go.setCursor(Qt.CursorShape.PointingHandCursor)

            def _go():
                if isinstance(dlg, QDialog):
                    dlg.accept()
                self._open_cpp()

            go.clicked.connect(_go)
            head.addWidget(go, 0, Qt.AlignmentFlag.AlignVCenter)
            cl.addLayout(head)
            found = [n for n in ("g++", "clang++", "cmake", "ninja", "gdb", "clangd") if which(n)]
            status = (
                _("В PATH: {tools}.").format(tools=", ".join(found))
                if found
                else _("Компилятор C++ в PATH не найден.")
            )
            note = _wrap(
                QLabel(
                    _(
                        "Компиляторы (MinGW, MSYS2, MSVC), CMake и Ninja, подсказки cpptools "
                        "или clangd, отладчики, библиотеки и vcpkg ставятся в C++-центре одним "
                        "списком: у каждого пункта написано, за что он отвечает."
                    )
                    + " "
                    + status
                )
            )
            note.setObjectName("CatNote")
            cl.addWidget(note)
            return card

        def _show_doctor_report(self, rep: dict):
            """#8: показать отчёт environment_report в читаемом виде."""
            dlg = QDialog(self)
            dlg.setWindowTitle(_("Проверка окружения"))
            dlg.resize(640, 620)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(18, 18, 18, 16)
            lay.setSpacing(10)
            title = QLabel(_("Проверка окружения"))
            title.setObjectName("Title")
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
            pu = rep.get("path_user", {})
            pm = rep.get("path_machine", {})
            lines.append(
                _("PATH: {n} записей, длина {l} символов").format(
                    n=ph.get("count", 0), l=ph.get("length", 0)
                )
            )
            # #3: раздельно user (чистится без прав) и machine (нужен админ).
            u_dups, u_miss = pu.get("duplicates", []), pu.get("missing", [])
            m_dups, m_miss = pm.get("duplicates", []), pm.get("missing", [])
            lines.append(
                _("  Ваш PATH: дублей {d}, мёртвых {m}").format(d=len(u_dups), m=len(u_miss))
            )
            for d in (u_dups + u_miss)[:10]:
                lines.append(f"      • {d}")
            lines.append(
                _("  Системный PATH: дублей {d}, мёртвых {m}  (нужны права админа)").format(
                    d=len(m_dups), m=len(m_miss)
                )
            )
            for d in (m_dups + m_miss)[:10]:
                lines.append(f"      • {d}")
            if not (u_dups or u_miss or m_dups or m_miss):
                lines.append(_("  PATH в порядке: дублей и мёртвых записей не найдено."))

            box = QPlainTextEdit("\n".join(lines))
            box.setReadOnly(True)
            lay.addWidget(box, 1)
            b = QHBoxLayout()

            def do_fix_java():
                ok, msg = _tc.repair_java_home()
                (QMessageBox.information if ok else QMessageBox.warning)(dlg, _("JAVA_HOME"), msg)
                box.setPlainText(box.toPlainText() + "\n\n— " + msg)

            if u_dups or u_miss or m_dups or m_miss:
                # Одна кнопка вместо двух «почистить»: умная починка видит обе ветки
                # PATH, конфликты и показывает, что изменится.
                fix_btn = QPushButton(_("Починить PATH…"))
                fix_btn.setObjectName("Ghost")
                fix_btn.setCursor(Qt.CursorShape.PointingHandCursor)

                def _open_fix():
                    dlg.accept()
                    self._open_path_doctor()

                fix_btn.clicked.connect(_open_fix)
                b.addWidget(fix_btn)
            # JAVA_HOME сломан/не задан, но JDK на машине есть — можно прописать.
            if (not jh.get("ok")) and _tc.find_jdk_home():
                java_btn = QPushButton(_("Исправить JAVA_HOME"))
                java_btn.setObjectName("Ghost")
                java_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                java_btn.setToolTip(_("Найти установленный JDK и прописать JAVA_HOME."))
                java_btn.clicked.connect(do_fix_java)
                b.addWidget(java_btn)
            b.addStretch()
            close = QPushButton(_("Закрыть"))
            close.setObjectName("Accent")
            close.clicked.connect(dlg.accept)
            b.addWidget(close)
            lay.addLayout(b)
            dlg.exec()

        def _show_duplicates(self):
            if not duplicates:
                return
            dlg = QDialog(self)
            dlg.setWindowTitle(_("Дубли в categories.json"))
            dlg.resize(600, 500)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(18, 18, 18, 16)
            lay.setSpacing(12)
            title = QLabel(_("Расширения в нескольких стеках"))
            title.setObjectName("Title")
            lay.addWidget(title)
            note = _wrap(
                QLabel(
                    _(
                        "Каждое расширение попадёт только в один стек — тот, что стоит "
                        "последним в data/categories.json. Убери дубли, чтобы галочка "
                        "работала предсказуемо."
                    )
                )
            )
            note.setObjectName("Subtitle")
            lay.addWidget(note)
            lay.addWidget(_hline())
            box = QPlainTextEdit()
            box.setObjectName("Log")
            box.setReadOnly(True)
            box.setMaximumHeight(16777215)
            text = "\n".join(
                f"{ext}  ->  {' + '.join(keys)}" for ext, keys in sorted(duplicates.items())
            )
            box.setPlainText(text)
            lay.addWidget(box, 1)
            bar = QHBoxLayout()
            copy = QPushButton(_("Копировать"))
            copy.setObjectName("Ghost")
            copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
            bar.addWidget(copy)
            bar.addStretch()
            close = QPushButton(_("Закрыть"))
            close.setObjectName("Accent")
            close.clicked.connect(dlg.accept)
            bar.addWidget(close)
            lay.addLayout(bar)
            dlg.exec()

        def _show_overrides(self):
            """Все персональные исключения в одном месте.

            Исключение по расширению («всегда включать» / «всегда выключать»)
            ставится в окне «Подробнее» конкретного стека — и там же терялось:
            через месяц человек видит, что стек выключен, а расширение грузится,
            и не помнит, где это включил. Здесь весь список сразу, с отменой."""
            rows = [(e, "enable") for e in sorted(self._force_enable)]
            rows += [(e, "disable") for e in sorted(self._force_disable)]
            dlg = QDialog(self)
            dlg.setWindowTitle(_("Исключения по расширениям"))
            dlg.resize(620, 520)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(18, 18, 18, 16)
            lay.setSpacing(12)
            ttl = QLabel(_("Исключения по расширениям"))
            ttl.setObjectName("Title")
            lay.addWidget(ttl)
            note = _wrap(
                QLabel(
                    _(
                        "Эти расширения игнорируют решение своего стека. Исключение "
                        "сильнее галочки: «всегда включать» переживёт выключенный стек, "
                        "«всегда выключать» — включённый."
                    )
                    if rows
                    else _(
                        "Исключений нет. Поставить их можно в «Подробнее» у любого "
                        "стека — там у каждого расширения есть выбор режима."
                    )
                )
            )
            note.setObjectName("Subtitle")
            lay.addWidget(note)
            lay.addWidget(_hline())

            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            host = QWidget()
            hv = QVBoxLayout(host)
            hv.setContentsMargins(0, 0, 6, 0)
            hv.setSpacing(6)

            def drop(ext_id, row_widget):
                self.set_override(ext_id, "default")
                row_widget.setVisible(False)
                self._refresh_override_chip()

            for ext_id, mode in rows:
                row = QFrame()
                row.setObjectName("CatCard")
                rl = QHBoxLayout(row)
                rl.setContentsMargins(12, 8, 12, 8)
                rl.setSpacing(10)
                lbl = QLabel(ext_id)
                lbl.setObjectName("CatTitle")
                rl.addWidget(lbl, 1)
                badge = QLabel(_("всегда включено") if mode == "enable" else _("всегда выключено"))
                badge.setObjectName("Wlight" if mode == "enable" else "Wheavy")
                rl.addWidget(badge, 0)
                cat = ext_index.get(ext_id)
                if cat:
                    title = cat_title(cats.get("categories", {}).get(cat, {}), cat)
                    stack_lbl = QLabel(title)
                    stack_lbl.setObjectName("CatNote")
                    rl.addWidget(stack_lbl, 0)
                rm = QPushButton(_("Убрать"))
                rm.setObjectName("Ghost")
                rm.clicked.connect(lambda _c=False, e=ext_id, r=row: drop(e, r))
                rl.addWidget(rm, 0)
                hv.addWidget(row)
            hv.addStretch(1)
            area.setWidget(host)
            lay.addWidget(area, 1)

            bar = QHBoxLayout()
            clear = QPushButton(_("Убрать все"))
            clear.setObjectName("Danger")
            clear.setEnabled(bool(rows))

            def clear_all():
                for ext_id, _mode in rows:
                    self.set_override(ext_id, "default")
                self._refresh_override_chip()
                dlg.accept()

            clear.clicked.connect(clear_all)
            bar.addWidget(clear)
            bar.addStretch()
            close = QPushButton(_("Закрыть"))
            close.setObjectName("Accent")
            close.clicked.connect(dlg.accept)
            bar.addWidget(close)
            lay.addLayout(bar)
            dlg.exec()

        def _refresh_override_chip(self):
            """Кнопка-счётчик исключений: видна, только когда они есть."""
            btn = getattr(self, "overrides_btn", None)
            if btn is None:
                return
            n = len(self._force_enable) + len(self._force_disable)
            btn.setText(_("Исключения: {n}").format(n=n))
            btn.setVisible(bool(n))

        def _show_unknown(self):
            unk = self._unknown()
            if not unk:
                return
            dlg = QDialog(self)
            dlg.setWindowTitle(_("Расширения не в карте"))
            dlg.resize(560, 560)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(18, 18, 18, 16)
            lay.setSpacing(12)
            title = QLabel(_("Не в data/categories.json"))
            title.setObjectName("Title")
            lay.addWidget(title)
            note = _wrap(
                QLabel(
                    _(
                        "{n} расширений нет в карте категорий, поэтому лаунчер всегда "
                        "оставляет их включёнными. Добавь их в нужную категорию в "
                        "data/categories.json, чтобы управлять ими из окна."
                    ).format(n=len(unk))
                )
            )
            note.setObjectName("Subtitle")
            lay.addWidget(note)
            lay.addWidget(_hline())
            box = QPlainTextEdit()
            box.setObjectName("Log")
            box.setReadOnly(True)
            box.setMaximumHeight(16777215)
            box.setPlainText("\n".join(unk))
            lay.addWidget(box, 1)
            bar = QHBoxLayout()
            copy = QPushButton(_("Копировать список"))
            copy.setObjectName("Ghost")
            copy.clicked.connect(lambda: QApplication.clipboard().setText("\n".join(unk)))
            bar.addWidget(copy)
            bar.addStretch()
            close = QPushButton(_("Закрыть"))
            close.setObjectName("Accent")
            close.clicked.connect(dlg.accept)
            bar.addWidget(close)
            lay.addLayout(bar)
            dlg.exec()

        def _show_autoconfig(self):
            recommended = load_recommended()
            present = categories_present(self.installed, ext_index)
            path = vscode_user_settings_path(code_cli)
            # always_on — общие настройки против фоновой нагрузки, нужны всем.
            # Показываем только то, чего в settings.json ещё нет: иначе список
            # из уже заданных ключей выглядит как «надо применить», а применять
            # нечего.
            to_add = {
                k: v
                for k, v in recommended_for(["always_on", *sorted(present)], recommended).items()
                if k != "_comment"
            }
            to_add = _missing_settings(path, to_add)
            text = (
                json.dumps(to_add, ensure_ascii=False, indent=2)
                if to_add
                else _("Нет рекомендаций для установленных стеков.")
            )

            dlg = QDialog(self)
            dlg.setWindowTitle(_("Автонастройка VS Code"))
            dlg.resize(600, 560)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(18, 18, 18, 16)
            lay.setSpacing(12)
            title = QLabel(_("Рекомендованные настройки"))
            title.setObjectName("Title")
            lay.addWidget(title)
            stacks = ", ".join(sorted(present)) or "—"
            info = _wrap(
                QLabel(
                    _(
                        "Стеки: {stacks}. «Применить» добавит только НЕДОСТАЮЩИЕ ключи в "
                        "settings.json и сделает бэкап; существующие настройки не меняются.\n"
                        "Файл: {path}"
                    ).format(stacks=stacks, path=path if path else _("не найден"))
                )
            )
            info.setObjectName("Subtitle")
            lay.addWidget(info)
            lay.addWidget(_hline())
            box = QPlainTextEdit()
            box.setObjectName("Log")
            box.setReadOnly(True)
            box.setMaximumHeight(16777215)
            box.setPlainText(text)
            lay.addWidget(box, 1)

            bar = QHBoxLayout()
            copy = QPushButton(_("Копировать"))
            copy.setObjectName("Ghost")
            copy.setEnabled(bool(to_add))
            copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
            bar.addWidget(copy)
            apply_btn = QPushButton(_("Применить (бэкап)"))
            apply_btn.setObjectName("Accent")
            apply_btn.setEnabled(bool(to_add and path))

            def do_apply():
                if (
                    QMessageBox.question(
                        dlg,
                        _("Применить настройки?"),
                        _(
                            "Добавить недостающие рекомендованные ключи в settings.json?\n"
                            "Существующие настройки не изменятся, будет сделан бэкап."
                        ),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    != QMessageBox.StandardButton.Yes
                ):
                    return
                ok, msg = apply_settings(path, to_add)
                log.info("Автонастройка: %s", msg.replace("\n", " | "))
                (QMessageBox.information if ok else QMessageBox.warning)(
                    dlg, _("Автонастройка"), msg
                )

            apply_btn.clicked.connect(do_apply)
            bar.addWidget(apply_btn)
            bar.addStretch()
            close = QPushButton(_("Закрыть"))
            close.setObjectName("Ghost")
            close.clicked.connect(dlg.accept)
            bar.addWidget(close)
            lay.addLayout(bar)
            dlg.exec()

        def _update_selcount(self):
            """Чип «выбрано N / M» в шапке секции стеков."""
            if hasattr(self, "sel_count"):
                self.sel_count.setText(
                    _("выбрано {n} / {m}").format(n=len(self._selected()), m=len(self.cat_checks))
                )

        def _set_savings_tooltip(self, disabled, n_calibrated: int):
            """Объяснить, откуда взялось число экономии. Пользователь вправе
            знать, что перед ним: прикидка по таблице или его собственные
            замеры — доверие к цифре важнее самой цифры."""
            cats_off = {
                c for e in disabled if (c := ext_index.get(e)) is not None and c != "always_on"
            }
            total = len(cats_off)
            if not total:
                tip = _("Ничего не выключается — экономить нечего.")
            elif n_calibrated >= total:
                tip = _(
                    "Все {n} выключаемых стеков посчитаны по твоим прошлым "
                    "замерам памяти — это не прикидка."
                ).format(n=total)
            elif n_calibrated:
                tip = _(
                    "По твоим замерам посчитано {n} стеков из {total}, "
                    "остальные — по таблице нагрузки. Чем чаще запускаешь "
                    "разные наборы, тем точнее число."
                ).format(n=n_calibrated, total=total)
            else:
                tip = _(
                    "Пока это прикидка по таблице нагрузки стеков. После "
                    "нескольких запусков разных наборов лаунчер посчитает "
                    "цену каждого стека по фактическим замерам."
                )
            for w in (self.savings_num, self.savings_unit):
                w.setToolTip(tip)

        def _set_hero(self, number, unit, en_txt, dis_txt, extra_txt=""):
            self.savings_num.setText(str(number))
            self.savings_unit.setText(unit)
            self.stat_en.setText(en_txt)
            self.stat_en.setVisible(bool(en_txt))
            self.stat_dis.setText(dis_txt)
            self.stat_dis.setVisible(bool(dis_txt))
            self.stat_extra.setText(extra_txt)
            self.stat_extra.setVisible(bool(extra_txt))

        def _update_summary(self):
            self._update_selcount()
            if self._bare():
                self._set_hero("MAX", "", _("голый режим"), _("все расширения выключены"))
                self.b_run.setText(_("Запустить (голый режим)"))
                return
            if not self.installed:
                self._set_hero("—", "", _("нет списка расширений"), "")
                self.b_run.setText(_("Запустить VS Code"))
                return
            dis = self._disabled_list()
            en = len(self.installed) - len(dis)
            # Оценка теперь опирается на СОБСТВЕННЫЕ замеры: если два прошлых
            # запуска отличались одним стеком, его цена известна точно, а не
            # взята из таблицы «тяжёлый/средний/лёгкий».
            saved, n_calibrated = _w.estimate_saved_mb(dis, ext_index, cfg)
            self._set_savings_tooltip(dis, n_calibrated)
            # Фактические замеры, если этот набор уже запускали (#6/#2).
            sig = selection_signature(self._selected(), self._bare())
            extra = ""
            sav = measured_savings_mb(cfg, sig)
            fp = lookup_footprint(cfg, sig)
            if sav:
                self._set_hero(
                    sav,
                    _("МБ"),
                    _("включено {en}").format(en=en),
                    _("выключится {dis}").format(dis=len(dis)),
                    _("реально · оценка ~{saved}").format(saved=saved),
                )
            else:
                extra = _("замерено {mb} МБ").format(mb=fp["mb"]) if fp else ""
                self._set_hero(
                    saved,
                    _("МБ"),
                    _("включено {en}").format(en=en),
                    _("выключится {dis}").format(dis=len(dis)),
                    extra,
                )
            self.b_run.setText(
                _("Запустить · −{dis}").format(dis=len(dis)) if dis else _("Запустить VS Code")
            )

        def _toggle_tray_setting(self):
            """Сохранить настройки трея сразу: это переключатели поведения окна,
            а не параметры конкретного запуска — ждать «Запустить» незачем."""
            cfg["tray"] = self.tray_cb.isChecked()
            cfg["close_to_tray"] = self.close_tray_cb.isChecked()
            self.close_tray_cb.setEnabled(self.tray_cb.isChecked())
            # Применяем сразу, не дожидаясь перезапуска: иначе включённое
            # «сворачивать в трей» пряталo бы окно, а Qt тут же завершал
            # приложение как «последнее окно закрыто».
            app = QApplication.instance()
            if app is not None and self._tray is not None:
                app.setQuitOnLastWindowClosed(not self.close_tray_cb.isChecked())
            save_config(cfg)

        def _cmd_kwargs(self) -> dict:
            return {
                "profile": self.profile_edit.text().strip(),
                "disable_gpu": self.gpu_cb.isChecked(),
                "bare": self._bare(),
            }

        def _plan_options(self) -> dict:
            """Опции запуска в форме, которую понимает quicklaunch.plan_launch.
            Отличается от _cmd_kwargs только именем ключа для GPU — там оно
            повторяет параметр build_launch_*, здесь — поле пресета."""
            return {
                "folder": self.folder_edit.text().strip(),
                "new_window": self.newwin_cb.isChecked(),
                "kill": self.kill_cb.isChecked(),
                "profile": self.profile_edit.text().strip(),
                "gpu_off": self.gpu_cb.isChecked(),
                "bare": self._bare(),
            }

        def _browse(self):
            d = QFileDialog.getExistingDirectory(self, _("Выбери папку проекта"))
            if d:
                self.folder_edit.setText(d.replace("/", "\\"))
                self._suggest_for_folder(self.folder_edit.text().strip())

        def _browse_workspace(self):
            """Выбрать .code-workspace — многопапочный проект VS Code. Он
            открывается той же позиционной аргументацией, что и папка, но
            раньше указать его было нельзя: диалог пускал только каталоги."""
            f, _filt = QFileDialog.getOpenFileName(
                self,
                _("Выбери файл рабочей области"),
                "",
                _("VS Code workspace (*.code-workspace);;Все файлы (*.*)"),
            )
            if f:
                self.folder_edit.setText(f.replace("/", "\\"))
                self._suggest_for_folder(self.folder_edit.text().strip())

        # --- перетаскивание папки/воркспейса в окно ----------------------
        def dragEnterEvent(self, e):
            """Принимаем перетаскивание папки или файла .code-workspace: это
            самый короткий путь «открыть вот этот проект» — не надо ни искать
            его в диалоге, ни копировать путь."""
            if e.mimeData().hasUrls() and any(u.isLocalFile() for u in e.mimeData().urls()):
                e.acceptProposedAction()

        def dragMoveEvent(self, e):
            if e.mimeData().hasUrls():
                e.acceptProposedAction()

        def dropEvent(self, e):
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            if not paths:
                return
            target = paths[0]
            try:
                p = Path(target)
                # Бросили обычный файл (не воркспейс) — открываем его папку:
                # человек тащил проект, а не конкретный файл.
                if p.is_file() and p.suffix.lower() != ".code-workspace":
                    target = str(p.parent)
            except Exception:
                pass
            self.folder_edit.setText(target.replace("/", "\\"))
            self._suggest_for_folder(target)
            self.log.appendPlainText(_("Папка проекта: {folder}").format(folder=target))
            e.acceptProposedAction()

        def _use_recent(self, path: str):
            self.folder_edit.setText(path)
            self._suggest_for_folder(path)

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
                    body = _(
                        "Выключается {n} расширений из невыбранных стеков. always_on "
                        "и всё, чего нет в карте, останется включённым."
                    ).format(n=len(dis))
                else:
                    body = _("Ничего не выключается — всё установленное останется включённым.")

            lines = []
            for cat, exts in groups:
                title = cat_title(cats.get("categories", {}).get(cat, {}), cat)
                lines.append(f"— {title} ({len(exts)}) —")
                lines.extend(f"    {e}" for e in exts)
                lines.append("")
            text = "\n".join(lines).strip()

            dlg = QDialog(self)
            dlg.setWindowTitle(_("Что будет выключено"))
            dlg.resize(560, 560)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(18, 18, 18, 16)
            lay.setSpacing(12)
            ttl = QLabel(_("Что будет выключено"))
            ttl.setObjectName("Title")
            lay.addWidget(ttl)
            note = _wrap(QLabel(body))
            note.setObjectName("Subtitle")
            lay.addWidget(note)
            lay.addWidget(_hline())
            box = QPlainTextEdit()
            box.setObjectName("Log")
            box.setReadOnly(True)
            box.setMaximumHeight(16777215)
            box.setPlainText(text)
            lay.addWidget(box, 1)
            bar = QHBoxLayout()
            copy = QPushButton(_("Копировать список"))
            copy.setObjectName("Ghost")
            copy.setEnabled(bool(text))
            copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
            bar.addWidget(copy)
            bar.addStretch()
            close = QPushButton(_("Закрыть"))
            close.setObjectName("Accent")
            close.clicked.connect(dlg.accept)
            bar.addWidget(close)
            lay.addLayout(bar)
            dlg.exec()

        def _show_cmd(self):
            # Сам лаунчер запускает Code.exe напрямую (без оболочки), но здесь
            # показываем эквивалентную команду для cmd — её удобно скопировать
            # в скрипт/ярлык. Помечаем это явно, чтобы не вводить в заблуждение.
            cmd = build_launch_command(
                code_cli or "code",
                self._disabled_list(),
                self.folder_edit.text().strip(),
                self.newwin_cb.isChecked(),
                self.kill_cb.isChecked(),
                **self._cmd_kwargs(),
            )
            self._text_dialog(
                _("Команда запуска"),
                _("Эквивалент для cmd (сам лаунчер запускает Code.exe напрямую, без оболочки):"),
                cmd,
            )

        def _run(self):
            if not code_cli:
                QMessageBox.critical(self, _("Ошибка"), _("Не найден CLI VS Code (code.cmd)."))
                return
            folder = self.folder_edit.text().strip()
            if folder and not Path(folder).exists():
                # Не открываем молча несуществующий путь — легче заметить опечатку
                # и это отсекает попытку подсунуть в поле что-то, что не является путём.
                r = QMessageBox.question(
                    self,
                    _("Папка не найдена"),
                    _("Путь не существует:\n{folder}\n\nОткрыть VS Code без папки?").format(
                        folder=folder
                    ),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if r != QMessageBox.StandardButton.Yes:
                    return
                self.folder_edit.clear()
            if self.kill_cb.isChecked():
                # Текст должен совпадать с тем, что реально произойдёт: при
                # мягком закрытии VS Code сам спросит про несохранённое, и
                # пугать потерей файлов здесь неправильно.
                if self.soft_cb.isChecked():
                    body = _(
                        "Сейчас VS Code получит обычный запрос на закрытие — он "
                        "сам спросит про несохранённые файлы. Когда закроется, "
                        "откроется новое окно с выбранным набором.\n\n"
                        "Продолжить?"
                    )
                else:
                    body = _(
                        "Сейчас будут ПРИНУДИТЕЛЬНО закрыты все окна VS Code, "
                        "затем откроется новое с выбранным набором.\n\n"
                        "Сохранил несохранённые файлы? Продолжить?"
                    )
                r = QMessageBox.question(
                    self,
                    _("Закрыть VS Code?"),
                    body,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if r != QMessageBox.StandardButton.Yes:
                    return
            if not self._confirm_stack_conflicts(folder):
                return
            bare = self._bare()
            # Один путь сборки запуска с CLI и треем (quicklaunch.plan_launch),
            # иначе три места считают выключаемое по чуть-чуть по-разному.
            # Списки отдаём готовыми: окно уже держит их в руках.
            plan = plan_launch(
                code_cli,
                cfg,
                ext_index,
                self._selected(),
                self._plan_options(),
                installed=self.installed,
                dep_map=self._get_dep_map(),
            )
            dis, args = plan["disabled"], plan["args"]

            def do_launch():
                try:
                    launch_detached(code_cli, args)  # без оболочки, напрямую Code.exe
                except Exception as e:
                    log.exception("Ошибка запуска")
                    QMessageBox.critical(self, _("Ошибка запуска"), str(e))
                    return
                log.info(
                    "Запуск: %s", "голый режим" if bare else f"выключено {len(dis)} расширений"
                )
                self.log.appendPlainText(
                    _("Запуск: голый режим (все расширения выкл). OK.")
                    if bare
                    else _("Запуск: выключено {n} расширений. OK.").format(n=len(dis))
                )
                # #6: замерить фактический footprint этого набора чуть погодя.
                self._pending_record_sig = selection_signature(self._selected(), bare)
                # #2: запуск без выключенных стеков (и не голый) — это базлайн
                # «всё включено», от которого считается реальная экономия.
                self._pending_is_baseline = (not bare) and len(dis) == 0
                QTimer.singleShot(6000, self._probe_memory)  # новый footprint

            if self.kill_cb.isChecked():
                if self.soft_cb.isChecked():
                    self._graceful_close_then(do_launch)  # дать сохранить, дождаться
                else:
                    kill_vscode(code_cli)  # жёстко (/F), затем стартуем с паузой
                    self.log.appendPlainText(_("Закрываю VS Code…"))
                    QTimer.singleShot(1800, do_launch)  # не блокируем интерфейс
            else:
                do_launch()
            self._persist()

        def _confirm_stack_conflicts(self, folder: str) -> bool:
            """cpptools и clangd вместе дают двойные подсказки и двойную память,
            если в проекте IntelliSense cpptools не отключён. Спросить."""
            if self._bare():
                return True
            from .categories import stack_conflicts

            pairs = stack_conflicts(self._selected(), cats)
            if not pairs:
                return True
            if {"cpp_cpptools", "cpp_clangd"} <= set(self._selected()) and folder:
                try:
                    from .detect import _loads_jsonc

                    ws = Path(folder) / ".vscode" / "settings.json"
                    data = _loads_jsonc(ws.read_text(encoding="utf-8-sig")) if ws.is_file() else {}
                    if (
                        isinstance(data, dict)
                        and data.get("C_Cpp.intelliSenseEngine") == "disabled"
                    ):
                        return True  # в проекте cpptools уже без IntelliSense
                except Exception:
                    pass
            names = "; ".join(
                " + ".join(cat_title(cats["categories"].get(k, {}), k) for k in pair)
                for pair in pairs
            )
            box = QMessageBox(self)
            box.setWindowTitle(_("Стеки мешают друг другу"))
            box.setText(
                _(
                    "Включены вместе: {pairs}.\n\nДва движка подсказок C++ дублируют "
                    "подсказки и память. Оставьте один, или настройте проект (кнопка "
                    "«C++…» → «Проект» с clangd) — там IntelliSense cpptools отключается "
                    "только для этой папки."
                ).format(pairs=names)
            )
            run = box.addButton(_("Запустить как есть"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(_("Отмена"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            return box.clickedButton() is run

        def _graceful_close_then(self, cont):
            """Мягко закрыть VS Code (с запросом на сохранение) и дождаться выхода,
            затем cont(). Если через ~15 с редактор ещё открыт (скорее всего висит
            диалог сохранения) — отменяем запуск, ничего не потеряв."""
            kill_vscode(code_cli, graceful=True)
            self.log.appendPlainText(_("Прошу VS Code закрыться (ответь на запрос сохранения)…"))
            self._soft_tries = 0

            def check():
                self._soft_tries += 1
                if vscode_process_count(code_cli) == 0:
                    self.log.appendPlainText(_("VS Code закрыт. Запускаю…"))
                    cont()
                    return
                if self._soft_tries >= 20:  # ~15 секунд
                    self.log.appendPlainText(
                        _(
                            "VS Code всё ещё открыт — запуск отменён. Закрой окна "
                            "(или ответь на запрос сохранения) и нажми «Запустить» снова."
                        )
                    )
                    return
                QTimer.singleShot(750, check)

            QTimer.singleShot(750, check)

        def _reload_presets(self):
            # Меню в трее показывает те же пресеты — пересобираем и его, иначе
            # только что сохранённый пресет не появился бы там до перезапуска.
            tray = getattr(self, "_tray", None)
            if tray is not None:
                tray.rebuild_menu()
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
            name, ok = QInputDialog.getText(self, _("Сохранить пресет"), _("Имя пресета:"))
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
                QMessageBox.information(self, _("Экспорт"), _("Пресетов пока нет."))
                return
            path, _filt = QFileDialog.getSaveFileName(
                self, _("Экспорт пресетов"), "vscode_launcher_presets.json", "JSON (*.json)"
            )
            if not path:
                return
            try:
                Path(path).write_text(
                    json.dumps(presets, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                self.log.appendPlainText(
                    _("Экспортировано пресетов: {n} → {path}").format(n=len(presets), path=path)
                )
            except Exception as e:
                QMessageBox.critical(self, _("Ошибка экспорта"), str(e))

        def _import_presets(self):
            path, _filt = QFileDialog.getOpenFileName(
                self, _("Импорт пресетов"), "", "JSON (*.json)"
            )
            if not path:
                return
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError(_("ожидается объект вида имя: [категории]"))
                # #4: значение пресета — список ключей ИЛИ словарь-профиль.
                raw = {str(k): v for k, v in data.items() if isinstance(v, (list, dict))}
            except Exception as e:
                QMessageBox.critical(self, _("Ошибка импорта"), str(e))
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
                incoming[name] = (
                    {**value, "stacks": cleaned} if isinstance(value, dict) else cleaned
                )
            if not incoming:
                self.log.appendPlainText(_("Импорт: в файле нет пресетов."))
                return
            cfg.setdefault("presets", {}).update(incoming)
            save_config(cfg)
            self._reload_presets()
            msg = _("Импортировано пресетов: {n}").format(n=len(incoming))
            if dropped_keys:
                sample = ", ".join(sorted(dropped_keys)[:6])
                tail = "…" if len(dropped_keys) > 6 else ""
                msg += _(" (пропущено неизвестных ключей категорий: {n} — {sample}{tail})").format(
                    n=len(dropped_keys), sample=sample, tail=tail
                )
            self.log.appendPlainText(msg)

        def _make_shortcut(self):
            """#5: сохранить .cmd-ярлык, открывающий VS Code с выбранным пресетом
            через тихий CLI-режим — один клик, без окна лаунчера."""
            name = self.preset_box.currentData()
            if not name:
                QMessageBox.information(
                    self,
                    _("Ярлык"),
                    _("Сначала выбери пресет в списке — ярлык открывает VS Code с ним."),
                )
                return
            path, _filt = QFileDialog.getSaveFileName(
                self, _("Сохранить ярлык"), f"{name}.cmd", "CMD (*.cmd)"
            )
            if not path:
                return
            try:
                body = build_shortcut_cmd(_launcher_invocation(), name)
                if not path.lower().endswith(".cmd"):
                    path += ".cmd"
                Path(path).write_text(body, encoding="utf-8")
                self.log.appendPlainText(_("Ярлык создан: {path}").format(path=path))
            except Exception as e:
                QMessageBox.critical(self, _("Ошибка"), str(e))

        def _export_profile(self):
            """#4: сохранить текущий выбор как нативный профиль VS Code
            (.code-profile). В профиль кладём ВКЛючённые расширения — тот же
            набор, что остался бы включённым при запуске через лаунчер, только
            в виде постоянного профиля, а не флагов --disable-extension."""
            if not self.installed:
                QMessageBox.information(
                    self, _("Профиль VS Code"), _("Список расширений ещё не загружен.")
                )
                return
            disabled = set(self._disabled_list())
            enabled = [e for e in self.installed if e not in disabled]
            keys = sorted(self._selected())
            default_name = "stacks-" + ("-".join(keys) if keys else "core")
            path, _filt = QFileDialog.getSaveFileName(
                self,
                _("Экспорт профиля VS Code"),
                f"{default_name}.code-profile",
                "VS Code Profile (*.code-profile)",
            )
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
                        n=len(enabled), path=path
                    )
                )
                QMessageBox.information(
                    self,
                    _("Профиль VS Code"),
                    _(
                        "Готово. В VS Code открой палитру команд и выполни "
                        "«Profiles: Import Profile…», затем выбери этот файл.\n\n"
                        "Расширений в профиле: {n}"
                    ).format(n=len(enabled)),
                )
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
                if getattr(self, "_page", "launch") == "launch" and self.b_run.isEnabled():
                    self._run()
                return
            if e.key() == Qt.Key.Key_Escape:
                self.close()
                return
            if e.key() == Qt.Key.Key_F and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.search_edit.setFocus()
                self.search_edit.selectAll()
                return
            super().keyPressEvent(e)

        def _reap_installer(self, worker):
            # Убираем завершившийся поток установки/удаления, чтобы список не рос.
            if worker in self._install_threads:
                self._install_threads.remove(worker)

        def request_quit(self):
            """Выйти по-настоящему (пункт «Выход» в трее): закрыть окно, не
            пряча его в трей."""
            self._quit_requested = True
            self.close()

        def closeEvent(self, e):
            # Окно с включённым «сворачивать в трей» не закрывается по крестику,
            # а прячется: лаунчер остаётся под рукой, а пресеты — в одном клике.
            if (
                not self._quit_requested
                and self._tray is not None
                and cfg.get("close_to_tray", False)
            ):
                e.ignore()
                self.hide()
                self._tray.showMessage(
                    "VS Code Launcher",
                    _("Лаунчер свёрнут в трей. Пресеты — правым кликом по значку."),
                    QSystemTrayIcon.MessageIcon.Information,
                    2500,
                )
                return
            try:  # запоминаем геометрию окна
                cfg["geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
                save_config(cfg)
            except Exception:
                pass
            # Дождёмся фоновых потоков, иначе Qt ругается «QThread destroyed while
            # running». Ждём с потолком, чтобы окно не зависало на сетевой установке.
            threads = [
                getattr(self, "_mem", None),
                getattr(self, "_loader", None),
                getattr(self, "_upd", None),
                getattr(self, "_dl", None),  # загрузка обновления: тоже дождаться
                getattr(self, "_sizes", None),  # обход папки расширений
                getattr(self, "_status", None),  # code --status
            ]
            threads += list(self._install_threads)
            for t in threads:
                if t is not None and t.isRunning():
                    t.wait(2000)
            super().closeEvent(e)

    return Launcher


# --- точка входа -----------------------------------------------------------


def _single_instance_guard(app_id: str = "vscode-launcher-single"):
    """Не поднимать второй лаунчер: если он уже запущен, разбудить его окно.

    Со значком в трее это стало обязательным — иначе «запустил ещё раз» даёт
    два значка и два окна, спорящих за один конфиг (кто последним сохранил, того
    и настройки). Возвращает (сервер, уже_запущен). Сервер надо держать живым всё
    время работы приложения, иначе имя освободится."""
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket

    probe = QLocalSocket()
    probe.connectToServer(app_id)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(300)
        probe.disconnectFromServer()
        return None, True
    # Прошлый экземпляр мог упасть и оставить имя занятым — снимаем.
    QLocalServer.removeServer(app_id)
    server = QLocalServer()
    server.listen(app_id)
    return server, False


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
    set_language(cfg.get("lang", "ru"))  # #7: до сборки UI, чтобы _() перевёл строки
    # Заполняется в конце run_gui (см. rebuild). Метод _switch_language дёргает
    # его, чтобы пересобрать окно на новом языке. Объявляем здесь, чтобы имя
    # стало локальным run_gui и попало в замыкание методов Launcher.
    _lang_switch = {"fn": None}
    descriptions = load_descriptions()
    log.info(
        "Старт v%s · CLI=%s · тема=%s%s",
        __version__,
        code_cli,
        cfg.get("theme", "dark"),
        f" · categories.json: {cats_err}" if cats_err else "",
    )
    # Дубли в карте — тихая мина: build_ext_index молча оставляет последнее
    # назначение, и стек, куда расширение было положено раньше, теряет его.
    # Пишем в лог сразу и покажем предупреждение в окне.
    if duplicates:
        preview = ", ".join(f"{e} ({'/'.join(k)})" for e, k in sorted(duplicates.items())[:3])
        more = "…" if len(duplicates) > 3 else ""
        log.warning("В categories.json дубли расширений: %d (%s%s)", len(duplicates), preview, more)

    # Чистим «мёртвые» ключи категорий в пресетах/последнем выборе (например,
    # если категорию переименовали в categories.json). Только когда карта
    # загрузилась — иначе пустой набор ключей стёр бы все пресеты.
    if not cats_err:
        valid_keys = set(cats.get("categories", {}))
        dirty = False
        for name, value in list(cfg.get("presets", {}).items()):
            stacks = preset_stacks(value)  # #4: пресет может быть списком или словарём
            cleaned = [k for k in stacks if k in valid_keys]
            if cleaned != stacks:
                cfg["presets"][name] = (
                    {**value, "stacks": cleaned} if isinstance(value, dict) else cleaned
                )
                dirty = True
        last = cfg.get("last_selected", [])
        cleaned_last = [k for k in last if k in valid_keys]
        if cleaned_last != last:
            cfg["last_selected"] = cleaned_last
            dirty = True
        if dirty:
            save_config(cfg)
            log.info("Очищены несуществующие ключи категорий в конфиге")

    Launcher = _launcher_factory(
        cats, cats_err, cfg, ext_index, code_cli, descriptions, duplicates, log, _lang_switch
    )

    app = QApplication(sys.argv)
    server, already_running = _single_instance_guard()
    if already_running:
        log.info("Лаунчер уже запущен — активирую его окно")
        return
    app.setStyle("Fusion")
    font = QFont()
    font.setPointSize(10)
    app.setFont(font)
    theme_name = cfg.get("theme", "dark")
    if theme_name not in PALETTES:
        theme_name = "dark"
    app.setStyleSheet(build_qss(make_palette(theme_name, cfg.get("palette", "mocha"))))

    def build_window():
        win = Launcher()
        if ICON_FILE.exists():
            win.setWindowIcon(QIcon(str(ICON_FILE)))
        win.show()
        apply_titlebar(win, win._theme == "dark")  # после show(), когда есть нативный hwnd
        return win

    # #7: смена языка пересобирает окно (текст виджетов задаётся при сборке).
    # Держим текущее окно в holder, чтобы кнопка языка могла заменить его,
    # перенеся геометрию и сохранённый выбор.
    holder = {"w": None}
    tray_holder = {"t": None}

    def rebuild(state=None):
        old = holder["w"]
        geo = old.saveGeometry() if old is not None else None
        nw = build_window()
        if geo is not None:
            nw.restoreGeometry(geo)
        if state:
            nw.apply_ui_state(state)  # не терять несохранённый выбор при смене языка
        holder["w"] = nw
        if old is not None:
            old._quit_requested = True  # старое окно закрываем, а не прячем в трей
            old.close()
            old.deleteLater()
        if tray_holder["t"] is not None:
            tray_holder["t"].attach(nw)

    _lang_switch["fn"] = rebuild

    w = build_window()
    holder["w"] = w

    # Значок в трее: пресеты запускаются без открытия окна. Создаём после
    # первого окна, потому что меню трея говорит именно с ним.
    if cfg.get("tray", True) and QSystemTrayIcon.isSystemTrayAvailable():
        try:
            from .gui_tray import LauncherTray

            def _quit_all():
                # Через окно, а не app.quit(): так сработает closeEvent и
                # геометрия с настройками успеет сохраниться.
                cur = holder["w"]
                if cur is not None:
                    cur.request_quit()
                app.quit()

            tray = LauncherTray(w, cfg, ext_index, lambda: code_cli, _quit_all)
            tray.show()
            tray_holder["t"] = tray
            w._tray = tray
            # Не выходить, когда последнее окно спрятано в трей: иначе
            # «свернуть в трей» мгновенно завершало бы приложение.
            app.setQuitOnLastWindowClosed(not cfg.get("close_to_tray", False))
        except Exception:
            log.exception("Не удалось создать значок в трее")

    # Второй запуск лаунчера не поднимает второе окно, а будит это.
    if server is not None:

        def _on_new_connection():
            conn = server.nextPendingConnection()
            if conn is not None:
                conn.disconnectFromServer()
            cur = holder["w"]
            if cur is not None:
                cur.showNormal()
                cur.raise_()
                cur.activateWindow()

        server.newConnection.connect(_on_new_connection)

    _shot = os.environ.get("LAUNCHER_SHOT")  # dev-хук: снять окно в PNG и выйти
    if _shot:
        sw, sh = os.environ.get("LAUNCHER_W"), os.environ.get("LAUNCHER_H")
        if sw and sh:
            w.resize(int(sw), int(sh))

        def _grab():
            holder["w"].grab().save(_shot)
            app.quit()

        QTimer.singleShot(1800, _grab)
    sys.exit(app.exec())
