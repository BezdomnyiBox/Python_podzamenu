@echo off
setlocal EnableExtensions

set "PROJECT_DIR=%~dp0..\.."
set "DIST_DIR=%PROJECT_DIR%\dist\PodzamenuWhatsApp"
set "BUILD_DIR=%PROJECT_DIR%\build"

cd /d "%PROJECT_DIR%"

if not exist "dist\PodzamenuWhatsAppWorker.exe" (
    echo [ERROR] Сначала выполните build_exe.bat
    exit /b 1
)

echo Упаковка дистрибутива...
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
mkdir "%DIST_DIR%"

move /y "dist\PodzamenuWhatsAppWorker.exe" "%DIST_DIR%\"
move /y "dist\PodzamenuWhatsAppLogin.exe" "%DIST_DIR%\"

copy /y ".env.example" "%DIST_DIR%\.env.example"
copy /y "whatsapp\windows\install_autostart_exe.bat" "%DIST_DIR%\"
copy /y "whatsapp\windows\uninstall_autostart_exe.bat" "%DIST_DIR%\"
copy /y "whatsapp\windows\start_worker_exe_hidden.vbs" "%DIST_DIR%\"

if not exist "%DIST_DIR%\.env" copy /y "%DIST_DIR%\.env.example" "%DIST_DIR%\.env"

mkdir "%DIST_DIR%\logs" 2>nul

echo.
echo Готово: %DIST_DIR%
echo.
echo Содержимое для офисного ПК:
echo   PodzamenuWhatsAppLogin.exe   - первый вход по QR
echo   PodzamenuWhatsAppWorker.exe  - фоновый воркер
echo   .env                         - настройки CRM
echo   install_autostart_exe.bat    - автозапуск
echo.
echo Заархивируйте папку PodzamenuWhatsApp в ZIP и раздайте менеджерам.
