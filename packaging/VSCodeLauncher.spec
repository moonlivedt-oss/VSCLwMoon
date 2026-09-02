# -*- mode: python ; coding: utf-8 -*-
# Сборка одиночного exe:  pyinstaller packaging/VSCodeLauncher.spec --noconfirm
# Результат: dist/VSCodeLauncher.exe
#
# Сам spec лежит в packaging/, а исходники — в корне. Пути к файлам считаем
# от корня репозитория (ROOT), а не от текущей папки запуска, чтобы сборка
# работала из любого CWD (важно для CI и Собрать_exe.bat).
#
# data/ и assets/ кладутся внутрь бандла и распаковываются в _MEIPASS при
# запуске (core.py это учитывает через sys.frozen). launcher_config.json
# пишется рядом с exe и переживает перезапуск.
#
# Иконка exe: assets/app.ico (сгенерирована из banner.png). Заменить —
# положи свой .ico по этому пути.

import os

# SPECPATH — папка этого spec (packaging/); ROOT — корень репозитория.
ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, 'vscode_launcher.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, 'data'), 'data'),
           (os.path.join(ROOT, 'assets'), 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VSCodeLauncher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX выключен намеренно: сжатые им exe часто ловят ложные срабатывания
    # Windows Defender/антивирусов. Для раздачи важнее отсутствие блокировок,
    # чем ~10 МБ размера.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # оконное приложение, без консоли
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, 'assets', 'app.ico'),
    version=os.path.join(SPECPATH, 'version_info.txt'),   # свойства файла: версия, описание, автор
)
