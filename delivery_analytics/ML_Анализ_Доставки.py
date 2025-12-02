"""
ML-Аналитика доставок версия 2.0

Программа для анализа и предсказания времени привоза с использованием
машинного обучения. Выдает рекомендации по корректировке графика поставок.

Возможности:
- Порционная загрузка исторических данных
- ML-предсказание отклонений времени привоза
- Детекция трендов и аномалий
- Интерактивные графики
- Экспорт рекомендаций в Excel
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkcalendar import DateEntry
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import webbrowser
from pathlib import Path
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
import requests
from io import BytesIO
import threading
import sys
import os
import time
import argparse

# Графики
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
import matplotlib.dates as mdates
# Настройка шрифтов для русского языка и эмодзи
import platform
if platform.system() == 'Windows':
    # На Windows используем шрифт с поддержкой эмодзи
    # Пробуем разные варианты для лучшей поддержки эмодзи
    # Убрали 'Arial Unicode MS' так как он может отсутствовать в системе
    plt.rcParams['font.family'] = ['Segoe UI', 'Segoe UI Emoji', 'Microsoft YaHei', 'DejaVu Sans']
    plt.rcParams['font.sans-serif'] = ['Segoe UI', 'Segoe UI Emoji', 'Microsoft YaHei', 'DejaVu Sans', 'Noto Color Emoji']
else:
    # На Linux/Mac используем системные шрифты
    plt.rcParams['font.family'] = ['DejaVu Sans', 'Noto Color Emoji', 'Apple Color Emoji']
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Noto Color Emoji', 'Apple Color Emoji']
plt.rcParams['axes.unicode_minus'] = False

# Импорт ML модуля
from ml_predictor import DeliveryMLPredictor, ScheduleRecommendation, TrendType

# ========================================
# ПАРСИНГ АРГУМЕНТОВ КОМАНДНОЙ СТРОКИ
# ========================================
def parse_arguments():
    """Парсинг аргументов командной строки"""
    parser = argparse.ArgumentParser(
        description='ML-Аналитика доставок - программа для анализа времени привоза',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python ML_Анализ_Доставки.py                    # Локальный CRM (по умолчанию)
  python ML_Анализ_Доставки.py --env local        # Локальный CRM
  python ML_Анализ_Доставки.py --env prod         # Production CRM
  python ML_Анализ_Доставки.py --crm-url http://custom.crm.com  # Произвольный URL
        """
    )
    
    parser.add_argument(
        '--env',
        choices=['local', 'prod'],
        default='local',
        help='Окружение: local (локальный CRM) или prod (production). По умолчанию: local'
    )
    
    parser.add_argument(
        '--crm-url',
        type=str,
        default=None,
        help='Прямое указание URL CRM (переопределяет --env). Пример: http://crm.example.com'
    )
    
    return parser.parse_args()


# Определяем URL CRM на основе аргументов командной строки
args = parse_arguments()

if args.crm_url:
    # Если указан прямой URL, используем его
    CRM_BASE_URL = args.crm_url.rstrip('/')
elif args.env == 'prod':
    # Production окружение
    CRM_BASE_URL = "https://crm.podzamenu.ru"
else:
    # Локальное окружение (по умолчанию)
    CRM_BASE_URL = "http://crm.public.lan"

# ========================================
# КОНСТАНТЫ
# ========================================
DAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
DAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

# Цветовая схема
COLORS = {
    'bg': '#f0f2f5',
    'header': '#1a237e',
    'primary': '#3f51b5',
    'success': '#4caf50',
    'warning': '#ff9800',
    'danger': '#f44336',
    'info': '#2196f3',
    'text': '#212121',
    'text_light': '#757575',
    'card': '#ffffff'
}

DEFAULT_PV_LABEL = "ПВ не указан"


def normalize_pv_value(value):
    """Единый формат отображения ПВ"""
    if value is None or pd.isna(value):
        return DEFAULT_PV_LABEL
    value_str = str(value).strip()
    return value_str if value_str else DEFAULT_PV_LABEL


def normalize_pv_column(df: pd.DataFrame) -> pd.DataFrame:
    """Гарантирует наличие и корректность столбца ПВ"""
    if 'ПВ' not in df.columns:
        df['ПВ'] = DEFAULT_PV_LABEL
    else:
        df['ПВ'] = df['ПВ'].apply(normalize_pv_value)
    return df

# ========================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ========================================
df_original = None
df_current = None
ml_predictor = None
recommendations = []
schedule_recommendations = []  # Рекомендации на основе расписания
is_model_trained = False
current_pv_filter = None  # Текущий фильтр по ПВ
schedules_cache = None  # Кэш расписания доставки

# Переменные сортировки для таблиц
sort_states = {}


# ========================================
# ЗАГРУЗКА РАСПИСАНИЯ ДОСТАВКИ
# ========================================
def fetch_schedules():
    """Загрузка расписания доставки с сервера"""
    global schedules_cache
    
    try:
        url = f"{CRM_BASE_URL}/logistic/schedules?type=jsonresponse"
        response = requests.get(url, timeout=30)
        
        if response.status_code == 500:
            print(f"Ошибка сервера 500: эндпоинт {url} не доступен или не реализован")
            return []
        
        response.raise_for_status()
        
        data = response.json()
        if data.get('result') == 'success':
            schedules_cache = data.get('data', [])
            print(f"Загружено {len(schedules_cache)} записей расписания")
            return schedules_cache
        else:
            print(f"API вернул ошибку: {data}")
    except requests.exceptions.ConnectionError:
        print(f"Ошибка подключения к серверу: {CRM_BASE_URL}")
    except requests.exceptions.Timeout:
        print(f"Таймаут при загрузке расписания")
    except Exception as e:
        print(f"Ошибка загрузки расписания: {e}")
    
    return []


def get_schedules_for_warehouse_pv(warehouse, pv):
    """Получить расписание для конкретного склада и ПВ"""
    global schedules_cache
    
    # Загружаем расписание если ещё не загружено
    if schedules_cache is None:
        fetch_schedules()
    
    if not schedules_cache:
        return []
    
    # Нормализуем для сравнения
    warehouse_lower = warehouse.lower().strip() if warehouse else ""
    pv_lower = pv.lower().strip() if pv else ""
    
    matching = []
    for schedule in schedules_cache:
        sched_warehouse = (schedule.get('warehouse') or '').lower().strip()
        sched_branch = (schedule.get('branch') or '').lower().strip()
        
        # Проверяем совпадение (warehouse = склад поставщика, branch = адрес ПВ)
        # Сравниваем частичное совпадение, так как названия могут немного отличаться
        warehouse_match = (sched_warehouse in warehouse_lower or warehouse_lower in sched_warehouse or 
                          any(word in warehouse_lower for word in sched_warehouse.split() if len(word) > 3))
        pv_match = (sched_branch in pv_lower or pv_lower in sched_branch or
                    any(word in pv_lower for word in sched_branch.split(',')[0].split() if len(word) > 3))
        
        if warehouse_match and pv_match:
            matching.append(schedule)
    
    return matching


def calculate_expected_delivery(time_order_str, delivery_duration):
    """Рассчитать ожидаемое время доставки"""
    try:
        # time_order в формате "HH:MM"
        hours, minutes = map(int, time_order_str.split(':'))
        total_minutes = hours * 60 + minutes + delivery_duration
        result_hours = total_minutes // 60
        result_minutes = total_minutes % 60
        
        # Если переходит на следующий день
        if result_hours >= 24:
            result_hours = result_hours % 24
            return f"{result_hours:02d}:{result_minutes:02d} (+1д)"
        
        return f"{result_hours:02d}:{result_minutes:02d}"
    except:
        return "—"


WEEKDAY_MAP = {
    1: "Понедельник",
    2: "Вторник", 
    3: "Среда",
    4: "Четверг",
    5: "Пятница",
    6: "Суббота",
    7: "Воскресенье"
}

WEEKDAY_TO_NUM = {
    "Понедельник": 1,
    "Вторник": 2, 
    "Среда": 3,
    "Четверг": 4,
    "Пятница": 5,
    "Суббота": 6,
    "Воскресенье": 7
}


def find_schedule_window_for_order(order_weekday, order_hour, order_minute, schedules_for_pv):
    """
    Найти окно расписания, в которое попадает заказ.
    
    Логика: заказ попадает в окно, если время заказа <= время "Заказ до" этого окна
    и > время "Заказ до" предыдущего окна того же дня.
    
    Returns:
        dict с информацией об окне или None
    """
    if not schedules_for_pv:
        return None
    
    weekday_num = WEEKDAY_TO_NUM.get(order_weekday, 0)
    if not weekday_num:
        return None
    
    # Фильтруем окна этого дня недели и сортируем по времени
    day_windows = [s for s in schedules_for_pv if s.get('weekday') == weekday_num]
    if not day_windows:
        return None
    
    # Сортируем по времени "Заказ до"
    def get_time_minutes(sched):
        try:
            t = sched.get('timeOrder', '00:00')
            h, m = map(int, t.split(':'))
            return h * 60 + m
        except:
            return 0
    
    day_windows.sort(key=get_time_minutes)
    
    order_time_minutes = order_hour * 60 + order_minute
    
    # Ищем подходящее окно
    for window in day_windows:
        window_time = get_time_minutes(window)
        if order_time_minutes <= window_time:
            return window
    
    # Если заказ после всех окон — возвращаем последнее (или None)
    return day_windows[-1] if day_windows else None


def generate_schedule_recommendations(df, schedules_data):
    """
    Генерация рекомендаций по корректировке расписания на основе фактических данных.
    
    Логика:
    1. Для каждого окна расписания находим заказы, попадающие в это окно
    2. Сопоставляем по: день недели + время заказа <= "Заказ до"
    3. Группируем по поставщику, складу, ПВ
    4. Рассчитываем медиану отклонений и рекомендуемую корректировку
    
    Returns:
        Список рекомендаций с полями:
        - supplier, warehouse, pv, weekday, time_order
        - current_duration, recommended_duration, shift_minutes
        - confidence, orders_count, median_deviation, delivery_type
    """
    if df is None or df.empty or not schedules_data:
        return []
    
    recommendations = []
    
    # Подготовка данных
    df_prep = df.copy()
    df_prep['Час'] = df_prep['Время заказа позиции'].dt.hour
    df_prep['Минута'] = df_prep['Время заказа позиции'].dt.minute
    df_prep['День_недели'] = df_prep['Время заказа позиции'].apply(get_weekday_name)
    
    # Индексируем расписание по складу для быстрого поиска
    schedule_by_warehouse = {}
    for sched in schedules_data:
        warehouse = sched.get('warehouse', '').lower().strip()
        if warehouse:
            # Берём первое слово склада для сопоставления
            key = warehouse.split()[0] if warehouse else ''
            if key not in schedule_by_warehouse:
                schedule_by_warehouse[key] = []
            schedule_by_warehouse[key].append(sched)
    
    # Обрабатываем каждое окно расписания
    processed_keys = set()  # Избегаем дубликатов
    
    for sched in schedules_data:
        warehouse_sched = sched.get('warehouse', '')
        branch = sched.get('branch', '')  # ПВ из расписания
        weekday_num = sched.get('weekday')
        time_order = sched.get('timeOrder', '')
        current_duration = sched.get('deliveryDuration', 0)
        delivery_type = sched.get('type', 'self')
        
        weekday_name = WEEKDAY_MAP.get(weekday_num, '')
        if not weekday_name or not time_order:
            continue
        
        try:
            order_hour = int(time_order.split(':')[0])
            order_minute = int(time_order.split(':')[1])
        except:
            continue
        
        # Фильтруем заказы для этого окна:
        # 1. День недели совпадает
        # 2. Время заказа в диапазоне: (предыдущее окно или 00:00) < время <= текущее окно
        day_mask = df_prep['День_недели'] == weekday_name
        
        # Текущее время окна в минутах
        current_window_minutes = order_hour * 60 + order_minute
        
        # Ищем предыдущее окно того же дня и склада
        same_day_windows = [s for s in schedules_data 
                          if s.get('weekday') == weekday_num and s.get('warehouse') == warehouse_sched]
        
        # Сортируем окна по времени
        def get_minutes(s):
            try:
                t = s.get('timeOrder', '00:00')
                h, m = map(int, t.split(':'))
                return h * 60 + m
            except:
                return 0
        
        same_day_windows.sort(key=get_minutes)
        
        # Находим границу предыдущего окна (или 00:00 для первого)
        prev_window_minutes = 0  # По умолчанию 00:00
        for i, w in enumerate(same_day_windows):
            if w.get('timeOrder') == time_order:
                if i > 0:
                    prev_window_minutes = get_minutes(same_day_windows[i-1])
                break
        
        # Время заказа в минутах
        order_time_minutes = df_prep['Час'] * 60 + df_prep['Минута']
        
        # Условие: prev_window < время_заказа <= current_window
        # Для первого окна: 0 <= время_заказа <= current_window (включаем 00:00)
        if prev_window_minutes == 0:
            time_mask = order_time_minutes <= current_window_minutes
        else:
            time_mask = (order_time_minutes > prev_window_minutes) & (order_time_minutes <= current_window_minutes)
        
        window_data = df_prep[day_mask & time_mask]
        
        if len(window_data) < 3:
            continue
        
        # Группируем по поставщику-складу-ПВ
        for (supplier, wh, pv), group in window_data.groupby(['Поставщик', 'Склад', 'ПВ']):
            # Создаём уникальный ключ для избежания дубликатов
            rec_key = f"{supplier}_{wh}_{pv}_{weekday_num}_{time_order}"
            if rec_key in processed_keys:
                continue
            
            if len(group) < 3:
                continue
            
            deviations = group['Разница во времени привоза (мин.)'].dropna()
            if len(deviations) < 3:
                continue
            
            median_dev = deviations.median()
            std_dev = deviations.std() if len(deviations) > 1 else 30
            on_time_pct = (deviations.between(-30, 30).sum() / len(deviations)) * 100
            
            # Рассчитываем рекомендуемую длительность
            recommended_duration = current_duration + int(round(median_dev))
            shift = recommended_duration - current_duration
            
            # Пропускаем, если корректировка незначительная
            if abs(shift) < 15:
                continue
            
            # Рассчитываем уверенность
            # Факторы: количество данных, стабильность, процент вовремя
            count_factor = min(1.0, len(group) / 20)
            std_factor = max(0, min(1, 1 - std_dev / 60)) if std_dev else 0.5
            ontime_factor = on_time_pct / 100  # Чем меньше % вовремя, тем нужнее рекомендация
            
            # Если много опозданий - уверенность выше
            if on_time_pct < 50:
                confidence = 0.5 + 0.25 * count_factor + 0.25 * std_factor
            else:
                confidence = 0.3 + 0.35 * count_factor + 0.35 * std_factor
            
            confidence = round(min(0.95, confidence), 2)
            
            processed_keys.add(rec_key)
            
            recommendations.append({
                'supplier': supplier,
                'warehouse': wh,
                'pv': pv,
                'weekday': weekday_name,
                'weekday_num': weekday_num,
                'time_order': time_order,
                'current_duration': current_duration,
                'recommended_duration': recommended_duration,
                'shift_minutes': shift,
                'confidence': confidence,
                'orders_count': len(group),
                'median_deviation': median_dev,
                'on_time_pct': on_time_pct,
                'delivery_type': delivery_type
            })
    
    # Удаляем дубликаты - оставляем только одну рекомендацию на комбинацию
    # Поставщик-Склад-ПВ-День-Заказ_до (выбираем с максимальной уверенностью)
    unique_recommendations = {}
    for rec in recommendations:
        # Ключ уникальности: поставщик + склад + ПВ + день + время заказа
        key = (
            rec['supplier'],
            rec['warehouse'], 
            rec['pv'],
            rec['weekday_num'],
            rec['time_order']
        )
        
        if key not in unique_recommendations:
            unique_recommendations[key] = rec
        else:
            # Если уже есть - оставляем с большей уверенностью
            if rec['confidence'] > unique_recommendations[key]['confidence']:
                unique_recommendations[key] = rec
    
    recommendations = list(unique_recommendations.values())
    
    # Сортируем по уверенности (от высокой к низкой), затем по дню и времени
    recommendations.sort(key=lambda x: (-x['confidence'], x['weekday_num'], x['time_order']))
    
    return recommendations


def get_weekday_name(dt):
    if pd.isna(dt):
        return ""
    return DAYS_RU[dt.weekday()]


def open_order_in_crm(order_id):
    """Открыть заказ в CRM в браузере"""
    if order_id:
        url = f"https://podzamenu.ru/crm/order/{order_id}"
        webbrowser.open(url)


# ========================================
# TOOLTIP (ПОДСКАЗКИ)
# ========================================
class Tooltip:
    """Класс для создания подсказок при наведении мыши"""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.widget.bind('<Enter>', self.on_enter)
        self.widget.bind('<Leave>', self.on_leave)
        self.widget.bind('<Motion>', self.on_motion)
    
    def on_enter(self, event=None):
        self.show_tooltip()
    
    def on_leave(self, event=None):
        self.hide_tooltip()
    
    def on_motion(self, event=None):
        if self.tooltip_window:
            self.hide_tooltip()
            self.show_tooltip()
    
    def show_tooltip(self):
        x, y, _, _ = self.widget.bbox('insert') if hasattr(self.widget, 'bbox') else (0, 0, 0, 0)
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 20
        
        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")
        
        label = tk.Label(
            self.tooltip_window,
            text=self.text,
            background="#ffffe0",
            relief='solid',
            borderwidth=1,
            font=("Segoe UI", 9),
            justify='left',
            wraplength=300
        )
        label.pack()
    
    def hide_tooltip(self):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None


def add_tooltips_to_treeview(tree, columns):
    """Добавить подсказки ко всем заголовкам столбцов таблицы"""
    tooltip_window = None
    HEADER_HEIGHT = 30  # Высота области заголовка в пикселях
    
    def show_tooltip(event):
        nonlocal tooltip_window
        
        # Проверяем, что мышь находится в области заголовка (верхние 30 пикселей)
        if event.y > HEADER_HEIGHT:
            # Мышь не в области заголовка - закрываем tooltip если открыт
            if tooltip_window:
                tooltip_window.destroy()
                tooltip_window = None
            return
        
        # Определяем, на какой столбец наведена мышь
        x = event.x
        column_id = tree.identify_column(x)
        
        if column_id:
            # column_id имеет формат "#0", "#1", "#2" и т.д.
            # "#0" - это tree column, остальные - наши столбцы
            try:
                col_index = int(column_id.replace('#', ''))
                if col_index == 0:
                    return  # Пропускаем tree column
                
                # Получаем список столбцов (без tree column)
                all_columns = tree['columns']
                if col_index <= len(all_columns):
                    column_name = all_columns[col_index - 1]
                    tooltip_text = COLUMN_TOOLTIPS.get(column_name, '')
                    
                    if tooltip_text:
                        # Закрываем предыдущий tooltip
                        if tooltip_window:
                            tooltip_window.destroy()
                        
                        # Создаём новый tooltip
                        tooltip_window = tk.Toplevel()
                        tooltip_window.wm_overrideredirect(True)
                        tooltip_window.wm_geometry(f"+{event.x_root + 10}+{event.y_root + 10}")
                        
                        label = tk.Label(
                            tooltip_window,
                            text=tooltip_text,
                            background="#ffffe0",
                            relief='solid',
                            borderwidth=1,
                            font=("Segoe UI", 9),
                            justify='left',
                            wraplength=300,
                            padx=8,
                            pady=5
                        )
                        label.pack()
            except (ValueError, IndexError):
                pass
    
    def hide_tooltip(event):
        nonlocal tooltip_window
        if tooltip_window:
            tooltip_window.destroy()
            tooltip_window = None
    
    # Привязываем события
    tree.bind('<Motion>', show_tooltip)
    tree.bind('<Leave>', hide_tooltip)


