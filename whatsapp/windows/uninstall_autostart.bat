@echo off
setlocal EnableExtensions

set "TASK_NAME=PodzamenuWhatsAppWorker"

echo Удаление задачи "%TASK_NAME%"...
schtasks /Delete /TN "%TASK_NAME%" /F

if errorlevel 1 (
    echo Задача не найдена или уже удалена.
) else (
    echo Автозапуск отключён.
)

pause
