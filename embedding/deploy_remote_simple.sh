#!/bin/bash

# Упрощенный скрипт для быстрого развертывания
# Использование: ./deploy_remote_simple.sh user@server.com github_repo_url

set -e

if [ $# -lt 2 ]; then
    echo "Использование: $0 user@server.com https://github.com/user/repo.git"
    exit 1
fi

SERVER=$1
GITHUB_REPO=$2
DEPLOY_PATH="/opt/embedding-api"
PORT=8000

echo "🚀 Развертывание на $SERVER..."

ssh $SERVER << EOF
    set -e
    
    # Установка зависимостей
    sudo apt-get update -qq
    sudo apt-get install -y python3 python3-pip python3-venv git || true
    
    # Создание директории
    sudo mkdir -p $DEPLOY_PATH
    sudo chown \$USER:\$USER $DEPLOY_PATH
    cd $DEPLOY_PATH
    
    # Клонирование репозитория
    if [ -d ".git" ]; then
        git pull origin main || git pull origin master
    else
        git clone $GITHUB_REPO .
    fi
    
    # Переход в директорию приложения
    cd embedding 2>/dev/null || true
    
    # Настройка виртуального окружения
    [ ! -d "venv" ] && python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip --quiet
    pip install -r requirements.txt
    
    # Создание systemd сервиса
    cat > /tmp/embedding-api.service << SERVICE_EOF
[Unit]
Description=Embedding API Service
After=network.target

[Service]
Type=simple
User=\$USER
WorkingDirectory=\$(pwd)
Environment="PATH=\$(pwd)/venv/bin"
ExecStart=\$(pwd)/venv/bin/uvicorn app:app --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICE_EOF
    
    sudo cp /tmp/embedding-api.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable embedding-api.service
    sudo systemctl restart embedding-api.service
    
    echo "✅ Готово! Сервис доступен на http://127.0.0.1:$PORT"
EOF