# Словарь подсказок для столбцов
COLUMN_TOOLTIPS = {
    # Статистика поставщиков
    'Поставщик': 'Название поставщика',
    'Склад': 'Название склада',
    'ПВ': 'Пункт выдачи (пункт привоза)',
    'Заказов': 'Общее количество заказов',
    'Ср. откл.': 'Среднее отклонение (мин)\n\nПоказывает среднее арифметическое всех отклонений.\nПоложительное = опоздание, отрицательное = ранний привоз.',
    'Медиана': 'Медианное отклонение (мин)\n\nЗначение, которое делит все отклонения пополам.\n50% заказов имеют отклонение меньше медианы, 50% - больше.\nМенее чувствительна к выбросам, чем среднее.',
    'Ст. откл.': 'Стандартное отклонение (мин)\n\nПоказывает разброс данных вокруг среднего.\nМаленькое значение = стабильный поставщик\nБольшое значение = непредсказуемый поставщик',
    '% вовремя': 'Процент заказов, привезённых вовремя (±30 минут от графика)',
    
    # Рекомендации
    'День': 'День недели',
    'Час': 'Час заказа',
    'Сдвиг': 'Рекомендуемый сдвиг времени привоза (в минутах)',
    'Уверенность': 'Уверенность модели в рекомендации (0-100%)\n\nЗависит от:\n- Количества данных\n- Стабильности отклонений\n- Консистентности данных по ПВ',
    'Тренд': 'Обнаруженный тренд:\n✓ Стабильно - без изменений\n⬆ Опоздания - увеличиваются\n⬇ Ранние - привозят раньше\n⚡ Сдвиг - резкое изменение',
    'Применить с': 'Рекомендуемая дата начала применения',
    
    # По дням недели
    'День недели': 'День недели',
    'Уник. заказов': 'Количество уникальных номеров заказов',
    '% ранних': 'Процент заказов, привезённых раньше графика (>30 мин)',
    '% поздних': 'Процент заказов, привезённых позже графика (>30 мин)',
    'Худший час': 'Час с максимальным средним опозданием\n\nФормат: ЧЧ:ММ (среднее отклонение)',
    
    # Сырые данные
    '№ заказа': 'Номер заказа в CRM',
    'Бренд': 'Бренд товара',
    'Артикул': 'Артикул товара',
    'Дата заказа': 'Дата и время создания заказа',
    'План привоза': 'Плановое время привоза на склад',
    'Факт привоза': 'Фактическое время поступления на склад',
    'Откл. (мин)': 'Отклонение фактического времени от планового (в минутах)\n\nПоложительное = опоздание\nОтрицательное = ранний привоз',
    
    # Детальные окна
    'Час': 'Час заказа',
    'План': 'Плановое время привоза',
    'Факт': 'Фактическое время привоза',
    'Откл.': 'Отклонение (в минутах)',
    'Время заказа': 'Время создания заказа',
    'Среднее откл.': 'Среднее отклонение (мин)',
    'Ст. откл.': 'Стандартное отклонение (мин)',
    'День': 'День недели',
    'Заказов': 'Количество заказов',
    'Дата': 'Дата заказа',
    'Дата заказа': 'Дата и время создания заказа'
}


# ========================================
# СОРТИРУЕМАЯ ТАБЛИЦА
# ========================================
class SortableTreeview(ttk.Treeview):
    """Расширенный Treeview с сортировкой по столбцам"""
    
    def __init__(self, master, columns, **kwargs):
        super().__init__(master, columns=columns, **kwargs)
        self.columns_list = columns
        self.sort_column = None
        self.sort_reverse = False
        
        for col in columns:
            self.heading(col, text=col, command=lambda c=col: self.sort_by(c))
            self.column(col, anchor='center')
    
    def sort_by(self, col):
        """Сортировка по столбцу"""
        # Переключаем направление если тот же столбец
        if self.sort_column == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = col
            self.sort_reverse = False
        
        # Получаем все данные
        data = [(self.set(child, col), child) for child in self.get_children('')]
        
        # Пробуем преобразовать в числа для числовой сортировки
        try:
            data.sort(key=lambda x: float(x[0].replace('%', '').replace('+', '').replace(' мин', '').replace(',', '.')), 
                     reverse=self.sort_reverse)
        except (ValueError, AttributeError):
            data.sort(key=lambda x: x[0], reverse=self.sort_reverse)
        
        # Перемещаем элементы
        for index, (_, child) in enumerate(data):
            self.move(child, '', index)
        
        # Обновляем заголовки
        for c in self.columns_list:
            if c == col:
                arrow = ' ▼' if self.sort_reverse else ' ▲'
                self.heading(c, text=c + arrow)
            else:
                self.heading(c, text=c)


# ========================================
# ЗАГРУЗКА ДАННЫХ
# ========================================
def fetch_data():
    """Загрузка данных с сервера за выбранный период"""
    start_date = cal_start.get_date()
    end_date = cal_end.get_date()
    
    def load():
        try:
            df = fetch_data_chunked(start_date, end_date)
            if df is not None and not df.empty:
                global df_original, df_current, is_model_trained
                df_original = df.copy()
                df_current = df.copy()
                is_model_trained = False
                
                root.after(0, update_pv_filter_options)
                root.after(0, update_stats_display)
                root.after(0, update_weekday_supplier_list)
                root.after(0, update_weekday_stats_display)
                root.after(0, update_raw_data_display)
                root.after(0, lambda: update_status(f"✅ Загружено {len(df):,} записей", "success"))
                root.after(0, train_model_async)
        except Exception as e:
            root.after(0, lambda: update_status(f"❌ Ошибка: {str(e)[:50]}", "error"))
    
    update_status("⏳ Загрузка данных...", "info")
    progress_bar.start()
    thread = threading.Thread(target=load, daemon=True)
    thread.start()


def fetch_data_chunked(start_date, end_date, chunk_days=14):
    """Порционная загрузка данных с сервера в формате JSON"""
    all_data = []
    current_start = start_date
    total_chunks = ((end_date - start_date).days // chunk_days) + 1
    chunk_num = 0
    
    while current_start < end_date:
        chunk_num += 1
        current_end = min(current_start + timedelta(days=chunk_days - 1), end_date)
        
        root.after(0, lambda cn=chunk_num, tc=total_chunks: 
            update_status(f"⏳ Загрузка части {cn}/{tc}...", "info"))
        
        url = (
            f"{CRM_BASE_URL}/logistic/delivery_statistic"
            f"?fromDate={current_start.strftime('%Y-%m-%d')}"
            f"&toDate={current_end.strftime('%Y-%m-%d')}"
            f"&type=jsonresponse"
        )
        
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            
            # Проверяем что это не HTML страница с ошибкой
            if b'<html' in response.content[:500]:
                current_start = current_end + timedelta(days=1)
                continue
            
            # Парсим JSON ответ
            json_data = response.json()
            
            if json_data.get('result') == 'success' and json_data.get('data'):
                # Преобразуем JSON в DataFrame
                df_chunk = pd.DataFrame(json_data['data'])
                
                if len(df_chunk) > 0:
                    # Переименовываем колонки из JSON в нужный формат
                    column_mapping = {
                        'orderNumber': '№ заказа',
                        'url': 'URL',
                        'supplierName': 'Поставщик',
                        'warehouseName': 'Склад',
                        'branchAddress': 'ПВ',
                        'brandName': 'Бренд',
                        'articleSearch': 'Артикул',
                        'expectedAssemblyTime': 'Рассчетное время привоза',
                        'onStoreDate': 'Время поступления на склад',
                        'orderedDate': 'Время заказа позиции',
                        'diffMinutes': 'Разница во времени привоза (мин.)'
                    }
                    df_chunk = df_chunk.rename(columns=column_mapping)
                    all_data.append(df_chunk)
            
        except Exception as e:
            print(f"Ошибка загрузки данных: {e}")
        
        current_start = current_end + timedelta(days=1)
        time.sleep(0.2)  # Уменьшил задержку т.к. JSON быстрее
    
    root.after(0, progress_bar.stop)
    
    if not all_data:
        return None
    
    df = pd.concat(all_data, ignore_index=True)
    
    # Убеждаемся что все нужные колонки есть
    required_cols = ['№ заказа', 'URL', 'Поставщик', 'Склад', 'ПВ', 'Бренд', 'Артикул',
                     'Рассчетное время привоза', 'Время поступления на склад', 'Время заказа позиции',
                     'Разница во времени привоза (мин.)']
    for col in required_cols:
        if col not in df.columns:
            df[col] = ''
    
    # Преобразуем даты
    for col in ['Рассчетное время привоза', 'Время поступления на склад', 'Время заказа позиции']:
        df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True)
    
    df['Разница во времени привоза (мин.)'] = pd.to_numeric(df['Разница во времени привоза (мин.)'], errors='coerce')
    df['День_недели'] = df['Время заказа позиции'].apply(get_weekday_name)
    df['Час_заказа'] = df['Время заказа позиции'].dt.floor('h').dt.strftime('%H:%M')
    
    df = df.drop_duplicates(subset=['№ заказа', 'Артикул', 'Время заказа позиции'])
    df = normalize_pv_column(df)
    
    return df


def fetch_historical_data():
    """Загрузка данных за 2023-2025"""
    result = messagebox.askyesno(
        "📚 Загрузка исторических данных",
        "Будут загружены данные с января 2023 года.\n\n"
        "⏱ Это может занять 5-15 минут.\n"
        "💾 Данные будут сохранены в кэш.\n\n"
        "Продолжить?"
    )
    
    if not result:
        return
    
    start_date = datetime(2023, 1, 1).date()
    end_date = datetime.today().date()
    
    def load():
        try:
            df = fetch_data_chunked(start_date, end_date, chunk_days=14)
            if df is not None and not df.empty:
                global df_original, df_current, is_model_trained
                df_original = df.copy()
                df_current = df.copy()
                is_model_trained = False
                
                cache_path = os.path.join(os.path.dirname(__file__), 'ml_data_cache.pkl')
                df.to_pickle(cache_path)
                
                root.after(0, update_pv_filter_options)
                root.after(0, update_stats_display)
                root.after(0, update_weekday_supplier_list)
                root.after(0, update_weekday_stats_display)
                root.after(0, update_raw_data_display)
                root.after(0, lambda: update_status(f"✅ Загружено {len(df):,} записей. Сохранено в кэш.", "success"))
                root.after(0, lambda: messagebox.showinfo(
                    "✅ Готово", 
                    f"Загружено записей: {len(df):,}\n"
                    f"Период: {start_date.strftime('%d.%m.%Y')} — {end_date.strftime('%d.%m.%Y')}\n\n"
                    f"Данные сохранены в кэш."
                ))
                root.after(0, train_model_async)
        except Exception as e:
            root.after(0, lambda: update_status(f"❌ Ошибка", "error"))
            root.after(0, lambda: messagebox.showerror("Ошибка", str(e)))
    
    update_status("⏳ Загрузка исторических данных...", "info")
    progress_bar.start()
    thread = threading.Thread(target=load, daemon=True)
    thread.start()


def load_cached_data():
    """Загрузка из кэша"""
    global df_original, df_current, is_model_trained
    
    cache_path = os.path.join(os.path.dirname(__file__), 'ml_data_cache.pkl')
    
    if not os.path.exists(cache_path):
        messagebox.showinfo("💾 Кэш не найден", "Сначала загрузите данные кнопкой '📚 История'")
        return
    
    try:
        update_status("⏳ Загрузка из кэша...", "info")
        progress_bar.start()
        
        df = pd.read_pickle(cache_path)
        df = normalize_pv_column(df)
        df_original = df.copy()
        df_current = df.copy()
        is_model_trained = False
        
        cache_date = datetime.fromtimestamp(os.path.getmtime(cache_path))
        
        progress_bar.stop()
        update_pv_filter_options()
        update_stats_display()
        update_weekday_supplier_list()
        update_weekday_stats_display()
        update_raw_data_display()
        update_status(f"✅ Загружено {len(df):,} записей из кэша ({cache_date.strftime('%d.%m.%Y')})", "success")
        
        train_model_async()
        
    except Exception as e:
        progress_bar.stop()
        messagebox.showerror("Ошибка", f"Ошибка загрузки: {e}")
        update_status("❌ Ошибка", "error")


# ========================================
# ML ОБУЧЕНИЕ
# ========================================
def train_model_async():
    """Асинхронное обучение модели и генерация рекомендаций по расписанию"""
    def train():
        global ml_predictor, is_model_trained, recommendations, schedule_recommendations
        
        root.after(0, lambda: update_status("🤖 Анализ данных и генерация рекомендаций...", "info"))
        root.after(0, progress_bar.start)
        
        try:
            # Обучаем ML модель
            ml_predictor = DeliveryMLPredictor()
            ml_predictor.fit(df_current)
            
            # Генерируем рекомендации на основе расписания (если оно загружено)
            if schedules_cache:
                schedule_recommendations = generate_schedule_recommendations(df_current, schedules_cache)
                rec_count = len(schedule_recommendations)
                root.after(0, lambda: update_status(
                    f"✅ Рекомендаций по расписанию: {rec_count}", "success"))
            else:
                # Пробуем загрузить расписание
                schedules = fetch_schedules()
                if schedules:
                    schedule_recommendations = generate_schedule_recommendations(df_current, schedules)
                    rec_count = len(schedule_recommendations)
                    root.after(0, lambda: update_status(
                        f"✅ Расписание загружено | Рекомендаций: {rec_count}", "success"))
                else:
                    # Если расписание недоступно, используем старые рекомендации
                    recommendations = ml_predictor.generate_recommendations(df_current, min_samples=5, min_shift=15)
                    schedule_recommendations = []
                    root.after(0, lambda: update_status(
                        f"⚠️ Расписание недоступно | ML-рекомендаций: {len(recommendations)}", "warning"))
            
            is_model_trained = True
            
            root.after(0, progress_bar.stop)
            root.after(0, update_recommendations_display)
            
        except Exception as e:
            root.after(0, progress_bar.stop)
            root.after(0, lambda: update_status(f"⚠️ Ошибка: {str(e)[:40]}", "warning"))
            print(f"Ошибка ML: {e}")
    
    thread = threading.Thread(target=train, daemon=True)
    thread.start()


def retrain_model():
    """Переобучение модели"""
    if df_current is None:
        messagebox.showwarning("⚠️ Внимание", "Сначала загрузите данные")
        return
    train_model_async()


# ========================================
# ОБНОВЛЕНИЕ ТАБЛИЦ
# ========================================
def update_stats_display():
    """Обновление статистики поставщиков"""
    if df_current is None:
        return
    
    for item in tree_stats.get_children():
        tree_stats.delete(item)
    
    stats = df_current.groupby(['Поставщик', 'Склад', 'ПВ']).agg(
        Заказов=('№ заказа', 'nunique'),
        Среднее=('Разница во времени привоза (мин.)', 'mean'),
        Медиана=('Разница во времени привоза (мин.)', 'median'),
        СтдОткл=('Разница во времени привоза (мин.)', 'std')
    ).round(1).reset_index()
    
    for idx, row in stats.iterrows():
        mask = (
            (df_current['Поставщик'] == row['Поставщик']) &
            (df_current['Склад'] == row['Склад']) &
            (df_current['ПВ'] == row['ПВ'])
        )
        subset = df_current[mask]
        on_time = (subset['Разница во времени привоза (мин.)'].between(-30, 30).sum() / len(subset)) * 100
        stats.loc[idx, 'Вовремя'] = round(on_time, 1)
    
    for _, row in stats.iterrows():
        pct = row['Вовремя']
        if pct >= 80:
            tags = ('good',)
        elif pct >= 60:
            tags = ('medium',)
        else:
            tags = ('bad',)
        
        tree_stats.insert('', 'end', values=(
            row['Поставщик'],
            row['Склад'],
            normalize_pv_value(row['ПВ']),
            f"{row['Заказов']:,}",
            f"{row['Среднее']:+.1f}",
            f"{row['Медиана']:+.1f}",
            f"{row['СтдОткл']:.1f}",
            f"{row['Вовремя']:.1f}%"
        ), tags=tags)
    
    # Обновляем счетчик с информацией о ПВ
    unique_pv = df_current['ПВ'].nunique()
    unique_suppliers = df_current['Поставщик'].nunique()
    lbl_stats_count.config(text=f"Направлений: {len(stats)} | Поставщиков: {unique_suppliers} | ПВ: {unique_pv}")


def update_recommendations_display():
    """Обновление таблицы рекомендаций на основе расписания"""
    for item in tree_rec.get_children():
        tree_rec.delete(item)
    
    if not schedule_recommendations:
        lbl_rec_count.config(text="Рекомендаций: 0 (загрузите расписание)")
        return
    
    for rec in schedule_recommendations:
        confidence = rec.get('confidence', 0)
        if confidence >= 0.8:
            tags = ('high',)
        elif confidence >= 0.6:
            tags = ('med',)
        else:
            tags = ('low',)
        
        shift = rec.get('shift_minutes', 0)
        shift_str = f"{shift:+d} мин" if shift != 0 else "OK"
        
        # Вычисляем "Доставят к" = заказ до + длительность
        time_order = rec.get('time_order', '00:00')
        current_duration = rec.get('current_duration', 0)
        deliver_by = calculate_expected_delivery(time_order, current_duration)
        
        # Рекомендуемое "Доставят к"
        recommended_duration = rec.get('recommended_duration', 0)
        recommend_deliver_by = calculate_expected_delivery(time_order, recommended_duration)
        
        tree_rec.insert('', 'end', values=(
            rec.get('supplier', '')[:25],
            rec.get('warehouse', '')[:20],
            normalize_pv_value(rec.get('pv'))[:30],
            rec.get('weekday', '')[:2],
            time_order,
            deliver_by,
            recommend_deliver_by,
            shift_str,
            f"{confidence*100:.0f}%",
            f"{rec.get('on_time_pct', 0):.0f}%"
        ), tags=tags)
    
    # Подсчитываем статистику
    unique_pv = len(set(r.get('pv', '') for r in schedule_recommendations))
    total_recs = len(schedule_recommendations)
    lbl_rec_count.config(text=f"Рекомендаций: {total_recs} | ПВ: {unique_pv}")


def update_raw_data_display():
    """Обновление таблицы сырых данных"""
    if df_current is None:
        return
    
    for item in tree_raw.get_children():
        tree_raw.delete(item)
    
    # Показываем последние 1000 записей
    display_df = df_current.sort_values('Время заказа позиции', ascending=False).head(1000)
    
    for _, row in display_df.iterrows():
        dev = row.get('Разница во времени привоза (мин.)', 0)
        tags = ()
        if pd.notna(dev):
            if abs(dev) <= 30:
                tags = ('good',)
            elif abs(dev) <= 60:
                tags = ('medium',)
            else:
                tags = ('bad',)
        
        order_date = row['Время заказа позиции'].strftime('%d.%m.%Y %H:%M') if pd.notna(row.get('Время заказа позиции')) else ''
        plan_time = row['Рассчетное время привоза'].strftime('%d.%m.%Y %H:%M') if pd.notna(row.get('Рассчетное время привоза')) else ''
        fact_time = row['Время поступления на склад'].strftime('%d.%m.%Y %H:%M') if pd.notna(row.get('Время поступления на склад')) else ''
        
        # Получаем дополнительные поля
        pv = normalize_pv_value(row.get('ПВ'))[:40]
        brand = str(row.get('Бренд', ''))[:25] if pd.notna(row.get('Бренд')) else ''
        article = str(row.get('Артикул', ''))[:20] if pd.notna(row.get('Артикул')) else ''
        
        tree_raw.insert('', 'end', values=(
            row.get('№ заказа', ''),
            row.get('Поставщик', '')[:25],
            row.get('Склад', '')[:18],
            pv,
            brand,
            article,
            order_date,
            plan_time,
            fact_time,
            f"{dev:+.0f}" if pd.notna(dev) else ''
        ), tags=tags)
    
    total = len(df_current)
    shown = min(total, 1000)
    lbl_raw_count.config(text=f"Записей: {shown:,} из {total:,}")


def update_status(text, status_type="info"):
    """Обновление статус-бара"""
    colors = {
        "info": COLORS['info'],
        "success": COLORS['success'],
        "warning": COLORS['warning'],
        "error": COLORS['danger']
    }
    status_label.config(text=text, fg=colors.get(status_type, COLORS['text']))


# ========================================
# ДЕТАЛИЗАЦИЯ ПРИ КЛИКЕ
# ========================================
def on_stats_double_click(event):
    """Двойной клик по поставщику - показать детали"""
    selected = tree_stats.selection()
    if not selected:
        return
    
    values = tree_stats.item(selected[0])['values']
    supplier = values[0]
    warehouse = values[1]
    pv = values[2] if len(values) > 2 else None
    
    show_supplier_details(supplier, warehouse, pv)


