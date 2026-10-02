@echo off
chcp 65001 >nul
setlocal
rem Диагностика C/C++ и VS Code на этом компьютере. Ничего не меняет и не ставит:
rem только читает настройки и собирает пробную программу во временной папке.
rem Итог - текстовый файл рядом со скриптом; его можно прислать автору.
rem Папку проекта можно перетащить на этот файл - тогда в отчёт попадут её .vscode.
if not exist "%~dp0diagnostics.ps1" (
    echo Не найден файл diagnostics.ps1 - он должен лежать рядом с этим скриптом.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0diagnostics.ps1" "%~1"
echo.
pause
