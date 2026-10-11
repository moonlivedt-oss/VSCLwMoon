@echo off
chcp 65001 >nul
setlocal
rem Запуск лаунчера отдельным процессом (pythonw = без окна консоли), отвязанным от
rem терминала VS Code: опция "Закрыть VS Code" не убьёт сам лаунчер.
rem Скрипт лежит в scripts\, точка входа - в корне (на уровень выше).
set "APP=%~dp0..\vscode_launcher.py"
if not exist "%APP%" (
    echo Не найден файл: %APP%
    pause
    exit /b 1
)
rem Ищем Python, в котором установлен PyQt6: сначала через py-лаунчер (3.14, 3.13,
rem 3.12), затем python из PATH. Версия жёстко не зашита: на другом компьютере
rem может стоять не та, что у автора.
set "PY="
for %%V in (3.14 3.13 3.12) do if not defined PY (
    py -%%V -c "import PyQt6.QtWidgets" >nul 2>&1 && set "PY=py -%%V"
)
if not defined PY (
    python -c "import sys, PyQt6.QtWidgets; sys.exit(sys.version_info < (3, 12))" >nul 2>&1 && set "PY=python"
)
if defined PY goto :run

rem PyQt6 нигде нет: берём самый новый Python 3.12+ и ставим пакет сами (один раз).
for %%V in (3.14 3.13 3.12) do if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
)
if not defined PY (
    python -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo.
    echo Не найден Python 3.12 или новее.
    echo Установите его с https://www.python.org/downloads/ или скачайте готовый
    echo VSCodeLauncher.exe со страницы Releases - ему Python не нужен.
    echo.
    pause
    exit /b 1
)
echo Первый запуск: ставлю PyQt6 (один раз, нужен интернет)...
%PY% -m pip install --disable-pip-version-check "PyQt6>=6.6"
%PY% -c "import PyQt6.QtWidgets" >nul 2>&1 || (
    echo Не удалось поставить PyQt6. Текст ошибки - выше.
    pause
    exit /b 1
)

:run
rem Настоящий pythonw.exe рядом с python.exe: заглушка pyw из Microsoft Store
rem мелькает и не стартует.
set "PYW="
for /f "delims=" %%p in ('%PY% -c "import os, sys; print(os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'))"') do set "PYW=%%p"
if exist "%PYW%" (
    start "" "%PYW%" "%APP%"
) else (
    start "" %PY% "%APP%"
)