def show_schedule_recommendation_details(rec):
    """Показать детали рекомендации по расписанию"""
    win = tk.Toplevel(root)
    pv_label = normalize_pv_value(rec.get('pv'))
    win.title(f"📋 Рекомендация: {rec.get('supplier', '')} — {rec.get('weekday', '')} до {rec.get('time_order', '')}")
    win.geometry("700x500")
    win.configure(bg=COLORS['bg'])
    
    # Определяем цвет по величине корректировки
    shift = rec.get('shift_minutes', 0)
    if abs(shift) > 30:
        header_color = COLORS['danger']
    elif abs(shift) > 15:
        header_color = COLORS['warning']
    else:
        header_color = COLORS['success']
    
    # Заголовок
    header = tk.Frame(win, bg=header_color)
    header.pack(fill='x')
    
    tk.Label(
        header,
        text=f"📋 Рекомендация по корректировке длительности",
        font=("Segoe UI", 14, "bold"),
        bg=header_color,
        fg='white'
    ).pack(pady=15)
    
    # Основная информация
    info_frame = tk.LabelFrame(win, text="📋 Параметры расписания", font=("Segoe UI", 10, "bold"), bg=COLORS['bg'])
    info_frame.pack(fill='x', padx=20, pady=15)
    
    params = [
        ("🏭 Поставщик:", rec.get('supplier', '')),
        ("📦 Склад:", rec.get('warehouse', '')),
        ("🏬 ПВ:", pv_label),
        ("📅 День недели:", rec.get('weekday', '')),
        ("⏰ Заказ до:", rec.get('time_order', '')),
        ("🚗 Тип доставки:", '🚗 self (поставщик)' if rec.get('delivery_type') == 'self' else '📦 courier (наш курьер)'),
        ("", ""),
        ("⏱ Текущее 'Доставят к':", calculate_expected_delivery(rec.get('time_order', ''), rec.get('current_duration', 0))),
        ("✅ Рекомендуемое 'Доставят к':", calculate_expected_delivery(rec.get('time_order', ''), rec.get('recommended_duration', 0))),
        ("📊 Корректировка:", f"{shift:+d} мин"),
        ("", ""),
        ("📈 Медиана отклонений:", f"{rec.get('median_deviation', 0):+.0f} мин"),
        ("✓ % вовремя:", f"{rec.get('on_time_pct', 0):.0f}%"),
        ("🎯 Уверенность:", f"{rec.get('confidence', 0)*100:.0f}%"),
        ("📦 Заказов в выборке:", f"{rec.get('orders_count', 0)}"),
    ]
    
    for i, (label, value) in enumerate(params):
        if label == "":
            ttk.Separator(info_frame, orient='horizontal').grid(row=i, column=0, columnspan=2, sticky='ew', pady=5)
        else:
            tk.Label(info_frame, text=label, font=("Segoe UI", 10), bg=COLORS['bg'], anchor='e').grid(
                row=i, column=0, sticky='e', padx=(10, 5), pady=3)
            
            # Выделяем корректировку цветом
            font_style = ("Segoe UI", 10, "bold")
            fg_color = COLORS['text']
            if "Корректировка" in label:
                if abs(shift) > 30:
                    fg_color = COLORS['danger']
                elif abs(shift) > 15:
                    fg_color = COLORS['warning']
                else:
                    fg_color = COLORS['success']
            
            tk.Label(info_frame, text=value, font=font_style, bg=COLORS['bg'], fg=fg_color, anchor='w').grid(
                row=i, column=1, sticky='w', padx=(5, 10), pady=3)
    
    # Пояснение
    reason_frame = tk.LabelFrame(win, text="💬 Рекомендация", font=("Segoe UI", 10, "bold"), bg=COLORS['bg'])
    reason_frame.pack(fill='x', padx=20, pady=10)
    
    time_order = rec.get('time_order', '')
    current_deliver = calculate_expected_delivery(time_order, rec.get('current_duration', 0))
    recommend_deliver = calculate_expected_delivery(time_order, rec.get('recommended_duration', 0))
    
    if shift > 0:
        reason = f"Поставщик систематически опаздывает в среднем на {rec.get('median_deviation', 0):+.0f} минут.\n\n" \
                 f"Рекомендуется изменить время 'Доставят к' с {current_deliver} на {recommend_deliver} " \
                 f"для окна \"{rec.get('weekday', '')} до {time_order}\"."
    elif shift < 0:
        reason = f"Поставщик стабильно привозит раньше графика на {abs(rec.get('median_deviation', 0)):.0f} минут.\n\n" \
                 f"Можно изменить время 'Доставят к' с {current_deliver} на {recommend_deliver} " \
                 f"для окна \"{rec.get('weekday', '')} до {time_order}\"."
    else:
        reason = "Текущее время доставки соответствует фактическим данным."
    
    tk.Label(
        reason_frame,
        text=reason,
        font=("Segoe UI", 10),
        bg=COLORS['bg'],
        wraplength=620,
        justify='left'
    ).pack(padx=15, pady=15)
    
    # Кнопки
    btn_frame = tk.Frame(win, bg=COLORS['bg'])
    btn_frame.pack(pady=15)
    
    tk.Button(
        btn_frame,
        text="📊 Анализ поставщика",
        command=lambda: show_supplier_details(rec.get('supplier', ''), rec.get('warehouse', ''), rec.get('pv')),
        font=("Segoe UI", 10),
        bg=COLORS['info'],
        fg='white',
        width=18
    ).pack(side='left', padx=5)
    
    tk.Button(
        btn_frame,
        text="✖ Закрыть",
        command=win.destroy,
        font=("Segoe UI", 10),
        bg=COLORS['text_light'],
        fg='white',
        width=12
    ).pack(side='left', padx=5)


def on_rec_double_click(event):
    """Двойной клик по рекомендации - показать детали"""
    selected = tree_rec.selection()
    if not selected:
        return
    
    values = tree_rec.item(selected[0])['values']
    supplier = str(values[0])
    warehouse = str(values[1])
    pv = str(values[2])
    weekday = str(values[3])
    time_order = str(values[4])
    
    # Ищем в рекомендациях по расписанию
    for rec in schedule_recommendations:
        if (
            rec.get('supplier', '').startswith(supplier[:10]) and
            rec.get('warehouse', '').startswith(warehouse[:10]) and
            normalize_pv_value(rec.get('pv', '')).startswith(pv[:10]) and
            rec.get('weekday', '').startswith(weekday) and
            rec.get('time_order', '') == time_order
        ):
            show_schedule_recommendation_details(rec)
            return


def show_orders_for_day(supplier, warehouse, pv, day, parent_df):
    """Показать все заказы за конкретный день недели"""
    day_data = parent_df[parent_df['День_недели'] == day].copy()
    
    if day_data.empty:
        messagebox.showinfo("ℹ️ Информация", f"Нет заказов в {day}")
        return
    
    win = tk.Toplevel()
    win.title(f"📋 Заказы: {supplier} — {warehouse} — {pv} ({day})")
    win.geometry("1300x600")
    win.configure(bg=COLORS['bg'])
    
    # Заголовок
    header = tk.Frame(win, bg=COLORS['info'])
    header.pack(fill='x')
    tk.Label(header, text=f"📋 {day} | {supplier}", font=("Segoe UI", 14, "bold"),
            bg=COLORS['info'], fg='white').pack(pady=10)
    tk.Label(header, text=f"Склад: {warehouse} | ПВ: {pv}", font=("Segoe UI", 10),
            bg=COLORS['info'], fg='white').pack()
    tk.Label(header, text=f"Всего заказов: {len(day_data)}", font=("Segoe UI", 10),
            bg=COLORS['info'], fg='white').pack(pady=(0, 10))
    
    # Таблица с прокруткой
    table_frame = tk.Frame(win, bg=COLORS['bg'])
    table_frame.pack(fill='both', expand=True, padx=10, pady=10)
    
    cols = ('№ заказа', 'Дата заказа', 'Час', 'План привоза', 'Факт привоза', 'Откл. (мин)')
    tree = SortableTreeview(table_frame, columns=cols, show='headings', height=20)
    tree.column('№ заказа', width=100)
    tree.column('Дата заказа', width=150)
    tree.column('Час', width=80)
    tree.column('План привоза', width=180)
    tree.column('Факт привоза', width=180)
    tree.column('Откл. (мин)', width=100)
    add_tooltips_to_treeview(tree, cols)
    
    for _, row in day_data.iterrows():
        dev = row['Разница во времени привоза (мин.)']
        tags = ()
        if pd.notna(dev):
            if abs(dev) <= 30:
                tags = ('good',)
            elif abs(dev) <= 60:
                tags = ('medium',)
            else:
                tags = ('bad',)
        
        tree.insert('', 'end', values=(
            row['№ заказа'],
            row['Время заказа позиции'].strftime('%d.%m.%Y') if pd.notna(row['Время заказа позиции']) else '',
            row['Время заказа позиции'].strftime('%H:%M') if pd.notna(row['Время заказа позиции']) else '',
            row['Рассчетное время привоза'].strftime('%d.%m.%Y %H:%M') if pd.notna(row['Рассчетное время привоза']) else '',
            row['Время поступления на склад'].strftime('%d.%m.%Y %H:%M') if pd.notna(row['Время поступления на склад']) else '',
            f"{dev:+.0f}" if pd.notna(dev) else ''
        ), tags=tags)
    
    tree.tag_configure('good', foreground=COLORS['success'])
    tree.tag_configure('medium', foreground=COLORS['warning'])
    tree.tag_configure('bad', foreground=COLORS['danger'])
    
    # Двойной клик — открыть заказ в CRM
    def on_click(event):
        selected = tree.selection()
        if selected:
            order_id = tree.item(selected[0])['values'][0]
            open_order_in_crm(order_id)
    
    tree.bind('<Double-1>', on_click)
    
    # Прокрутка для таблицы
    scrollbar_v = ttk.Scrollbar(table_frame, orient='vertical', command=tree.yview)
    scrollbar_h = ttk.Scrollbar(table_frame, orient='horizontal', command=tree.xview)
    tree.configure(yscrollcommand=scrollbar_v.set, xscrollcommand=scrollbar_h.set)
    
    # Размещение через grid
    tree.grid(row=0, column=0, sticky='nsew')
    scrollbar_v.grid(row=0, column=1, sticky='ns')
    scrollbar_h.grid(row=1, column=0, sticky='ew')
    table_frame.grid_rowconfigure(0, weight=1)
    table_frame.grid_columnconfigure(0, weight=1)
    
    tk.Label(win, text="💡 Двойной клик на заказ — открыть в CRM", 
            font=("Segoe UI", 9), fg=COLORS['text_light'], bg=COLORS['bg']).pack(pady=5)


def show_orders_for_hour(supplier, warehouse, pv, hour, parent_df):
    """Показать все заказы за конкретный час"""
    hour_data = parent_df[parent_df['Время заказа позиции'].dt.hour == hour].copy()
    
    if hour_data.empty:
        messagebox.showinfo("ℹ️ Информация", f"Нет заказов в {hour}:00")
        return
    
    win = tk.Toplevel()
    win.title(f"📋 Заказы: {supplier} — {warehouse} — {pv} ({hour:02d}:00)")
    win.geometry("1300x600")
    win.configure(bg=COLORS['bg'])
    
    # Заголовок
    header = tk.Frame(win, bg=COLORS['warning'])
    header.pack(fill='x')
    tk.Label(header, text=f"⏰ Час: {hour:02d}:00 | {supplier}", font=("Segoe UI", 14, "bold"),
            bg=COLORS['warning'], fg='white').pack(pady=10)
    tk.Label(header, text=f"Склад: {warehouse} | ПВ: {pv}", font=("Segoe UI", 10),
            bg=COLORS['warning'], fg='white').pack()
    tk.Label(header, text=f"Всего заказов: {len(hour_data)}", font=("Segoe UI", 10),
            bg=COLORS['warning'], fg='white').pack(pady=(0, 10))
    
    # Таблица с прокруткой
    table_frame = tk.Frame(win, bg=COLORS['bg'])
    table_frame.pack(fill='both', expand=True, padx=10, pady=10)
    
    cols = ('№ заказа', 'День', 'Дата заказа', 'План привоза', 'Факт привоза', 'Откл. (мин)')
    tree = SortableTreeview(table_frame, columns=cols, show='headings', height=20)
    tree.column('№ заказа', width=100)
    tree.column('День', width=80)
    tree.column('Дата заказа', width=150)
    tree.column('План привоза', width=180)
    tree.column('Факт привоза', width=180)
    tree.column('Откл. (мин)', width=100)
    add_tooltips_to_treeview(tree, cols)
    
    for _, row in hour_data.iterrows():
        dev = row['Разница во времени привоза (мин.)']
        tags = ()
        if pd.notna(dev):
            if abs(dev) <= 30:
                tags = ('good',)
            elif abs(dev) <= 60:
                tags = ('medium',)
            else:
                tags = ('bad',)
        
        tree.insert('', 'end', values=(
            row['№ заказа'],
            row['День_недели'][:2] if row['День_недели'] else '',
            row['Время заказа позиции'].strftime('%d.%m.%Y %H:%M') if pd.notna(row['Время заказа позиции']) else '',
            row['Рассчетное время привоза'].strftime('%d.%m.%Y %H:%M') if pd.notna(row['Рассчетное время привоза']) else '',
            row['Время поступления на склад'].strftime('%d.%m.%Y %H:%M') if pd.notna(row['Время поступления на склад']) else '',
            f"{dev:+.0f}" if pd.notna(dev) else ''
        ), tags=tags)
    
    tree.tag_configure('good', foreground=COLORS['success'])
    tree.tag_configure('medium', foreground=COLORS['warning'])
    tree.tag_configure('bad', foreground=COLORS['danger'])
    
    # Двойной клик — открыть заказ в CRM
    def on_click(event):
        selected = tree.selection()
        if selected:
            order_id = tree.item(selected[0])['values'][0]
            open_order_in_crm(order_id)
    
    tree.bind('<Double-1>', on_click)
    
    # Прокрутка для таблицы
    scrollbar_v = ttk.Scrollbar(table_frame, orient='vertical', command=tree.yview)
    scrollbar_h = ttk.Scrollbar(table_frame, orient='horizontal', command=tree.xview)
    tree.configure(yscrollcommand=scrollbar_v.set, xscrollcommand=scrollbar_h.set)
    
    # Размещение через grid
    tree.grid(row=0, column=0, sticky='nsew')
    scrollbar_v.grid(row=0, column=1, sticky='ns')
    scrollbar_h.grid(row=1, column=0, sticky='ew')
    table_frame.grid_rowconfigure(0, weight=1)
    table_frame.grid_columnconfigure(0, weight=1)
    
    tk.Label(win, text="💡 Двойной клик на заказ — открыть в CRM", 
            font=("Segoe UI", 9), fg=COLORS['text_light'], bg=COLORS['bg']).pack(pady=5)


def show_orders_for_schedule_window(supplier, warehouse, pv, day, time_order, parent_df):
    """Показать заказы для конкретного окна расписания"""
    try:
        order_hour = int(time_order.split(':')[0])
    except:
        order_hour = 12
    
    # Фильтруем заказы для этого окна
    # day может быть полным названием или сокращённым
    day_full = day
    for d in DAYS_RU:
        if d.startswith(day) or d == day:
            day_full = d
            break
    
    day_mask = parent_df['День_недели'] == day_full
    time_mask = (
        (parent_df['Час'] >= max(0, order_hour - 4)) & 
        (parent_df['Час'] <= order_hour)
    )
    window_data = parent_df[day_mask & time_mask].copy()
    
    if window_data.empty:
        messagebox.showinfo("ℹ️ Информация", f"Нет заказов в окне {day} до {time_order}")
        return
    
    win = tk.Toplevel()
    win.title(f"📋 Заказы: {supplier} — {warehouse} — {pv} ({day}, до {time_order})")
    win.geometry("1300x600")
    win.configure(bg=COLORS['bg'])
    
    # Заголовок
    header = tk.Frame(win, bg='#0288d1')
    header.pack(fill='x')
    tk.Label(header, text=f"📋 Окно расписания: {day} до {time_order}", font=("Segoe UI", 14, "bold"),
            bg='#0288d1', fg='white').pack(pady=10)
    tk.Label(header, text=f"{supplier} | Склад: {warehouse} | ПВ: {pv}", font=("Segoe UI", 10),
            bg='#0288d1', fg='white').pack()
    
    # Статистика окна
    deviations = window_data['Разница во времени привоза (мин.)'].dropna()
    if len(deviations) > 0:
        on_time_pct = (deviations.between(-30, 30).sum() / len(deviations)) * 100
        mean_dev = deviations.mean()
        stats_text = f"Заказов: {len(window_data)} | Ср. откл.: {mean_dev:+.1f} мин | Вовремя: {on_time_pct:.0f}%"
    else:
        stats_text = f"Заказов: {len(window_data)}"
    
    tk.Label(header, text=stats_text, font=("Segoe UI", 10),
            bg='#0288d1', fg='white').pack(pady=(0, 10))
    
    # Таблица с прокруткой
    table_frame = tk.Frame(win, bg=COLORS['bg'])
    table_frame.pack(fill='both', expand=True, padx=10, pady=10)
    
    cols = ('№ заказа', 'Дата заказа', 'Час', 'План привоза', 'Факт привоза', 'Откл. (мин)')
    tree = SortableTreeview(table_frame, columns=cols, show='headings', height=20)
    tree.column('№ заказа', width=100)
    tree.column('Дата заказа', width=150)
    tree.column('Час', width=80)
    tree.column('План привоза', width=180)
    tree.column('Факт привоза', width=180)
    tree.column('Откл. (мин)', width=100)
    add_tooltips_to_treeview(tree, cols)
    
    for _, row in window_data.iterrows():
        dev = row['Разница во времени привоза (мин.)']
        tags = ()
        if pd.notna(dev):
            if abs(dev) <= 30:
                tags = ('good',)
            elif abs(dev) <= 60:
                tags = ('medium',)
            else:
                tags = ('bad',)
        
        tree.insert('', 'end', values=(
            row['№ заказа'],
            row['Время заказа позиции'].strftime('%d.%m.%Y') if pd.notna(row['Время заказа позиции']) else '',
            row['Время заказа позиции'].strftime('%H:%M') if pd.notna(row['Время заказа позиции']) else '',
            row['Рассчетное время привоза'].strftime('%d.%m.%Y %H:%M') if pd.notna(row['Рассчетное время привоза']) else '',
            row['Время поступления на склад'].strftime('%d.%m.%Y %H:%M') if pd.notna(row['Время поступления на склад']) else '',
            f"{dev:+.0f}" if pd.notna(dev) else ''
        ), tags=tags)
    
    tree.tag_configure('good', foreground=COLORS['success'])
    tree.tag_configure('medium', foreground=COLORS['warning'])
    tree.tag_configure('bad', foreground=COLORS['danger'])
    
    # Двойной клик — открыть заказ в CRM
    def on_click(event):
        selected = tree.selection()
        if selected:
            order_id = tree.item(selected[0])['values'][0]
            open_order_in_crm(order_id)
    
    tree.bind('<Double-1>', on_click)
    
    # Прокрутка для таблицы
    scrollbar_v = ttk.Scrollbar(table_frame, orient='vertical', command=tree.yview)
    scrollbar_h = ttk.Scrollbar(table_frame, orient='horizontal', command=tree.xview)
    tree.configure(yscrollcommand=scrollbar_v.set, xscrollcommand=scrollbar_h.set)
    
    # Размещение через grid
    tree.grid(row=0, column=0, sticky='nsew')
    scrollbar_v.grid(row=0, column=1, sticky='ns')
    scrollbar_h.grid(row=1, column=0, sticky='ew')
    table_frame.grid_rowconfigure(0, weight=1)
    table_frame.grid_columnconfigure(0, weight=1)
    
    tk.Label(win, text="💡 Двойной клик на заказ — открыть в CRM", 
            font=("Segoe UI", 9), fg=COLORS['text_light'], bg=COLORS['bg']).pack(pady=5)


