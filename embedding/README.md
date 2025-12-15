# API классификации намерений клиентов

FastAPI сервис для определения намерений клиентов с использованием sentence transformers.

## Запуск

```bash
# Активация виртуального окружения
source ../venv/bin/activate

# Запуск сервера
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

## API Endpoints

### POST /classify

Классифицирует текст клиента и определяет его намерение.

**Request:**
```json
{
  "text": "Где мой заказ №12345?"
}
```

**Response:**
```json
{
  "intent": "ORDER_INFO",
  "confidence": 0.7283040285110474,
  "order_number": "12345"
}
```

## Поддерживаемые интенты

- `ORDER_INFO` - Запрос информации о заказе
- `DELIVERY` - Вопрос о доставке (включая отслеживание через транспортную компанию)

## Извлечение номера заказа

API автоматически извлекает номер заказа из текста, если он упоминается в следующих форматах:
- `#12345`
- `заказ №12345`
- `заказ 12345`
- `номер заказа 12345`
- `заказ12345`

## Пример использования в Symfony

```php
<?php

namespace App\Controller;

use Symfony\Bundle\FrameworkBundle\Controller\AbstractController;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Annotation\Route;
use Symfony\Contracts\HttpClient\HttpClientInterface;

class ChatController extends AbstractController
{
    private HttpClientInterface $httpClient;
    private string $intentApiUrl;

    public function __construct(HttpClientInterface $httpClient, string $intentApiUrl)
    {
        $this->httpClient = $httpClient;
        $this->intentApiUrl = $intentApiUrl; // http://localhost:8000
    }

    #[Route('/api/chat', methods: ['POST'])]
    public function handleMessage(Request $request): JsonResponse
    {
        $data = json_decode($request->getContent(), true);
        $userMessage = $data['message'] ?? '';

        // Отправляем запрос в API классификации
        $response = $this->httpClient->request('POST', $this->intentApiUrl . '/classify', [
            'json' => ['text' => $userMessage]
        ]);

        $intentData = $response->toArray();
        $intent = $intentData['intent'];
        $orderNumber = $intentData['order_number'] ?? null;

        // Обработка намерения ORDER_INFO
        if ($intent === 'ORDER_INFO') {
            if ($orderNumber) {
                // Генерируем ссылку на заказ
                $orderLink = $this->generateOrderLink($orderNumber);
                return new JsonResponse([
                    'message' => "Вот ссылка на ваш заказ: {$orderLink}",
                    'intent' => $intent,
                    'order_number' => $orderNumber,
                    'order_link' => $orderLink
                ]);
            } else {
                // Запрашиваем номер заказа, если он не указан
                return new JsonResponse([
                    'message' => 'Пожалуйста, укажите номер вашего заказа',
                    'intent' => $intent
                ]);
            }
        }

        // Обработка намерения DELIVERY
        if ($intent === 'DELIVERY') {
            if ($orderNumber) {
                // Генерируем ссылку на отслеживание доставки
                $trackingLink = $this->generateTrackingLink($orderNumber);
                return new JsonResponse([
                    'message' => "Вот ссылка для отслеживания доставки заказа №{$orderNumber}: {$trackingLink}",
                    'intent' => $intent,
                    'order_number' => $orderNumber,
                    'tracking_link' => $trackingLink
                ]);
            } else {
                return new JsonResponse([
                    'message' => 'Пожалуйста, укажите номер заказа для отслеживания доставки',
                    'intent' => $intent
                ]);
            }
        }

        // Обработка других интентов
        return new JsonResponse([
            'message' => 'Чем могу помочь?',
            'intent' => $intent
        ]);
    }

    private function generateOrderLink(string $orderNumber): string
    {
        // Генерация ссылки на заказ
        return "https://your-site.com/orders/{$orderNumber}";
    }

    private function generateTrackingLink(string $orderNumber): string
    {
        // Генерация ссылки на отслеживание доставки через ТК
        return "https://your-site.com/tracking/{$orderNumber}";
    }
}
```

## Конфигурация Symfony

В `config/services.yaml`:

```yaml
parameters:
    intent_api_url: '%env(INTENT_API_URL)%'
```

В `.env`:

```
INTENT_API_URL=http://localhost:8000
```
