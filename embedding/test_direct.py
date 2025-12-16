"""
Прямой тест без запуска HTTP сервера - использует TestClient FastAPI
"""
from fastapi.testclient import TestClient
import app

# Создаем тестовый клиент
client = TestClient(app.app)

# Выполняем тест
test_text = "Когда доставят мой заказ?"
print(f"Отправка запроса: {test_text}")

response = client.post('/classify', json={'text': test_text})
print(f"Статус: {response.status_code}")

if response.status_code == 200:
    result = response.json()
    import json
    print(f"Результат: {json.dumps(result, indent=2, ensure_ascii=False)}")
    print("\nТест пройден успешно! Код ответа: 200")
else:
    print(f"Ошибка: {response.text}")

