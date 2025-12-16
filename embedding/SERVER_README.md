# Управление проектом на сервере podzamenu

## Информация о сервере

- **Сервер:** dev@podzamenu
- **Путь:** `/media/ssd3/python_projects/embedding`
- **Репозиторий:** https://github.com/BezdomnyiBox/Python_podzamenu
- **Ветка:** main
- **Порт:** 8000 (localhost)
- **Сервис:** embedding-api.service

## Быстрые команды

### Обновление кода на сервере

```bash
./update_server.sh
```

Что делает:
- Обновляет код из GitHub (ветка main)
- Обновляет зависимости Python
- Перезапускает сервис
- Проверяет работу API

### Первоначальная настройка (если еще не настроено)

```bash
./setup_server.sh
```

Что делает:
- Устанавливает системные зависимости
- Клонирует репозиторий
- Создает виртуальное окружение
- Устанавливает зависимости Python
- Настраивает systemd сервис
- Запускает сервис

### Автоматический деплой

```bash
./quick_deploy.sh
```

Автоматически определяет, нужна первоначальная настройка или просто обновление.

## Работа с сервисом на сервере

Подключитесь к серверу:
```bash
ssh dev@podzamenu
```

### Просмотр статуса

```bash
sudo systemctl status embedding-api.service
```

### Просмотр логов

```bash
# Просмотр в реальном времени
sudo journalctl -u embedding-api.service -f

# Последние 100 строк
sudo journalctl -u embedding-api.service -n 100

# Логи с ошибками
sudo journalctl -u embedding-api.service -p err
```

### Управление сервисом

```bash
# Перезапуск
sudo systemctl restart embedding-api.service

# Остановка
sudo systemctl stop embedding-api.service

# Запуск
sudo systemctl start embedding-api.service

# Перезагрузка конфигурации
sudo systemctl daemon-reload
sudo systemctl restart embedding-api.service
```

### Проверка работы API

```bash
# Проверка здоровья
curl http://127.0.0.1:8000/test

# Тест классификации
curl -X POST http://127.0.0.1:8000/classify \
  -H "Content-Type: application/json" \
  -d '{"text": "Где мой заказ №12345?"}'
```

## Ручное обновление на сервере

Если нужно обновить код вручную:

```bash
ssh dev@podzamenu

# Переходим в директорию проекта
cd /media/ssd3/python_projects

# Обновляем код
git pull origin main

# Переходим в embedding
cd embedding

# Обновляем зависимости
source venv/bin/activate
pip install -r requirements.txt

# Перезапускаем сервис
sudo systemctl restart embedding-api.service

# Проверяем статус
sudo systemctl status embedding-api.service
```

## Структура на сервере

```
/media/ssd3/python_projects/
├── .git/                    # Git репозиторий
├── embedding/               # Приложение
│   ├── venv/               # Виртуальное окружение
│   ├── app.py              # Основной файл приложения
│   ├── requirements.txt    # Зависимости Python
│   └── ...
├── avito/                   # Другие модули проекта
├── delivery_analytics/
├── dialogs/
└── ...
```

## Доступ к сервису

Сервис работает как **внутренний микросервис** и доступен только на localhost:

- На сервере: `http://127.0.0.1:8000`
- Извне: недоступен (по дизайну)

Если нужен внешний доступ, используйте SSH туннель:

```bash
# Создайте туннель
ssh -L 8000:127.0.0.1:8000 dev@podzamenu

# Затем на локальной машине:
curl http://localhost:8000/test
```

## Изменение конфигурации сервиса

Если нужно изменить порт, пользователя или другие параметры:

```bash
ssh dev@podzamenu

# Отредактируйте сервис
sudo nano /etc/systemd/system/embedding-api.service

# Перезагрузите конфигурацию
sudo systemctl daemon-reload
sudo systemctl restart embedding-api.service
```

## Мониторинг

### Использование ресурсов

```bash
# На сервере
htop

# Или конкретно для процесса
ps aux | grep uvicorn
```

### Размер логов

```bash
sudo journalctl --disk-usage
```

### Очистка старых логов

```bash
# Удалить логи старше 7 дней
sudo journalctl --vacuum-time=7d

# Оставить только 100MB логов
sudo journalctl --vacuum-size=100M
```

## Устранение проблем

### Сервис не запускается

```bash
# Проверьте логи
sudo journalctl -u embedding-api.service -n 100

# Проверьте синтаксис
sudo systemd-analyze verify embedding-api.service

# Попробуйте запустить вручную
cd /media/ssd3/python_projects/embedding
source venv/bin/activate
uvicorn app:app --host 127.0.0.1 --port 8000
```

### Порт занят

```bash
# Проверьте, что использует порт 8000
sudo lsof -i :8000
sudo netstat -tulpn | grep 8000

# Убейте процесс если нужно
sudo kill -9 <PID>
```

### Проблемы с зависимостями

```bash
cd /media/ssd3/python_projects/embedding
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt --force-reinstall
```

### Проблемы с правами

```bash
# Проверьте владельца файлов
ls -la /media/ssd3/python_projects/embedding

# Измените если нужно
sudo chown -R dev:dev /media/ssd3/python_projects
```

## Разработка

### Работа с веткой main

Код на сервере всегда синхронизирован с веткой `main`. Чтобы обновить:

1. Закоммитьте изменения локально
2. Запушьте в GitHub: `git push origin main`
3. Запустите обновление: `./update_server.sh`

### Тестирование перед деплоем

Тестируйте локально перед пушем в main:

```bash
# Локально или в WSL
cd embedding
source venv/bin/activate
uvicorn app:app --host 127.0.0.1 --port 8000 --reload

# Тестируйте
curl http://localhost:8000/test
```

## Backup

### Создание бэкапа

```bash
ssh dev@podzamenu

# Создайте архив
cd /media/ssd3
tar -czf python_projects_backup_$(date +%Y%m%d).tar.gz python_projects/

# Скачайте на локальную машину
# На локальной машине:
scp dev@podzamenu:/media/ssd3/python_projects_backup_*.tar.gz ./
```

## Контакты и поддержка

- **GitHub:** https://github.com/BezdomnyiBox/Python_podzamenu
- **Документация API:** [README.md](README.md)

