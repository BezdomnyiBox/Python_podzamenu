#!/bin/bash

# Скрипт для развертывания на удаленном сервере через SSH
# Клонирует репозиторий с GitHub и настраивает как внутренний микросервис
# Использование: ./deploy_remote.sh [user] [server_host] [github_repo_url] [deploy_path] [port]

set -e

SERVER_USER=${1:-"user"}
SERVER_HOST=${2:-"your-server.com"}
GITHUB_REPO=${3:-"https://github.com/your-username/your-repo.git"}
DEPLOY_PATH=${4:-"/opt/embedding-api"}
APP_DIR="embedding"
PORT=${5:-8000}
SERVICE_NAME="embedding-api"

echo "🚀 Развертывание на удаленном сервере $SERVER_USER@$SERVER_HOST..."
echo "📦 Репозиторий: $GITHUB_REPO"
echo "📁 Путь развертывания: $DEPLOY_PATH"
echo "🔌 Порт: $PORT"
echo ""

# Выполняем развертывание на сервере
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
        echo "🔄 Обновляем существующий репозиторий..."
        git fetch origin
        git reset --hard origin/main 2>/dev/null || git reset --hard origin/master
        git clean -fd
    else
        echo "📥 Клонируем репозиторий с GitHub..."
        git clone $GITHUB_REPO .
    fi
    
    # Переходим в директорию приложения
    if [ -d "$APP_DIR" ]; then
        cd $APP_DIR
    else
        echo "⚠️  Директория $APP_DIR не найдена. Используем корневую директорию."
    fi
    
    # Создаем виртуальное окружение
    if [ ! -d "venv" ]; then
        echo "📦 Создаем виртуальное окружение..."
        python3 -m venv venv
    fi
    
    # Устанавливаем зависимости
    echo "📥 Устанавливаем зависимости Python..."
    source venv/bin/activate
    pip install --upgrade pip --quiet
    pip install -r requirements.txt
    
    # Создаем systemd сервис
    echo "⚙️  Настраиваем systemd сервис..."
    CURRENT_DIR=\$(pwd)
    SERVICE_FILE="/tmp/${SERVICE_NAME}.service"
    
    cat > \$SERVICE_FILE << SERVICE_EOF
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
    sudo cp \$SERVICE_FILE /etc/systemd/system/${SERVICE_NAME}.service
    rm -f \$SERVICE_FILE
    
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
EOF

echo ""
echo "🎉 Развертывание завершено!"
echo "🔒 Сервис работает как внутренний микросервис на localhost:$PORT"
