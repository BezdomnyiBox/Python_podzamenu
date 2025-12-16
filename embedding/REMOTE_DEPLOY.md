# Развертывание на удаленном сервере через SSH

Инструкция по развертыванию проекта на удаленном сервере с клонированием из GitHub.

## Быстрый старт

### Вариант 1: Автоматическое развертывание (рекомендуется)

1. **Подготовьте скрипт на локальной машине:**

```bash
cd embedding
chmod +x deploy_remote.sh
```

2. **Запустите развертывание:**

```bash
./deploy_remote.sh user server.com https://github.com/your-username/your-repo.git /opt/embedding-api 8000
```

Параметры:
- `user` - пользователь SSH на сервере
- `server.com` - адрес сервера (IP или домен)
- `https://github.com/...` - URL вашего GitHub репозитория
- `/opt/embedding-api` - путь на сервере (по умолчанию)
- `8000` - порт (по умолчанию)

### Вариант 2: Упрощенный скрипт

```bash
chmod +x deploy_remote_simple.sh
./deploy_remote_simple.sh user@server.com https://github.com/your-username/your-repo.git
```

### Вариант 3: Ручное развертывание

1. **Подключитесь к серверу:**

```bash
ssh user@your-server.com
```

2. **Установите зависимости:**

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git curl
```

3. **Клонируйте репозиторий:**

```bash
sudo mkdir -p /opt/embedding-api
sudo chown $USER:$USER /opt/embedding-api
cd /opt/embedding-api
git clone https://github.com/your-username/your-repo.git .
```

4. **Настройте приложение:**

```bash
cd embedding
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

5. **Создайте systemd сервис:**

```bash
sudo nano /etc/systemd/system/embedding-api.service
```

Вставьте следующее содержимое (замените пути на ваши):

```ini
[Unit]
Description=Embedding API Service (Internal Microservice)
After=network.target

[Service]
Type=simple
User=ваш_пользователь
WorkingDirectory=/opt/embedding-api/embedding
Environment="PATH=/opt/embedding-api/embedding/venv/bin"
ExecStart=/opt/embedding-api/embedding/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

6. **Запустите сервис:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable embedding-api.service
sudo systemctl start embedding-api.service
sudo systemctl status embedding-api.service
```

## Проверка работы

### На сервере:

```bash
# Проверка статуса
sudo systemctl status embedding-api.service

# Проверка работы API
curl http://127.0.0.1:8000/test

# Тест классификации
curl -X POST http://127.0.0.1:8000/classify \
  -H "Content-Type: application/json" \
  -d '{"text": "Где мой заказ №12345?"}'
```

### С локальной машины (если настроен SSH туннель):

```bash
# Создайте SSH туннель
ssh -L 8000:127.0.0.1:8000 user@server.com

# В другом терминале проверьте
curl http://localhost:8000/test
```

## Важные особенности

### Внутренний микросервис

Сервис настроен на работу только на `127.0.0.1` (localhost), что означает:
- ✅ Доступен только внутри сервера
- ✅ Недоступен извне (без дополнительной настройки)
- ✅ Безопасно для внутренних микросервисов

### Если нужен внешний доступ

Если нужно сделать сервис доступным извне, измените в systemd сервисе:

```ini
ExecStart=.../uvicorn app:app --host 0.0.0.0 --port 8000
```

⚠️ **Внимание:** Убедитесь, что настроен firewall и сервис защищен!

## Обновление приложения

### Автоматическое обновление:

```bash
# На сервере
cd /opt/embedding-api
git pull origin main
cd embedding
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart embedding-api.service
```

### Или через скрипт:

```bash
./deploy_remote.sh user server.com https://github.com/your-username/your-repo.git
```

## Мониторинг и логи

```bash
# Просмотр логов в реальном времени
sudo journalctl -u embedding-api.service -f

# Последние 100 строк логов
sudo journalctl -u embedding-api.service -n 100

# Логи за последний час
sudo journalctl -u embedding-api.service --since "1 hour ago"

# Логи с ошибками
sudo journalctl -u embedding-api.service -p err
```

## Управление сервисом

```bash
# Запуск
sudo systemctl start embedding-api.service

# Остановка
sudo systemctl stop embedding-api.service

# Перезапуск
sudo systemctl restart embedding-api.service

# Статус
sudo systemctl status embedding-api.service

# Включить автозапуск
sudo systemctl enable embedding-api.service

# Отключить автозапуск
sudo systemctl disable embedding-api.service
```

## Устранение проблем

### Сервис не запускается

```bash
# Проверьте статус
sudo systemctl status embedding-api.service

# Проверьте логи
sudo journalctl -u embedding-api.service -n 50

# Проверьте синтаксис systemd файла
sudo systemd-analyze verify embedding-api.service
```

### Порт занят

```bash
# Проверьте, что использует порт
sudo lsof -i :8000
# Или
sudo netstat -tulpn | grep 8000

# Убейте процесс или измените порт
```

### Проблемы с зависимостями

```bash
cd /opt/embedding-api/embedding
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt --force-reinstall
```

### Проблемы с правами доступа

```bash
# Проверьте владельца файлов
ls -la /opt/embedding-api

# Измените владельца если нужно
sudo chown -R $USER:$USER /opt/embedding-api
```

## Интеграция с другими сервисами

### Nginx как reverse proxy

Если нужно предоставить доступ через Nginx:

```nginx
server {
    listen 80;
    server_name api.your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Docker Compose

Если предпочитаете Docker:

```bash
cd /opt/embedding-api/embedding
docker-compose up -d --build
```

## Безопасность

1. **Firewall:** Убедитесь, что порт 8000 закрыт для внешнего доступа (если сервис только внутренний)
2. **SSH ключи:** Используйте SSH ключи вместо паролей
3. **Обновления:** Регулярно обновляйте зависимости
4. **Логи:** Мониторьте логи на предмет подозрительной активности

## Резервное копирование

```bash
# Создание бэкапа
tar -czf embedding-api-backup-$(date +%Y%m%d).tar.gz /opt/embedding-api

# Восстановление
tar -xzf embedding-api-backup-YYYYMMDD.tar.gz -C /
```
```

Создайте эти файлы в папке `embedding`:

1. `deploy_remote.sh` — основной скрипт развертывания
2. `deploy_remote_simple.sh` — упрощенная версия
3. `REMOTE_DEPLOY.md` — инструкция

## Использование:

```bash
# Сделайте скрипты исполняемыми
chmod +x deploy_remote.sh deploy_remote_simple.sh

# Запустите развертывание
./deploy_remote.sh user server.com https://github.com/your-username/your-repo.git
```

Скрипт:
- Подключится к серверу по SSH
- Установит зависимости
- Клонирует репозиторий с GitHub
- Настроит виртуальное окружение
- Установит зависимости Python
- Создаст и запустит systemd сервис
- Настроит сервис на работу только на localhost (внутренний микросервис)

Нужна помощь с настройкой конкретных параметров?
