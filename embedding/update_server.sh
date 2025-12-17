#!/bin/bash

# Скрипт для обновления проекта на сервере podzamenu
# Обновляет код из GitHub и перезапускает сервис
#
# Использование:
#   ./update_server.sh                    # использует hostname по умолчанию (podzamenu)
#   ./update_server.sh 192.168.1.100      # использует IP-адрес
#   ./update_server.sh podzamenu.local    # использует другое доменное имя
#
# Переменные окружения:
#   export SERVER_HOST="your_host_or_ip"  # установить hostname/IP
#   export SERVER_SUDO_PASSWORD="pass"    # пароль для sudo на сервере

set -e

# Показываем справку
if [ "$1" == "-h" ] || [ "$1" == "--help" ]; then
    echo "Использование: $0 [hostname_or_ip] [port]"
    echo ""
    echo "Примеры:"
    echo "  $0                          # использует hostname и порт по умолчанию"
    echo "  $0 192.168.1.100            # использует IP-адрес с портом по умолчанию (33)"
    echo "  $0 192.168.1.100 22         # использует IP-адрес и порт 22"
    echo "  $0 podzamenu.example.com    # использует полное доменное имя"
    echo ""
    echo "Переменные окружения:"
    echo "  SERVER_HOST                 # hostname или IP сервера"
    echo "  SERVER_PORT                 # порт SSH (по умолчанию 33)"
    echo "  SERVER_SUDO_PASSWORD       # пароль для sudo на сервере"
    exit 0
fi

SERVER_USER="dev"
# Можно указать через параметр командной строки или переменную окружения
# Использование: ./update_server.sh [hostname] [port]
SERVER_HOST="${1:-${SERVER_HOST:-podzamenu}}"
SERVER_PORT="${2:-${SERVER_PORT:-33}}"
DEPLOY_PATH="/media/ssd3/python_projects"
REPO_URL="https://github.com/BezdomnyiBox/Python_podzamenu.git"
BRANCH="main"
SERVICE_NAME="embedding-api"

# Показываем информацию о подключении
echo "🔗 Подключение к серверу: $SERVER_USER@$SERVER_HOST:$SERVER_PORT"
if [ "$SERVER_HOST" == "podzamenu" ]; then
    echo "💡 Если hostname 'podzamenu' не разрешается, используйте:"
    echo "   ./update_server.sh <IP_адрес>  или  export SERVER_HOST='<IP_адрес>'"
    echo ""
fi

# Проверяем наличие переменной окружения для sudo пароля
if [ -z "$SERVER_SUDO_PASSWORD" ]; then
    echo "⚠️  Переменная окружения SERVER_SUDO_PASSWORD не установлена"
    echo "Экспортируйте её перед запуском: export SERVER_SUDO_PASSWORD='your_password'"
    echo "Или добавьте в ~/.bashrc для постоянного использования"
fi

echo "🚀 Обновление проекта на сервере $SERVER_USER@$SERVER_HOST:$SERVER_PORT..."
echo "📦 Репозиторий: $REPO_URL"
echo "🌿 Ветка: $BRANCH"
echo ""

# Используем -o StrictHostKeyChecking=no для автоматического принятия ключей
# -o ConnectTimeout устанавливает таймаут подключения (10 секунд)
# Временно отключаем set -e для обработки ошибок SSH
set +e
# Используем двойные кавычки для heredoc, чтобы переменные подставлялись локально
# Переменные с экранированным $ выполняются на сервере
ssh -p $SERVER_PORT -o ConnectTimeout=10 -o StrictHostKeyChecking=no $SERVER_USER@$SERVER_HOST << SSH_EOF
    set -e
    
    DEPLOY_PATH="$DEPLOY_PATH"
    REPO_URL="$REPO_URL"
    BRANCH="$BRANCH"
    SERVICE_NAME="$SERVICE_NAME"
    
    echo "📂 Переходим в директорию проекта..."
    # Создаем директорию если её нет
    mkdir -p "\$DEPLOY_PATH"
    cd "\$DEPLOY_PATH"
    
    # Проверяем наличие репозитория
    if [ ! -d ".git" ]; then
        echo "❌ Git репозиторий не найден в \$DEPLOY_PATH"
        echo "Клонируем репозиторий..."
        # Если директория не пуста, выводим предупреждение и очищаем
        if [ "\$(ls -A . 2>/dev/null)" ]; then
            echo "⚠️  Внимание: директория не пуста, но .git отсутствует"
            echo "Очищаем директорию для клонирования..."
            rm -rf ./*
            rm -rf ./.* 2>/dev/null || true
        fi
        if ! git clone "\$REPO_URL" .; then
            echo "❌ Ошибка при клонировании репозитория"
            echo "Проверьте доступность репозитория и права доступа к директории"
            exit 1
        fi
    fi
    
    # Показываем текущую ветку
    CURRENT_BRANCH=\$(git rev-parse --abbrev-ref HEAD)
    echo "📍 Текущая ветка: \$CURRENT_BRANCH"
    
    # Обновляем код
    echo "🔄 Обновляем код из GitHub..."
    git fetch origin
    git checkout "\$BRANCH"
    git pull origin "\$BRANCH"
    
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
    if systemctl is-active --quiet "\$SERVICE_NAME.service" 2>/dev/null; then
        echo "🔄 Перезапускаем сервис..."
        if [ -n "\$SUDO_PASSWORD" ]; then
            echo "\$SUDO_PASSWORD" | sudo -S systemctl restart "\$SERVICE_NAME.service" 2>/dev/null
        else
            sudo systemctl restart "\$SERVICE_NAME.service" 2>/dev/null || echo "⚠️  Для перезапуска нужны права sudo"
        fi
        sleep 2
        
        if sudo systemctl is-active --quiet "\$SERVICE_NAME.service" 2>/dev/null; then
            echo "✅ Сервис успешно перезапущен!"
            
            # Проверяем работу
            echo "🧪 Проверяем работу API..."
            sleep 1
            curl -s http://127.0.0.1:8000/test && echo "" || echo "⚠️  API не отвечает"
        else
            echo "❌ Ошибка при перезапуске сервиса"
            sudo systemctl status "\$SERVICE_NAME.service" --no-pager -l 2>/dev/null || echo "Не удалось получить статус"
        fi
    else
        echo "⚠️  Сервис \$SERVICE_NAME.service не найден или не запущен"
        echo "Запустите вручную: uvicorn app:app --host 127.0.0.1 --port 8000"
    fi
    
    echo ""
    echo "📊 Статус сервиса:"
    sudo systemctl status "\$SERVICE_NAME.service" --no-pager -l 2>/dev/null || echo "Сервис не настроен"
SSH_EOF
SSH_EXIT_CODE=$?
set -e  # Восстанавливаем set -e

if [ $SSH_EXIT_CODE -eq 0 ]; then
    echo ""
    echo "🎉 Обновление завершено!"
else
    echo ""
    echo "❌ Ошибка подключения к $SERVER_USER@$SERVER_HOST"
    echo ""
    echo "💡 Возможные решения:"
    echo "   1. Использовать IP-адрес: ./update_server.sh 192.168.1.100"
    echo "   2. Использовать полное доменное имя: ./update_server.sh podzamenu.example.com"
    echo "   3. Проверить SSH конфигурацию в ~/.ssh/config"
    echo "   4. Установить переменную: export SERVER_HOST='your_host_or_ip'"
    echo "   5. Проверить доступность: ping $SERVER_HOST"
    echo "   6. Проверить SSH ключи: ssh $SERVER_USER@$SERVER_HOST"
    exit 1
fi

