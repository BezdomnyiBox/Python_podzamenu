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
# КОНСТАНТЫ
# ========================================
CRM_BASE_URL = "https://crm.podzamenu.ru"
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
is_model_trained = False
current_pv_filter = None  # Текущий фильтр по ПВ

# Переменные сортировки для таблиц
sort_states = {}


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
    """Порционная загрузка данных с сервера"""
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
        )
        
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            
            if b'<html' in response.content[:500]:
                current_start = current_end + timedelta(days=1)
                continue
            
            excel_file = BytesIO(response.content)
            df_chunk = pd.read_excel(excel_file, engine='openpyxl')
            
            if df_chunk.shape[1] >= 11 and len(df_chunk) > 0:
                all_data.append(df_chunk)
            
        except Exception as e:
            print(f"Ошибка: {e}")
        
        current_start = current_end + timedelta(days=1)
        time.sleep(0.3)
    
    root.after(0, progress_bar.stop)
    
    if not all_data:
        return None
    
    df = pd.concat(all_data, ignore_index=True)
    
    df.columns = [
        '№ заказа', 'URL', 'Поставщик', 'Склад', 'ПВ', 'Бренд', 'Артикул',
        'Рассчетное время привоза', 'Время поступления на склад', 'Время заказа позиции',
        'Разница во времени привоза (мин.)'
    ]
    
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
    """Асинхронное обучение модели"""
    def train():
        global ml_predictor, is_model_trained, recommendations
        
        root.after(0, lambda: update_status("🤖 Обучение ML модели...", "info"))
        root.after(0, progress_bar.start)
        
        try:
            ml_predictor = DeliveryMLPredictor()
            ml_predictor.fit(df_current)
            
            recommendations = ml_predictor.generate_recommendations(df_current, min_samples=5, min_shift=15)
            is_model_trained = True
            
            root.after(0, progress_bar.stop)
            root.after(0, update_recommendations_display)
            root.after(0, lambda: update_status(
                f"✅ Модель обучена | Рекомендаций: {len(recommendations)}", "success"))
            
        except Exception as e:
            root.after(0, progress_bar.stop)
            root.after(0, lambda: update_status(f"⚠️ Ошибка ML: {str(e)[:40]}", "warning"))
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
    """Обновление таблицы рекомендаций"""
    for item in tree_rec.get_children():
        tree_rec.delete(item)
    
    if not recommendations:
        lbl_rec_count.config(text="Рекомендаций: 0")
        return
    
    for rec in recommendations:
        if rec.confidence >= 0.8:
            tags = ('high',)
        elif rec.confidence >= 0.6:
            tags = ('med',)
        else:
            tags = ('low',)
        
        shift_str = f"{rec.shift_minutes:+d} мин"
        
        # Перевод тренда
        trend_ru = {
            'stable': '✓ Стабильно',
            'delay': '⬆ Опоздания',
            'early': '⬇ Ранние',
            'shift': '⚡ Сдвиг',
            'seasonal': '🔄 Сезонный'
        }.get(rec.trend_detected, rec.trend_detected)
        
        tree_rec.insert('', 'end', values=(
            rec.supplier,
            rec.warehouse,
            normalize_pv_value(rec.pv),
            rec.weekday[:2],
            f"{rec.order_time_start[:2]}:00",
            shift_str,
            f"{rec.confidence*100:.0f}%",
            trend_ru,
            rec.effective_from
        ), tags=tags)
    
    # Подсчитываем уникальные ПВ в рекомендациях
    unique_pv_in_rec = len(set(r.pv for r in recommendations))
    lbl_rec_count.config(text=f"Рекомендаций: {len(recommendations)} | ПВ: {unique_pv_in_rec}")


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


