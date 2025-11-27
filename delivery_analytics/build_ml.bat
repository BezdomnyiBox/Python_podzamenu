@echo off
chcp 65001
cd /d "%~dp0"
echo.
echo ============================================
echo Сборка ML-Аналитики доставок
echo ============================================
echo.

REM Проверка наличия PyInstaller
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller не установлен. Устанавливаю...
    pip install pyinstaller
    echo.
)

REM Очистка старых файлов сборки
if exist "build" (
    echo Удаление старых файлов сборки...
    rmdir /s /q build
)
if exist "dist\ML_Delivery_Analytics.exe" (
    echo Удаление старого exe...
    del /q "dist\ML_Delivery_Analytics.exe"
)

echo Начинаю сборку...
echo.

REM Сборка через spec файл (более надежно)
python -m PyInstaller ML_Delivery_Analytics.spec --clean

if errorlevel 1 (
    echo.
    echo ============================================
    echo ОШИБКА при сборке!
    echo ============================================
    pause
    exit /b 1
)

echo.
echo ============================================
echo Готово! Файл: dist\ML_Delivery_Analytics.exe
echo ============================================
echo.
echo Размер файла:
dir "dist\ML_Delivery_Analytics.exe" | find "ML_Delivery_Analytics.exe"
echo.
pause

