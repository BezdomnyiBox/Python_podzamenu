# Сборка Windows-приложения (Podzamenu WhatsApp Agent)

## Что получится

Папка `dist/PodzamenuWhatsApp/`:

```
PodzamenuWhatsApp/
├── PodzamenuWhatsAppWorker.exe   # фоновый воркер (опрос CRM)
├── PodzamenuWhatsAppLogin.exe    # вход по QR (один раз)
├── .env                          # настройки (токен CRM)
├── .env.example
├── chrome_profile/               # создаётся автоматически (сессия WhatsApp)
├── logs/whatsapp_worker.log
├── install_autostart_exe.bat
└── start_worker_exe_hidden.vbs
```

**Google Chrome** на офисном ПК нужно установить отдельно — в .exe он не входит (~150 МБ и лицензия).

## Требования для сборки

- **Windows 10/11** (собирать нужно на Windows, не на Linux)
- Python 3.10+
- Интернет (pip, PyInstaller)

## Сборка

```bat
cd путь\к\Python_podzamenu
whatsapp\windows\build_exe.bat
```

Скрипт сам:
1. Создаст `venv` (если нет)
2. Установит `whatsapp/requirements-agent.txt`
3. Запустит PyInstaller
4. Сложит готовую папку в `dist/PodzamenuWhatsApp/`

Заархивируйте `dist/PodzamenuWhatsApp` в ZIP и отдайте на офисный ПК.

## Установка на офисном ПК

1. Распаковать ZIP в `C:\PodzamenuWhatsApp\`
2. Установить [Google Chrome](https://www.google.com/chrome/)
3. Открыть `.env`, прописать `CRM_AGENT_TOKEN` и `CRM_BASE_URL`
4. Запустить `PodzamenuWhatsAppLogin.exe` → сканировать QR
5. Запустить `PodzamenuWhatsAppWorker.exe` (или `install_autostart_exe.bat`)

## Ручная сборка (без bat)

```bat
python -m venv venv
venv\Scripts\pip install -r whatsapp\requirements-agent.txt
venv\Scripts\pyinstaller --noconfirm whatsapp\windows\PodzamenuWhatsApp.spec
whatsapp\windows\package_dist.bat
```

## Размер и антивирус

- Один .exe ≈ 25–40 МБ (Python + Selenium внутри)
- Windows Defender может ругаться на неподписанный exe — это нормально для PyInstaller
- Для продакшена: код-подпись (Authenticode) ~$200/год

## Обновление версии

1. Пересобрать на dev-машине
2. На офисном ПК заменить только `.exe` файлы
3. **Не удалять** `chrome_profile/` и `.env`

## Отладка

Запуск воркера с видимой консолью:

```bat
PodzamenuWhatsAppWorker.exe
```

Логи: `logs\whatsapp_worker.log`
