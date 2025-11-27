@echo off
chcp 65001
cd /d "%~dp0"
python -m PyInstaller --onefile --windowed --name "Delivery_Analytics" "Анализ_Доставки.py"
echo.
echo ============================================
echo Готово! Файл находится в папке dist\
echo ============================================
pause