def show_supplier_details(supplier, warehouse, pv=None):
    """Окно с детальным анализом поставщика"""
    if df_current is None:
        return
    
    pv_label = normalize_pv_value(pv) if pv is not None else "Все ПВ"
    mask = (df_current['Поставщик'] == supplier) & (df_current['Склад'] == warehouse)
    if pv is not None:
        mask &= (df_current['ПВ'] == pv_label)
    subset = df_current[mask].copy()
    
    if subset.empty:
        messagebox.showinfo("ℹ️ Информация", "Нет данных")
        return
    
    # Создаем окно
    win = tk.Toplevel(root)
    win.title(f"📊 {supplier} — {warehouse} | {pv_label}")
    win.geometry("1200x800")
    win.configure(bg=COLORS['bg'])
    
    # Заголовок
    header = tk.Frame(win, bg=COLORS['header'])
    header.pack(fill='x')
    
    tk.Label(
        header,
        text=f"📊 Анализ: {supplier}",
        font=("Segoe UI", 16, "bold"),
        bg=COLORS['header'],
        fg='white'
    ).pack(pady=10)
    
    tk.Label(
        header,
        text=f"Склад: {warehouse} | ПВ: {pv_label} | Заказов: {len(subset):,}",
        font=("Segoe UI", 11),
        bg=COLORS['header'],
        fg='#b0bec5'
    ).pack(pady=(0, 10))
    
    # Notebook для вкладок
    notebook = ttk.Notebook(win)
    notebook.pack(fill='both', expand=True, padx=10, pady=10)
    
    # === Вкладка 1: Графики ===
    frame_charts = ttk.Frame(notebook)
    notebook.add(frame_charts, text="📈 Графики")
    
    # Кнопка помощи
    help_frame = tk.Frame(frame_charts, bg=COLORS['bg'])
    help_frame.pack(fill='x', padx=10, pady=5)
    
    tk.Button(
        help_frame,
        text="❓ Как читать графики?",
        command=lambda: show_charts_guide(),
        font=("Segoe UI", 10),
        bg=COLORS['info'],
        fg='white',
        cursor='hand2'
    ).pack(side='right', padx=5)
    
    create_supplier_charts(frame_charts, subset, supplier, pv_label)
    
    # === Вкладка 2: Сетка ПВ × Дни (как расписание) ===
    frame_weekday = ttk.Frame(notebook)
    notebook.add(frame_weekday, text="📅 По расписанию (все ПВ)")
    
    # Информация
    info_wd = tk.Frame(frame_weekday, bg='#e8f5e9')
    info_wd.pack(fill='x', padx=10, pady=5)
    tk.Label(info_wd, text="📅 Расписание с фактическими данными. Красные окна требуют корректировки. Клик — детали.",
            font=("Segoe UI", 9), bg='#e8f5e9', fg=COLORS['text']).pack(pady=5)
    
    # Canvas для прокрутки
    canvas_wd = tk.Canvas(frame_weekday, bg=COLORS['bg'], highlightthickness=0)
    scrollbar_wd_v = ttk.Scrollbar(frame_weekday, orient='vertical', command=canvas_wd.yview)
    scrollbar_wd_h = ttk.Scrollbar(frame_weekday, orient='horizontal', command=canvas_wd.xview)
    
    grid_frame = tk.Frame(canvas_wd, bg=COLORS['bg'])
    canvas_wd.create_window((0, 0), window=grid_frame, anchor='nw')
    canvas_wd.configure(yscrollcommand=scrollbar_wd_v.set, xscrollcommand=scrollbar_wd_h.set)
    
    def on_grid_configure(event):
        canvas_wd.configure(scrollregion=canvas_wd.bbox('all'))
    grid_frame.bind('<Configure>', on_grid_configure)
    
    # Прокрутка колесом
    def on_mousewheel_wd(event):
        canvas_wd.yview_scroll(int(-1*(event.delta/120)), 'units')
    canvas_wd.bind('<MouseWheel>', on_mousewheel_wd)
    
    # Загружаем расписание для данного склада
    schedules_for_supplier = get_schedules_for_warehouse_pv(warehouse, None)  # Все ПВ для склада
    
    # Подготовка данных с часами
    subset_wd = subset.copy()
    subset_wd['Час'] = subset_wd['Время заказа позиции'].dt.hour
    subset_wd['Минута'] = subset_wd['Время заказа позиции'].dt.minute
    
    # Группируем по ПВ
    pv_list_wd = sorted(subset_wd['ПВ'].unique())
    
    # Заголовок таблицы
    header_bg = '#1a237e'
    header_fg = 'white'
    
    tk.Label(grid_frame, text="ПВ", font=("Segoe UI", 10, "bold"), 
            bg=header_bg, fg=header_fg, width=30, anchor='w', padx=10, pady=8,
            relief='ridge').grid(row=0, column=0, sticky='nsew')
    
    for col, day in enumerate(DAYS_SHORT, 1):
        tk.Label(grid_frame, text=day, font=("Segoe UI", 10, "bold"), 
                bg=header_bg, fg=header_fg, width=18, padx=5, pady=8,
                relief='ridge').grid(row=0, column=col, sticky='nsew')
    
    # Функция показа деталей при клике
    def show_window_details(pv_name, day_name, window_info):
        """Показать детали окна расписания"""
        detail_win = tk.Toplevel(win)
        detail_win.title(f"📊 Детали: {day_name}")
        detail_win.geometry("500x400")
        detail_win.configure(bg=COLORS['bg'])
        
        # Заголовок с цветом в зависимости от статуса
        status = window_info.get('status', 'ok')
        if status == 'bad':
            header_color = COLORS['danger']
        elif status == 'warning':
            header_color = COLORS['warning']
        else:
            header_color = COLORS['success']
        
        header_d = tk.Frame(detail_win, bg=header_color)
        header_d.pack(fill='x')
        tk.Label(header_d, text=f"📊 {day_name} — {pv_name[:40]}", 
                font=("Segoe UI", 12, "bold"), bg=header_color, fg='white').pack(pady=10)
        
        # Информация
        info_frame_d = tk.LabelFrame(detail_win, text="📋 Данные окна", font=("Segoe UI", 10, "bold"), bg=COLORS['bg'])
        info_frame_d.pack(fill='x', padx=15, pady=10)
        
        params = [
            ("Заказ до:", window_info.get('time_order', '—')),
            ("Доставят к (план):", window_info.get('deliver_by', '—')),
            ("Тип доставки:", '🚗 self' if window_info.get('type') == 'self' else '📦 courier'),
            ("", ""),
            ("Заказов в выборке:", f"{window_info.get('orders_count', 0)}"),
            ("Медиана отклонений:", f"{window_info.get('median_dev', 0):+.0f} мин"),
            ("% вовремя:", f"{window_info.get('on_time_pct', 0):.0f}%"),
        ]
        
        for i, (label, value) in enumerate(params):
            if label == "":
                ttk.Separator(info_frame_d, orient='horizontal').grid(row=i, column=0, columnspan=2, sticky='ew', pady=5)
            else:
                tk.Label(info_frame_d, text=label, font=("Segoe UI", 10), bg=COLORS['bg']).grid(row=i, column=0, sticky='e', padx=5, pady=2)
                tk.Label(info_frame_d, text=value, font=("Segoe UI", 10, "bold"), bg=COLORS['bg']).grid(row=i, column=1, sticky='w', padx=5, pady=2)
        
        # Рекомендация
        if window_info.get('needs_correction'):
            rec_frame = tk.LabelFrame(detail_win, text="💡 Рекомендация", font=("Segoe UI", 10, "bold"), bg=COLORS['bg'])
            rec_frame.pack(fill='x', padx=15, pady=10)
            
            shift = window_info.get('shift', 0)
            new_deliver = window_info.get('recommended_deliver', '—')
            
            rec_text = f"Требуется корректировка на {shift:+d} мин.\n\n"
            rec_text += f"Текущее 'Доставят к': {window_info.get('deliver_by', '—')}\n"
            rec_text += f"Рекомендуемое: {new_deliver}\n\n"
            
            if shift > 0:
                rec_text += f"Причина: систематические опоздания (медиана {window_info.get('median_dev', 0):+.0f} мин)"
            else:
                rec_text += f"Причина: систематический ранний привоз (медиана {window_info.get('median_dev', 0):+.0f} мин)"
            
            tk.Label(rec_frame, text=rec_text, font=("Segoe UI", 10), bg=COLORS['bg'],
                    justify='left', wraplength=450).pack(padx=10, pady=10)
        else:
            ok_frame = tk.Frame(detail_win, bg='#c8e6c9')
            ok_frame.pack(fill='x', padx=15, pady=10)
            tk.Label(ok_frame, text="✅ Окно работает корректно, корректировка не требуется",
                    font=("Segoe UI", 10), bg='#c8e6c9', fg=COLORS['success']).pack(pady=10)
    
    # Заполняем таблицу по ПВ
    row_num = 1
    for pv_name in pv_list_wd:
        pv_data = subset_wd[subset_wd['ПВ'] == pv_name]
        row_bg = '#ffffff' if row_num % 2 == 1 else '#f5f5f5'
        
        # Ячейка ПВ
        tk.Label(grid_frame, text=normalize_pv_value(pv_name)[:35], font=("Segoe UI", 9), 
                bg=row_bg, anchor='w', padx=10, pady=5, relief='ridge',
                wraplength=220).grid(row=row_num, column=0, sticky='nsew')
        
        # Находим расписание для этого ПВ
        pv_schedules = [s for s in schedules_for_supplier 
                       if pv_name.lower() in s.get('branch', '').lower() or 
                          s.get('branch', '').lower() in pv_name.lower()]
        
        # Ячейки по дням
        for col, (day_num, day_name) in enumerate(zip(range(7), DAYS_RU), 1):
            day_data = pv_data[pv_data['День_недели'] == day_name]
            
            cell_frame = tk.Frame(grid_frame, bg=row_bg, relief='ridge', bd=1)
            cell_frame.grid(row=row_num, column=col, sticky='nsew')
            
            # Ищем окна расписания для этого дня
            day_schedules = [s for s in pv_schedules if s.get('weekday') == day_num + 1]
            day_schedules.sort(key=lambda x: x.get('timeOrder', '00:00'))
            
            if day_schedules:
                for sched in day_schedules:
                    time_order = sched.get('timeOrder', '')
                    duration = sched.get('deliveryDuration', 0)
                    dtype = sched.get('type', 'self')
                    deliver_by = calculate_expected_delivery(time_order, duration)
                    
                    # Фильтруем данные для этого окна
                    try:
                        order_hour = int(time_order.split(':')[0])
                    except:
                        order_hour = 12
                    
                    window_mask = (day_data['Час'] <= order_hour) & (day_data['Час'] >= max(0, order_hour - 4))
                    window_data = day_data[window_mask]
                    
                    orders_count = len(window_data)
                    median_dev = 0
                    on_time_pct = 0
                    needs_correction = False
                    shift = 0
                    
                    if orders_count > 0:
                        deviations = window_data['Разница во времени привоза (мин.)'].dropna()
                        if len(deviations) > 0:
                            median_dev = deviations.median()
                            on_time_pct = (deviations.between(-30, 30).sum() / len(deviations)) * 100
                            
                            # Определяем нужна ли корректировка
                            if abs(median_dev) > 30 or on_time_pct < 60:
                                needs_correction = True
                                shift = int(round(median_dev))
                    
                    # Определяем цвет фона
                    if needs_correction and abs(shift) > 30:
                        window_bg = '#ffcdd2'  # Красный - требует корректировки
                        status = 'bad'
                    elif needs_correction:
                        window_bg = '#fff9c4'  # Желтый - предупреждение
                        status = 'warning'
                    elif dtype == 'self':
                        window_bg = '#e3f2fd'  # Голубой - self OK
                        status = 'ok'
                    else:
                        window_bg = '#fff3e0'  # Оранжевый - courier OK
                        status = 'ok'
                    
                    icon = '🚗' if dtype == 'self' else '📦'
                    
                    # Текст окна
                    if orders_count > 0:
                        window_text = f"{time_order}→{deliver_by} {icon}\n({orders_count} зак, {median_dev:+.0f}м)"
                    else:
                        window_text = f"{time_order}→{deliver_by} {icon}\n(нет данных)"
                    
                    # Сохраняем информацию для детального просмотра
                    window_info = {
                        'time_order': time_order,
                        'deliver_by': deliver_by,
                        'type': dtype,
                        'orders_count': orders_count,
                        'median_dev': median_dev,
                        'on_time_pct': on_time_pct,
                        'needs_correction': needs_correction,
                        'shift': shift,
                        'recommended_deliver': calculate_expected_delivery(time_order, duration + shift) if needs_correction else deliver_by,
                        'status': status
                    }
                    
                    window_label = tk.Label(cell_frame, text=window_text, font=("Segoe UI", 8), 
                                           bg=window_bg, padx=4, pady=3, cursor='hand2',
                                           relief='raised' if needs_correction else 'flat')
                    window_label.pack(fill='x', padx=2, pady=1)
                    
                    # Привязка клика
                    window_label.bind('<Button-1>', lambda e, p=pv_name, d=day_name, w=window_info: show_window_details(p, d, w))
            
            elif len(day_data) > 0:
                # Есть данные но нет расписания
                deviations = day_data['Разница во времени привоза (мин.)'].dropna()
                median_dev = deviations.median() if len(deviations) > 0 else 0
                
                info_text = f"📊 {len(day_data)} зак.\nМедиана: {median_dev:+.0f}м\n(нет расписания)"
                tk.Label(cell_frame, text=info_text, font=("Segoe UI", 8), 
                        bg='#eeeeee', fg=COLORS['text_light'], padx=4, pady=3).pack(fill='x')
            else:
                tk.Label(cell_frame, text="—", font=("Segoe UI", 9), 
                        bg=row_bg, fg=COLORS['text_light'], pady=8).pack()
        
        row_num += 1
    
    # Размещение
    canvas_wd.pack(side='left', fill='both', expand=True)
    scrollbar_wd_v.pack(side='right', fill='y')
    scrollbar_wd_h.pack(side='bottom', fill='x')
    
    # === Вкладка 3: По ПВ ===
    frame_pv = ttk.Frame(notebook)
    notebook.add(frame_pv, text="🏬 По ПВ")
    
    # Frame для таблицы с прокруткой
    table_frame_pv = tk.Frame(frame_pv, bg=COLORS['bg'])
    table_frame_pv.pack(fill='both', expand=True, padx=10, pady=10)
    
    cols_pv = ('ПВ', 'Заказов', 'Среднее откл.', 'Медиана', 'Ст. откл.', '% вовремя')
    tree_pv = SortableTreeview(table_frame_pv, columns=cols_pv, show='headings', height=12)
    for col in cols_pv:
        tree_pv.column(col, width=120 if col == 'ПВ' else 100)
    tree_pv.column('ПВ', width=250)
    add_tooltips_to_treeview(tree_pv, cols_pv)
    
    # Статистика по ПВ
    pv_stats = subset.groupby('ПВ').agg(
        Заказов=('№ заказа', 'nunique'),
        Среднее=('Разница во времени привоза (мин.)', 'mean'),
        Медиана=('Разница во времени привоза (мин.)', 'median'),
        СтдОткл=('Разница во времени привоза (мин.)', 'std')
    ).round(1).reset_index()
    
    for _, row in pv_stats.iterrows():
        pv_data = subset[subset['ПВ'] == row['ПВ']]
        on_time_pct = (pv_data['Разница во времени привоза (мин.)'].between(-30, 30).sum() / len(pv_data)) * 100
        
        tags = ()
        if on_time_pct >= 80:
            tags = ('good',)
        elif on_time_pct >= 60:
            tags = ('medium',)
        else:
            tags = ('bad',)
        
        tree_pv.insert('', 'end', values=(
            normalize_pv_value(row['ПВ']),
            row['Заказов'],
            f"{row['Среднее']:+.1f}",
            f"{row['Медиана']:+.1f}",
            f"{row['СтдОткл']:.1f}",
            f"{on_time_pct:.1f}%"
        ), tags=tags)
    
    tree_pv.tag_configure('good', foreground=COLORS['success'])
    tree_pv.tag_configure('medium', foreground=COLORS['warning'])
    tree_pv.tag_configure('bad', foreground=COLORS['danger'])
    
    # Прокрутка для таблицы tree_pv
    scrollbar_pv_v = ttk.Scrollbar(table_frame_pv, orient='vertical', command=tree_pv.yview)
    scrollbar_pv_h = ttk.Scrollbar(table_frame_pv, orient='horizontal', command=tree_pv.xview)
    tree_pv.configure(yscrollcommand=scrollbar_pv_v.set, xscrollcommand=scrollbar_pv_h.set)
    
    # Размещение через grid
    tree_pv.grid(row=0, column=0, sticky='nsew')
    scrollbar_pv_v.grid(row=0, column=1, sticky='ns')
    scrollbar_pv_h.grid(row=1, column=0, sticky='ew')
    table_frame_pv.grid_rowconfigure(0, weight=1)
    table_frame_pv.grid_columnconfigure(0, weight=1)
    
    tk.Label(frame_pv, text="💡 Статистика по каждому пункту выдачи (ПВ)", 
            font=("Segoe UI", 9), fg=COLORS['text_light']).pack(pady=5)
    
    # === Вкладка 4: По текущему расписанию ===
    frame_schedule = ttk.Frame(notebook)
    notebook.add(frame_schedule, text="📋 По расписанию")
    
    # Информация о вкладке
    schedule_info = tk.Frame(frame_schedule, bg='#e1f5fe')
    schedule_info.pack(fill='x', padx=10, pady=10)
    
    tk.Label(schedule_info, text="📋 Сравнение фактических данных с расписанием доставки поставщика.\n"
            "Показывает окна заказов, текущую длительность и рекомендуемую корректировку.",
            font=("Segoe UI", 9), bg='#e1f5fe', fg=COLORS['text'], justify='left').pack(padx=10, pady=8)
    
    # Frame для таблицы расписания
    table_frame_sched = tk.Frame(frame_schedule, bg=COLORS['bg'])
    table_frame_sched.pack(fill='both', expand=True, padx=10, pady=5)
    
    cols_sched = ('День', 'Заказ до', 'Доставят к', 'Тип', 'Заказов', 'Медиана откл.', '% вовремя', 'Рекоменд.', 'Статус')
    tree_sched = SortableTreeview(table_frame_sched, columns=cols_sched, show='headings', height=14)
    tree_sched.column('День', width=100)
    tree_sched.column('Заказ до', width=80)
    tree_sched.column('Доставят к', width=80)
    tree_sched.column('Тип', width=80)
    tree_sched.column('Заказов', width=70)
    tree_sched.column('Медиана откл.', width=100)
    tree_sched.column('% вовремя', width=80)
    tree_sched.column('Рекоменд.', width=90)
    tree_sched.column('Статус', width=130)
    
    # Добавляем подсказки для столбцов расписания
    schedule_tooltips = {
        'День': 'День недели',
        'Заказ до': 'Время, до которого нужно сделать заказ',
        'Доставят к': 'Ожидаемое время доставки (Заказ до + Длительность)',
        'Тип': 'Тип доставки:\n• self - поставщик сам возит\n• courier - наш курьер забирает',
        'Заказов': 'Количество заказов в этом окне',
        'Медиана откл.': 'Медианное отклонение от графика (мин)\nПоложительное = опоздание',
        '% вовремя': 'Процент заказов вовремя (±30 мин)',
        'Рекоменд.': 'Рекомендуемое время "Доставят к"\nна основе фактических данных',
        'Статус': 'Оценка: нужна ли корректировка расписания'
    }
    COLUMN_TOOLTIPS.update(schedule_tooltips)
    add_tooltips_to_treeview(tree_sched, cols_sched)
    
    tree_sched.tag_configure('good', foreground=COLORS['success'])
    tree_sched.tag_configure('medium', foreground=COLORS['warning'])
    tree_sched.tag_configure('bad', foreground=COLORS['danger'])
    tree_sched.tag_configure('no_data', foreground=COLORS['text_light'])
    
    # Загружаем расписание для данного поставщика/склада и ПВ
    schedules = get_schedules_for_warehouse_pv(warehouse, pv_label)
    
    # Добавляем колонку часа для сопоставления
    subset_with_hour = subset.copy()
    subset_with_hour['Час'] = subset_with_hour['Время заказа позиции'].dt.hour
    subset_with_hour['Минута'] = subset_with_hour['Время заказа позиции'].dt.minute
    
    # Сортируем расписание: по дню недели (Пн=1...Вс=7), затем по времени
    def sort_schedules(schedules_list):
        """Сортировка расписания: Пн→Вс, внутри дня по времени 'Заказ до'"""
        def sort_key(sched):
            weekday = sched.get('weekday', 8)  # 1-7, неизвестные в конец
            time_order = sched.get('timeOrder', '99:99')
            try:
                hours, mins = map(int, time_order.split(':'))
                time_minutes = hours * 60 + mins
            except:
                time_minutes = 9999
            return (weekday, time_minutes)
        
        return sorted(schedules_list, key=sort_key)
    
    schedule_count = 0
    schedule_rows = []  # Собираем данные для вставки
    
    if schedules:
        sorted_schedules = sort_schedules(schedules)
        
        for sched in sorted_schedules:
            weekday_num = sched.get('weekday')
            time_order = sched.get('timeOrder', '')
            delivery_duration = sched.get('deliveryDuration', 0)
            delivery_type = sched.get('type', 'self')
            
            weekday_name = WEEKDAY_MAP.get(weekday_num, f"День {weekday_num}")
            
            # Фильтруем заказы для этого окна расписания
            try:
                order_hour = int(time_order.split(':')[0])
                order_minute = int(time_order.split(':')[1])
            except:
                order_hour = 0
                order_minute = 0
            
            # Фильтруем заказы: день недели совпадает и время заказа до указанного часа
            day_mask = subset_with_hour['День_недели'] == weekday_name
            # Заказы в диапазоне: от предыдущего окна до текущего
            time_mask = (
                (subset_with_hour['Час'] >= max(0, order_hour - 4)) & 
                (subset_with_hour['Час'] <= order_hour)
            )
            window_data = subset_with_hour[day_mask & time_mask]
            
            orders_count = len(window_data)
            
            if orders_count > 0:
                deviations = window_data['Разница во времени привоза (мин.)'].dropna()
                median_dev = deviations.median() if len(deviations) > 0 else 0
                on_time_pct = (deviations.between(-30, 30).sum() / len(deviations)) * 100 if len(deviations) > 0 else 0
                
                # Рассчитываем рекомендуемую длительность
                # Текущая длительность + медианное отклонение = рекомендуемая длительность
                recommended_duration = delivery_duration + int(round(median_dev))
                
                # Определяем статус и нужна ли корректировка
                duration_diff = recommended_duration - delivery_duration
                
                # Вычисляем время "Доставят к"
                deliver_by = calculate_expected_delivery(time_order, delivery_duration)
                recommend_deliver_by = calculate_expected_delivery(time_order, recommended_duration)
                
                if abs(duration_diff) <= 15 and on_time_pct >= 70:
                    status = "✅ OK"
                    tags = ('good',)
                    rec_text = f"{deliver_by} (OK)"
                elif abs(duration_diff) <= 30:
                    status = f"⚠️ {duration_diff:+d} мин"
                    tags = ('medium',)
                    rec_text = f"{recommend_deliver_by} ({duration_diff:+d})"
                else:
                    status = f"❌ {duration_diff:+d} мин"
                    tags = ('bad',)
                    rec_text = f"{recommend_deliver_by} ({duration_diff:+d})"
                
                schedule_rows.append({
                    'values': (
                        weekday_name,
                        time_order,
                        deliver_by,
                        '🚗 self' if delivery_type == 'self' else '📦 courier',
                        orders_count,
                        f"{median_dev:+.0f} мин",
                        f"{on_time_pct:.0f}%",
                        rec_text,
                        status
                    ),
                    'tags': tags,
                    'weekday_num': weekday_num,
                    'time_order': time_order
                })
            else:
                # Вычисляем время "Доставят к" даже если нет данных
                deliver_by = calculate_expected_delivery(time_order, delivery_duration)
                
                schedule_rows.append({
                    'values': (
                        weekday_name,
                        time_order,
                        deliver_by,
                        '🚗 self' if delivery_type == 'self' else '📦 courier',
                        0,
                        "—",
                        "—",
                        "— нет данных",
                        "📭 Нет данных"
                    ),
                    'tags': ('no_data',),
                    'weekday_num': weekday_num,
                    'time_order': time_order
                })
            
            schedule_count += 1
    
    # Вставляем отсортированные строки в таблицу
    for row in schedule_rows:
        tree_sched.insert('', 'end', values=row['values'], tags=row['tags'])
    
    if schedule_count == 0:
        # Если расписание не найдено, показываем сообщение
        tree_sched.insert('', 'end', values=(
            "—", "—", "—", "—", "—", "—", "—", "—",
            "Расписание не найдено"
        ), tags=('no_data',))
    
    # Прокрутка для таблицы tree_sched
    scrollbar_sched_v = ttk.Scrollbar(table_frame_sched, orient='vertical', command=tree_sched.yview)
    scrollbar_sched_h = ttk.Scrollbar(table_frame_sched, orient='horizontal', command=tree_sched.xview)
    tree_sched.configure(yscrollcommand=scrollbar_sched_v.set, xscrollcommand=scrollbar_sched_h.set)
    
    # Размещение через grid
    tree_sched.grid(row=0, column=0, sticky='nsew')
    scrollbar_sched_v.grid(row=0, column=1, sticky='ns')
    scrollbar_sched_h.grid(row=1, column=0, sticky='ew')
    table_frame_sched.grid_rowconfigure(0, weight=1)
    table_frame_sched.grid_columnconfigure(0, weight=1)
    
    # Подсчёт проблемных окон
    problems_count = sum(1 for r in schedule_rows if 'bad' in r['tags'])
    warnings_count = sum(1 for r in schedule_rows if 'medium' in r['tags'])
    
    # Кнопка обновления расписания
    btn_frame_sched = tk.Frame(frame_schedule, bg=COLORS['bg'])
    btn_frame_sched.pack(fill='x', padx=10, pady=5)
    
    def refresh_schedules():
        global schedules_cache
        schedules_cache = None  # Сбрасываем кэш
        fetch_schedules()
        messagebox.showinfo("📋 Расписание", f"Загружено {len(schedules_cache or [])} записей расписания")
    
    tk.Button(btn_frame_sched, text="🔄 Обновить расписание", command=refresh_schedules,
              font=("Segoe UI", 9), bg=COLORS['info'], fg='white').pack(side='left', padx=5)
    
    # Информация о расписании с подсчётом проблем
    summary_parts = [f"📋 Окон: {schedule_count}"]
    if problems_count > 0:
        summary_parts.append(f"❌ Проблем: {problems_count}")
    if warnings_count > 0:
        summary_parts.append(f"⚠️ Предупреждений: {warnings_count}")
    
    schedule_info_label = tk.Label(btn_frame_sched, 
        text=" | ".join(summary_parts),
        font=("Segoe UI", 9, "bold"), fg=COLORS['danger'] if problems_count > 0 else COLORS['text'], bg=COLORS['bg'])
    schedule_info_label.pack(side='right', padx=5)
    
    # Обработчик двойного клика для расписания - показать заказы в этом окне
    def on_schedule_double_click(event):
        selected = tree_sched.selection()
        if not selected:
            return
        values = tree_sched.item(selected[0])['values']
        day_name = values[0]
        time_order = values[1]
        
        if day_name != "—" and time_order != "—":
            show_orders_for_schedule_window(supplier, warehouse, pv_label, day_name, time_order, subset_with_hour)
    
    tree_sched.bind('<Double-1>', on_schedule_double_click)
    tk.Label(frame_schedule, text="💡 Двойной клик — просмотр заказов | Рекоменд. = Заказ до + (Длит. + Медиана откл.)", 
            font=("Segoe UI", 9), fg=COLORS['text_light']).pack(pady=5)


