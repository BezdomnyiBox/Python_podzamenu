@echo off
setlocal EnableExtensions

REM Корень проекта: на два уровня выше папки windows
set "PROJECT_DIR=%~dp0..\.."
cd /d "%PROJECT_DIR%"

if not exist ".env" (
    echo [ERROR] Файл .env не найден в %PROJECT_DIR%
    echo Скопируйте .env.example в .env и настройте CRM_AGENT_TOKEN
    pause
    exit /b 1
)

set "VENV_PYTHON=%PROJECT_DIR%\venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    echo [ERROR] Не найден venv\Scripts\python.exe
    echo Выполните: python -m venv venv ^&^& venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

if not exist "logs" mkdir "logs"

echo [%date% %time%] Запуск WhatsApp Worker...
"%VENV_PYTHON%" -m whatsapp.worker >> "logs\whatsapp_worker.log" 2>&1

echo [%date% %time%] Worker завершился с кодом %ERRORLEVEL%
exit /b %ERRORLEVEL%
