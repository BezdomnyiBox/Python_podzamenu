@echo off
chcp 65001
cd /d "%~dp0"
echo.
echo ============================================
echo Сборка ML-Аналитики доставок
echo ============================================
echo.
python -m PyInstaller --onefile --windowed --name "ML_Delivery_Analytics" --hidden-import sklearn --hidden-import sklearn.ensemble --hidden-import sklearn.preprocessing "ML_Анализ_Доставки.py"
echo.
echo ============================================
echo Готово! Файл: dist\ML_Delivery_Analytics.exe
echo ============================================
pause

