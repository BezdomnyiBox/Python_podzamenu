#!/bin/bash

# Скрипт для обновления проекта на сервере podzamenu
# Обновляет код из GitHub и перезапускает сервис
# Использование: ./update_server.sh

set -e

SERVER_USER="dev"
SERVER_HOST="podzamenu"
DEPLOY_PATH="/media/ssd3/python_projects"
REPO_URL="https://github.com/BezdomnyiBox/Python_podzamenu.git"
BRANCH="main"
SERVICE_NAME="embedding-api"

# Проверяем наличие переменной окружения для sudo пароля
if [ -z "$SERVER_SUDO_PASSWORD" ]; then
    echo "⚠️  Переменная окружения SERVER_SUDO_PASSWORD не установлена"
    echo "Экспортируйте её перед запуском: export SERVER_SUDO_PASSWORD='your_password'"
    echo "Или добавьте в ~/.bashrc для постоянного использования"
fi

echo "🚀 Обновление проекта на сервере $SERVER_USER@$SERVER_HOST..."
echo "📦 Репозиторий: $REPO_URL"
echo "🌿 Ветка: $BRANCH"
echo ""

ssh $SERVER_USER@$SERVER_HOST << EOF
    set -e
    
    echo "📂 Переходим в директорию проекта..."
    cd $DEPLOY_PATH
    
    # Проверяем наличие репозитория
    if [ ! -d ".git" ]; then
        echo "❌ Git репозиторий не найден в $DEPLOY_PATH"
        echo "Клонируем репозиторий..."
        git clone $REPO_URL .
    fi
    
    # Показываем текущую ветку
    CURRENT_BRANCH=\$(git rev-parse --abbrev-ref HEAD)
    echo "📍 Текущая ветка: \$CURRENT_BRANCH"
    
    # Обновляем код
    echo "🔄 Обновляем код из GitHub..."
    git fetch origin
    git checkout $BRANCH
    git pull origin $BRANCH
    
    # Показываем последний коммит
    echo ""
    echo "📝 Последний коммит:"
    git log -1 --oneline
    echo ""
    
    # Переходим в директорию embedding
    cd embedding
    
    # Обновляем зависимости
    echo "📥 Обновляем зависимости..."
    source venv/bin/activate
    pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
    
    # Перезапускаем сервис (если настроен sudo без пароля или передан пароль)
    if systemctl is-active --quiet $SERVICE_NAME.service 2>/dev/null; then
        echo "🔄 Перезапускаем сервис..."
        if [ -n "\$SUDO_PASSWORD" ]; then
            echo "\$SUDO_PASSWORD" | sudo -S systemctl restart $SERVICE_NAME.service 2>/dev/null
        else
            sudo systemctl restart $SERVICE_NAME.service 2>/dev/null || echo "⚠️  Для перезапуска нужны права sudo"
        fi
        sleep 2
        
        if sudo systemctl is-active --quiet $SERVICE_NAME.service 2>/dev/null; then
            echo "✅ Сервис успешно перезапущен!"
            
            # Проверяем работу
            echo "🧪 Проверяем работу API..."
            sleep 1
            curl -s http://127.0.0.1:8000/test && echo "" || echo "⚠️  API не отвечает"
        else
            echo "❌ Ошибка при перезапуске сервиса"
            sudo systemctl status $SERVICE_NAME.service --no-pager -l 2>/dev/null || echo "Не удалось получить статус"
        fi
    else
        echo "⚠️  Сервис $SERVICE_NAME.service не найден или не запущен"
        echo "Запустите вручную: uvicorn app:app --host 127.0.0.1 --port 8000"
    fi
    
    echo ""
    echo "📊 Статус сервиса:"
    sudo systemctl status $SERVICE_NAME.service --no-pager -l 2>/dev/null || echo "Сервис не настроен"
EOF

echo ""
echo "🎉 Обновление завершено!"