def show_charts_guide():
    """Окно с гайдом по чтению графиков"""
    win = tk.Toplevel(root)
    win.title("❓ Как читать графики")
    win.geometry("900x700")
    win.configure(bg=COLORS['bg'])
    
    # Заголовок
    header = tk.Frame(win, bg=COLORS['info'])
    header.pack(fill='x')
    tk.Label(header, text="❓ Гайд по чтению графиков", 
            font=("Segoe UI", 16, "bold"), bg=COLORS['info'], fg='white').pack(pady=15)
    
    # Контент с прокруткой
    canvas = tk.Canvas(win, bg=COLORS['bg'])
    scrollbar = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas, bg=COLORS['bg'])
    
    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    
    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    content = scrollable_frame
    
    guides = [
        ("📊 Распределение отклонений", 
         "Показывает, как часто поставщик привозит вовремя, рано или поздно.\n\n"
         "• 🟢 Зелёный — привоз раньше графика (хорошо)\n"
         "• 🔵 Синий — привоз вовремя (±30 мин от графика)\n"
         "• 🟠 Оранжевый — небольшое опоздание (30-60 мин)\n"
         "• 🔴 Красный — сильное опоздание (>60 мин)\n\n"
         "Синяя пунктирная линия — график (0 минут отклонения)\n"
         "Красная линия — медиана (среднее значение отклонений)"),
        
        ("📅 Распределение по дням недели",
         "Показывает разброс отклонений по каждому дню недели.\n\n"
         "• Коробка — 50% всех заказов (между 25% и 75%)\n"
         "• Красная линия — медиана (середина)\n"
         "• Усы — минимальные и максимальные значения\n"
         "• Точки — редкие случаи (выбросы)\n\n"
         "Чем выше коробка, тем больше опозданий в этот день."),
        
        ("🔥 Тепловая карта: День × Час",
         "Цветовая карта показывает, в какие дни и часы поставщик опаздывает.\n\n"
         "• 🟢 Зелёный — привоз вовремя или раньше\n"
         "• 🟡 Жёлтый — небольшое опоздание\n"
         "• 🔴 Красный — сильное опоздание\n\n"
         "Используйте для поиска проблемных периодов."),
        
        ("⏰ Отклонение по часам",
         "Показывает среднее отклонение для каждого часа заказа.\n\n"
         "• Синяя линия — медианное отклонение\n"
         "• Серая зона — диапазон отклонений (±1 стандартное отклонение)\n"
         "• Зелёная пунктирная — график (0 минут)\n\n"
         "Если линия выше 0 — поставщик опаздывает в этот час."),
        
        ("📈 Динамика отклонений",
         "Показывает, как меняется точность поставок со временем.\n\n"
         "• Размер точки — количество заказов в этот день\n"
         "• Цвет точки — величина отклонения (зелёный=хорошо, красный=плохо)\n"
         "• Красная линия — 7-дневное среднее (сглаженный тренд)\n"
         "• Фиолетовая пунктирная — общий тренд (улучшение/ухудшение)\n\n"
         "Если фиолетовая линия идёт вверх — ситуация ухудшается."),
        
        ("✅ % вовремя по дням",
         "Процент заказов, привезённых вовремя (±30 минут от графика).\n\n"
         "• 🟢 Зелёный — ≥80% (отлично)\n"
         "• 🟠 Оранжевый — 60-80% (приемлемо)\n"
         "• 🔴 Красный — <60% (плохо)\n\n"
         "Цель — 80% и выше (зелёная пунктирная линия).")
    ]
    
    for i, (title, text) in enumerate(guides):
        frame = tk.LabelFrame(content, text=title, font=("Segoe UI", 12, "bold"),
                             bg=COLORS['bg'], fg=COLORS['primary'], padx=15, pady=10)
        frame.pack(fill='x', padx=20, pady=10)
        
        tk.Label(frame, text=text, font=("Segoe UI", 10), bg=COLORS['bg'],
                justify='left', wraplength=800).pack(anchor='w', padx=10, pady=5)
    
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    
    # Подсказка
    tk.Label(win, text="💡 Используйте колесо мыши для прокрутки", 
            font=("Segoe UI", 9), fg=COLORS['text_light'], bg=COLORS['bg']).pack(pady=5)


def create_supplier_charts(parent, df, supplier, pv_label=None):
    """Создание улучшенных графиков для поставщика с пояснениями"""
    fig = Figure(figsize=(14, 10), dpi=100, facecolor=COLORS['bg'])
    
    # 2x3 сетка для 6 графиков
    ax1 = fig.add_subplot(231)
    ax2 = fig.add_subplot(232)
    ax3 = fig.add_subplot(233)
    ax4 = fig.add_subplot(234)
    ax5 = fig.add_subplot(235)
    ax6 = fig.add_subplot(236)
    
    # График 1: Распределение с градиентом
    deviations = df['Разница во времени привоза (мин.)'].dropna()
    counts, bins, patches = ax1.hist(deviations, bins=40, edgecolor='white', linewidth=0.5)
    
    # Градиентная заливка
    for i, patch in enumerate(patches):
        bin_center = (bins[i] + bins[i+1]) / 2
        if bin_center < -60:
            color = '#4caf50'  # Зелёный (ранние)
        elif bin_center < -30:
            color = '#8bc34a'
        elif bin_center < 30:
            color = '#2196f3'  # Синий (вовремя)
        elif bin_center < 60:
            color = '#ff9800'  # Оранжевый
        else:
            color = '#f44336'  # Красный (опоздания)
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    
    ax1.axvline(x=0, color='#1565c0', linestyle='--', linewidth=2.5, label='График (0 мин)')
    ax1.axvline(x=deviations.median(), color='#d32f2f', linestyle='-', linewidth=2.5, 
               label=f'Среднее: {deviations.median():.0f} мин')
    ax1.set_title('📊 Распределение отклонений\n(🟢 раньше | 🔵 вовремя | 🔴 позже)', 
                 fontsize=11, fontweight='bold', pad=10)
    ax1.set_xlabel('Отклонение от графика (минуты)\nОтрицательные = раньше, Положительные = позже', 
                   fontsize=9)
    ax1.set_ylabel('Количество заказов', fontsize=10)
    ax1.set_xlim(-500, 500)  # Ограничиваем ось X от -500 до 500 минут
    ax1.legend(fontsize=8, loc='upper right', framealpha=0.9)
    ax1.grid(True, alpha=0.2, linestyle='--')
    ax1.set_facecolor('#fafafa')
    
    # График 2: Box plot по дням недели
    df['dow_num'] = df['День_недели'].map({day: i for i, day in enumerate(DAYS_RU)})
    weekday_data = [df[df['dow_num'] == i]['Разница во времени привоза (мин.)'].dropna().values 
                   for i in range(7)]
    
    bp = ax2.boxplot(weekday_data, labels=DAYS_SHORT, patch_artist=True,
                    boxprops=dict(facecolor='#64b5f6', alpha=0.7),
                    medianprops=dict(color='#d32f2f', linewidth=2),
                    whiskerprops=dict(color='#1976d2'),
                    capprops=dict(color='#1976d2'))
    ax2.axhline(y=0, color=COLORS['success'], linestyle='--', linewidth=1.5, alpha=0.8, label='График')
    ax2.set_title('📅 Распределение по дням недели\n(Коробка = 50% заказов, Красная линия = среднее)', 
                 fontsize=11, fontweight='bold', pad=10)
    ax2.set_ylabel('Отклонение от графика (минуты)', fontsize=9)
    ax2.set_xlabel('День недели', fontsize=10)
    ax2.legend(fontsize=8, loc='upper right', framealpha=0.9)
    ax2.grid(True, alpha=0.2, axis='y', linestyle='--')
    ax2.set_facecolor('#fafafa')
    
    # График 3: Тепловая карта день-час
    df['hour'] = df['Время заказа позиции'].dt.hour
    heatmap_data = df.groupby(['dow_num', 'hour'])['Разница во времени привоза (мин.)'].median().unstack(fill_value=0)
    
    if not heatmap_data.empty:
        im = ax3.imshow(heatmap_data.values, cmap='RdYlGn_r', aspect='auto', vmin=-90, vmax=90)
        ax3.set_yticks(range(len(DAYS_SHORT)))
        ax3.set_yticklabels(DAYS_SHORT)
        ax3.set_xticks(range(len(heatmap_data.columns)))
        ax3.set_xticklabels([f"{h:02d}" for h in heatmap_data.columns], fontsize=8)
        ax3.set_title('🔥 Тепловая карта: День × Час\n(🟢 вовремя | 🔴 опоздание)', 
                     fontsize=11, fontweight='bold', pad=10)
        ax3.set_xlabel('Час заказа', fontsize=10)
        ax3.set_ylabel('День недели', fontsize=10)
        cbar = fig.colorbar(im, ax=ax3, shrink=0.8)
        cbar.set_label('Отклонение (мин)\n<0 = раньше, >0 = позже', fontsize=8)
    
    # График 4: Медиана по часам с доверительным интервалом
    hour_stats = df.groupby('hour')['Разница во времени привоза (мин.)'].agg(['median', 'std', 'count'])
    hour_stats = hour_stats[hour_stats['count'] >= 3]
    
    if not hour_stats.empty:
        hours = hour_stats.index
        medians = hour_stats['median']
        stds = hour_stats['std'].fillna(0)
        
        ax4.plot(hours, medians, marker='o', color='#1976d2', linewidth=3, markersize=8, 
                label='Среднее отклонение', markeredgecolor='white', markeredgewidth=2)
        ax4.fill_between(hours, medians - stds, medians + stds, alpha=0.2, color='#2196f3', 
                        label='Диапазон отклонений')
        ax4.axhline(y=0, color=COLORS['success'], linestyle='--', linewidth=2, alpha=0.8, label='График (0)')
        ax4.set_title('⏰ Отклонение по часам заказа\n(Выше 0 = опоздание, Ниже 0 = ранний привоз)', 
                     fontsize=11, fontweight='bold', pad=10)
        ax4.set_xlabel('Час заказа', fontsize=10)
        ax4.set_ylabel('Отклонение (минуты)', fontsize=9)
        ax4.legend(fontsize=8, loc='best', framealpha=0.9)
        ax4.grid(True, alpha=0.2, linestyle='--')
        ax4.set_facecolor('#fafafa')
        ax4.set_xticks(range(6, 22, 2))
    
    # График 5: Динамика с трендом
    df['Дата'] = df['Время заказа позиции'].dt.date
    daily_stats = df.groupby('Дата')['Разница во времени привоза (мин.)'].agg(['median', 'count'])
    daily_stats = daily_stats[daily_stats['count'] >= 2]
    
    if len(daily_stats) > 0:
        dates = pd.to_datetime(daily_stats.index)
        
        # Точки с размером по количеству
        sizes = (daily_stats['count'] / daily_stats['count'].max() * 100) + 20
        scatter = ax5.scatter(dates, daily_stats['median'], s=sizes, alpha=0.4, 
                            c=daily_stats['median'], cmap='RdYlGn_r', vmin=-60, vmax=60,
                            edgecolors='#1976d2', linewidth=1)
        
        # Скользящее среднее
        if len(daily_stats) > 7:
            rolling = daily_stats['median'].rolling(window=7, center=True).mean()
            ax5.plot(dates, rolling.values, color='#d32f2f', linewidth=3, 
                    label='7-дневное среднее', alpha=0.9)
        
        # Линия тренда
        if len(daily_stats) > 14:
            z = np.polyfit(range(len(daily_stats)), daily_stats['median'].values, 1)
            p = np.poly1d(z)
            ax5.plot(dates, p(range(len(daily_stats))), "--", color='#7b1fa2', 
                    linewidth=2, label=f'Тренд: {z[0]:.2f} мин/день', alpha=0.7)
        
        ax5.axhline(y=0, color=COLORS['success'], linestyle='--', linewidth=2, alpha=0.8, label='График')
        ax5.set_title('📈 Динамика отклонений во времени\n(Размер точки = количество заказов)', 
                     fontsize=11, fontweight='bold', pad=10)
        ax5.set_xlabel('Дата', fontsize=10)
        ax5.set_ylabel('Отклонение (минуты)', fontsize=9)
        ax5.legend(fontsize=8, loc='best', framealpha=0.9)
        ax5.grid(True, alpha=0.2, linestyle='--')
        ax5.set_facecolor('#fafafa')
        ax5.tick_params(axis='x', rotation=45)
        cbar = fig.colorbar(scatter, ax=ax5, shrink=0.8)
        cbar.set_label('Отклонение (мин)', fontsize=8)
    
    # График 6: Процент вовремя по дням
    weekday_ontime = []
    for day in DAYS_RU:
        day_data = df[df['День_недели'] == day]
        if len(day_data) > 0:
            pct = (day_data['Разница во времени привоза (мин.)'].between(-30, 30).sum() / len(day_data)) * 100
            weekday_ontime.append(pct)
        else:
            weekday_ontime.append(0)
    
    colors_bars = ['#4caf50' if p >= 80 else '#ff9800' if p >= 60 else '#f44336' for p in weekday_ontime]
    bars = ax6.bar(range(7), weekday_ontime, color=colors_bars, alpha=0.8, edgecolor='white', linewidth=1.5)
    
    # Добавляем значения на столбцы
    for i, (bar, value) in enumerate(zip(bars, weekday_ontime)):
        height = bar.get_height()
        ax6.text(bar.get_x() + bar.get_width()/2., height + 1,
                f'{value:.0f}%', ha='center', va='bottom', fontsize=9, fontweight='bold')
    
    ax6.axhline(y=80, color=COLORS['success'], linestyle='--', linewidth=2, alpha=0.7, label='Цель: 80%')
    ax6.set_xticks(range(7))
    ax6.set_xticklabels(DAYS_SHORT)
    ax6.set_ylim(0, 105)
    ax6.set_title('✅ Процент вовремя по дням\n(🟢 ≥80% отлично | 🟠 60-80% норма | 🔴 <60% плохо)', 
                 fontsize=11, fontweight='bold', pad=10)
    ax6.set_ylabel('Процент заказов вовремя (±30 мин)', fontsize=9)
    ax6.set_xlabel('День недели', fontsize=10)
    ax6.legend(fontsize=8, loc='lower right', framealpha=0.9)
    ax6.grid(True, alpha=0.2, axis='y', linestyle='--')
    ax6.set_facecolor('#fafafa')
    
    fig.tight_layout(pad=1.5)
    
    canvas = FigureCanvasTkAgg(fig, parent)
    canvas.draw()
    canvas.get_tk_widget().pack(fill='both', expand=True)
    
    # Toolbar
    toolbar = NavigationToolbar2Tk(canvas, parent)
    toolbar.update()


