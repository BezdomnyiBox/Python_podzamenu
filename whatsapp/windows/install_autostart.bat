@echo off
setlocal EnableExtensions

REM Установка автозапуска WhatsApp Worker через Планировщик заданий Windows
REM Запускайте от имени пользователя офисного ПК (ПКМ -^> Запуск от имени администратора не обязателен)

set "TASK_NAME=PodzamenuWhatsAppWorker"
set "SCRIPT_DIR=%~dp0"
set "VBS_LAUNCHER=%SCRIPT_DIR%start_worker_hidden.vbs"

if not exist "%VBS_LAUNCHER%" (
    echo [ERROR] Не найден %VBS_LAUNCHER%
    exit /b 1
)

echo Удаление старой задачи (если есть)...
schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>&1

echo Создание задачи "%TASK_NAME%"...
schtasks /Create ^
    /TN "%TASK_NAME%" ^
    /TR "wscript.exe \"%VBS_LAUNCHER%\"" ^
    /SC ONLOGON ^
    /RL LIMITED ^
    /F

if errorlevel 1 (
    echo [ERROR] Не удалось создать задачу. Проверьте права и schtasks.
    pause
    exit /b 1
)

echo.
echo Готово. Воркер будет запускаться при входе пользователя в Windows.
echo Логи: ..\..\logs\whatsapp_worker.log
echo.
echo Первый раз выполните авторизацию WhatsApp:
echo   venv\Scripts\python.exe -m whatsapp.login
echo.
echo Запустить воркер сейчас:
schtasks /Run /TN "%TASK_NAME%"
echo.
pause
