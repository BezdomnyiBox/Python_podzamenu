#!/bin/bash

# Первоначальная настройка проекта на сервере podzamenu
# Использование: ./setup_server.sh

set -e

SERVER_USER="dev"
SERVER_HOST="podzamenu"
DEPLOY_PATH="/media/ssd3/python_projects"
REPO_URL="https://github.com/BezdomnyiBox/Python_podzamenu.git"
BRANCH="main"
SERVICE_NAME="embedding-api"
PORT=8000

echo "🚀 Первоначальная настройка проекта на сервере $SERVER_USER@$SERVER_HOST..."
echo ""

ssh $SERVER_USER@$SERVER_HOST << EOF
    set -e
    
    echo "📥 Устанавливаем системные зависимости..."
    sudo apt-get update -qq
    sudo apt-get install -y python3 python3-pip python3-venv git curl || true
    
    echo "📂 Создаем директорию для проекта..."
    sudo mkdir -p $DEPLOY_PATH
    sudo chown \$USER:\$USER $DEPLOY_PATH
    cd $DEPLOY_PATH
    
    # Клонируем или обновляем репозиторий
    if [ -d ".git" ]; then
        echo "🔄 Репозиторий уже существует, обновляем..."
        git fetch origin
        git checkout $BRANCH
        git pull origin $BRANCH
    else
        echo "📥 Клонируем репозиторий с GitHub..."
        git clone $REPO_URL .
        git checkout $BRANCH
    fi
    
    echo "🌿 Используем ветку: $BRANCH"
    
    # Переходим в директорию приложения
    cd embedding
    
    # Создаем виртуальное окружение
    if [ ! -d "venv" ]; then
        echo "📦 Создаем виртуальное окружение..."
        python3 -m venv venv
    fi
    
    # Устанавливаем зависимости
    echo "📥 Устанавливаем зависимости Python..."
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    
    # Создаем systemd сервис
    echo "⚙️  Настраиваем systemd сервис..."
    CURRENT_DIR=\$(pwd)
    
    cat > /tmp/${SERVICE_NAME}.service << SERVICE_EOF
[Unit]
Description=Embedding API Service (Internal Microservice)
After=network.target

[Service]
Type=simple
User=\$USER
WorkingDirectory=\$CURRENT_DIR
Environment="PATH=\$CURRENT_DIR/venv/bin"
ExecStart=\$CURRENT_DIR/venv/bin/uvicorn app:app --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE_EOF
    
    # Копируем сервис файл
    sudo cp /tmp/${SERVICE_NAME}.service /etc/systemd/system/
    rm -f /tmp/${SERVICE_NAME}.service
    
    # Перезагружаем systemd
    sudo systemctl daemon-reload
    
    # Включаем и запускаем сервис
    echo "🚀 Запускаем сервис..."
    sudo systemctl enable ${SERVICE_NAME}.service
    sudo systemctl restart ${SERVICE_NAME}.service
    
    # Ждем немного и проверяем статус
    sleep 2
    if sudo systemctl is-active --quiet ${SERVICE_NAME}.service; then
        echo "✅ Сервис успешно запущен!"
        echo ""
        echo "📊 Статус сервиса:"
        sudo systemctl status ${SERVICE_NAME}.service --no-pager -l
        echo ""
        echo "🧪 Проверка работы:"
        sleep 1
        curl -s http://127.0.0.1:$PORT/test || echo "⚠️  Сервис еще запускается, подождите несколько секунд"
    else
        echo "❌ Ошибка при запуске сервиса. Проверьте логи:"
        echo "   sudo journalctl -u ${SERVICE_NAME}.service -n 50"
    fi
    
    echo ""
    echo "📋 Полезные команды:"
    echo "   Статус: sudo systemctl status ${SERVICE_NAME}.service"
    echo "   Логи:   sudo journalctl -u ${SERVICE_NAME}.service -f"
    echo "   Стоп:   sudo systemctl stop ${SERVICE_NAME}.service"
    echo "   Старт:  sudo systemctl start ${SERVICE_NAME}.service"
    echo "   Рестарт: sudo systemctl restart ${SERVICE_NAME}.service"
    echo ""
    echo "🌐 Сервис доступен только на localhost: http://127.0.0.1:$PORT"
    echo "📁 Путь к проекту: $DEPLOY_PATH/embedding"
EOF

echo ""
echo "🎉 Настройка завершена!"
echo "🔒 Сервис работает как внутренний микросервис на localhost:$PORT"

