# Symfony: API очереди WhatsApp для офисного агента

Справочные файлы для переноса в проект CRM на Symfony.  
Агент на офисном ПК опрашивает эти эндпоинты (`whatsapp/worker.py`).

## Установка в CRM

1. Выполните `migration.sql` или создайте Doctrine Migration.
2. Скопируйте классы в `src/` (пути в namespace `App\...`).
3. Добавьте фрагмент из `security.yaml.snippet`.
4. В `.env` CRM:

```env
WHATSAPP_AGENT_TOKEN=тот-же-токен-что-CRM_AGENT_TOKEN-на-офисном-ПК
WHATSAPP_AGENT_ID=office-main
```

5. Зарегистрируйте сервис `EnqueueWhatsappMessage` с `$defaultAgentId: '%whatsapp.agent_id%'`.

## API

### GET `/api/whatsapp/outbox`

Забрать пачку сообщений (статус → `processing`).

```
GET /api/whatsapp/outbox?agent_id=office-main&limit=5
Authorization: Bearer {WHATSAPP_AGENT_TOKEN}
```

Ответ:

```json
{
  "messages": [
    {
      "id": 1,
      "phone": "+79001234567",
      "text": "Заказ готов",
      "attempts": 1,
      "order_id": 987
    }
  ]
}
```

### POST `/api/whatsapp/outbox/{id}/ack`

```json
{"status": "sent", "message_id": "selenium_7900...", "sent_at": "2026-06-10T10:00:00+00:00"}
```

```json
{"status": "failed", "error": "Номер недоступен в WhatsApp"}
```

При `failed` и `attempts < max_attempts` статус возвращается в `pending` для повтора.

### POST `/api/whatsapp/agent/heartbeat`

```json
{"agent_id": "office-main", "logged_in": true, "version": "1.0"}
```

Таблица `whatsapp_agent_heartbeat` — для виджета «агент онлайн / нужен QR» в CRM.

## Схема таблицы `whatsapp_outbox`

| Поле | Тип | Описание |
|------|-----|----------|
| id | BIGINT | PK |
| agent_id | VARCHAR(64) | Какой офисный агент забирает |
| phone | VARCHAR(32) | Номер получателя |
| body | TEXT | Текст сообщения |
| status | VARCHAR(20) | pending / processing / sent / failed |
| attempts | SMALLINT | Счётчик попыток |
| max_attempts | SMALLINT | По умолчанию 3 |
| error_message | TEXT | Последняя ошибка |
| external_message_id | VARCHAR(128) | ID от агента |
| order_id | BIGINT | Связь с заказом (опционально) |
| scheduled_at | DATETIME | Отложенная отправка |
| locked_at / locked_by | | Блокировка при выдаче агенту |
| sent_at | DATETIME | Время успешной отправки |

## Тест вручную

```sql
INSERT INTO whatsapp_outbox (agent_id, phone, body, status, attempts, max_attempts, created_at, updated_at)
VALUES ('office-main', '+79001234567', 'Тест из CRM', 'pending', 0, 3, NOW(), NOW());
```

На офисном ПК: `python -m whatsapp.worker`
