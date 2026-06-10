@echo off
setlocal EnableExtensions

REM Автозапуск собранного .exe (запускать из папки PodzamenuWhatsApp)

set "TASK_NAME=PodzamenuWhatsAppWorker"
set "APP_DIR=%~dp0"
set "VBS_LAUNCHER=%APP_DIR%start_worker_exe_hidden.vbs"

if not exist "%APP_DIR%PodzamenuWhatsAppWorker.exe" (
    echo [ERROR] PodzamenuWhatsAppWorker.exe не найден в %APP_DIR%
    pause
    exit /b 1
)

schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>&1

schtasks /Create ^
    /TN "%TASK_NAME%" ^
    /TR "wscript.exe \"%VBS_LAUNCHER%\"" ^
    /SC ONLOGON ^
    /RL LIMITED ^
    /F

if errorlevel 1 (
    echo [ERROR] Не удалось создать задачу в Планировщике
    pause
    exit /b 1
)

echo Автозапуск настроен.
echo Сначала выполните PodzamenuWhatsAppLogin.exe для QR-кода.
schtasks /Run /TN "%TASK_NAME%"
pause
