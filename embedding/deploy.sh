#!/bin/bash

# Скрипт для ручного деплоймента на сервер
# Использование: ./deploy.sh [server_user] [server_host] [deploy_path]

set -e

SERVER_USER=${1:-"user"}
SERVER_HOST=${2:-"your-server.com"}
DEPLOY_PATH=${3:-"/opt/embedding-api"}
APP_DIR="embedding"

echo "🚀 Начинаем деплой на сервер $SERVER_USER@$SERVER_HOST..."

# Создаем временный архив
echo "📦 Создаем архив проекта..."
tar -czf deploy.tar.gz \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    --exclude='venv' \
    --exclude='*.log' \
    $APP_DIR/

# Копируем архив на сервер
echo "📤 Копируем файлы на сервер..."
scp deploy.tar.gz $SERVER_USER@$SERVER_HOST:/tmp/

# Выполняем деплой на сервере
echo "🔧 Разворачиваем приложение на сервере..."
ssh $SERVER_USER@$SERVER_HOST << EOF
    set -e
    
    # Создаем директорию если её нет
    mkdir -p $DEPLOY_PATH
    cd $DEPLOY_PATH
    
    # Распаковываем архив
    tar -xzf /tmp/deploy.tar.gz
    
    cd $APP_DIR
    
    # Создаем виртуальное окружение если его нет
    if [ ! -d "venv" ]; then
        echo "📦 Создаем виртуальное окружение..."
        python3 -m venv venv
    fi
    
    # Активируем виртуальное окружение и устанавливаем зависимости
    echo "📥 Устанавливаем зависимости..."
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    
    # Перезапускаем сервис если он существует
    if systemctl is-active --quiet embedding-api.service 2>/dev/null; then
        echo "🔄 Перезапускаем сервис..."
        sudo systemctl restart embedding-api.service
    else
        echo "⚠️  Сервис embedding-api.service не найден. Запустите вручную:"
        echo "   uvicorn app:app --host 0.0.0.0 --port 8000"
    fi
    
    # Удаляем временный архив
    rm -f /tmp/deploy.tar.gz
    
    echo "✅ Деплой завершен успешно!"
EOF

# Удаляем локальный архив
rm -f deploy.tar.gz

echo "🎉 Готово! Приложение развернуто на сервере."

