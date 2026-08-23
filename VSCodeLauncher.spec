# -*- mode: python ; coding: utf-8 -*-
# Сборка одиночного exe:  pyinstaller VSCodeLauncher.spec --noconfirm
# Результат: dist/VSCodeLauncher.exe
#
# data/ и assets/ кладутся внутрь бандла и распаковываются в _MEIPASS при
# запуске (core.py это учитывает через sys.frozen). launcher_config.json
# пишется рядом с exe и переживает перезапуск.
#
# Иконка exe: assets/app.ico (сгенерирована из banner.png). Заменить —
# положи свой .ico по этому пути.

a = Analysis(
    ['vscode_launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('data', 'data'), ('assets', 'assets')],
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
    icon='assets/app.ico',
    version='version_info.txt',   # свойства файла: версия, описание, автор
)