def show_recommendation_details(rec):
    """Детали рекомендации с примерами заказов"""
    win = tk.Toplevel(root)
    pv_label = normalize_pv_value(getattr(rec, 'pv', None))
    win.title(f"💡 Рекомендация: {rec.supplier} — {pv_label}")
    win.geometry("800x750")
    win.configure(bg=COLORS['bg'])
    
    # Заголовок
    header = tk.Frame(win, bg=COLORS['primary'])
    header.pack(fill='x')
    
    tk.Label(
        header,
        text=f"💡 Рекомендация по корректировке",
        font=("Segoe UI", 14, "bold"),
        bg=COLORS['primary'],
        fg='white'
    ).pack(pady=15)
    
    # Основная информация
    info_frame = tk.LabelFrame(win, text="📋 Параметры", font=("Segoe UI", 10, "bold"), bg=COLORS['bg'])
    info_frame.pack(fill='x', padx=20, pady=15)
    
    params = [
        ("🏭 Поставщик:", rec.supplier),
        ("📦 Склад:", rec.warehouse),
        ("🏬 ПВ:", pv_label),
        ("📅 День недели:", rec.weekday),
        ("⏰ Интервал заказов:", f"{rec.order_time_start} — {rec.order_time_end}"),
        ("", ""),
        ("📊 Текущее отклонение:", rec.current_expected_time),
        ("✅ Рекомендуемое:", rec.recommended_time),
        ("⚡ Сдвиг:", f"{rec.shift_minutes:+d} минут"),
        ("", ""),
        ("🎯 Уверенность:", f"{rec.confidence*100:.0f}%"),
        ("📈 Тренд:", rec.trend_detected),
        ("📆 Применить с:", rec.effective_from),
    ]
    
    for i, (label, value) in enumerate(params):
        if label == "":
            ttk.Separator(info_frame, orient='horizontal').grid(row=i, column=0, columnspan=2, sticky='ew', pady=5)
        else:
            tk.Label(info_frame, text=label, font=("Segoe UI", 10), bg=COLORS['bg'], anchor='e').grid(
                row=i, column=0, sticky='e', padx=(10, 5), pady=3)
            tk.Label(info_frame, text=value, font=("Segoe UI", 10, "bold"), bg=COLORS['bg'], anchor='w').grid(
                row=i, column=1, sticky='w', padx=(5, 10), pady=3)
    
    # Причина
    reason_frame = tk.LabelFrame(win, text="💬 Причина рекомендации", font=("Segoe UI", 10, "bold"), bg=COLORS['bg'])
    reason_frame.pack(fill='x', padx=20, pady=10)
    
    tk.Label(
        reason_frame,
        text=rec.reason,
        font=("Segoe UI", 10),
        bg=COLORS['bg'],
        wraplength=720,
        justify='left'
    ).pack(padx=15, pady=15)
    
    # Примеры заказов
    if hasattr(rec, 'example_orders') and rec.example_orders:
        examples_frame = tk.LabelFrame(win, text="📦 Примеры заказов (последние)", font=("Segoe UI", 10, "bold"), bg=COLORS['bg'])
        examples_frame.pack(fill='both', expand=True, padx=20, pady=10)
        
        # Frame для таблицы с прокруткой
        table_frame_examples = tk.Frame(examples_frame, bg=COLORS['bg'])
        table_frame_examples.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Таблица примеров
        cols = ('№ заказа', 'ПВ', 'Дата', 'Время заказа', 'План', 'Факт', 'Откл.')
        tree_examples = ttk.Treeview(table_frame_examples, columns=cols, show='headings', height=5)
        
        tree_examples.column('№ заказа', width=100)
        tree_examples.column('ПВ', width=160)
        tree_examples.column('Дата', width=100)
        tree_examples.column('Время заказа', width=100)
        tree_examples.column('План', width=80)
        tree_examples.column('Факт', width=80)
        tree_examples.column('Откл.', width=80)
        
        for col in cols:
            tree_examples.heading(col, text=col)
        
        add_tooltips_to_treeview(tree_examples, cols)
        
        for ex in rec.example_orders:
            dev = ex.get('deviation', 0)
            tags = ()
            if abs(dev) <= 30:
                tags = ('good',)
            elif abs(dev) <= 60:
                tags = ('medium',)
            else:
                tags = ('bad',)
            
            tree_examples.insert('', 'end', values=(
                ex.get('order_id', ''),
                normalize_pv_value(ex.get('pv')),
                ex.get('order_date', ''),
                ex.get('order_time', ''),
                ex.get('plan_time', ''),
                ex.get('fact_time', ''),
                f"{dev:+d} мин" if dev else ''
            ), tags=tags)
        
        tree_examples.tag_configure('good', foreground=COLORS['success'])
        tree_examples.tag_configure('medium', foreground=COLORS['warning'])
        tree_examples.tag_configure('bad', foreground=COLORS['danger'])
        
        # Прокрутка для таблицы tree_examples
        scrollbar_examples_v = ttk.Scrollbar(table_frame_examples, orient='vertical', command=tree_examples.yview)
        scrollbar_examples_h = ttk.Scrollbar(table_frame_examples, orient='horizontal', command=tree_examples.xview)
        tree_examples.configure(yscrollcommand=scrollbar_examples_v.set, xscrollcommand=scrollbar_examples_h.set)
        
        # Размещение через grid
        tree_examples.grid(row=0, column=0, sticky='nsew')
        scrollbar_examples_v.grid(row=0, column=1, sticky='ns')
        scrollbar_examples_h.grid(row=1, column=0, sticky='ew')
        table_frame_examples.grid_rowconfigure(0, weight=1)
        table_frame_examples.grid_columnconfigure(0, weight=1)
        
        # Подсказка для клика
        tk.Label(
            examples_frame,
            text="💡 Двойной клик на заказ — открыть в CRM",
            font=("Segoe UI", 9),
            fg=COLORS['text_light'],
            bg=COLORS['bg']
        ).pack(pady=5)
        
        # Обработчик двойного клика
        def on_example_double_click(event):
            selected = tree_examples.selection()
            if selected:
                order_id = tree_examples.item(selected[0])['values'][0]
                open_order_in_crm(order_id)
        
        tree_examples.bind('<Double-1>', on_example_double_click)
    
    # Кнопки
    btn_frame = tk.Frame(win, bg=COLORS['bg'])
    btn_frame.pack(pady=15)
    
    tk.Button(
        btn_frame,
        text="📊 Анализ поставщика",
        command=lambda: show_supplier_details(rec.supplier, rec.warehouse, rec.pv),
        font=("Segoe UI", 10),
        bg=COLORS['info'],
        fg='white',
        width=18
    ).pack(side='left', padx=5)
    
    tk.Button(
        btn_frame,
        text="📥 Экспорт в Excel",
        command=lambda: export_single_rec(rec),
        font=("Segoe UI", 10),
        bg=COLORS['success'],
        fg='white',
        width=18
    ).pack(side='left', padx=5)


def export_single_rec(rec):
    """Экспорт одной рекомендации"""
    filepath = filedialog.asksaveasfilename(
        defaultextension=".xlsx",
        filetypes=[("Excel", "*.xlsx")],
        initialfile=f"Рекомендация_{rec.supplier}_{rec.warehouse}.xlsx"
    )
    if filepath:
        data = {
            'Параметр': ['Поставщик', 'Склад', 'ПВ', 'День', 'Интервал', 'Сдвиг', 'Уверенность', 'Тренд', 'Причина'],
            'Значение': [
                rec.supplier,
                rec.warehouse,
                normalize_pv_value(getattr(rec, 'pv', None)),
                rec.weekday,
                f"{rec.order_time_start}-{rec.order_time_end}",
                f"{rec.shift_minutes:+d} мин",
                f"{rec.confidence*100:.0f}%",
                rec.trend_detected,
                rec.reason
            ]
        }
        pd.DataFrame(data).to_excel(filepath, index=False)
        messagebox.showinfo("✅ Готово", f"Сохранено: {Path(filepath).name}")


def export_all_recommendations():
    """Экспорт всех рекомендаций"""
    if not recommendations:
        messagebox.showwarning("⚠️ Внимание", "Нет рекомендаций")
        return
    
    filepath = filedialog.asksaveasfilename(
        defaultextension=".xlsx",
        filetypes=[("Excel", "*.xlsx")],
        initialfile=f"ML_Рекомендации_{datetime.now().strftime('%Y%m%d')}.xlsx"
    )
    
    if not filepath:
        return
    
    data = [{
        'Поставщик': r.supplier,
        'Склад': r.warehouse,
        'ПВ': normalize_pv_value(r.pv),
        'День': r.weekday,
        'Час заказа': r.order_time_start,
        'Сдвиг (мин)': r.shift_minutes,
        'Уверенность': f"{r.confidence*100:.0f}%",
        'Тренд': r.trend_detected,
        'Причина': r.reason,
        'Применить с': r.effective_from
    } for r in recommendations]
    
    df = pd.DataFrame(data)
    df.to_excel(filepath, index=False, engine='openpyxl')
    
    # Форматирование
    wb = load_workbook(filepath)
    ws = wb.active
    header_fill = PatternFill(start_color="1a237e", end_color="1a237e", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
    
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 50)
    
    wb.save(filepath)
    messagebox.showinfo("✅ Готово", f"Экспортировано {len(recommendations)} рекомендаций")


