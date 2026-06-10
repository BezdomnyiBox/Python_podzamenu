# Исходники Python - Внутренние утилиты

Набор Python-скриптов для автоматизации бизнес-процессов.

## Структура проекта

```
ИсходникиПитон/
├── avito/                      # Автоматизация Авито
│   └── Avito_Del_parser.py     # Удаление товаров с ошибками
│
├── delivery_analytics/         # Аналитика доставок
│   └── Анализ_Доставки.py      # GUI-приложение (v4.4, API CRM)
│
├── dialogs/                    # Обработка диалогов
│   └── Диалоги_фарпост.py      # Парсинг диалогов из Farpost
│
├── parsers/                    # Веб-парсеры
│   └── Парсинг_Конкурентов.py  # Парсер цен с Drom.ru
│
├── photo_tools/                # Работа с фото
│   └── Фотки_CRM.py            # Обработка .jpg файлов
│
├── whatsapp/                   # WhatsApp Web через Selenium (альтернатива Wazzup API)
│   ├── app.py                  # FastAPI HTTP-сервис (отладка)
│   ├── worker.py               # Опрос очереди CRM и отправка
│   ├── crm_client.py           # HTTP-клиент к Symfony API
│   ├── login.py                # Первичная авторизация по QR
│   ├── sender.py               # Отправка сообщений
│   ├── symfony_reference/      # Схема БД и PHP для CRM
│   └── windows/                # Автозапуск на Windows
│
├── requirements.txt            # Зависимости проекта
└── README.md                   # Документация
```

## Установка

```bash
# Создание виртуального окружения
python -m venv venv

# Активация (Windows)
venv\Scripts\activate

# Установка зависимостей
pip install -r requirements.txt
```

## Модули

### avito/

**Avito Error Items Deleter** - автоматическое удаление товаров с ошибками на Авито.

- Использует `undetected_chromedriver` для обхода защиты
- Требует ручной авторизации

### delivery_analytics/

**Аналитика доставок** - GUI-приложение для анализа логистики.

- Загрузка данных с CRM API (`crm.podzamenu.ru`)
- SQLite база для расписания поставок
- Экспорт отчётов в Excel
- Статистика: % вовремя, медианное отклонение, рекомендации

### dialogs/

**Dialog Splitter** - обработка диалогов из Excel/Farpost.

- Парсинг HTML-разметки (BeautifulSoup)
- Разбивка на части по N диалогов
- Выравнивание и форматирование Excel

### parsers/

**Drom Parser** - парсер цен конкурентов с Drom.ru.

- Чтение брендов/артикулов из Excel
- Selenium-парсинг с обработкой CAPTCHA
- Сохранение результатов в Excel

### photo_tools/

**Photo Manager** - утилита для работы с .jpg файлами.

- Очистка имён от спецсимволов
- Фильтрация по артикулов из Excel
- Организация по папкам

### whatsapp/

**WhatsApp Selenium API** — отправка сообщений через WhatsApp Web без Wazzup.

> ⚠️ Неофициальный способ: риск бана номера, сессия может слететь. Используйте отдельный тестовый номер.

**Быстрый старт:**

```bash
cd "/home/vladimir/Рабочий стол/PythonPodzamenu/Python_podzamenu"
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # задайте WHATSAPP_API_KEY

# 1. Авторизация (один раз, откроется Chrome с QR)
python -m whatsapp.login

# 2. Запуск воркера (опрос CRM)
python -m whatsapp.worker

# Опционально: локальный HTTP API для тестов
python -m whatsapp.app
```

**Автозапуск на Windows:** `whatsapp\windows\install_autostart.bat`

**Сборка отдельного .exe:** `whatsapp\windows\build_exe.bat` (только на Windows), см. `whatsapp/windows/BUILD.md`

**API на стороне CRM (Symfony):** см. `whatsapp/symfony_reference/README.md`

**Отправка через HTTP:**

```bash
curl -X POST http://127.0.0.1:8765/send \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me-to-secret-key" \
  -d '{"phone": "+79001234567", "text": "Тестовое сообщение"}'
```

**Проверка сессии:**

```bash
curl -H "X-API-Key: change-me-to-secret-key" http://127.0.0.1:8765/status
```

Переменные окружения — в `.env.example`.

## Требования

- Python 3.10+
- Google Chrome (для Selenium-скриптов)
- Windows OS (для некоторых скриптов)

## Лицензия

Внутреннее использование (c) 2025
