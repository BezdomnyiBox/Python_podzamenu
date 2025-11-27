import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException
import time
import random

# Функция для случайных задержек
def random_delay(min_delay=0.5, max_delay=2.5):
    time.sleep(random.uniform(min_delay, max_delay))

# Настройки браузера
chrome_options = uc.ChromeOptions()
chrome_options.add_argument("--start-maximized")
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_argument("--disable-infobars")
chrome_options.add_argument("--disable-extensions")
chrome_options.add_argument("--disable-plugins-discovery")
chrome_options.add_argument("--disable-web-security")
chrome_options.add_argument("--allow-running-insecure-content")

# Запуск браузера с указанием версии Chrome (чтобы избежать ошибки SessionNotCreatedException)
# Укажи свою основную версию Chrome (например, 138), или оставь None — автоопределение
try:
    # Попробуем определить версию Chrome (опционально)
    import subprocess
    import re
    result = subprocess.run(
        ['reg', 'query', 'HKEY_CURRENT_USER\\Software\\Google\\Chrome\\BLBeacon', '/v', 'version'],
        capture_output=True, text=True
    )
    version_match = re.search(r'\d+\.\d+', result.stdout)
    chrome_version = int(version_match.group(0).split('.')[0]) if version_match else None
except Exception:
    chrome_version = None  # автоопределение

# Запускаем драйвер
driver = uc.Chrome(options=chrome_options, version_main=chrome_version)
wait = WebDriverWait(driver, 15)

# Скрытие следов автоматизации
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
    "source": """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => false
        });
        window.navigator = {
            ...window.navigator,
            languages: ['ru-RU', 'ru', 'en'],
            plugins: [1, 2, 3],
            webdriver: false
        };
    """
})

try:
    # 1) Открытие страницы (убраны лишние пробелы в URL)
    driver.get("https://www.avito.ru/profile/pro/items")
    print("Браузер открыт. Авторизуйтесь вручную.")
    input("После авторизации нажмите Enter в терминале, чтобы продолжить...")

    while True:
        try:
            # === 1. Перейти во вкладку "С ошибками" ===
            print("Поиск вкладки 'С ошибками'...")
            error_tab = wait.until(
                EC.element_to_be_clickable((By.XPATH, '//span[contains(text(), "С ошибками")]'))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", error_tab)
            random_delay(1, 2)

            try:
                error_tab.click()
            except ElementClickInterceptedException:
                print("Клик по вкладке 'С ошибками' заблокирован. Кликаю через JS...")
                driver.execute_script("arguments[0].click();", error_tab)

            random_delay(2, 3)

            # === 2. Клик по чекбоксу (обёртка) ===
            print("Поиск чекбокса (обёртка)...")
            checkbox_cover = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, '.css-1s1m1fg'))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", checkbox_cover)
            random_delay(1, 2)

            try:
                checkbox_cover.click()
            except ElementClickInterceptedException:
                print("Клик по чекбоксу заблокирован. Кликаю через JS...")
                driver.execute_script("arguments[0].click();", checkbox_cover)

            random_delay()

            # === 3. Нажать кнопку "Удалить" ===
            print("Поиск кнопки 'Удалить'...")
            delete_button = wait.until(
                EC.element_to_be_clickable((By.XPATH, '//span[contains(text(), "Удалить")]'))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", delete_button)
            random_delay()

            try:
                delete_button.click()
            except ElementClickInterceptedException:
                print("Клик по 'Удалить' заблокирован. Кликаю через JS...")
                driver.execute_script("arguments[0].click();", delete_button)

            random_delay(2, 3)

            # === 4. Подтвердить удаление (прокрутка вниз + клик) ===
            print("Прокручиваю вниз для кнопки подтверждения...")
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            random_delay(1, 2)

            confirm_button = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'span.button-textBox-I7MBX'))
            )
            try:
                confirm_button.click()
            except ElementClickInterceptedException:
                print("Клик по подтверждению заблокирован. Кликаю через JS...")
                driver.execute_script("arguments[0].click();", confirm_button)

            print("Удаление подтверждено.")
            random_delay(3, 5)

            # === 5. Обновить страницу ===
            print("Обновление страницы...")
            driver.refresh()
            random_delay(4, 6)

        except TimeoutException:
            print("Элемент не найден или страница не загрузилась. Обновляю...")
            driver.refresh()
            random_delay(5, 7)

        except ElementClickInterceptedException as e:
            print(f"Не удалось кликнуть: {e}. Обновляю страницу...")
            driver.refresh()
            random_delay(5, 7)

        except Exception as e:
            print(f"Неожиданная ошибка: {e}")
            print("Повторная попытка...")
            driver.refresh()
            random_delay(5, 7)

except KeyboardInterrupt:
    print("Скрипт остановлен пользователем.")

finally:
    print("Закрытие браузера...")
    try:
        driver.quit()
    except Exception as e:
        print(f"Ошибка при закрытии браузера: {e}")