# -*- mode: python ; coding: utf-8 -*-
# Сборка одиночного exe:  pyinstaller VSCodeLauncher.spec --noconfirm
# Результат: dist/VSCodeLauncher.exe
#
# data/ и assets/ кладутся внутрь бандла и распаковываются в _MEIPASS при
# запуске (core.py это учитывает через sys.frozen). launcher_config.json
# пишется рядом с exe и переживает перезапуск.
#
# Иконку exe можно задать через icon='assets/app.ico' (нужен .ico; PNG DWM
# не принимает). Оставлено пустым, чтобы сборка не требовала конвертации.

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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # оконное приложение, без консоли
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
