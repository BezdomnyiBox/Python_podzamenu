# Инструкция по развертыванию на сервере

## Вариант 1: Автоматический деплой через GitLab CI/CD

### Настройка GitLab CI/CD

1. **Настройте переменные в GitLab** (Settings → CI/CD → Variables):
   - `SSH_PRIVATE_KEY` - приватный SSH ключ для доступа к серверу
   - `SERVER_HOST` - IP адрес или домен сервера
   - `SERVER_USER` - пользователь для SSH подключения
   - `DEPLOY_PATH` - путь на сервере для развертывания (например, `/opt/embedding-api`)
   - `SERVER_PORT` - порт приложения (например, `8000`)

2. **Добавьте публичный ключ на сервер**:
   ```bash
   # На сервере
   mkdir -p ~/.ssh
   echo "ВАШ_ПУБЛИЧНЫЙ_SSH_КЛЮЧ" >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   ```

3. **Настройте systemd сервис на сервере**:
   ```bash
   # Скопируйте файл embedding-api.service в /etc/systemd/system/
   sudo cp embedding-api.service /etc/systemd/system/
   
   # Обновите пути в файле под ваш сервер
   sudo nano /etc/systemd/system/embedding-api.service
   
   # Перезагрузите systemd и включите сервис
   sudo systemctl daemon-reload
   sudo systemctl enable embedding-api.service
   sudo systemctl start embedding-api.service
   ```

4. **Проверьте статус сервиса**:
   ```bash
   sudo systemctl status embedding-api.service
   ```

5. **При пуше в main/master ветку** GitLab автоматически развернет приложение.

## Вариант 2: Ручной деплой через скрипт

### Использование deploy.sh

1. **Сделайте скрипт исполняемым**:
   ```bash
   chmod +x deploy.sh
   ```

2. **Запустите деплой**:
   ```bash
   ./deploy.sh [user] [server_host] [deploy_path]
   
   # Пример:
   ./deploy.sh root 192.168.1.100 /opt/embedding-api
   ```

3. **Настройте systemd сервис** (см. Вариант 1, шаг 3)

## Вариант 3: Деплой через Docker

### Использование Docker Compose

1. **На сервере скопируйте файлы**:
   ```bash
   scp -r embedding/ user@server:/opt/embedding-api/
   ```

2. **На сервере запустите**:
   ```bash
   cd /opt/embedding-api/embedding
   docker-compose up -d --build
   ```

3. **Проверьте статус**:
   ```bash
   docker-compose ps
   docker-compose logs -f
   ```

## Вариант 4: Ручной деплой без автоматизации

### Шаги для развертывания:

1. **Подключитесь к серверу**:
   ```bash
   ssh user@your-server.com
   ```

2. **Установите зависимости**:
   ```bash
   sudo apt update
   sudo apt install -y python3 python3-pip python3-venv git
   ```

3. **Клонируйте репозиторий**:
   ```bash
   cd /opt
   git clone https://gitlab.com/your-username/your-repo.git embedding-api
   cd embedding-api/embedding
   ```

4. **Создайте виртуальное окружение**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

5. **Настройте systemd сервис**:
   ```bash
   sudo cp embedding-api.service /etc/systemd/system/
   sudo nano /etc/systemd/system/embedding-api.service  # Отредактируйте пути
   sudo systemctl daemon-reload
   sudo systemctl enable embedding-api.service
   sudo systemctl start embedding-api.service
   ```

6. **Проверьте работу**:
   ```bash
   curl http://localhost:8000/test
   ```

## Обновление приложения

### При использовании GitLab CI/CD:
Просто сделайте push в main/master ветку - деплой произойдет автоматически.

### При ручном деплое:
```bash
cd /opt/embedding-api/embedding
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart embedding-api.service
```

## Проверка работы API

```bash
# Проверка здоровья сервиса
curl http://your-server:8000/test

# Тест классификации
curl -X POST http://your-server:8000/classify \
  -H "Content-Type: application/json" \
  -d '{"text": "Где мой заказ №12345?"}'
```

## Настройка Nginx (опционально)

Если хотите использовать Nginx как reverse proxy:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Мониторинг и логи

```bash
# Просмотр логов systemd сервиса
sudo journalctl -u embedding-api.service -f

# Просмотр последних логов
sudo journalctl -u embedding-api.service -n 100

# Просмотр логов Docker контейнера
docker-compose logs -f
```

## Устранение проблем

1. **Сервис не запускается**:
   ```bash
   sudo systemctl status embedding-api.service
   sudo journalctl -u embedding-api.service -n 50
   ```

2. **Порт занят**:
   ```bash
   sudo netstat -tulpn | grep 8000
   # Или измените порт в embedding-api.service
   ```

3. **Проблемы с зависимостями**:
   ```bash
   source venv/bin/activate
   pip install --upgrade -r requirements.txt
   ```

