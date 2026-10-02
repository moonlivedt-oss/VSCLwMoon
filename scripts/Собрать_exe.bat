@echo off
chcp 65001 >nul
setlocal
rem Сборка одиночного VSCodeLauncher.exe в папку dist\ (в корне репозитория).
rem Скрипт лежит в scripts\ - переходим в корень, чтобы dist\ и build\ легли туда.
cd /d "%~dp0.."
rem Ищем Python, в котором установлен PyQt6: сначала через py-лаунчер (3.14, 3.13,
rem 3.12), затем python из PATH. Версия жёстко не зашита: на другом компьютере
rem может стоять не та, что у автора.
set "PY="
set "PYW="
for %%V in (3.14 3.13 3.12) do if not defined PY (
    py -%%V -c "import PyQt6.QtWidgets" >nul 2>&1 && set "PY=py -%%V" && set "PYW=pyw -%%V"
)
if not defined PY (
    python -c "import sys, PyQt6.QtWidgets; sys.exit(sys.version_info < (3, 12))" >nul 2>&1 && set "PY=python" && set "PYW=pythonw"
)
if not defined PY (
    echo.
    echo Не найден Python 3.12+ с установленным PyQt6.
    echo Установите Python с python.org и выполните:  py -m pip install PyQt6
    echo.
    pause
    exit /b 1
)
echo Сборка через: %PY%
%PY% -m pip install --upgrade pyinstaller || goto :fail
%PY% -m PyInstaller packaging\VSCodeLauncher.spec --noconfirm || goto :fail
if not exist "dist\VSCodeLauncher.exe" goto :fail
rem Архив для раздачи: exe и диагностика рядом с ним. Скрипты запуска и сборки из
rem исходников в архив не кладём - без исходников они бесполезны.
powershell -NoProfile -Command "$f = @('dist\VSCodeLauncher.exe') + @(Get-ChildItem scripts -File | Where-Object { $_.Extension -in '.bat','.ps1' -and -not (Select-String -Path $_.FullName -Pattern 'vscode_launcher.py|PyInstaller' -Quiet) } | ForEach-Object { $_.FullName }); Compress-Archive -Force -Path $f -DestinationPath 'dist\VSCodeLauncher.zip'"
if errorlevel 1 echo Не удалось обновить dist\VSCodeLauncher.zip
echo.
echo Готово: %CD%\dist\VSCodeLauncher.exe
pause
exit /b 0

:fail
echo.
echo Сборка не удалась - причина в сообщениях выше.
echo Если запущен dist\VSCodeLauncher.exe (в том числе в трее), закройте его и повторите.
pause
exit /b 1
