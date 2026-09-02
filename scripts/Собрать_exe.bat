@echo off
rem Сборка одиночного VSCodeLauncher.exe в папку dist\ (в корне репозитория).
rem PyQt6 стоит в Python 3.14 -> собираем тем же интерпретатором.
rem Скрипт лежит в scripts\ — переходим в корень, чтобы dist\/build\ легли туда.
cd /d "%~dp0.."
py -3.14 -m pip install --upgrade pyinstaller
py -3.14 -m PyInstaller packaging\VSCodeLauncher.spec --noconfirm
echo.
echo Готово: dist\VSCodeLauncher.exe
pause
