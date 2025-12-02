#!/bin/bash
# Скрипт сборки ML-Аналитики доставок для Linux

echo ""
echo "============================================"
echo "Сборка ML-Аналитики доставок"
echo "============================================"
echo ""

# Переходим в директорию скрипта
cd "$(dirname "$0")"

# Активируем виртуальное окружение если есть
if [ -d "../venv" ]; then
    source ../venv/bin/activate
    echo "✅ Виртуальное окружение активировано"
fi

# Проверка наличия PyInstaller
python3 -c "import PyInstaller" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "PyInstaller не установлен. Устанавливаю..."
    pip install pyinstaller
    echo ""
fi

# Очистка старых файлов сборки
if [ -d "build" ]; then
    echo "Удаление старых файлов сборки..."
    rm -rf build
fi
if [ -f "dist/ML_Delivery_Analytics" ]; then
    echo "Удаление старого исполняемого файла..."
    rm -f "dist/ML_Delivery_Analytics"
fi

echo "Начинаю сборку..."
echo ""

# Сборка через spec файл
python3 -m PyInstaller ML_Delivery_Analytics.spec --clean

if [ $? -ne 0 ]; then
    echo ""
    echo "============================================"
    echo "❌ ОШИБКА при сборке!"
    echo "============================================"
    exit 1
fi

echo ""
echo "============================================"
echo "✅ Готово! Файл: dist/ML_Delivery_Analytics"
echo "============================================"
echo ""

if [ -f "dist/ML_Delivery_Analytics" ]; then
    echo "Размер файла:"
    ls -lh "dist/ML_Delivery_Analytics"
    echo ""
    echo "Для запуска: ./dist/ML_Delivery_Analytics"
fi