def on_rec_double_click(event):
    """Двойной клик по рекомендации - показать детали"""
    selected = tree_rec.selection()
    if not selected:
        return
    
    values = tree_rec.item(selected[0])['values']
    supplier = values[0]
    warehouse = values[1]
    pv = values[2]
    weekday = values[3]
    
    # Находим полную рекомендацию
    for rec in recommendations:
        if (
            rec.supplier == supplier and
            rec.warehouse == warehouse and
            normalize_pv_value(rec.pv) == pv and
            rec.weekday.startswith(weekday)
        ):
            show_recommendation_details(rec)
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
    
    # === Вкладка 2: По дням недели ===
    frame_weekday = ttk.Frame(notebook)
    notebook.add(frame_weekday, text="📅 По дням")
    
    # Frame для таблицы с прокруткой
    table_frame_wd = tk.Frame(frame_weekday, bg=COLORS['bg'])
    table_frame_wd.pack(fill='both', expand=True, padx=10, pady=10)
    
    cols_wd = ('День', 'Заказов', 'Среднее откл.', 'Медиана', 'Ст. откл.', '% вовремя')
    tree_wd = SortableTreeview(table_frame_wd, columns=cols_wd, show='headings', height=12)
    for col in cols_wd:
        tree_wd.column(col, width=100)
    
    for day_idx, day in enumerate(DAYS_RU):
        day_data = subset[subset['День_недели'] == day]
        if len(day_data) < 1:
            continue
        
        mean_dev = day_data['Разница во времени привоза (мин.)'].mean()
        median_dev = day_data['Разница во времени привоза (мин.)'].median()
        std_dev = day_data['Разница во времени привоза (мин.)'].std()
        on_time = (day_data['Разница во времени привоза (мин.)'].between(-30, 30).sum() / len(day_data)) * 100
        
        tree_wd.insert('', 'end', values=(
            day, len(day_data), f"{mean_dev:+.1f}", f"{median_dev:+.1f}", 
            f"{std_dev:.1f}", f"{on_time:.1f}%"
        ))
    
    # Прокрутка для таблицы tree_wd
    scrollbar_wd_v = ttk.Scrollbar(table_frame_wd, orient='vertical', command=tree_wd.yview)
    scrollbar_wd_h = ttk.Scrollbar(table_frame_wd, orient='horizontal', command=tree_wd.xview)
    tree_wd.configure(yscrollcommand=scrollbar_wd_v.set, xscrollcommand=scrollbar_wd_h.set)
    
    # Размещение через grid
    tree_wd.grid(row=0, column=0, sticky='nsew')
    scrollbar_wd_v.grid(row=0, column=1, sticky='ns')
    scrollbar_wd_h.grid(row=1, column=0, sticky='ew')
    table_frame_wd.grid_rowconfigure(0, weight=1)
    table_frame_wd.grid_columnconfigure(0, weight=1)
    
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
    
    # === Вкладка 4: По часам ===
    frame_hour = ttk.Frame(notebook)
    notebook.add(frame_hour, text="⏰ По часам")
    
    # Frame для таблицы с прокруткой
    table_frame_hr = tk.Frame(frame_hour, bg=COLORS['bg'])
    table_frame_hr.pack(fill='both', expand=True, padx=10, pady=10)
    
    cols_hr = ('Час', 'Заказов', 'Среднее откл.', 'Медиана', '% вовремя')
    tree_hr = SortableTreeview(table_frame_hr, columns=cols_hr, show='headings', height=15)
    for col in cols_hr:
        tree_hr.column(col, width=100)
    
    subset['Час'] = subset['Время заказа позиции'].dt.hour
    for hour in range(6, 22):
        hour_data = subset[subset['Час'] == hour]
        if len(hour_data) < 1:
            continue
        
        mean_dev = hour_data['Разница во времени привоза (мин.)'].mean()
        median_dev = hour_data['Разница во времени привоза (мин.)'].median()
        on_time = (hour_data['Разница во времени привоза (мин.)'].between(-30, 30).sum() / len(hour_data)) * 100
        
        tree_hr.insert('', 'end', values=(
            f"{hour:02d}:00", len(hour_data), f"{mean_dev:+.1f}", 
            f"{median_dev:+.1f}", f"{on_time:.1f}%"
        ))
    
    # Прокрутка для таблицы tree_hr
    scrollbar_hr_v = ttk.Scrollbar(table_frame_hr, orient='vertical', command=tree_hr.yview)
    scrollbar_hr_h = ttk.Scrollbar(table_frame_hr, orient='horizontal', command=tree_hr.xview)
    tree_hr.configure(yscrollcommand=scrollbar_hr_v.set, xscrollcommand=scrollbar_hr_h.set)
    
    # Размещение через grid
    tree_hr.grid(row=0, column=0, sticky='nsew')
    scrollbar_hr_v.grid(row=0, column=1, sticky='ns')
    scrollbar_hr_h.grid(row=1, column=0, sticky='ew')
    table_frame_hr.grid_rowconfigure(0, weight=1)
    table_frame_hr.grid_columnconfigure(0, weight=1)
    
    # Обработчики двойного клика для раскрывающихся списков
    def on_weekday_double_click(event):
        selected = tree_wd.selection()
        if not selected:
            return
        day = tree_wd.item(selected[0])['values'][0]
        show_orders_for_day(supplier, warehouse, pv_label, day, subset)
    
    def on_hour_double_click(event):
        selected = tree_hr.selection()
        if not selected:
            return
        hour_str = tree_hr.item(selected[0])['values'][0]
        hour = int(hour_str.split(':')[0])
        show_orders_for_hour(supplier, warehouse, pv_label, hour, subset)
    
    tree_wd.bind('<Double-1>', on_weekday_double_click)
    tree_hr.bind('<Double-1>', on_hour_double_click)
    
    # Подсказки
    tk.Label(frame_weekday, text="💡 Двойной клик — просмотр заказов за этот день", 
            font=("Segoe UI", 9), fg=COLORS['text_light']).pack(pady=5)
    tk.Label(frame_hour, text="💡 Двойной клик — просмотр заказов в этот час", 
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

# --- Вкладка 2: Рекомендации ---
frame_rec = ttk.Frame(notebook)
notebook.add(frame_rec, text="🤖 ML-Рекомендации")

rec_info = tk.Frame(frame_rec, bg='#e3f2fd')
rec_info.pack(fill='x', padx=10, pady=10)

tk.Label(rec_info, text="💡 Рекомендации сформированы на основе анализа трендов.\n"
        "Двойной клик — подробности. Кликните на заголовок столбца для сортировки.",
        font=("Segoe UI", 9), bg='#e3f2fd', fg=COLORS['text'], justify='left').pack(padx=10, pady=8)

rec_header = tk.Frame(frame_rec, bg=COLORS['bg'])
rec_header.pack(fill='x', padx=10)
lbl_rec_count = tk.Label(rec_header, text="Рекомендаций: 0", font=("Segoe UI", 9, "bold"),
                        bg=COLORS['bg'], fg=COLORS['primary'])
lbl_rec_count.pack(side='right')

# Frame для таблицы с прокруткой
table_frame_rec = tk.Frame(frame_rec, bg=COLORS['bg'])
table_frame_rec.pack(fill='both', expand=True, padx=10, pady=5)

cols_rec = ('Поставщик', 'Склад', 'ПВ', 'День', 'Час', 'Сдвиг', 'Уверенность', 'Тренд', 'Применить с')
tree_rec = SortableTreeview(table_frame_rec, columns=cols_rec, show='headings', height=20)
tree_rec.column('Поставщик', width=180)
tree_rec.column('Склад', width=150)
tree_rec.column('ПВ', width=200)
tree_rec.column('День', width=50)
tree_rec.column('Час', width=60)
tree_rec.column('Сдвиг', width=80)
tree_rec.column('Уверенность', width=90)
tree_rec.column('Тренд', width=110)
tree_rec.column('Применить с', width=100)

tree_rec.tag_configure('high', background='#c8e6c9')
tree_rec.tag_configure('med', background='#fff9c4')
tree_rec.tag_configure('low', background='#ffecb3')

tree_rec.bind('<Double-1>', on_rec_double_click)

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

# --- Вкладка 3: Статистика по дням недели ---
frame_weekday_stats = ttk.Frame(notebook)
notebook.add(frame_weekday_stats, text="📅 По дням недели")

weekday_info = tk.Frame(frame_weekday_stats, bg='#e8f5e9')
weekday_info.pack(fill='x', padx=10, pady=10)

tk.Label(weekday_info, text="📅 Статистика по дням недели.\n"
        "Показывает в какие дни поставщики чаще опаздывают или приезжают вовремя.",
        font=("Segoe UI", 9), bg='#e8f5e9', fg=COLORS['text'], justify='left').pack(padx=10, pady=8)

weekday_header = tk.Frame(frame_weekday_stats, bg=COLORS['bg'])
weekday_header.pack(fill='x', padx=10)
lbl_weekday_count = tk.Label(weekday_header, text="", font=("Segoe UI", 9, "bold"),
                            bg=COLORS['bg'], fg=COLORS['success'])
lbl_weekday_count.pack(side='right')

# Frame для таблицы с прокруткой
table_frame_weekday = tk.Frame(frame_weekday_stats, bg=COLORS['bg'])
table_frame_weekday.pack(fill='both', expand=True, padx=10, pady=5)

cols_weekday = ('День недели', 'Заказов', 'Уник. заказов', 'Ср. откл.', 'Медиана', 'Ст. откл.', '% вовремя', '% ранних', '% поздних', 'Худший час')
tree_weekday = SortableTreeview(table_frame_weekday, columns=cols_weekday, show='headings', height=10)
tree_weekday.column('День недели', width=120)
tree_weekday.column('Заказов', width=80)
tree_weekday.column('Уник. заказов', width=100)
tree_weekday.column('Ср. откл.', width=80)
tree_weekday.column('Медиана', width=80)
tree_weekday.column('Ст. откл.', width=80)
tree_weekday.column('% вовремя', width=90)
tree_weekday.column('% ранних', width=80)
tree_weekday.column('% поздних', width=80)
tree_weekday.column('Худший час', width=100)

tree_weekday.tag_configure('good', foreground=COLORS['success'])
tree_weekday.tag_configure('medium', foreground=COLORS['warning'])
tree_weekday.tag_configure('bad', foreground=COLORS['danger'])

# Прокрутка для таблицы tree_weekday
scrollbar_weekday_v = ttk.Scrollbar(table_frame_weekday, orient='vertical', command=tree_weekday.yview)
scrollbar_weekday_h = ttk.Scrollbar(table_frame_weekday, orient='horizontal', command=tree_weekday.xview)
tree_weekday.configure(yscrollcommand=scrollbar_weekday_v.set, xscrollcommand=scrollbar_weekday_h.set)

# Размещение через grid
tree_weekday.grid(row=0, column=0, sticky='nsew')
scrollbar_weekday_v.grid(row=0, column=1, sticky='ns')
scrollbar_weekday_h.grid(row=1, column=0, sticky='ew')
table_frame_weekday.grid_rowconfigure(0, weight=1)
table_frame_weekday.grid_columnconfigure(0, weight=1)


def update_weekday_stats_display():
    """Обновление статистики по дням недели"""
    if df_current is None:
        return
    
    for item in tree_weekday.get_children():
        tree_weekday.delete(item)
    
    # Добавляем колонку дня недели если её нет
    df_temp = df_current.copy()
    if 'День_недели' not in df_temp.columns:
        df_temp['День_недели'] = df_temp['Время заказа позиции'].apply(get_weekday_name)
    if 'Час' not in df_temp.columns:
        df_temp['Час'] = df_temp['Время заказа позиции'].dt.hour
    
    best_day = None
    best_pct = 0
    worst_day = None
    worst_pct = 100
    
    for day in DAYS_RU:
        day_data = df_temp[df_temp['День_недели'] == day]
        if len(day_data) < 1:
            continue
        
        deviations = day_data['Разница во времени привоза (мин.)'].dropna()
        if len(deviations) < 1:
            continue
        
        total = len(deviations)
        on_time = deviations.between(-30, 30).sum()
        early = (deviations < -30).sum()
        late = (deviations > 30).sum()
        
        on_time_pct = (on_time / total) * 100
        early_pct = (early / total) * 100
        late_pct = (late / total) * 100
        
        # Определяем лучший и худший день
        if on_time_pct > best_pct:
            best_pct = on_time_pct
            best_day = day
        if on_time_pct < worst_pct:
            worst_pct = on_time_pct
            worst_day = day
        
        # Находим худший час (с наибольшим средним опозданием)
        hour_stats = day_data.groupby('Час')['Разница во времени привоза (мин.)'].mean()
        worst_hour = hour_stats.idxmax() if len(hour_stats) > 0 else None
        worst_hour_val = hour_stats.max() if len(hour_stats) > 0 else 0
        worst_hour_str = f"{worst_hour:02d}:00 ({worst_hour_val:+.0f})" if worst_hour is not None else "-"
        
        # Определяем цвет строки
        tags = ()
        if on_time_pct >= 80:
            tags = ('good',)
        elif on_time_pct >= 60:
            tags = ('medium',)
        else:
            tags = ('bad',)
        
        tree_weekday.insert('', 'end', values=(
            day,
            f"{total:,}",
            f"{day_data['№ заказа'].nunique():,}",
            f"{deviations.mean():+.1f}",
            f"{deviations.median():+.1f}",
            f"{deviations.std():.1f}",
            f"{on_time_pct:.1f}%",
            f"{early_pct:.1f}%",
            f"{late_pct:.1f}%",
            worst_hour_str
        ), tags=tags)
    
    # Обновляем заголовок с лучшим и худшим днём
    summary = []
    if best_day:
        summary.append(f"✅ Лучший: {best_day} ({best_pct:.1f}%)")
    if worst_day:
        summary.append(f"❌ Худший: {worst_day} ({worst_pct:.1f}%)")
    lbl_weekday_count.config(text=" | ".join(summary))


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

tk.Label(footer, text="🤖 Алгоритм: Gradient Boosting | 📊 Признаки: день недели, час, скользящие средние, тренды",
        font=("Segoe UI", 8), bg='#eceff1', fg=COLORS['text_light']).pack(pady=5)

root.mainloop()
