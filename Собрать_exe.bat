@echo off
rem Сборка одиночного VSCodeLauncher.exe в папку dist\
rem PyQt6 стоит в Python 3.14 -> собираем тем же интерпретатором.
py -3.14 -m pip install --upgrade pyinstaller
py -3.14 -m PyInstaller VSCodeLauncher.spec --noconfirm
echo.
echo Готово: dist\VSCodeLauncher.exe
pause
