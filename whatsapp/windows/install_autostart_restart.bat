@echo off
setlocal EnableExtensions

REM Вариант с автоперезапуском при падении (каждые 5 минут проверка)
set "TASK_NAME=PodzamenuWhatsAppWorker"
set "SCRIPT_DIR=%~dp0"
set "BAT_LAUNCHER=%SCRIPT_DIR%start_worker.bat"

schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>&1

schtasks /Create ^
    /TN "%TASK_NAME%" ^
    /TR "cmd.exe /c \"%BAT_LAUNCHER%\"" ^
    /SC MINUTE /MO 5 ^
    /RL LIMITED ^
    /F

echo Задача создана: запуск каждые 5 минут (если воркер упал — поднимется снова).
echo Для постоянно работающего процесса лучше install_autostart.bat (ONLOGON).
pause
