@echo off
setlocal EnableExtensions

REM Сборка PodzamenuWhatsAppWorker.exe и PodzamenuWhatsAppLogin.exe
REM Запускать на Windows с установленным Python 3.10+

set "PROJECT_DIR=%~dp0..\.."
cd /d "%PROJECT_DIR%"

echo === Podzamenu WhatsApp: сборка .exe ===
echo Проект: %PROJECT_DIR%
echo.

if not exist "venv\Scripts\python.exe" (
    echo Создание venv...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Не удалось создать venv. Установите Python 3.10+
        pause
        exit /b 1
    )
)

echo Установка зависимостей агента...
venv\Scripts\pip install -r whatsapp\requirements-agent.txt
if errorlevel 1 (
    echo [ERROR] pip install failed
    pause
    exit /b 1
)

echo.
echo Сборка PyInstaller (2-5 минут)...
venv\Scripts\pyinstaller --noconfirm whatsapp\windows\PodzamenuWhatsApp.spec
if errorlevel 1 (
    echo [ERROR] PyInstaller failed
    pause
    exit /b 1
)

call "%~dp0package_dist.bat"
pause