def show_overall_charts():
    """Общие графики по всем данным"""
    if df_current is None:
        messagebox.showwarning("⚠️ Внимание", "Сначала загрузите данные")
        return
    
    win = tk.Toplevel(root)
    win.title("📊 Общая аналитика")
    win.geometry("1400x900")
    win.configure(bg=COLORS['bg'])
    
    # Заголовок
    header = tk.Frame(win, bg=COLORS['header'])
    header.pack(fill='x')
    tk.Label(header, text="📊 Общая аналитика по всем поставщикам", 
            font=("Segoe UI", 16, "bold"), bg=COLORS['header'], fg='white').pack(pady=12)
    
    fig = Figure(figsize=(15, 10), dpi=100, facecolor=COLORS['bg'])
    
    # 2x3 сетка
    ax1 = fig.add_subplot(231)
    ax2 = fig.add_subplot(232)
    ax3 = fig.add_subplot(233)
    ax4 = fig.add_subplot(234)
    ax5 = fig.add_subplot(235)
    ax6 = fig.add_subplot(236)
    
    # 1. Топ-10 поставщиков по количеству опозданий
    late_by_supplier = df_current[df_current['Разница во времени привоза (мин.)'] > 30].groupby('Поставщик').size().nlargest(10)
    colors_top = plt.cm.Reds(np.linspace(0.4, 0.8, len(late_by_supplier)))
    bars1 = ax1.barh(range(len(late_by_supplier)), late_by_supplier.values, color=colors_top, edgecolor='white', linewidth=1)
    ax1.set_yticks(range(len(late_by_supplier)))
    ax1.set_yticklabels([s[:25] for s in late_by_supplier.index], fontsize=9)
    ax1.set_title('🔴 Топ-10 по опозданиям (>30 мин)', fontsize=12, fontweight='bold', pad=10)
    ax1.set_xlabel('Количество опозданий', fontsize=10)
    ax1.invert_yaxis()
    ax1.grid(True, alpha=0.2, axis='x', linestyle='--')
    ax1.set_facecolor('#fafafa')
    
    for i, bar in enumerate(bars1):
        width = bar.get_width()
        ax1.text(width, bar.get_y() + bar.get_height()/2., f' {int(width)}',
                ha='left', va='center', fontsize=8, fontweight='bold')
    
    # 2. Топ-10 поставщиков по % вовремя
    supplier_stats = df_current.groupby('Поставщик').apply(
        lambda x: (x['Разница во времени привоза (мин.)'].between(-30, 30).sum() / len(x)) * 100
    ).nlargest(10)
    
    colors_best = ['#4caf50' if p >= 90 else '#8bc34a' if p >= 80 else '#fdd835' for p in supplier_stats.values]
    bars2 = ax2.barh(range(len(supplier_stats)), supplier_stats.values, color=colors_best, 
                    edgecolor='white', linewidth=1, alpha=0.8)
    ax2.set_yticks(range(len(supplier_stats)))
    ax2.set_yticklabels([s[:25] for s in supplier_stats.index], fontsize=9)
    ax2.set_title('🟢 Топ-10 лучших по % вовремя', fontsize=12, fontweight='bold', pad=10)
    ax2.set_xlabel('% вовремя', fontsize=10)
    ax2.axvline(x=80, color='#2e7d32', linestyle='--', linewidth=2, alpha=0.6, label='Цель: 80%')
    ax2.invert_yaxis()
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.2, axis='x', linestyle='--')
    ax2.set_facecolor('#fafafa')
    
    for i, bar in enumerate(bars2):
        width = bar.get_width()
        ax2.text(width - 3, bar.get_y() + bar.get_height()/2., f'{width:.1f}%',
                ha='right', va='center', fontsize=9, fontweight='bold', color='white')
    
    # 3. Распределение всех отклонений (улучшенная гистограмма)
    deviations = df_current['Разница во времени привоза (мин.)'].dropna()
    counts, bins, patches = ax3.hist(deviations, bins=60, edgecolor='white', linewidth=0.5)
    
    for i, patch in enumerate(patches):
        bin_center = (bins[i] + bins[i+1]) / 2
        if -30 <= bin_center <= 30:
            color = '#4caf50'
        elif -60 <= bin_center <= 60:
            color = '#ff9800'
        else:
            color = '#f44336'
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    
    ax3.axvline(x=0, color='#1565c0', linestyle='--', linewidth=2.5, label='График')
    ax3.axvline(x=deviations.median(), color='#d32f2f', linestyle='-', linewidth=2.5, 
               label=f'Медиана: {deviations.median():.0f} мин')
    ax3.axvline(x=-30, color='#7cb342', linestyle=':', linewidth=1.5, alpha=0.6)
    ax3.axvline(x=30, color='#7cb342', linestyle=':', linewidth=1.5, alpha=0.6, label='±30 мин')
    ax3.set_title('📊 Распределение отклонений', fontsize=12, fontweight='bold', pad=10)
    ax3.set_xlabel('Отклонение (мин)', fontsize=10)
    ax3.set_ylabel('Количество', fontsize=10)
    ax3.set_xlim(-500, 500)  # Ограничиваем ось X от -500 до 500 минут
    ax3.legend(fontsize=9)
    ax3.grid(True, alpha=0.2, linestyle='--')
    ax3.set_facecolor('#fafafa')
    
    # 4. Заказы по дням недели с медианой
    weekday_counts = df_current.groupby('День_недели').size().reindex(DAYS_RU).fillna(0)
    weekday_median = df_current.groupby('День_недели')['Разница во времени привоза (мин.)'].median().reindex(DAYS_RU).fillna(0)
    
    colors_wd = ['#2196f3' if i < 5 else '#ff9800' for i in range(7)]
    bars4 = ax4.bar(range(7), weekday_counts.values, color=colors_wd, alpha=0.7, edgecolor='white', linewidth=1)
    
    ax4_twin = ax4.twinx()
    ax4_twin.plot(range(7), weekday_median.values, color='#d32f2f', marker='D', 
                 linewidth=3, markersize=8, label='Медиана откл.', markeredgecolor='white', markeredgewidth=2)
    ax4_twin.axhline(y=0, color=COLORS['success'], linestyle='--', linewidth=1.5, alpha=0.6)
    
    ax4.set_xticks(range(7))
    ax4.set_xticklabels(DAYS_SHORT)
    ax4.set_title('📅 Нагрузка по дням недели', fontsize=12, fontweight='bold', pad=10)
    ax4.set_ylabel('Количество заказов', color='#2196f3', fontsize=10)
    ax4_twin.set_ylabel('Медиана откл. (мин)', color='#d32f2f', fontsize=10)
    ax4_twin.legend(fontsize=9, loc='upper right')
    ax4.grid(True, alpha=0.2, axis='y', linestyle='--')
    ax4.set_facecolor('#fafafa')
    
    # 5. Динамика по месяцам
    df_current['Месяц'] = df_current['Время заказа позиции'].dt.to_period('M')
    monthly = df_current.groupby('Месяц')['Разница во времени привоза (мин.)'].agg(['median', 'count', 'std'])
    
    if len(monthly) > 0:
        x = range(len(monthly))
        
        ax5.bar(x, monthly['count'], color='#64b5f6', alpha=0.4, label='Количество', edgecolor='white')
        
        ax5_twin = ax5.twinx()
        ax5_twin.plot(x, monthly['median'], color='#d32f2f', marker='o', linewidth=3, 
                     markersize=7, label='Медиана откл.', markeredgecolor='white', markeredgewidth=2)
        ax5_twin.fill_between(x, 
                             monthly['median'] - monthly['std'].fillna(0), 
                             monthly['median'] + monthly['std'].fillna(0),
                             alpha=0.2, color='#f44336', label='±1σ')
        ax5_twin.axhline(y=0, color=COLORS['success'], linestyle='--', linewidth=1.5, alpha=0.7)
        
        ax5.set_xticks(x[::max(1, len(x)//15)])
        ax5.set_xticklabels([str(m) for m in monthly.index[::max(1, len(x)//15)]], rotation=45, fontsize=8)
        ax5.set_title('📆 Динамика по месяцам', fontsize=12, fontweight='bold', pad=10)
        ax5.set_ylabel('Заказов', color='#1976d2', fontsize=10)
        ax5_twin.set_ylabel('Откл. (мин)', color='#d32f2f', fontsize=10)
        ax5.legend(loc='upper left', fontsize=8)
        ax5_twin.legend(loc='upper right', fontsize=8)
        ax5.grid(True, alpha=0.2, linestyle='--')
        ax5.set_facecolor('#fafafa')
    
    # 6. Общая сводка: вовремя/ранние/опоздания
    total = len(df_current)
    on_time = len(df_current[df_current['Разница во времени привоза (мин.)'].between(-30, 30)])
    early = len(df_current[df_current['Разница во времени привоза (мин.)'] < -30])
    late = len(df_current[df_current['Разница во времени привоза (мин.)'] > 30])
    
    sizes = [on_time, early, late]
    labels = [f'✅ Вовремя\n{on_time:,}\n({on_time/total*100:.1f}%)', 
             f'⬇ Ранние\n{early:,}\n({early/total*100:.1f}%)',
             f'⬆ Опоздания\n{late:,}\n({late/total*100:.1f}%)']
    colors_pie = ['#4caf50', '#2196f3', '#f44336']
    explode = (0.05, 0, 0.08)
    
    wedges, texts, autotexts = ax6.pie(sizes, labels=labels, colors=colors_pie, autopct='',
                                       startangle=90, explode=explode,
                                       textprops={'fontsize': 11, 'fontweight': 'bold'},
                                       wedgeprops={'edgecolor': 'white', 'linewidth': 3})
    
    ax6.set_title('⚖️ Общая сводка', fontsize=12, fontweight='bold', pad=10)
    
    fig.tight_layout(pad=1.5)
    
    canvas = FigureCanvasTkAgg(fig, win)
    canvas.draw()
    canvas.get_tk_widget().pack(fill='both', expand=True, padx=10, pady=10)
    
    toolbar = NavigationToolbar2Tk(canvas, win)
    toolbar.update()


# ========================================
# ГЛАВНОЕ ОКНО
# ========================================
root = tk.Tk()
root.title("🤖 ML-Аналитика доставок v2.0")
root.geometry("1400x900")
root.configure(bg=COLORS['bg'])

# Стиль
style = ttk.Style()
style.theme_use("clam")
style.configure("Treeview", rowheight=26, font=("Segoe UI", 9))
style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background="#e0e0e0")
style.map("Treeview", background=[('selected', COLORS['primary'])])

# === ЗАГОЛОВОК ===
header_frame = tk.Frame(root, bg=COLORS['header'])
header_frame.pack(fill='x')

tk.Label(
    header_frame,
    text="🤖 ML-Аналитика доставок",
    font=("Segoe UI", 22, "bold"),
    bg=COLORS['header'],
    fg='white'
).pack(pady=(15, 5))

tk.Label(
    header_frame,
    text="Машинное обучение для оптимизации графика поставок",
    font=("Segoe UI", 10),
    bg=COLORS['header'],
    fg='#90a4ae'
).pack(pady=(0, 2))

# Информация об окружении
env_label_text = f"🔗 CRM: {CRM_BASE_URL}"
if args.env == 'prod':
    env_color = '#ff9800'
elif args.env == 'local':
    env_color = '#4caf50'
else:
    env_color = '#2196f3'

tk.Label(
    header_frame,
    text=env_label_text,
    font=("Segoe UI", 8),
    bg=COLORS['header'],
    fg=env_color
).pack(pady=(0, 15))

# === ПАНЕЛЬ УПРАВЛЕНИЯ ===
control_frame = tk.Frame(root, bg=COLORS['bg'])
control_frame.pack(fill='x', padx=15, pady=10)

# Даты
date_frame = tk.LabelFrame(control_frame, text="📅 Период", font=("Segoe UI", 9), bg=COLORS['bg'])
date_frame.pack(side='left', padx=5)

# Календари - используем только базовые параметры для избежания проблем
# Проблема: в некоторых версиях tkcalendar календарь закрывается при выборе месяца
# Решение: используем минимальные параметры без selectmode и других проблемных опций
cal_start = DateEntry(
    date_frame, 
    width=12, 
    date_pattern='dd.mm.yyyy'
)
cal_start.set_date(datetime.today() - timedelta(days=30))
cal_start.pack(side='left', padx=5, pady=5)

tk.Label(date_frame, text="—", bg=COLORS['bg']).pack(side='left')

cal_end = DateEntry(
    date_frame, 
    width=12, 
    date_pattern='dd.mm.yyyy'
)
cal_end.set_date(datetime.today())
cal_end.pack(side='left', padx=5, pady=5)

# Кнопки загрузки
btn_load_frame = tk.LabelFrame(control_frame, text="📥 Загрузка", font=("Segoe UI", 9), bg=COLORS['bg'])
btn_load_frame.pack(side='left', padx=10)

tk.Button(btn_load_frame, text="📥 Период", command=fetch_data, bg=COLORS['primary'], fg='white', 
          font=("Segoe UI", 9), width=10).pack(side='left', padx=3, pady=5)
tk.Button(btn_load_frame, text="📚 История", command=fetch_historical_data, bg='#7b1fa2', fg='white',
          font=("Segoe UI", 9), width=10).pack(side='left', padx=3, pady=5)
tk.Button(btn_load_frame, text="💾 Кэш", command=load_cached_data, bg=COLORS['success'], fg='white',
          font=("Segoe UI", 9), width=8).pack(side='left', padx=3, pady=5)

# Фильтр по ПВ
pv_filter_frame = tk.LabelFrame(control_frame, text="🏬 Фильтр ПВ", font=("Segoe UI", 9), bg=COLORS['bg'])
pv_filter_frame.pack(side='left', padx=10)

pv_filter_var = tk.StringVar(value="Все ПВ")
pv_filter_combo = ttk.Combobox(pv_filter_frame, textvariable=pv_filter_var, width=20, state='readonly')
pv_filter_combo['values'] = ["Все ПВ"]
pv_filter_combo.pack(side='left', padx=3, pady=5)

def apply_pv_filter(event=None):
    """Применить фильтр по ПВ"""
    global df_current, current_pv_filter
    if df_original is None:
        return
    
    selected = pv_filter_var.get()
    if selected == "Все ПВ":
        df_current = df_original.copy()
        current_pv_filter = None
    else:
        df_current = df_original[df_original['ПВ'] == selected].copy()
        current_pv_filter = selected
    
    update_stats_display()
    update_weekday_supplier_list()
    update_weekday_stats_display()
    update_raw_data_display()
    update_status(f"🏬 Фильтр: {selected} | Записей: {len(df_current):,}", "info")

pv_filter_combo.bind('<<ComboboxSelected>>', apply_pv_filter)

def update_pv_filter_options():
    """Обновить список ПВ в фильтре"""
    if df_original is not None:
        pv_list = ["Все ПВ"] + sorted(df_original['ПВ'].dropna().unique().tolist())
        pv_filter_combo['values'] = pv_list

# Кнопки анализа
btn_analysis_frame = tk.LabelFrame(control_frame, text="🔍 Анализ", font=("Segoe UI", 9), bg=COLORS['bg'])
btn_analysis_frame.pack(side='left', padx=10)

tk.Button(btn_analysis_frame, text="🔄 Переобучить", command=retrain_model, bg='#9c27b0', fg='white',
          font=("Segoe UI", 9), width=12).pack(side='left', padx=3, pady=5)
tk.Button(btn_analysis_frame, text="📊 Графики", command=show_overall_charts, bg=COLORS['info'], fg='white',
          font=("Segoe UI", 9), width=10).pack(side='left', padx=3, pady=5)
tk.Button(btn_analysis_frame, text="📥 Экспорт", command=export_all_recommendations, bg=COLORS['warning'], fg='white',
          font=("Segoe UI", 9), width=10).pack(side='left', padx=3, pady=5)


def load_schedule_button():
    """Загрузить расписание из CRM"""
    global schedules_cache
    
    def load():
        try:
            root.after(0, lambda: update_status("⏳ Загрузка расписания...", "info"))
            root.after(0, progress_bar.start)
            
            schedules_cache = None
            schedules = fetch_schedules()
            
            root.after(0, progress_bar.stop)
            
            if schedules:
                root.after(0, lambda: update_status(f"📋 Загружено {len(schedules)} записей расписания", "success"))
            else:
                root.after(0, lambda: update_status("⚠️ Расписание не найдено или ошибка", "warning"))
        except Exception as e:
            root.after(0, progress_bar.stop)
            root.after(0, lambda: update_status(f"❌ Ошибка: {str(e)[:30]}", "error"))
    
    thread = threading.Thread(target=load, daemon=True)
    thread.start()


def show_all_schedules():
    """Показать расписания с выбором ПВ и сеткой склад × день недели"""
    global schedules_cache
    
    if not schedules_cache:
        fetch_schedules()
    
    if not schedules_cache:
        messagebox.showwarning("⚠️ Внимание", "Расписание не загружено. Проверьте подключение к CRM.")
        return
    
    win = tk.Toplevel(root)
    win.title("📋 Расписание доставки")
    win.geometry("1400x700")
    win.configure(bg=COLORS['bg'])
    
    # Заголовок
    header = tk.Frame(win, bg=COLORS['header'])
    header.pack(fill='x')
    tk.Label(header, text="📋 Расписание доставки по ПВ", 
            font=("Segoe UI", 16, "bold"), bg=COLORS['header'], fg='white').pack(pady=10)
    
    # Собираем уникальные ПВ
    pv_list = sorted(set(s.get('branch', '') for s in schedules_cache if s.get('branch')))
    
    tk.Label(header, text=f"Всего ПВ: {len(pv_list)} | Окон: {len(schedules_cache)}", 
            font=("Segoe UI", 9), bg=COLORS['header'], fg='#90a4ae').pack(pady=(0, 10))
    
    # Фрейм выбора ПВ
    select_frame = tk.Frame(win, bg=COLORS['bg'])
    select_frame.pack(fill='x', padx=10, pady=10)
    
    tk.Label(select_frame, text="🏬 Выберите ПВ:", font=("Segoe UI", 11, "bold"), 
            bg=COLORS['bg']).pack(side='left', padx=5)
    
    pv_var = tk.StringVar()
    pv_combo = ttk.Combobox(select_frame, textvariable=pv_var, width=70, state='readonly')
    pv_combo['values'] = pv_list
    pv_combo.pack(side='left', padx=10)
    
    if pv_list:
        pv_combo.current(0)
    
    info_label = tk.Label(select_frame, text="", font=("Segoe UI", 9, "bold"), 
                         bg=COLORS['bg'], fg=COLORS['primary'])
    info_label.pack(side='right', padx=10)
    
    # Фрейм для таблицы с прокруткой
    table_outer = tk.Frame(win, bg=COLORS['bg'])
    table_outer.pack(fill='both', expand=True, padx=10, pady=5)
    
    # Canvas для прокрутки
    canvas = tk.Canvas(table_outer, bg=COLORS['bg'], highlightthickness=0)
    scrollbar_v = ttk.Scrollbar(table_outer, orient='vertical', command=canvas.yview)
    scrollbar_h = ttk.Scrollbar(table_outer, orient='horizontal', command=canvas.xview)
    
    # Внутренний фрейм для таблицы
    table_frame = tk.Frame(canvas, bg=COLORS['bg'])
    
    canvas.create_window((0, 0), window=table_frame, anchor='nw')
    canvas.configure(yscrollcommand=scrollbar_v.set, xscrollcommand=scrollbar_h.set)
    
    def on_frame_configure(event):
        canvas.configure(scrollregion=canvas.bbox('all'))
    
    table_frame.bind('<Configure>', on_frame_configure)
    
    # Прокрутка колесом мыши
    def on_mousewheel(event):
        canvas.yview_scroll(int(-1*(event.delta/120)), 'units')
    
    def on_mousewheel_linux(event):
        if event.num == 4:
            canvas.yview_scroll(-1, 'units')
        elif event.num == 5:
            canvas.yview_scroll(1, 'units')
    
    canvas.bind_all('<MouseWheel>', on_mousewheel)
    canvas.bind_all('<Button-4>', on_mousewheel_linux)
    canvas.bind_all('<Button-5>', on_mousewheel_linux)
    
    def format_window(sched):
        """Форматирование окна расписания"""
        time_order = sched.get('timeOrder', '')
        duration = sched.get('deliveryDuration', 0)
        delivery_type = sched.get('type', 'self')
        deliver_by = calculate_expected_delivery(time_order, duration)
        
        icon = '🚗' if delivery_type == 'self' else '📦'
        return f"{time_order}→{deliver_by} {icon}", delivery_type
    
    def update_table(*args):
        """Обновить таблицу для выбранного ПВ"""
        # Очищаем таблицу
        for widget in table_frame.winfo_children():
            widget.destroy()
        
        selected_pv = pv_var.get()
        if not selected_pv:
            return
        
        # Фильтруем расписание для выбранного ПВ
        pv_schedules = [s for s in schedules_cache if s.get('branch') == selected_pv]
        
        if not pv_schedules:
            tk.Label(table_frame, text="Нет расписания для выбранного ПВ", 
                    font=("Segoe UI", 12), bg=COLORS['bg'], fg=COLORS['text_light']).grid(row=0, column=0)
            return
        
        # Группируем по складу
        warehouses = {}
        for sched in pv_schedules:
            warehouse = sched.get('warehouse', 'Неизвестный склад')
            if warehouse not in warehouses:
                warehouses[warehouse] = {i: [] for i in range(1, 8)}  # 1=Пн ... 7=Вс
            
            weekday = sched.get('weekday', 1)
            if 1 <= weekday <= 7:
                warehouses[warehouse][weekday].append(sched)
        
        # Заголовок таблицы
        header_bg = '#1a237e'
        header_fg = 'white'
        
        tk.Label(table_frame, text="Склад", font=("Segoe UI", 10, "bold"), 
                bg=header_bg, fg=header_fg, width=25, anchor='w', padx=10, pady=8,
                relief='ridge').grid(row=0, column=0, sticky='nsew')
        
        for col, day in enumerate(DAYS_SHORT, 1):
            tk.Label(table_frame, text=day, font=("Segoe UI", 10, "bold"), 
                    bg=header_bg, fg=header_fg, width=15, padx=5, pady=8,
                    relief='ridge').grid(row=0, column=col, sticky='nsew')
        
        # Заполняем таблицу
        row_num = 1
        for warehouse in sorted(warehouses.keys()):
            day_data = warehouses[warehouse]
            
            # Цвет строки
            row_bg = '#ffffff' if row_num % 2 == 1 else '#f5f5f5'
            
            # Ячейка склада
            tk.Label(table_frame, text=warehouse[:35], font=("Segoe UI", 9), 
                    bg=row_bg, anchor='w', padx=10, pady=5,
                    relief='ridge', wraplength=200).grid(row=row_num, column=0, sticky='nsew')
            
            # Ячейки по дням
            for col, day_num in enumerate(range(1, 8), 1):
                day_windows = sorted(day_data[day_num], key=lambda x: x.get('timeOrder', '00:00'))
                
                cell_frame = tk.Frame(table_frame, bg=row_bg, relief='ridge', bd=1)
                cell_frame.grid(row=row_num, column=col, sticky='nsew')
                
                if day_windows:
                    for sched in day_windows:
                        window_text, dtype = format_window(sched)
                        
                        # Цвет фона в зависимости от типа
                        if dtype == 'self':
                            window_bg = '#e3f2fd'
                        else:
                            window_bg = '#fff3e0'
                        
                        tk.Label(cell_frame, text=window_text, font=("Segoe UI", 9), 
                                bg=window_bg, padx=4, pady=2, anchor='w').pack(fill='x', padx=2, pady=1)
                else:
                    tk.Label(cell_frame, text="—", font=("Segoe UI", 9), 
                            bg=row_bg, fg=COLORS['text_light'], padx=4, pady=5).pack()
            
            row_num += 1
        
        # Обновляем счётчик
        info_label.config(text=f"📦 Складов: {len(warehouses)} | Окон: {len(pv_schedules)}")
        
        # Обновляем размер canvas
        table_frame.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox('all'))
    
    # Привязка выбора ПВ
    pv_combo.bind('<<ComboboxSelected>>', update_table)
    
    # Размещение
    canvas.pack(side='left', fill='both', expand=True)
    scrollbar_v.pack(side='right', fill='y')
    scrollbar_h.pack(side='bottom', fill='x')
    
    # Статистика внизу
    stats_frame = tk.Frame(win, bg='#eceff1')
    stats_frame.pack(fill='x')
    
    tk.Label(stats_frame, 
            text="🚗 self = поставщик возит | 📦 courier = наш курьер | Формат: Заказ до → Доставят к",
            font=("Segoe UI", 9), bg='#eceff1', fg=COLORS['text']).pack(pady=8)
    
    # Инициализация таблицы
    update_table()
    
    # Очистка при закрытии
    def on_close():
        canvas.unbind_all('<MouseWheel>')
        canvas.unbind_all('<Button-4>')
        canvas.unbind_all('<Button-5>')
        win.destroy()
    
    win.protocol('WM_DELETE_WINDOW', on_close)


tk.Button(btn_analysis_frame, text="📋 Расписание", command=show_all_schedules, bg='#00796b', fg='white',
          font=("Segoe UI", 9), width=11).pack(side='left', padx=3, pady=5)

# Прогресс и статус
progress_frame = tk.Frame(control_frame, bg=COLORS['bg'])
progress_frame.pack(side='right', padx=10)

progress_bar = ttk.Progressbar(progress_frame, mode='indeterminate', length=150)
progress_bar.pack(side='top', pady=2)

status_label = tk.Label(progress_frame, text="Ожидание данных...", font=("Segoe UI", 9), 
                       bg=COLORS['bg'], fg=COLORS['text_light'])
status_label.pack(side='top')

# === NOTEBOOK ===
notebook = ttk.Notebook(root)
notebook.pack(fill='both', expand=True, padx=15, pady=10)

# --- Вкладка 1: Статистика ---
frame_stats = ttk.Frame(notebook)
notebook.add(frame_stats, text="📊 Статистика поставщиков")

stats_header = tk.Frame(frame_stats, bg=COLORS['bg'])
stats_header.pack(fill='x', padx=10, pady=5)

tk.Label(stats_header, text="💡 Двойной клик — подробный анализ поставщика", 
        font=("Segoe UI", 9), bg=COLORS['bg'], fg=COLORS['text_light']).pack(side='left')
lbl_stats_count = tk.Label(stats_header, text="Поставщиков: 0", font=("Segoe UI", 9, "bold"), 
                          bg=COLORS['bg'], fg=COLORS['primary'])
lbl_stats_count.pack(side='right')

# Frame для таблицы с прокруткой
table_frame_stats = tk.Frame(frame_stats, bg=COLORS['bg'])
table_frame_stats.pack(fill='both', expand=True, padx=10, pady=5)

cols_stats = ('Поставщик', 'Склад', 'ПВ', 'Заказов', 'Ср. откл.', 'Медиана', 'Ст. откл.', '% вовремя')
tree_stats = SortableTreeview(table_frame_stats, columns=cols_stats, show='headings', height=22)
tree_stats.column('Поставщик', width=200)
tree_stats.column('Склад', width=180)
tree_stats.column('ПВ', width=200)
tree_stats.column('Заказов', width=80)
tree_stats.column('Ср. откл.', width=80)
tree_stats.column('Медиана', width=80)
tree_stats.column('Ст. откл.', width=80)
tree_stats.column('% вовремя', width=90)

tree_stats.tag_configure('good', foreground=COLORS['success'])
tree_stats.tag_configure('medium', foreground=COLORS['warning'])
tree_stats.tag_configure('bad', foreground=COLORS['danger'])

tree_stats.bind('<Double-1>', on_stats_double_click)
add_tooltips_to_treeview(tree_stats, cols_stats)

# Прокрутка для таблицы tree_stats
scrollbar_stats_v = ttk.Scrollbar(table_frame_stats, orient='vertical', command=tree_stats.yview)
scrollbar_stats_h = ttk.Scrollbar(table_frame_stats, orient='horizontal', command=tree_stats.xview)
tree_stats.configure(yscrollcommand=scrollbar_stats_v.set, xscrollcommand=scrollbar_stats_h.set)

# Размещение через grid
tree_stats.grid(row=0, column=0, sticky='nsew')
scrollbar_stats_v.grid(row=0, column=1, sticky='ns')
scrollbar_stats_h.grid(row=1, column=0, sticky='ew')
table_frame_stats.grid_rowconfigure(0, weight=1)
table_frame_stats.grid_columnconfigure(0, weight=1)

# --- Вкладка 2: Рекомендации по расписанию ---
frame_rec = ttk.Frame(notebook)
notebook.add(frame_rec, text="📋 Корректировки расписания")

rec_info = tk.Frame(frame_rec, bg='#e3f2fd')
rec_info.pack(fill='x', padx=10, pady=10)

tk.Label(rec_info, text="📋 Рекомендации по корректировке длительности доставки на основе расписания.\n"
        "Показывает, на сколько нужно изменить длительность в каждом окне. Двойной клик — подробности.",
        font=("Segoe UI", 9), bg='#e3f2fd', fg=COLORS['text'], justify='left').pack(padx=10, pady=8)

rec_header = tk.Frame(frame_rec, bg=COLORS['bg'])
rec_header.pack(fill='x', padx=10)
lbl_rec_count = tk.Label(rec_header, text="Рекомендаций: 0", font=("Segoe UI", 9, "bold"),
                        bg=COLORS['bg'], fg=COLORS['primary'])
lbl_rec_count.pack(side='right')

# Frame для таблицы с прокруткой
table_frame_rec = tk.Frame(frame_rec, bg=COLORS['bg'])
table_frame_rec.pack(fill='both', expand=True, padx=10, pady=5)

cols_rec = ('Поставщик', 'Склад', 'ПВ', 'День', 'Заказ до', 'Доставят к', 'Рекоменд.', 'Корректир.', 'Уверен.', '% вовр.')
tree_rec = SortableTreeview(table_frame_rec, columns=cols_rec, show='headings', height=20)
tree_rec.column('Поставщик', width=160)
tree_rec.column('Склад', width=140)
tree_rec.column('ПВ', width=180)
tree_rec.column('День', width=50)
tree_rec.column('Заказ до', width=70)
tree_rec.column('Доставят к', width=80)
tree_rec.column('Рекоменд.', width=80)
tree_rec.column('Корректир.', width=90)
tree_rec.column('Уверен.', width=70)
tree_rec.column('% вовр.', width=70)

tree_rec.tag_configure('high', background='#c8e6c9')
tree_rec.tag_configure('med', background='#fff9c4')
tree_rec.tag_configure('low', background='#ffecb3')

tree_rec.bind('<Double-1>', on_rec_double_click)
add_tooltips_to_treeview(tree_rec, cols_rec)

# Прокрутка для таблицы tree_rec
scrollbar_rec_v = ttk.Scrollbar(table_frame_rec, orient='vertical', command=tree_rec.yview)
scrollbar_rec_h = ttk.Scrollbar(table_frame_rec, orient='horizontal', command=tree_rec.xview)
tree_rec.configure(yscrollcommand=scrollbar_rec_v.set, xscrollcommand=scrollbar_rec_h.set)

# Размещение через grid
tree_rec.grid(row=0, column=0, sticky='nsew')
scrollbar_rec_v.grid(row=0, column=1, sticky='ns')
scrollbar_rec_h.grid(row=1, column=0, sticky='ew')
table_frame_rec.grid_rowconfigure(0, weight=1)
table_frame_rec.grid_columnconfigure(0, weight=1)

# --- Вкладка 3: Расписание по дням недели (сетка) ---
frame_weekday_stats = ttk.Frame(notebook)
notebook.add(frame_weekday_stats, text="📅 По дням недели")

weekday_info = tk.Frame(frame_weekday_stats, bg='#e8f5e9')
weekday_info.pack(fill='x', padx=10, pady=5)

tk.Label(weekday_info, text="📅 Расписание с фактическими отклонениями. Красные окна требуют корректировки.\n"
        "Клик на окно — детали рекомендации. Выберите поставщика для фильтрации.",
        font=("Segoe UI", 9), bg='#e8f5e9', fg=COLORS['text'], justify='left').pack(padx=10, pady=5)

# Панель управления
weekday_control_frame = tk.Frame(frame_weekday_stats, bg=COLORS['bg'])
weekday_control_frame.pack(fill='x', padx=10, pady=5)

tk.Label(weekday_control_frame, text="Поставщик:", font=("Segoe UI", 10),
        bg=COLORS['bg']).pack(side='left', padx=5)

weekday_supplier_var = tk.StringVar(value="Все поставщики")
weekday_supplier_combo = ttk.Combobox(weekday_control_frame, textvariable=weekday_supplier_var, 
                                      width=50, state='readonly')
weekday_supplier_combo.pack(side='left', padx=5)

lbl_weekday_count = tk.Label(weekday_control_frame, text="", font=("Segoe UI", 9, "bold"),
                            bg=COLORS['bg'], fg=COLORS['success'])
lbl_weekday_count.pack(side='right', padx=10)

# Контейнер для сетки с прокруткой
weekday_grid_container = tk.Frame(frame_weekday_stats, bg=COLORS['bg'])
weekday_grid_container.pack(fill='both', expand=True, padx=10, pady=5)

weekday_canvas = tk.Canvas(weekday_grid_container, bg=COLORS['bg'], highlightthickness=0)
weekday_scrollbar_v = ttk.Scrollbar(weekday_grid_container, orient='vertical', command=weekday_canvas.yview)
weekday_scrollbar_h = ttk.Scrollbar(weekday_grid_container, orient='horizontal', command=weekday_canvas.xview)

weekday_grid_frame = tk.Frame(weekday_canvas, bg=COLORS['bg'])
weekday_canvas.create_window((0, 0), window=weekday_grid_frame, anchor='nw')
weekday_canvas.configure(yscrollcommand=weekday_scrollbar_v.set, xscrollcommand=weekday_scrollbar_h.set)

def on_weekday_grid_configure(event):
    weekday_canvas.configure(scrollregion=weekday_canvas.bbox('all'))
weekday_grid_frame.bind('<Configure>', on_weekday_grid_configure)

def on_weekday_mousewheel(event):
    weekday_canvas.yview_scroll(int(-1*(event.delta/120)), 'units')
weekday_canvas.bind('<MouseWheel>', on_weekday_mousewheel)
weekday_canvas.bind('<Button-4>', lambda e: weekday_canvas.yview_scroll(-1, 'units'))
weekday_canvas.bind('<Button-5>', lambda e: weekday_canvas.yview_scroll(1, 'units'))

weekday_canvas.pack(side='left', fill='both', expand=True)
weekday_scrollbar_v.pack(side='right', fill='y')
weekday_scrollbar_h.pack(side='bottom', fill='x')


def show_weekday_window_details(supplier, warehouse, pv, day_name, window_info):
    """Показать детали окна с рекомендацией"""
    detail_win = tk.Toplevel(root)
    detail_win.title(f"📊 Детали окна расписания")
    detail_win.geometry("550x500")
    detail_win.configure(bg=COLORS['bg'])
    
    # Заголовок с цветом в зависимости от статуса
    needs_correction = window_info.get('needs_correction', False)
    shift = window_info.get('shift', 0)
    
    if needs_correction and abs(shift) > 30:
        header_color = COLORS['danger']
    elif needs_correction:
        header_color = COLORS['warning']
    else:
        header_color = COLORS['success']
    
    header = tk.Frame(detail_win, bg=header_color)
    header.pack(fill='x')
    tk.Label(header, text=f"📊 {day_name}", 
            font=("Segoe UI", 14, "bold"), bg=header_color, fg='white').pack(pady=5)
    tk.Label(header, text=f"{supplier} → {warehouse} → {pv[:40] if len(pv) > 40 else pv}", 
            font=("Segoe UI", 10), bg=header_color, fg='white').pack(pady=(0, 10))
    
    # Информация об окне
    info_frame = tk.LabelFrame(detail_win, text="📋 Данные окна", font=("Segoe UI", 10, "bold"), bg=COLORS['bg'])
    info_frame.pack(fill='x', padx=15, pady=10)
    
    params = [
        ("Заказ до:", window_info.get('time_order', '—')),
        ("Доставят к (план):", window_info.get('deliver_by', '—')),
        ("Тип доставки:", '🚗 self' if window_info.get('type') == 'self' else '📦 courier'),
        ("", ""),
        ("Заказов в выборке:", f"{window_info.get('orders_count', 0)}"),
        ("Медиана отклонений:", f"{window_info.get('median_dev', 0):+.0f} мин"),
        ("% вовремя:", f"{window_info.get('on_time_pct', 0):.0f}%"),
    ]
    
    for i, (label, value) in enumerate(params):
        if label == "":
            ttk.Separator(info_frame, orient='horizontal').grid(row=i, column=0, columnspan=2, sticky='ew', pady=5)
        else:
            tk.Label(info_frame, text=label, font=("Segoe UI", 10), bg=COLORS['bg']).grid(row=i, column=0, sticky='e', padx=5, pady=2)
            tk.Label(info_frame, text=value, font=("Segoe UI", 10, "bold"), bg=COLORS['bg']).grid(row=i, column=1, sticky='w', padx=5, pady=2)
    
    # Рекомендация
    if needs_correction:
        rec_frame = tk.LabelFrame(detail_win, text="💡 Рекомендация по корректировке", 
                                 font=("Segoe UI", 10, "bold"), bg=COLORS['bg'])
        rec_frame.pack(fill='x', padx=15, pady=10)
        
        new_deliver = window_info.get('recommended_deliver', '—')
        
        rec_text = f"Требуется корректировка длительности доставки на {shift:+d} мин.\n\n"
        rec_text += f"Текущее 'Доставят к': {window_info.get('deliver_by', '—')}\n"
        rec_text += f"Рекомендуемое 'Доставят к': {new_deliver}\n\n"
        
        if shift > 0:
            rec_text += f"📌 Причина: систематические опоздания\n"
            rec_text += f"   Медиана отклонений: {window_info.get('median_dev', 0):+.0f} мин"
        else:
            rec_text += f"📌 Причина: систематический ранний привоз\n"
            rec_text += f"   Медиана отклонений: {window_info.get('median_dev', 0):+.0f} мин"
        
        tk.Label(rec_frame, text=rec_text, font=("Segoe UI", 10), bg=COLORS['bg'],
                justify='left', wraplength=480).pack(padx=10, pady=10)
        
        # Кнопка для просмотра заказов
        btn_frame = tk.Frame(detail_win, bg=COLORS['bg'])
        btn_frame.pack(fill='x', padx=15, pady=5)
        
        def show_orders():
            if df_current is not None:
                show_orders_for_schedule_window(supplier, warehouse, pv, day_name, 
                                               window_info.get('time_order', ''), df_current)
        
        tk.Button(btn_frame, text="📋 Показать заказы этого окна", command=show_orders,
                 font=("Segoe UI", 10), bg=COLORS['info'], fg='white', cursor='hand2').pack(pady=5)
    else:
        ok_frame = tk.Frame(detail_win, bg='#c8e6c9')
        ok_frame.pack(fill='x', padx=15, pady=10)
        tk.Label(ok_frame, text="✅ Окно работает корректно, корректировка не требуется",
                font=("Segoe UI", 10), bg='#c8e6c9', fg=COLORS['success']).pack(pady=15)


def update_weekday_stats_display():
    """Обновление сетки расписания по дням недели"""
    global schedule_recommendations
    
    if df_current is None:
        return
    
    if not schedules_cache:
        lbl_weekday_count.config(text="⚠️ Расписание не загружено. Нажмите 'Загрузить расписание'")
        return
    
    # Очищаем сетку
    for widget in weekday_grid_frame.winfo_children():
        widget.destroy()
    
    # Получаем выбранного поставщика
    selected_supplier = weekday_supplier_var.get()
    
    # Требуем выбора конкретного поставщика
    if not selected_supplier or selected_supplier == "Все поставщики":
        # Показываем сообщение вместо загрузки всех данных
        msg_frame = tk.Frame(weekday_grid_frame, bg='#fff3e0')
        msg_frame.grid(row=0, column=0, sticky='nsew', padx=20, pady=20)
        tk.Label(msg_frame, text="👆 Выберите поставщика из списка выше для отображения расписания.\n\n"
                "Отображение всех поставщиков одновременно отключено для производительности.",
                font=("Segoe UI", 11), bg='#fff3e0', fg=COLORS['text'], justify='center',
                wraplength=500).pack(padx=30, pady=30)
        lbl_weekday_count.config(text=f"📋 Поставщиков в списке: {len(weekday_supplier_combo['values']) - 1}")
        return
    
    # Фильтруем данные
    df_temp = df_current.copy()
    if 'День_недели' not in df_temp.columns:
        df_temp['День_недели'] = df_temp['Время заказа позиции'].apply(get_weekday_name)
    if 'Час' not in df_temp.columns:
        df_temp['Час'] = df_temp['Время заказа позиции'].dt.hour
    if 'Минута' not in df_temp.columns:
        df_temp['Минута'] = df_temp['Время заказа позиции'].dt.minute
    
    # Фильтруем по выбранному поставщику
    parts = selected_supplier.split(" — ")
    if len(parts) >= 2:
        supplier_name = parts[0]
        warehouse_name = parts[1]
        df_temp = df_temp[(df_temp['Поставщик'] == supplier_name) & (df_temp['Склад'] == warehouse_name)]
    
    if df_temp.empty:
        lbl_weekday_count.config(text="⚠️ Нет данных для отображения")
        return
    
    # Получаем список уникальных комбинаций Поставщик-Склад-ПВ
    combos = df_temp.groupby(['Поставщик', 'Склад', 'ПВ']).size().reset_index()[['Поставщик', 'Склад', 'ПВ']]
    combos = combos.sort_values(['Поставщик', 'Склад', 'ПВ'])
    
    # Создаем словарь рекомендаций для быстрого поиска
    rec_dict = {}
    if schedule_recommendations:
        for rec in schedule_recommendations:
            key = (rec.supplier, rec.warehouse, rec.pv, rec.weekday_num, rec.time_order)
            rec_dict[key] = rec
    
    # Заголовок таблицы
    header_bg = '#1a237e'
    header_fg = 'white'
    
    tk.Label(weekday_grid_frame, text="Поставщик / Склад / ПВ", font=("Segoe UI", 9, "bold"), 
            bg=header_bg, fg=header_fg, width=40, anchor='w', padx=10, pady=8,
            relief='ridge').grid(row=0, column=0, sticky='nsew')
    
    for col, day in enumerate(DAYS_SHORT, 1):
        tk.Label(weekday_grid_frame, text=day, font=("Segoe UI", 9, "bold"), 
                bg=header_bg, fg=header_fg, width=16, padx=5, pady=8,
                relief='ridge').grid(row=0, column=col, sticky='nsew')
    
    # Заполняем данные (ограничение 100 строк для производительности)
    MAX_ROWS = 100
    row_num = 1
    problems_count = 0
    total_combos = len(combos)
    
    for _, combo_row in combos.iterrows():
        if row_num > MAX_ROWS:
            # Показываем предупреждение об ограничении
            warn_frame = tk.Frame(weekday_grid_frame, bg='#fff9c4')
            warn_frame.grid(row=row_num, column=0, columnspan=8, sticky='nsew', pady=5)
            tk.Label(warn_frame, text=f"⚠️ Показано {MAX_ROWS} из {total_combos} ПВ. Используйте поиск в других вкладках для полного списка.",
                    font=("Segoe UI", 9), bg='#fff9c4', fg=COLORS['warning']).pack(pady=5)
            break
            
        supplier = combo_row['Поставщик']
        warehouse = combo_row['Склад']
        pv = combo_row['ПВ']
        
        row_bg = '#ffffff' if row_num % 2 == 1 else '#f5f5f5'
        
        # Ячейка с названием комбинации
        combo_text = f"{supplier[:15]}.. / {warehouse[:15]}.. / {normalize_pv_value(pv)[:25]}"
        tk.Label(weekday_grid_frame, text=combo_text, font=("Segoe UI", 8), 
                bg=row_bg, anchor='w', padx=5, pady=3, relief='ridge',
                wraplength=280).grid(row=row_num, column=0, sticky='nsew')
        
        # Находим расписание для этого ПВ и склада
        pv_schedules = get_schedules_for_warehouse_pv(warehouse, pv)
        
        # Данные для этой комбинации
        combo_data = df_temp[(df_temp['Поставщик'] == supplier) & 
                            (df_temp['Склад'] == warehouse) & 
                            (df_temp['ПВ'] == pv)]
        
        # Ячейки по дням
        for col, (day_num, day_name) in enumerate(zip(range(7), DAYS_RU), 1):
            day_data = combo_data[combo_data['День_недели'] == day_name]
            
            cell_frame = tk.Frame(weekday_grid_frame, bg=row_bg, relief='ridge', bd=1)
            cell_frame.grid(row=row_num, column=col, sticky='nsew')
            
            # Ищем окна расписания для этого дня
            day_schedules = [s for s in pv_schedules if s.get('weekday') == day_num + 1]
            day_schedules.sort(key=lambda x: x.get('timeOrder', '00:00'))
            
            if day_schedules:
                for sched in day_schedules:
                    time_order = sched.get('timeOrder', '')
                    duration = sched.get('deliveryDuration', 0)
                    dtype = sched.get('type', 'self')
                    deliver_by = calculate_expected_delivery(time_order, duration)
                    
                    # Фильтруем данные для этого окна
                    try:
                        order_hour = int(time_order.split(':')[0])
                        order_minute = int(time_order.split(':')[1]) if ':' in time_order else 0
                    except:
                        order_hour = 12
                        order_minute = 0
                    
                    window_mask = (day_data['Час'] <= order_hour) & (day_data['Час'] >= max(0, order_hour - 4))
                    window_data = day_data[window_mask]
                    
                    orders_count = len(window_data)
                    median_dev = 0
                    on_time_pct = 0
                    needs_correction = False
                    shift = 0
                    
                    # Проверяем есть ли рекомендация для этого окна
                    rec_key = (supplier, warehouse, pv, day_num + 1, time_order)
                    rec = rec_dict.get(rec_key)
                    
                    if rec:
                        needs_correction = True
                        shift = rec.shift
                        median_dev = rec.median_deviation
                        on_time_pct = rec.on_time_percent
                        problems_count += 1
                    elif orders_count > 0:
                        deviations = window_data['Разница во времени привоза (мин.)'].dropna()
                        if len(deviations) > 0:
                            median_dev = deviations.median()
                            on_time_pct = (deviations.between(-30, 30).sum() / len(deviations)) * 100
                            
                            if abs(median_dev) > 30 or on_time_pct < 60:
                                needs_correction = True
                                shift = int(round(median_dev))
                                problems_count += 1
                    
                    # Определяем цвет фона
                    if needs_correction and abs(shift) > 30:
                        window_bg = '#ffcdd2'  # Красный
                        status = 'bad'
                    elif needs_correction:
                        window_bg = '#fff9c4'  # Желтый
                        status = 'warning'
                    elif dtype == 'self':
                        window_bg = '#e3f2fd'  # Голубой
                        status = 'ok'
                    else:
                        window_bg = '#fff3e0'  # Оранжевый (courier)
                        status = 'ok'
                    
                    icon = '🚗' if dtype == 'self' else '📦'
                    
                    # Текст окна
                    if orders_count > 0:
                        window_text = f"{time_order}→{deliver_by}\n{median_dev:+.0f}м ({orders_count})"
                    else:
                        window_text = f"{time_order}→{deliver_by}\n(нет данных)"
                    
                    # Информация для детального просмотра
                    window_info = {
                        'time_order': time_order,
                        'deliver_by': deliver_by,
                        'type': dtype,
                        'orders_count': orders_count,
                        'median_dev': median_dev,
                        'on_time_pct': on_time_pct,
                        'needs_correction': needs_correction,
                        'shift': shift,
                        'recommended_deliver': calculate_expected_delivery(time_order, duration + shift) if needs_correction else deliver_by,
                        'status': status
                    }
                    
                    window_label = tk.Label(cell_frame, text=window_text, font=("Segoe UI", 7), 
                                           bg=window_bg, padx=2, pady=2, cursor='hand2',
                                           relief='raised' if needs_correction else 'flat')
                    window_label.pack(fill='x', padx=1, pady=1)
                    
                    # Привязка клика
                    window_label.bind('<Button-1>', lambda e, s=supplier, w=warehouse, p=pv, 
                                     d=day_name, wi=window_info: show_weekday_window_details(s, w, p, d, wi))
            
            elif len(day_data) > 0:
                # Есть данные но нет расписания
                deviations = day_data['Разница во времени привоза (мин.)'].dropna()
                median_dev = deviations.median() if len(deviations) > 0 else 0
                
                info_text = f"{len(day_data)} зак.\n{median_dev:+.0f}м"
                tk.Label(cell_frame, text=info_text, font=("Segoe UI", 7), 
                        bg='#eeeeee', fg=COLORS['text_light'], padx=2, pady=2).pack(fill='x')
            else:
                tk.Label(cell_frame, text="—", font=("Segoe UI", 8), 
                        bg=row_bg, fg=COLORS['text_light'], pady=5).pack()
        
        row_num += 1
    
    # Обновляем счетчик
    if problems_count > 0:
        lbl_weekday_count.config(text=f"⚠️ Окон требующих корректировки: {problems_count}", fg=COLORS['danger'])
    else:
        lbl_weekday_count.config(text=f"✅ Все окна работают корректно", fg=COLORS['success'])


def update_weekday_supplier_list():
    """Обновление списка поставщиков для фильтра"""
    if df_current is None:
        return
    
    # Получаем уникальные комбинации Поставщик-Склад
    combos = df_current.groupby(['Поставщик', 'Склад']).size().reset_index()[['Поставщик', 'Склад']]
    combos_list = ["Все поставщики"] + [f"{row['Поставщик']} — {row['Склад']}" for _, row in combos.iterrows()]
    
    weekday_supplier_combo['values'] = combos_list
    if weekday_supplier_var.get() not in combos_list:
        weekday_supplier_var.set("Все поставщики")


# Привязка обновления при выборе поставщика
weekday_supplier_combo.bind('<<ComboboxSelected>>', lambda e: update_weekday_stats_display())


# --- Вкладка 4: Сырые данные ---
frame_raw = ttk.Frame(notebook)
notebook.add(frame_raw, text="📄 Сырые данные")

raw_info = tk.Frame(frame_raw, bg='#fff3e0')
raw_info.pack(fill='x', padx=10, pady=10)

tk.Label(raw_info, text="📄 Исходные данные после импорта из CRM.\n"
        "Двойной клик на заказ — открыть в CRM. Кликните на заголовок столбца для сортировки.",
        font=("Segoe UI", 9), bg='#fff3e0', fg=COLORS['text'], justify='left').pack(padx=10, pady=8)

raw_header = tk.Frame(frame_raw, bg=COLORS['bg'])
raw_header.pack(fill='x', padx=10)
lbl_raw_count = tk.Label(raw_header, text="Записей: 0", font=("Segoe UI", 9, "bold"),
                        bg=COLORS['bg'], fg=COLORS['warning'])
lbl_raw_count.pack(side='right')

# Frame для таблицы с прокрутками
tree_frame_raw = tk.Frame(frame_raw, bg=COLORS['bg'])
tree_frame_raw.pack(fill='both', expand=True, padx=10, pady=5)

cols_raw = ('№ заказа', 'Поставщик', 'Склад', 'ПВ', 'Бренд', 'Артикул', 'Дата заказа', 'План привоза', 'Факт привоза', 'Откл. (мин)')
tree_raw = SortableTreeview(tree_frame_raw, columns=cols_raw, show='headings', height=20)
tree_raw.column('№ заказа', width=90)
tree_raw.column('Поставщик', width=150)
tree_raw.column('Склад', width=120)
tree_raw.column('ПВ', width=200)
tree_raw.column('Бренд', width=120)
tree_raw.column('Артикул', width=100)
tree_raw.column('Дата заказа', width=130)
tree_raw.column('План привоза', width=130)
tree_raw.column('Факт привоза', width=130)
tree_raw.column('Откл. (мин)', width=90)

tree_raw.tag_configure('good', foreground=COLORS['success'])
tree_raw.tag_configure('medium', foreground=COLORS['warning'])
tree_raw.tag_configure('bad', foreground=COLORS['danger'])

def on_raw_double_click(event):
    """Открыть заказ в CRM при двойном клике"""
    selected = tree_raw.selection()
    if selected:
        order_id = tree_raw.item(selected[0])['values'][0]
        open_order_in_crm(order_id)

tree_raw.bind('<Double-1>', on_raw_double_click)
add_tooltips_to_treeview(tree_raw, cols_raw)

# Вертикальная и горизонтальная прокрутка
scrollbar_raw_v = ttk.Scrollbar(tree_frame_raw, orient='vertical', command=tree_raw.yview)
scrollbar_raw_h = ttk.Scrollbar(tree_frame_raw, orient='horizontal', command=tree_raw.xview)
tree_raw.configure(yscrollcommand=scrollbar_raw_v.set, xscrollcommand=scrollbar_raw_h.set)

# Размещаем таблицу и прокрутки через grid
tree_raw.grid(row=0, column=0, sticky='nsew')
scrollbar_raw_v.grid(row=0, column=1, sticky='ns')
scrollbar_raw_h.grid(row=1, column=0, sticky='ew')
tree_frame_raw.grid_rowconfigure(0, weight=1)
tree_frame_raw.grid_columnconfigure(0, weight=1)

# === FOOTER ===
footer = tk.Frame(root, bg='#eceff1')
footer.pack(fill='x')

tk.Label(footer, text="🤖 Признаки: Поставщик×Склад×ПВ, день недели, час, скользящие средние, тренды | Рекомендации: на основе расписания и медианы отклонений",
        font=("Segoe UI", 8), bg='#eceff1', fg=COLORS['text_light']).pack(pady=5)

# === АВТОЗАГРУЗКА РАСПИСАНИЯ ПРИ ЗАПУСКЕ ===
def auto_load_schedules():
    """Автозагрузка расписания при запуске приложения"""
    global schedules_cache
    
    def load():
        try:
            schedules = fetch_schedules()
            if schedules:
                root.after(0, lambda: update_status(f"📋 Расписание загружено: {len(schedules)} окон", "success"))
            else:
                root.after(0, lambda: update_status("⚠️ Расписание недоступно", "warning"))
        except Exception as e:
            print(f"Ошибка автозагрузки расписания: {e}")
    
    # Запускаем в отдельном потоке через 500мс после старта
    root.after(500, lambda: threading.Thread(target=load, daemon=True).start())

# Автозагрузка расписания
auto_load_schedules()

root.mainloop()
