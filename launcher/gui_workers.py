# -*- coding: utf-8 -*-
"""Фоновые QThread'ы: чтение списка расширений, замер памяти,
последовательная установка/удаление.

Всё, что уходит в фон — здесь. Окно не подмерзает на старте (ExtLoader),
не блокируется на tasklist (MemProbe) и на длинных установках (Installer).
Каждый поток эмитит сигналы, GUI слушает их и меняет UI из главного треда.
"""
from PyQt6.QtCore import QThread, pyqtSignal

from .toolchains import (
    install_package, install_package_elevated, uninstall_package, upgrade_package,
)
from .updates import check_for_update
from .vscode import (
    code_footprint_mb, install_extension, load_installed, uninstall_extension,
)


class ExtLoader(QThread):
    """Фоновая загрузка списка расширений — чтобы окно не подмерзало на старте."""
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
        mb, n = code_footprint_mb(self._cli)
        self.measured.emit(mb, n)


class UpdateCheck(QThread):
    """Фоновая проверка обновлений на GitHub (#8). Никогда не роняет окно:
    сеть изолирована в updates.check_for_update, наружу — только тег новой
    версии (или пустая строка, если новее ничего нет)."""
    done = pyqtSignal(str)

    def __init__(self, current: str):
        super().__init__()
        self._current = current

    def run(self):
        newer = check_for_update(self._current)
        self.done.emit(newer or "")


class UpdateDownloader(QThread):
    """Фоновое скачивание и проверка новой версии (#10). Сама сеть и сверка
    SHA256 — в updates; наружу летят прогресс и итог. Окно не подмерзает на
    скачивании десятков МБ."""
    progress = pyqtSignal(int, int)      # получено, всего (0 — размер неизвестен)
    done = pyqtSignal(bool, str, str)    # успех, сообщение, путь к скачанному

    def __init__(self, dest):
        super().__init__()
        self._dest = str(dest)

    def run(self):
        from .updates import download_and_verify, fetch_latest_release_info
        info = fetch_latest_release_info()
        if not info:
            self.done.emit(False, "Не удалось получить информацию о релизе "
                                  "(нет сети или в релизе нет .exe).", "")
            return
        ok, msg = download_and_verify(
            info, self._dest,
            progress=lambda got, total: self.progress.emit(got, total))
        self.done.emit(ok, msg, self._dest if ok else "")


class Installer(QThread):
    """Последовательная установка/удаление в фоне.
    action: 'install' | 'uninstall'.

    progress(i, total) шлётся ПЕРЕД обработкой i-го элемента (для строки
    «Устанавливаю i/total…»). Отмена (cancel) прерывает между элементами —
    текущий code-процесс не убиваем, но следующие не запускаем; all_done
    приходит в любом случае, поэтому UI всегда разблокируется."""
    progress = pyqtSignal(int, int)
    one_done = pyqtSignal(str, bool, str)
    all_done = pyqtSignal()

    def __init__(self, cli, ids, action="install"):
        super().__init__()
        self._cli = cli
        self._ids = list(ids)
        self._action = action
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        fn = install_extension if self._action == "install" else uninstall_extension
        total = len(self._ids)
        for idx, i in enumerate(self._ids, 1):
            if self._cancelled:
                break
            self.progress.emit(idx, total)
            ok, msg = fn(self._cli, i)
            self.one_done.emit(i, ok, msg)
        self.all_done.emit()


class ToolchainInstaller(QThread):
    """Последовательная установка языковых тулчейнов (winget) в фоне.

    Устройство повторяет Installer, но работает не с id расширений, а с
    объектами Package (toolchains.py). Установка одного пакета — минуты
    (скачивание сотен МБ), поэтому обязательно в фоне: окно не должно
    подмерзать. progress(i, total) шлётся ПЕРЕД обработкой i-го пакета;
    one_done(winget_id, ok, message) — после; all_done — всегда, даже при
    отмене, чтобы UI разблокировался. Отмена прерывает между пакетами:
    текущий winget-процесс не убиваем (иначе останется полу-установка),
    следующие не запускаем."""
    progress = pyqtSignal(int, int)
    one_done = pyqtSignal(str, bool, str)
    all_done = pyqtSignal()

    def __init__(self, packages, scope=None, action="install"):
        super().__init__()
        self._packages = list(packages)
        self._scope = scope
        self._action = action   # install | upgrade | uninstall
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total = len(self._packages)
        for idx, pkg in enumerate(self._packages, 1):
            if self._cancelled:
                break
            self.progress.emit(idx, total)
            if self._action == "upgrade":
                ok, msg = upgrade_package(pkg, scope=self._scope)
            elif self._action == "uninstall":
                ok, msg = uninstall_package(pkg)
            else:
                ok, msg = install_package(pkg, scope=self._scope)
            self.one_done.emit(pkg.winget_id, ok, msg)
        self.all_done.emit()


class FnWorker(QThread):
    """Выполнить произвольную функцию в фоне и вернуть результат (#5/#8).
    Для недолгих, но блокирующих операций (winget upgrade, опрос версий всех
    тулчейнов), которые нельзя звать из главного треда — окно подмёрзнет.
    Исключение не роняет поток: приходит в done как объект-исключение."""
    done = pyqtSignal(object)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            res = self._fn()
        except Exception as e:   # noqa: BLE001 — намеренно ловим всё, отдаём наружу
            res = e
        self.done.emit(res)


class ElevatedInstaller(QThread):
    """Установка одного пакета с правами администратора в фоне (#10). Показывает
    запрос UAC (внутри install_package_elevated) и ждёт завершения — поэтому в
    фоне, чтобы окно не подмерзало на время elevated-установки."""
    done = pyqtSignal(bool, str)

    def __init__(self, package, scope="machine"):
        super().__init__()
        self._package = package
        self._scope = scope

    def run(self):
        ok, msg = install_package_elevated(self._package, scope=self._scope)
        self.done.emit(ok, msg)
