import subprocess
import time
import sys
import os
import requests
import signal
import atexit

# Получаем директорию скрипта
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# Запускаем сервер
print("Запуск сервера...")
# Используем DEVNULL для подавления вывода сервера
PORT = 8002  # Используем другой порт
log_file = os.path.join(script_dir, 'server.log')
with open(log_file, 'w') as f:
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', f'--port', str(PORT)],
        cwd=script_dir,
        stdout=f,
        stderr=subprocess.STDOUT
    )

# Функция для остановки сервера
def stop_server():
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except:
        try:
            proc.kill()
        except:
            pass

atexit.register(stop_server)

# Ждем запуска сервера и проверяем, что процесс работает
print("Ожидание запуска сервера...")
for i in range(25):
    if proc.poll() is not None:
        print(f"ОШИБКА: Сервер завершился с кодом {proc.returncode}")
        break
    time.sleep(1)
    if i == 8:
        print("Сервер запускается...")
    elif i == 15:
        print("Сервер должен быть готов...")

if proc.poll() is None:
    print("Сервер запущен и работает")
    # Дополнительное ожидание для полной инициализации
    print("Дополнительное ожидание для полной инициализации (3 сек)...")
    time.sleep(3)
else:
    print("Сервер не запущен!")

try:
    # Сначала проверяем простой эндпоинт
    print("Проверка простого эндпоинта /test...")
    try:
        test_response = requests.get(f'http://127.0.0.1:{PORT}/test', timeout=10)
        print(f"Тестовый эндпоинт: статус {test_response.status_code}")
        try:
            print(f"Ответ: {test_response.json()}")
        except:
            print(f"Тело ответа: {test_response.text[:100]}")
    except Exception as e:
        print(f"Ошибка при проверке тестового эндпоинта: {e}")
        import traceback
        traceback.print_exc()
    
    # Выполняем тест
    print("\nВыполнение теста...")
    test_text = "Когда доставят мой заказ?"
    print(f"Отправка запроса: {test_text}")
    print(f"URL: http://127.0.0.1:{PORT}/classify")
    response = requests.post(
        f'http://127.0.0.1:{PORT}/classify',
        json={'text': test_text},
        timeout=60
    )
    print(f"Статус: {response.status_code}")
    print(f"Заголовки: {dict(response.headers)}")
    if response.status_code == 200:
        result = response.json()
        import json
        print(f"Результат: {json.dumps(result, indent=2, ensure_ascii=False)}")
        print("\n✓ Тест пройден успешно! Код ответа: 200")
    else:
        print(f"Ошибка ({response.status_code}): {response.text}")
        print(f"Полный ответ: {response.content}")
finally:
    # Останавливаем сервер
    print("\nОстановка сервера...")
    stop_server()
    
    # Показываем логи сервера
    if os.path.exists(log_file):
        print("\nПоследние строки лога сервера:")
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                for line in lines[-10:]:
                    print(line.rstrip())
        except:
            pass
    
    print("Тест завершен")
