import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import pandas as pd
import os
import time
import random
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from pathlib import Path

# Настройки
BASE_URL = "https://baza.drom.ru/{city}/sell_spare_parts/?goodPresentState%5B%5D=present&manufacturer={brand}&query={part_number}"


class DromParserGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Drom.ru Парсер запчастей")
        self.root.geometry("600x300")
        self.root.resizable(False, False)

        # Путь к входному файлу
        self.input_path = tk.StringVar()
        # Город
        self.city = tk.StringVar(value="vladivostok")
        # Папка для сохранения
        self.output_dir = tk.StringVar()

        self.create_widgets()

    def create_widgets(self):
        frame = ttk.Frame(self.root, padding="15")
        frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Загрузка Excel файла
        ttk.Label(frame, text="1. Выберите Excel-файл с брендами и артикулами:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(frame, textvariable=self.input_path, width=50, state="readonly").grid(row=1, column=0, sticky=tk.W)
        ttk.Button(frame, text="Обзор...", command=self.browse_input).grid(row=1, column=1, padx=5)

        # Ввод города
        ttk.Label(frame, text="2. Укажите город (латиницей, как в URL drom.ru):").grid(row=2, column=0, sticky=tk.W, pady=(15,5))
        ttk.Entry(frame, textvariable=self.city, width=30).grid(row=3, column=0, sticky=tk.W)

        # Выбор папки для сохранения
        ttk.Label(frame, text="3. Папка для сохранения результатов:").grid(row=4, column=0, sticky=tk.W, pady=(15,5))
        ttk.Entry(frame, textvariable=self.output_dir, width=50, state="readonly").grid(row=5, column=0, sticky=tk.W)
        ttk.Button(frame, text="Выбрать папку...", command=self.browse_output_dir).grid(row=5, column=1, padx=5)

        # Старт
        ttk.Button(frame, text="▶️ Запустить парсинг", command=self.start_parsing).grid(row=6, column=0, pady=20, sticky=tk.W)

        # Прогресс
        self.progress = ttk.Progressbar(frame, orient="horizontal", mode="determinate", length=500)
        self.progress.grid(row=7, column=0, columnspan=2, pady=5)

        self.status_label = ttk.Label(frame, text="", foreground="gray")
        self.status_label.grid(row=8, column=0, columnspan=2, pady=5)

    def browse_input(self):
        path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx")])
        if path:
            self.input_path.set(path)

    def browse_output_dir(self):
        path = filedialog.askdirectory()
        if path:
            self.output_dir.set(path)

    def human_delay(self, min_sec=1.5, max_sec=4.2):
        delay = random.uniform(min_sec, max_sec)
        time.sleep(delay)

    def start_parsing(self):
        if not self.input_path.get():
            messagebox.showerror("Ошибка", "Выберите Excel-файл!")
            return
        if not self.output_dir.get():
            messagebox.showerror("Ошибка", "Выберите папку для сохранения!")
            return
        if not self.city.get().strip():
            messagebox.showerror("Ошибка", "Укажите город!")
            return

        try:
            self.run_parsing()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Произошла ошибка:\n{str(e)}")
            self.status_label.config(text="Остановлено из-за ошибки", foreground="red")

    def run_parsing(self):
        input_file = self.input_path.get()
        city = self.city.get().strip().lower()
        output_dir = self.output_dir.get()

        # Чтение Excel
        try:
            df = pd.read_excel(input_file, header=None)
        except Exception as e:
            raise Exception(f"Не удалось прочитать Excel-файл: {e}")

        # Предполагаем, что бренды — столбец B (индекс 1), артикулы — D (индекс 3)
        if len(df.columns) < 4:
            raise Exception("Файл должен содержать как минимум 4 столбца (A, B, C, D).")

        brands = df.iloc[:, 1].dropna().astype(str).tolist()  # B:B
        part_numbers = df.iloc[:, 3].dropna().astype(str).tolist()  # D:D

        min_len = min(len(brands), len(part_numbers))
        if min_len == 0:
            raise Exception("Нет данных в столбцах B или D.")

        self.progress["maximum"] = min_len
        self.status_label.config(text=f"Найдено {min_len} пар бренд/артикул. Готов к работе...", foreground="green")

        # Настройка Chrome
        chrome_options = Options()
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
        chrome_options.add_argument("--start-maximized")

        # Для отладки — закомментируйте следующую строку, чтобы видеть браузер
        # chrome_options.add_argument("--headless=new")  # ⚠️ НЕ использовать headless — CAPTCHA чаще

        driver = webdriver.Chrome(options=chrome_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            for i in range(min_len):
                brand = brands[i]
                part_num = part_numbers[i]

                self.status_label.config(text=f"Обработка [{i+1}/{min_len}]: {brand} — {part_num}", foreground="blue")
                self.progress["value"] = i + 1
                self.root.update_idletasks()

                # Формируем URL
                safe_brand = brand.replace(" ", "%20")
                url = BASE_URL.format(city=city, brand=safe_brand, part_number=part_num)
                self.status_label.config(text=f"Открываем: {brand} / {part_num}", foreground="gray")

                driver.get(url)
                self.human_delay(2.0, 5.0)

                # Проверка на CAPTCHA (ручное ожидание)
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CLASS_NAME, "bulletinLink"))
                    )
                except TimeoutException:
                    # Проверим, не CAPTCHA ли на экране
                    if "Вы не робот?" in driver.page_source or "подозрительный трафик" in driver.page_source:
                        messagebox.showwarning(
                            "CAPTCHA обнаружена",
                            f"Появилась проверка 'Вы не робот?'.\nРешите её в браузере, затем нажмите OK, чтобы продолжить."
                        )
                        # Ждем, пока пользователь не решит — просто пауза
                        input("Нажмите Enter в консоли после прохождения CAPTCHA (если запущено в IDE — просто закройте окно предупреждения и продолжите вручную)...")

                # Парсинг первых 6 товаров
                items = []
                try:
                    listings = driver.find_elements(By.CSS_SELECTOR, ".bull-item")
                    for idx, listing in enumerate(listings[:6]):
                        try:
                            # Цена
                            price_el = listing.find_element(By.CSS_SELECTOR, ".price-block__price[data-role='price']")
                            price_text = price_el.text.replace("₽", "").replace(" ", "").replace("\u2009", "").strip()
                            price = int(price_text) if price_text.isdigit() else None

                            # Конкурент (магазин)
                            try:
                                seller_el = listing.find_element(By.CSS_SELECTOR, ".ellipsis-text__left-side")
                                seller = seller_el.text.strip().strip('"')
                            except:
                                seller = "Не указан"

                            # Ссылка
                            link_el = listing.find_element(By.CSS_SELECTOR, "a.bulletinLink[data-role='bulletin-link']")
                            href = link_el.get_attribute("href")
                            title = link_el.text.strip()

                            items.append({
                                "Цена, ₽": price,
                                "Конкурент": seller,
                                "Название": title,
                                "Ссылка": href
                            })
                        except Exception as e:
                            print(f"  Ошибка при парсинге элемента {idx+1}: {e}")
                            continue

                except Exception as e:
                    print(f"Ошибка при извлечении списка: {e}")
                    items = []

                # Сортируем по цене (None — в конец)
                items.sort(key=lambda x: x["Цена, ₽"] if x["Цена, ₽"] is not None else float('inf'))

                # Сохраняем в Excel
                if items:
                    wb = Workbook()
                    ws = wb.active
                    ws.title = "Результаты"

                    # Заголовки
                    headers = ["Цена, ₽", "Конкурент", "Название", "Ссылка"]
                    ws.append(headers)
                    for cell in ws[1]:
                        cell.font = Font(bold=True)
                        cell.alignment = Alignment(horizontal="left")

                    for item in items:
                        ws.append([
                            item["Цена, ₽"] or "",
                            item["Конкурент"],
                            item["Название"],
                            item["Ссылка"]
                        ])

                    filename = f"{brand}_{part_num}_{city}.xlsx".replace("/", "_").replace("\\", "_")
                    filepath = os.path.join(output_dir, filename)
                    wb.save(filepath)
                    self.status_label.config(text=f"✅ Сохранено: {filename}", foreground="green")
                else:
                    self.status_label.config(text=f"⚠️ Нет товаров для {brand} / {part_num}", foreground="orange")

                # Задержка между итерациями
                self.human_delay(3.0, 7.5)

        finally:
            driver.quit()

        messagebox.showinfo("Готово!", f"Обработано {min_len} строк.\nРезультаты сохранены в:\n{output_dir}")
        self.status_label.config(text="✅ Завершено", foreground="green")


if __name__ == "__main__":
    root = tk.Tk()
    app = DromParserGUI(root)
    root.mainloop()