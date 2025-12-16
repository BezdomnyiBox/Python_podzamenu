import requests
import json

# Простой тест
test_text = "Когда доставят мой заказ?"

try:
    print(f"Отправка запроса: {test_text}")
    response = requests.post(
        'http://127.0.0.1:8000/classify',
        json={'text': test_text},
        timeout=60
    )
    print(f"Статус: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        print(f"Результат: {json.dumps(result, indent=2, ensure_ascii=False)}")
    else:
        print(f"Ошибка: {response.text}")
except requests.exceptions.ConnectionError:
    print("❌ Сервер не запущен. Запустите: python -m uvicorn app:app --host 127.0.0.1 --port 8000")
except Exception as e:
    print(f"❌ Ошибка: {e}")

