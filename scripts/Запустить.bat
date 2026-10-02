@echo off
chcp 65001 >nul
setlocal
rem Запуск лаунчера отдельным процессом (pyw = без окна консоли), отвязанным от
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
start "" %PYW% "%APP%"
