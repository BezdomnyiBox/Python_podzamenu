# Безопасность и развертывание

## Настройка безопасного доступа к серверу

### 1. SSH ключи (✅ Уже настроено)

SSH ключи обеспечивают безопасный вход без пароля.

### 2. Sudo без пароля для systemctl (Рекомендуется)

Для автоматического перезапуска сервиса без хранения паролей настройте sudo:

```bash
# На сервере выполните:
sudo visudo

# Добавьте в конец файла:
dev ALL=(ALL) NOPASSWD: /bin/systemctl restart embedding-api.service
dev ALL=(ALL) NOPASSWD: /bin/systemctl status embedding-api.service
dev ALL=(ALL) NOPASSWD: /bin/systemctl is-active embedding-api.service
```

После этого скрипт `update_server.sh` будет работать без запроса пароля.

### 3. Использование переменных окружения (Альтернатива)

Если не хотите настраивать sudo без пароля, используйте переменную окружения:

```bash
# Экспортируйте переменную перед запуском скрипта:
export SERVER_SUDO_PASSWORD='your_password'
./update_server.sh

# Или добавьте в ~/.bashrc для постоянного использования:
echo "export SERVER_SUDO_PASSWORD='your_password'" >> ~/.bashrc
source ~/.bashrc
```

**ВАЖНО:** Никогда не коммитьте пароли в Git!

## Безопасность файлов конфигурации

### SSH Config
Файл `~/.ssh/config` содержит только публичную информацию:
- IP адрес сервера
- Порт SSH
- Имя пользователя
- Путь к SSH ключу

Приватный ключ (`~/.ssh/id_ed25519`) должен иметь права доступа 600:
```bash
chmod 600 ~/.ssh/id_ed25519
```

### Git
Файлы `.env` и приватные ключи автоматически игнорируются Git через `.gitignore`.

## Проверка безопасности

```bash
# Проверьте, что пароли не попали в Git:
git log --all --full-history --source -- "*password*" "*secret*" "*.env"

# Проверьте права доступа к SSH ключам:
ls -la ~/.ssh/
```

## Что делать если пароль попал в Git

1. Смените пароль на сервере
2. Используйте git filter-branch или BFG Repo-Cleaner для очистки истории
3. Сделайте force push (с осторожностью!)

```bash
# Пример использования BFG:
# bfg --replace-text passwords.txt repo.git
```

