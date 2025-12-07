"""
ML-модуль для анализа и предсказания времени привоза.
Использует машинное обучение для:
1. Предсказания ожидаемого времени привоза
2. Обнаружения трендов и аномалий
3. Генерации рекомендаций по корректировке графика
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

# ML библиотеки
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor, IsolationForest
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.model_selection import cross_val_score, TimeSeriesSplit
from sklearn.cluster import DBSCAN
import warnings
warnings.filterwarnings('ignore')


DEFAULT_PV_LABEL = "ПВ не указан"


class TrendType(Enum):
    """Типы трендов во времени привоза"""
    STABLE = "stable"           # Стабильный
    INCREASING_DELAY = "delay"  # Увеличивающееся опоздание
    DECREASING_DELAY = "early"  # Ранние привозы
    SEASONAL = "seasonal"       # Сезонный паттерн
    SHIFT = "shift"            # Резкий сдвиг


@dataclass
class DeliveryPrediction:
    """Результат предсказания времени привоза"""
    supplier: str
    warehouse: str
    pv: str
    weekday: str
    order_hour: int
    predicted_delivery_time: float  # Предсказанное время в минутах от планового
    confidence: float               # Уверенность модели (0-1)
    trend: TrendType               # Тип тренда
    recommendation: str            # Текстовая рекомендация
    shift_minutes: int             # Рекомендуемый сдвиг в минутах


@dataclass
class ScheduleRecommendation:
    """Рекомендация по корректировке расписания"""
    supplier: str
    warehouse: str
    pv: str
    weekday: str
    order_time_start: str          # Начало временного окна заказа (или "Заказ до")
    order_time_end: str            # Конец временного окна заказа (или "Доставят к")
    current_expected_time: str     # Текущее ожидаемое время привоза
    recommended_time: str          # Рекомендуемое время привоза
    shift_minutes: int             # Сдвиг в минутах
    confidence: float              # Уверенность в рекомендации
    reason: str                    # Причина рекомендации
    trend_detected: str            # Обнаруженный тренд
    effective_from: str            # Рекомендуемая дата начала применения
    example_orders: List[Dict] = field(default_factory=list)  # Примеры заказов
    schedule_window: Optional[Dict] = None  # Окно расписания (если найдено)


class DeliveryMLPredictor:
    """
    ML-предиктор для анализа времени привоза.
    
    Использует ансамбль моделей:
    - Random Forest для предсказания времени
    - Isolation Forest для детекции аномалий
    - Linear Regression для обнаружения трендов
    """
    
    DAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    
    def __init__(self):
        self.models: Dict[str, RandomForestRegressor] = {}
        self.scalers: Dict[str, StandardScaler] = {}
        self.label_encoders: Dict[str, LabelEncoder] = {}
        self.is_fitted = False
        self.feature_importance: Dict[str, pd.DataFrame] = {}
        self.pv_mapping: Dict[str, int] = {}
        self.default_pv_label = DEFAULT_PV_LABEL

    def _normalize_pv(self, value: Optional[Any]) -> str:
        """Единообразное представление значения ПВ"""
        if value is None or pd.isna(value):
            return self.default_pv_label
        value_str = str(value).strip()
        return value_str if value_str else self.default_pv_label

    def _encode_pv(self, df: pd.DataFrame, fit_mode: bool = False) -> pd.DataFrame:
        """Добавление числового признака для ПВ"""
        df = df.copy()
        if 'ПВ' not in df.columns:
            df['ПВ'] = self.default_pv_label
        df['ПВ'] = df['ПВ'].apply(self._normalize_pv)
        if fit_mode:
            self.pv_mapping = {}
        for pv in df['ПВ'].unique():
            if pv not in self.pv_mapping:
                self.pv_mapping[pv] = len(self.pv_mapping)
        df['pv_encoded'] = df['ПВ'].map(lambda x: self.pv_mapping.get(x, -1))
        return df
        
    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Подготовка признаков для ML-модели.
        
        Features:
        - День недели (encoded)
        - Час заказа
        - Неделя года
        - День месяца
        - Месяц
        - Является ли день выходным
        - Скользящее среднее отклонений
        - Тренд за последние N дней
        """
        df = df.copy()
        
        # Базовые временные признаки
        if 'Время заказа позиции' in df.columns:
            df['hour'] = df['Время заказа позиции'].dt.hour
            df['day_of_week'] = df['Время заказа позиции'].dt.dayofweek
            df['week_of_year'] = df['Время заказа позиции'].dt.isocalendar().week.astype(int)
            df['day_of_month'] = df['Время заказа позиции'].dt.day
            df['month'] = df['Время заказа позиции'].dt.month
            df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
            df['order_date'] = df['Время заказа позиции'].dt.date
        
        # Циклические признаки для часа и дня недели
        df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
        df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)
        df['dow_sin'] = np.sin(2 * np.pi * df['day_of_week'] / 7)
        df['dow_cos'] = np.cos(2 * np.pi * df['day_of_week'] / 7)
        
        return df
    
    def add_rolling_features(self, df: pd.DataFrame, group_cols: List[str], 
                            target_col: str = 'Разница во времени привоза (мин.)') -> pd.DataFrame:
        """Добавление скользящих признаков по группам"""
        df = df.copy()
        df = df.sort_values('Время заказа позиции')
        
        for window in [3, 7, 14]:
            col_name = f'rolling_mean_{window}'
            df[col_name] = df.groupby(group_cols)[target_col].transform(
                lambda x: x.rolling(window=window, min_periods=1).mean()
            )
            
            col_name_std = f'rolling_std_{window}'
            df[col_name_std] = df.groupby(group_cols)[target_col].transform(
                lambda x: x.rolling(window=window, min_periods=1).std().fillna(0)
            )
        
        # Тренд (разница между последними и предыдущими)
        df['trend_7d'] = df.groupby(group_cols)[target_col].transform(
            lambda x: x.rolling(window=7, min_periods=1).mean() - 
                     x.rolling(window=14, min_periods=1).mean()
        ).fillna(0)
        
        return df
    
    def fit(self, df: pd.DataFrame) -> 'DeliveryMLPredictor':
        """
        Обучение ML-модели на исторических данных.
        
        Создает отдельную модель для каждой комбинации поставщик-склад.
        """
        if df is None or df.empty:
            raise ValueError("Нет данных для обучения")
        
        # Удаляем строки с критичными NaN
        df = df.dropna(subset=['Время заказа позиции', 'Разница во времени привоза (мин.)'])
        
        if df.empty:
            raise ValueError("Нет валидных данных после очистки NaN")
        
        df = self.prepare_features(df)
        df = self._encode_pv(df, fit_mode=True)
        df = self.add_rolling_features(df, ['Поставщик', 'Склад', 'ПВ', 'day_of_week', 'hour'])
        
        # Признаки для модели
        feature_cols = [
            'hour', 'day_of_week', 'week_of_year', 'day_of_month', 'month',
            'is_weekend', 'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos',
            'rolling_mean_3', 'rolling_mean_7', 'rolling_mean_14',
            'rolling_std_3', 'rolling_std_7', 'rolling_std_14', 'trend_7d',
            'pv_encoded'
        ]
        
        target_col = 'Разница во времени привоза (мин.)'
        
        # Обучаем модель для каждого поставщика-склада-ПВ
        # Это позволяет учитывать специфику каждого ПВ при предсказании
        for (supplier, warehouse, pv), group_df in df.groupby(['Поставщик', 'Склад', 'ПВ']):
            if len(group_df) < 10:  # Минимум 10 записей для обучения
                continue
            
            key = f"{supplier}_{warehouse}_{pv}"
            
            # Удаляем строки с NaN в целевой переменной
            group_df = group_df.dropna(subset=[target_col])
            if len(group_df) < 10:
                continue
            
            X = group_df[feature_cols].fillna(0)
            y = group_df[target_col].values
            
            # Масштабирование
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
            self.scalers[key] = scaler
            
            # Обучение Random Forest
            model = GradientBoostingRegressor(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                random_state=42
            )
            model.fit(X_scaled, y)
            self.models[key] = model
            
            # Сохраняем важность признаков
            self.feature_importance[key] = pd.DataFrame({
                'feature': feature_cols,
                'importance': model.feature_importances_
            }).sort_values('importance', ascending=False)
        
        self.is_fitted = True
        return self
    
    def detect_trend(self, df: pd.DataFrame, supplier: str, warehouse: str,
                    weekday: int, hour: int, lookback_days: int = 30,
                    pv: Optional[str] = None) -> Tuple[TrendType, float]:
        """
        Обнаружение тренда во времени привоза.
        
        Использует линейную регрессию для определения направления тренда.
        """
        # Фильтруем данные
        if hour == -1:
            # Анализ по всем часам
            mask = (
                (df['Поставщик'] == supplier) &
                (df['Склад'] == warehouse) &
                (df['day_of_week'] == weekday)
            )
        else:
            mask = (
                (df['Поставщик'] == supplier) &
                (df['Склад'] == warehouse) &
                (df['day_of_week'] == weekday) &
                (df['hour'] == hour)
            )
        if pv is not None:
            mask &= (df['ПВ'] == self._normalize_pv(pv))
        
        subset = df[mask].copy()
        subset = subset.dropna(subset=['Разница во времени привоза (мин.)'])
        
        if len(subset) < 5:
            return TrendType.STABLE, 0.0
        
        # Сортируем по дате
        subset = subset.sort_values('Время заказа позиции')
        
        # Разделяем на две половины для сравнения
        mid = len(subset) // 2
        first_half = subset.iloc[:mid]['Разница во времени привоза (мин.)'].mean()
        second_half = subset.iloc[mid:]['Разница во времени привоза (мин.)'].mean()
        
        diff = second_half - first_half
        
        # Линейная регрессия для определения тренда
        X = np.arange(len(subset)).reshape(-1, 1)
        y = subset['Разница во времени привоза (мин.)'].values
        
        lr = LinearRegression()
        lr.fit(X, y)
        slope = lr.coef_[0]
        
        # Определяем тип тренда
        if abs(slope) < 1:  # Менее 1 минуты изменения за запись
            return TrendType.STABLE, slope
        elif slope > 5:
            return TrendType.INCREASING_DELAY, slope
        elif slope < -5:
            return TrendType.DECREASING_DELAY, slope
        elif abs(diff) > 30:  # Резкий сдвиг более 30 минут
            return TrendType.SHIFT, diff
        else:
            return TrendType.STABLE, slope
    
    def detect_anomalies(self, df: pd.DataFrame, contamination: float = 0.1) -> pd.DataFrame:
        """
        Обнаружение аномалий с помощью Isolation Forest.
        
        Возвращает DataFrame с флагом аномалии.
        """
        df = df.copy()
        df = self.prepare_features(df)
        
        feature_cols = ['hour', 'day_of_week', 'Разница во времени привоза (мин.)']
        X = df[feature_cols].fillna(0)
        
        iso_forest = IsolationForest(contamination=contamination, random_state=42)
        df['is_anomaly'] = iso_forest.fit_predict(X)
        df['is_anomaly'] = (df['is_anomaly'] == -1).astype(int)
        
        return df
    
    def predict(self, df: pd.DataFrame, supplier: str, warehouse: str,
               weekday: int, hour: int, pv: Optional[str] = None) -> Optional[DeliveryPrediction]:
        """
        Предсказание времени привоза для заданных параметров.
        """
        if not self.is_fitted:
            raise ValueError("Модель не обучена. Сначала вызовите fit()")
        
        # Пробуем найти модель для конкретного ПВ, если не найдена - используем общую
        pv_normalized = self._normalize_pv(pv) if pv is not None else self.default_pv_label
        key = f"{supplier}_{warehouse}_{pv_normalized}"
        
        # Fallback на общую модель поставщик-склад если нет специфичной для ПВ
        if key not in self.models:
            # Ищем любую модель для этого поставщика-склада
            fallback_keys = [k for k in self.models.keys() if k.startswith(f"{supplier}_{warehouse}_")]
            if fallback_keys:
                key = fallback_keys[0]  # Берем первую доступную
            else:
                return None
        
        # Подготовка признаков для предсказания
        df = self.prepare_features(df)
        df = self._encode_pv(df)
        df = self.add_rolling_features(df, ['Поставщик', 'Склад', 'ПВ', 'day_of_week', 'hour'])
        
        # Фильтруем данные для этого поставщика
        pv_normalized = self._normalize_pv(pv) if pv is not None else None
        mask = (
            (df['Поставщик'] == supplier) &
            (df['Склад'] == warehouse) &
            (df['day_of_week'] == weekday) &
            (df['hour'] == hour)
        )
        if pv_normalized is not None:
            mask &= (df['ПВ'] == pv_normalized)
        subset = df[mask]
        
        if subset.empty:
            return None
        
        # Берем последние значения скользящих признаков
        latest = subset.iloc[-1]
        
        feature_cols = [
            'hour', 'day_of_week', 'week_of_year', 'day_of_month', 'month',
            'is_weekend', 'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos',
            'rolling_mean_3', 'rolling_mean_7', 'rolling_mean_14',
            'rolling_std_3', 'rolling_std_7', 'rolling_std_14', 'trend_7d',
            'pv_encoded'
        ]
        
        X = latest[feature_cols].values.reshape(1, -1)
        X = np.nan_to_num(X, 0)
        X_scaled = self.scalers[key].transform(X)
        
        # Предсказание
        prediction = self.models[key].predict(X_scaled)[0]
        
        # Оценка уверенности на основе стандартного отклонения
        std = latest.get('rolling_std_7', 30)
        confidence = max(0, min(1, 1 - std / 60))  # Нормализуем
        
        # Определяем тренд
        pv_for_prediction = pv_normalized or latest.get('ПВ', self.default_pv_label)
        trend, _ = self.detect_trend(df, supplier, warehouse, weekday, hour, pv=pv_for_prediction)
        
        # Генерируем рекомендацию
        shift_minutes = int(round(prediction))
        weekday_name = self.DAYS_RU[weekday]
        
        if abs(shift_minutes) < 15:
            recommendation = f"График соответствует реальности. Корректировка не требуется."
        elif shift_minutes > 0:
            recommendation = f"Рекомендуется сдвинуть время привоза на +{shift_minutes} мин " \
                           f"({weekday_name}, заказы в {hour}:00)"
        else:
            recommendation = f"Рекомендуется сдвинуть время привоза на {shift_minutes} мин " \
                           f"({weekday_name}, заказы в {hour}:00)"
        
        return DeliveryPrediction(
            supplier=supplier,
            warehouse=warehouse,
            pv=pv_for_prediction,
            weekday=weekday_name,
            order_hour=hour,
            predicted_delivery_time=prediction,
            confidence=confidence,
            trend=trend,
            recommendation=recommendation,
            shift_minutes=shift_minutes
        )
    
    def get_example_orders(self, df: pd.DataFrame, supplier: str, warehouse: str,
                           weekday: int, hour: int, pv: Optional[str] = None,
                           limit: int = 5) -> List[Dict]:
        """
        Получение примеров заказов для обоснования рекомендации.
        
        Returns:
            Список словарей с данными заказов
        """
        # Отладочный вывод в начале метода
        # print(f"DEBUG get_example_orders: Вызван с supplier={supplier}, warehouse={warehouse}, weekday={weekday}, hour={hour}, pv={pv}")
        # print(f"DEBUG: df.shape = {df.shape}")
        # print(f"DEBUG: Колонки в df: {list(df.columns)}")
        # print(f"DEBUG: Есть 'Время заказа позиции'? {'Время заказа позиции' in df.columns}")
        # print(f"DEBUG: Есть 'Рассчетное время привоза'? {'Рассчетное время привоза' in df.columns}")
        # print(f"DEBUG: Есть 'Время поступления на склад'? {'Время поступления на склад' in df.columns}")
        
        mask = (
            (df['Поставщик'] == supplier) &
            (df['Склад'] == warehouse)
        )
        if pv is not None:
            mask &= (df['ПВ'] == self._normalize_pv(pv))
        
        if 'day_of_week' in df.columns:
            mask &= (df['day_of_week'] == weekday)
        if 'hour' in df.columns:
            mask &= (df['hour'] == hour)
        
        subset = df[mask].copy()
        
        if subset.empty:
            return []
        
        # Берем последние заказы
        subset = subset.sort_values('Время заказа позиции', ascending=False).head(limit)
        
        # Отладочный вывод для диагностики
        # print(f"DEBUG get_example_orders: subset.shape = {subset.shape}")
        # if not subset.empty:
        #     print(f"DEBUG: Колонки в subset: {list(subset.columns)}")
        #     print(f"DEBUG: Первая строка subset:")
        #     first_row = subset.iloc[0]
        #     print(f"  order_id: {first_row.get('№ заказа', 'N/A')}")
        #     print(f"  Время заказа позиции: {first_row.get('Время заказа позиции', 'N/A')} (type: {type(first_row.get('Время заказа позиции', None))})")
        #     print(f"  Рассчетное время привоза: {first_row.get('Рассчетное время привоза', 'N/A')} (type: {type(first_row.get('Рассчетное время привоза', None))})")
        #     print(f"  Время поступления на склад: {first_row.get('Время поступления на склад', 'N/A')} (type: {type(first_row.get('Время поступления на склад', None))})")
        #     print(f"  pd.notna(Время заказа): {pd.notna(first_row.get('Время заказа позиции', None))}")
        
        examples = []
        for idx, row in subset.iterrows():
            try:
                dev = row.get('Разница во времени привоза (мин.)', 0)
                
                # Получаем значения напрямую из колонок с проверкой
                # Используем безопасный доступ через get() с проверкой наличия колонки
                try:
                    order_time_val = row['Время заказа позиции'] if 'Время заказа позиции' in row.index else pd.NaT
                except (KeyError, IndexError):
                    order_time_val = pd.NaT
                
                try:
                    plan_time_val = row['Рассчетное время привоза'] if 'Рассчетное время привоза' in row.index else pd.NaT
                except (KeyError, IndexError):
                    plan_time_val = pd.NaT
                
                try:
                    fact_time_val = row['Время поступления на склад'] if 'Время поступления на склад' in row.index else pd.NaT
                except (KeyError, IndexError):
                    fact_time_val = pd.NaT
                
                # Форматируем даты и времена
                order_date = ''
                order_time = ''
                if pd.notna(order_time_val):
                    try:
                        if hasattr(order_time_val, 'strftime'):
                            order_date = order_time_val.strftime('%d.%m.%Y')
                            order_time = order_time_val.strftime('%H:%M')
                        else:
                            # Если это строка, пытаемся преобразовать
                            dt = pd.to_datetime(order_time_val, errors='coerce')
                            if pd.notna(dt):
                                order_date = dt.strftime('%d.%m.%Y')
                                order_time = dt.strftime('%H:%M')
                    except Exception as e:
                        if len(examples) == 0:
                            print(f"DEBUG: Ошибка форматирования order_time_val: {e}")
                        pass
                else:
                    if len(examples) == 0:
                        print(f"DEBUG: order_time_val is NaN or None")
                
                plan_time = ''
                if pd.notna(plan_time_val):
                    try:
                        if hasattr(plan_time_val, 'strftime'):
                            plan_time = plan_time_val.strftime('%H:%M')
                        else:
                            dt = pd.to_datetime(plan_time_val, errors='coerce')
                            if pd.notna(dt):
                                plan_time = dt.strftime('%H:%M')
                    except Exception as e:
                        if len(examples) == 0:
                            print(f"DEBUG: Ошибка форматирования plan_time_val: {e}")
                        pass
                else:
                    if len(examples) == 0:
                        print(f"DEBUG: plan_time_val is NaN or None")
                
                fact_time = ''
                if pd.notna(fact_time_val):
                    try:
                        if hasattr(fact_time_val, 'strftime'):
                            fact_time = fact_time_val.strftime('%H:%M')
                        else:
                            dt = pd.to_datetime(fact_time_val, errors='coerce')
                            if pd.notna(dt):
                                fact_time = dt.strftime('%H:%M')
                    except Exception as e:
                        if len(examples) == 0:
                            print(f"DEBUG: Ошибка форматирования fact_time_val: {e}")
                        pass
                else:
                    if len(examples) == 0:
                        print(f"DEBUG: fact_time_val is NaN or None")
                
                examples.append({
                    'order_id': row.get('№ заказа', ''),
                    'pv': row.get('ПВ', self.default_pv_label),
                    'order_date': order_date,
                    'order_time': order_time,
                    'plan_time': plan_time,
                    'fact_time': fact_time,
                    'deviation': int(dev) if pd.notna(dev) else 0
                })
            except Exception as e:
                # В случае ошибки добавляем запись с пустыми значениями
                if len(examples) == 0:
                    print(f"DEBUG: Исключение при обработке строки: {e}")
                    import traceback
                    traceback.print_exc()
                examples.append({
                    'order_id': row.get('№ заказа', ''),
                    'pv': row.get('ПВ', self.default_pv_label),
                    'order_date': '',
                    'order_time': '',
                    'plan_time': '',
                    'fact_time': '',
                    'deviation': 0
                })
        
        return examples
    
    def remove_outliers(self, df: pd.DataFrame, column: str, n_std: float = 3.0) -> pd.DataFrame:
        """Удаление выбросов по правилу n стандартных отклонений"""
        mean = df[column].mean()
        std = df[column].std()
        return df[(df[column] >= mean - n_std * std) & (df[column] <= mean + n_std * std)]
    
    def generate_recommendations(self, df: pd.DataFrame, 
                                 min_samples: int = 3,
                                 min_shift: int = 15) -> List[ScheduleRecommendation]:
        """
        Генерация рекомендаций по корректировке расписания.
        
        Args:
            df: DataFrame с историческими данными
            min_samples: Минимальное количество записей для анализа
            min_shift: Минимальный сдвиг для рекомендации (в минутах)
        
        Returns:
            Список рекомендаций по корректировке
        """
        if df is None or df.empty:
            return []
        
        # Подготовка данных
        df_prep = self.prepare_features(df.copy())
        df_prep = self._encode_pv(df_prep)
        df_prep = self.add_rolling_features(df_prep, ['Поставщик', 'Склад', 'ПВ', 'day_of_week', 'hour'])
        
        recommendations = []
        
        # Удаляем строки с NaN в ключевых полях
        df_prep = df_prep.dropna(subset=['Разница во времени привоза (мин.)', 'Поставщик', 'Склад'])
        
        # Группируем по поставщик-склад-день-час
        grouped = df_prep.groupby(['Поставщик', 'Склад', 'ПВ', 'day_of_week', 'hour'])
        
        for (supplier, warehouse, pv, weekday, hour), group in grouped:
            if len(group) < min_samples:
                continue
            
            # Удаляем выбросы для более точного анализа
            group_clean = self.remove_outliers(group, 'Разница во времени привоза (мин.)', n_std=2.5)
            if len(group_clean) < min_samples:
                group_clean = group  # Если после удаления выбросов мало данных, используем все
            
            # Анализируем последние 2 недели vs предыдущие
            group_clean = group_clean.sort_values('Время заказа позиции')
            
            # Разделяем на периоды
            cutoff_date = group_clean['Время заказа позиции'].max() - timedelta(days=14)
            recent = group_clean[group_clean['Время заказа позиции'] >= cutoff_date]
            older = group_clean[group_clean['Время заказа позиции'] < cutoff_date]
            
            if len(recent) < 3 or len(older) < 3:
                continue
            
            # Считаем медианы
            recent_median = recent['Разница во времени привоза (мин.)'].median()
            older_median = older['Разница во времени привоза (мин.)'].median()
            
            # Определяем сдвиг
            shift = recent_median - older_median
            
            if abs(shift) < min_shift:
                continue
            
            # Определяем тренд
            trend, slope = self.detect_trend(df_prep, supplier, warehouse, weekday, hour, pv=pv)
            
            # Улучшенный расчет уверенности с учетом ПВ
            std = recent['Разница во времени привоза (мин.)'].std()
            count_factor = min(1.0, len(recent) / 20)  # Больше данных = выше уверенность
            std_factor = max(0, min(1, 1 - std / 60))
            
            # Бонус за консистентность данных по этому ПВ
            pv_consistency = 1.0
            if len(group) >= 10:
                # Проверяем, насколько стабильны данные по этому ПВ
                pv_std = group['Разница во времени привоза (мин.)'].std()
                pv_consistency = max(0.7, min(1.0, 1 - pv_std / 120))
            
            confidence = 0.4 + 0.2 * count_factor + 0.2 * std_factor + 0.2 * pv_consistency
            confidence = round(min(0.95, confidence), 2)
            
            # Формируем рекомендацию
            weekday_name = self.DAYS_RU[weekday]
            
            # Рекомендуемое время
            shift_minutes = int(round(recent_median))
            
            if abs(recent_median) > 30:
                # Значительное отклонение - рекомендуем изменить
                reason = self._generate_reason(trend, shift_minutes, weekday_name, hour)
                
                # Получаем примеры заказов
                print(f"DEBUG generate_recommendations: Перед вызовом get_example_orders")
                print(f"DEBUG: df_prep.shape = {df_prep.shape}")
                print(f"DEBUG: Колонки в df_prep: {list(df_prep.columns)[:10]}...")  # Первые 10 колонок
                print(f"DEBUG: Есть нужные колонки? 'Время заказа позиции'={('Время заказа позиции' in df_prep.columns)}, 'Рассчетное время привоза'={('Рассчетное время привоза' in df_prep.columns)}, 'Время поступления на склад'={('Время поступления на склад' in df_prep.columns)}")
                examples = self.get_example_orders(df_prep, supplier, warehouse, weekday, hour, pv=pv, limit=5)
                print(f"DEBUG generate_recommendations: После вызова get_example_orders, получено {len(examples)} примеров")
                
                rec = ScheduleRecommendation(
                    supplier=supplier,
                    warehouse=warehouse,
                    pv=pv,
                    weekday=weekday_name,
                    order_time_start=f"{hour:02d}:00",
                    order_time_end=f"{hour:02d}:59",
                    current_expected_time=f"План + {int(older_median)} мин",
                    recommended_time=f"План + {shift_minutes} мин",
                    shift_minutes=shift_minutes,
                    confidence=confidence,
                    reason=reason,
                    trend_detected=trend.value,
                    effective_from=(datetime.now() + timedelta(days=1)).strftime('%d.%m.%Y'),
                    example_orders=examples
                )
                recommendations.append(rec)
        
        # Сортируем по уверенности
        recommendations.sort(key=lambda x: (-x.confidence, -abs(x.shift_minutes)))
        
        return recommendations
    
    def generate_recommendations_by_schedule(self, df: pd.DataFrame, 
                                             schedules: List[Dict],
                                             min_samples: int = 3,
                                             min_shift: int = 15) -> List[ScheduleRecommendation]:
        """
        Генерация рекомендаций с привязкой к реальным окнам расписания.
        
        Группирует заказы по окнам расписания вместо фиксированных часовых интервалов.
        Время заказа должно попадать в рамки: предыдущее_окно < время_заказа <= текущее_окно.
        Если заказ после последнего окна дня - относим к первому окну следующего дня.
        
        Args:
            df: DataFrame с историческими данными
            schedules: Список расписаний из CRM
            min_samples: Минимальное количество записей для анализа
            min_shift: Минимальный сдвиг для рекомендации (в минутах)
        
        Returns:
            Список рекомендаций по корректировке
        """
        if df is None or df.empty or not schedules:
            return self.generate_recommendations(df, min_samples, min_shift)
        
        # Подготовка данных
        df_prep = self.prepare_features(df.copy())
        df_prep = self._encode_pv(df_prep)
        
        # Добавляем колонку минут от начала дня
        df_prep['order_minutes'] = df_prep['hour'] * 60 + df_prep['Время заказа позиции'].dt.minute
        
        recommendations = []
        
        # Удаляем строки с NaN в ключевых полях
        df_prep = df_prep.dropna(subset=['Разница во времени привоза (мин.)', 'Поставщик', 'Склад'])
        
        # Индексируем расписание: {(warehouse_lower, pv_lower, weekday): [(time_minutes, schedule), ...]}
        schedule_index = {}
        for sched in schedules:
            warehouse = (sched.get('warehouseName') or '').lower().strip()
            branch = (sched.get('branchAddress') or '').lower().strip()
            weekday = sched.get('weekday', 0)
            
            if not warehouse or not weekday:
                continue
            
            key = (warehouse, branch, weekday)
            
            try:
                time_str = sched.get('timeOrder', '00:00')
                h, m = map(int, time_str.split(':'))
                time_minutes = h * 60 + m
            except:
                continue
            
            if key not in schedule_index:
                schedule_index[key] = []
            schedule_index[key].append((time_minutes, sched))
        
        # Сортируем окна по времени
        for key in schedule_index:
            schedule_index[key].sort(key=lambda x: x[0])
        
        # Функция определения окна для заказа
        def find_window_for_order(warehouse, pv, weekday, order_minutes):
            """Найти окно расписания для заказа"""
            wh_lower = warehouse.lower().strip()
            pv_lower = (pv or '').lower().strip()
            
            # Ищем точное совпадение
            key = (wh_lower, pv_lower, weekday + 1)  # weekday в данных 0-6, в расписании 1-7
            windows = schedule_index.get(key, [])
            
            # Если не нашли точное совпадение по ПВ, ищем по первому слову склада
            if not windows:
                wh_first = wh_lower.split()[0] if wh_lower else ''
                for k, v in schedule_index.items():
                    if k[0].startswith(wh_first) and k[2] == weekday + 1:
                        if not pv_lower or k[1] == pv_lower or not k[1]:
                            windows = v
                            break
            
            if not windows:
                return None, False
            
            # Ищем подходящее окно
            for i, (window_minutes, sched) in enumerate(windows):
                if order_minutes <= window_minutes:
                    return sched, False
            
            # Заказ после последнего окна - ищем первое окно следующего дня
            next_weekday = ((weekday + 1) % 7) + 1
            for k, v in schedule_index.items():
                if k[0] == wh_lower and k[2] == next_weekday:
                    if not pv_lower or k[1] == pv_lower or not k[1]:
                        return v[0][1], True  # Первое окно следующего дня
            
            return None, False
        
        # Группируем заказы по (поставщик, склад, ПВ, день, окно расписания)
        processed_groups = {}
        
        for idx, row in df_prep.iterrows():
            supplier = row['Поставщик']
            warehouse = row['Склад']
            pv = row.get('ПВ', '')
            weekday = row['day_of_week']
            order_minutes = row['order_minutes']
            deviation = row['Разница во времени привоза (мин.)']
            
            if pd.isna(deviation):
                continue
            
            sched, is_next_day = find_window_for_order(warehouse, pv, weekday, order_minutes)
            if sched is None:
                continue
            
            time_order = sched.get('timeOrder', '')
            actual_weekday = weekday if not is_next_day else (weekday + 1) % 7
            
            key = (supplier, warehouse, pv, actual_weekday, time_order)
            
            if key not in processed_groups:
                processed_groups[key] = {
                    'data': [],
                    'schedule': sched,
                    'is_next_day': is_next_day
                }
            
            processed_groups[key]['data'].append({
                'deviation': deviation,
                'date': row['Время заказа позиции'],
                'order_id': row.get('№ заказа', '')
            })
        
        # Анализируем каждую группу
        for key, group_info in processed_groups.items():
            supplier, warehouse, pv, weekday, time_order = key
            data = group_info['data']
            sched = group_info['schedule']
            
            if len(data) < min_samples:
                continue
            
            # Сортируем по дате
            data.sort(key=lambda x: x['date'])
            deviations = [d['deviation'] for d in data]
            
            # Разделяем на периоды (последние 2 недели vs предыдущие)
            cutoff_idx = len(data) * 2 // 3  # Примерно 2/3 старые, 1/3 новые
            if cutoff_idx < 3 or len(data) - cutoff_idx < 3:
                continue
            
            recent_devs = deviations[cutoff_idx:]
            older_devs = deviations[:cutoff_idx]
            
            import statistics
            recent_median = statistics.median(recent_devs)
            older_median = statistics.median(older_devs)
            
            shift = recent_median - older_median
            
            if abs(recent_median) < 30 and abs(shift) < min_shift:
                continue
            
            # Уверенность
            try:
                std = statistics.stdev(recent_devs) if len(recent_devs) > 1 else 30
            except:
                std = 30
            
            count_factor = min(1.0, len(recent_devs) / 15)
            std_factor = max(0, min(1, 1 - std / 60))
            confidence = 0.4 + 0.3 * count_factor + 0.3 * std_factor
            confidence = round(min(0.95, confidence), 2)
            
            weekday_name = self.DAYS_RU[weekday]
            shift_minutes = int(round(recent_median))
            
            # Формируем текст рекомендации
            duration = sched.get('deliveryDuration', 0)
            new_duration = duration + shift_minutes
            
            if shift_minutes > 0:
                reason = f"Систематические опоздания в {weekday_name} для окна 'Заказ до {time_order}'. " \
                         f"Медиана отклонений: {shift_minutes:+d} мин. Рекомендуется увеличить длительность доставки."
            else:
                reason = f"Ранние привозы в {weekday_name} для окна 'Заказ до {time_order}'. " \
                         f"Медиана отклонений: {shift_minutes:+d} мин. Можно уменьшить длительность доставки."
            
            # Примеры заказов - используем get_example_orders для правильного формата
            # Получаем час из time_order для вызова get_example_orders
            try:
                h, m = map(int, time_order.split(':'))
                hour_for_examples = h
            except:
                hour_for_examples = 0
            
            # Используем исходный DataFrame для получения примеров
            examples = self.get_example_orders(df_prep, supplier, warehouse, weekday, hour_for_examples, pv=pv, limit=5)
            
            # Если get_example_orders вернул пустой список, формируем из data
            if not examples:
                examples = []
                for d in data[-5:]:
                    order_date_val = d['date']
                    order_id = d.get('order_id', '')
                    deviation = d.get('deviation', 0)
                    
                    # Форматируем дату и время
                    if pd.notna(order_date_val) and hasattr(order_date_val, 'strftime'):
                        order_date = order_date_val.strftime('%d.%m.%Y')
                        order_time = order_date_val.strftime('%H:%M')
                    else:
                        order_date = ''
                        order_time = ''
                    
                    # Для plan_time и fact_time нужно получить из исходной строки
                    # Найдем строку в df_prep по order_id
                    plan_time = ''
                    fact_time = ''
                    if order_id:
                        matching_rows = df_prep[df_prep['№ заказа'] == order_id]
                        if not matching_rows.empty:
                            row = matching_rows.iloc[0]
                            if pd.notna(row.get('Рассчетное время привоза')):
                                plan_val = row['Рассчетное время привоза']
                                if hasattr(plan_val, 'strftime'):
                                    plan_time = plan_val.strftime('%H:%M')
                            if pd.notna(row.get('Время поступления на склад')):
                                fact_val = row['Время поступления на склад']
                                if hasattr(fact_val, 'strftime'):
                                    fact_time = fact_val.strftime('%H:%M')
                    
                    examples.append({
                        'order_id': order_id,
                        'order_date': order_date,
                        'order_time': order_time,
                        'plan_time': plan_time,
                        'fact_time': fact_time,
                        'deviation': int(deviation) if pd.notna(deviation) else 0
                    })
            
            rec = ScheduleRecommendation(
                supplier=supplier,
                warehouse=warehouse,
                pv=pv,
                weekday=weekday_name,
                order_time_start=time_order,  # "Заказ до"
                order_time_end=self._calculate_deliver_by(time_order, duration),  # "Доставят к"
                current_expected_time=f"Длительность: {duration} мин",
                recommended_time=f"Длительность: {new_duration} мин ({shift_minutes:+d})",
                shift_minutes=shift_minutes,
                confidence=confidence,
                reason=reason,
                trend_detected='delay' if shift_minutes > 0 else 'early',
                effective_from=(datetime.now() + timedelta(days=1)).strftime('%d.%m.%Y'),
                example_orders=examples,
                schedule_window=sched
            )
            recommendations.append(rec)
        
        # Сортируем по уверенности
        recommendations.sort(key=lambda x: (-x.confidence, -abs(x.shift_minutes)))
        
        return recommendations
    
    def _calculate_deliver_by(self, time_order: str, duration: int) -> str:
        """Вычислить время 'Доставят к' на основе 'Заказ до' и длительности"""
        try:
            h, m = map(int, time_order.split(':'))
            total_minutes = h * 60 + m + duration
            new_h = (total_minutes // 60) % 24
            new_m = total_minutes % 60
            return f"{new_h:02d}:{new_m:02d}"
        except:
            return "—"
    
    def _generate_reason(self, trend: TrendType, shift: int, weekday: str, hour: int) -> str:
        """Генерация текстового объяснения рекомендации"""
        if trend == TrendType.INCREASING_DELAY:
            return f"Обнаружен тренд увеличения опозданий в {weekday} для заказов в {hour}:00. " \
                   f"Рекомендуется увеличить ожидаемое время привоза на {shift} мин."
        elif trend == TrendType.DECREASING_DELAY:
            return f"Поставщик стал приезжать раньше в {weekday} для заказов в {hour}:00. " \
                   f"Рекомендуется уменьшить ожидаемое время привоза на {abs(shift)} мин."
        elif trend == TrendType.SHIFT:
            direction = "позже" if shift > 0 else "раньше"
            return f"Обнаружен резкий сдвиг времени привоза на {abs(shift)} мин {direction} " \
                   f"в {weekday} для заказов в {hour}:00."
        else:
            return f"Систематическое отклонение от графика на {shift} мин " \
                   f"в {weekday} для заказов в {hour}:00."
    
    def analyze_supplier_patterns(self, df: pd.DataFrame, 
                                  supplier: str, 
                                  warehouse: str,
                                  pv: Optional[str] = None) -> Dict:
        """
        Комплексный анализ паттернов поставщика.
        
        Returns:
            Словарь с анализом по дням недели и часам
        """
        # Очистка NaN
        df = df.dropna(subset=['Время заказа позиции', 'Разница во времени привоза (мин.)'])
        df = self.prepare_features(df)
        
        if 'ПВ' not in df.columns:
            df['ПВ'] = self.default_pv_label
        df['ПВ'] = df['ПВ'].apply(self._normalize_pv)
        mask = (df['Поставщик'] == supplier) & (df['Склад'] == warehouse)
        if pv is not None:
            mask &= (df['ПВ'] == self._normalize_pv(pv))
        subset = df[mask]
        
        if subset.empty:
            return {}
        
        analysis = {
            'supplier': supplier,
            'warehouse': warehouse,
            'pv': pv if pv else 'Все ПВ',
            'total_orders': len(subset),
            'date_range': {
                'from': subset['Время заказа позиции'].min().strftime('%d.%m.%Y'),
                'to': subset['Время заказа позиции'].max().strftime('%d.%m.%Y')
            },
            'overall_stats': {
                'mean_deviation': round(subset['Разница во времени привоза (мин.)'].mean(), 1),
                'median_deviation': round(subset['Разница во времени привоза (мин.)'].median(), 1),
                'std_deviation': round(subset['Разница во времени привоза (мин.)'].std(), 1),
                'on_time_pct': round((subset['Разница во времени привоза (мин.)'].between(-30, 30).sum() / len(subset)) * 100, 1)
            },
            'by_weekday': {},
            'by_hour': {},
            'by_pv': {},  # Статистика по каждому ПВ
            'recommendations': []
        }
        
        # Анализ по ПВ (если не фильтруем по конкретному ПВ)
        if pv is None:
            for pv_name in subset['ПВ'].unique():
                pv_data = subset[subset['ПВ'] == pv_name]
                if len(pv_data) >= 3:
                    analysis['by_pv'][pv_name] = {
                        'orders': len(pv_data),
                        'mean_deviation': round(pv_data['Разница во времени привоза (мин.)'].mean(), 1),
                        'median_deviation': round(pv_data['Разница во времени привоза (мин.)'].median(), 1),
                        'std_deviation': round(pv_data['Разница во времени привоза (мин.)'].std(), 1),
                        'on_time_pct': round((pv_data['Разница во времени привоза (мин.)'].between(-30, 30).sum() / len(pv_data)) * 100, 1)
                    }
        
        # Анализ по дням недели
        for weekday in range(7):
            day_data = subset[subset['day_of_week'] == weekday]
            if len(day_data) < 3:
                continue
            
            analysis['by_weekday'][self.DAYS_RU[weekday]] = {
                'orders': len(day_data),
                'mean_deviation': round(day_data['Разница во времени привоза (мин.)'].mean(), 1),
                'median_deviation': round(day_data['Разница во времени привоза (мин.)'].median(), 1),
                'trend': self.detect_trend(df, supplier, warehouse, weekday, -1)[0].value
            }
        
        # Анализ по часам заказа
        for hour in range(6, 22):  # Рабочие часы
            hour_data = subset[subset['hour'] == hour]
            if len(hour_data) < 3:
                continue
            
            analysis['by_hour'][f"{hour:02d}:00"] = {
                'orders': len(hour_data),
                'mean_deviation': round(hour_data['Разница во времени привоза (мин.)'].mean(), 1),
                'median_deviation': round(hour_data['Разница во времени привоза (мин.)'].median(), 1)
            }
        
        return analysis


    def get_pv_statistics(self, df: pd.DataFrame, supplier: str, warehouse: str) -> Dict[str, Dict]:
        """
        Получение статистики по всем ПВ для поставщика-склада.
        
        Returns:
            Словарь {pv_name: {stats}}
        """
        df = df.dropna(subset=['Время заказа позиции', 'Разница во времени привоза (мин.)'])
        
        if 'ПВ' not in df.columns:
            df['ПВ'] = self.default_pv_label
        df['ПВ'] = df['ПВ'].apply(self._normalize_pv)
        
        mask = (df['Поставщик'] == supplier) & (df['Склад'] == warehouse)
        subset = df[mask]
        
        if subset.empty:
            return {}
        
        result = {}
        for pv_name in subset['ПВ'].unique():
            pv_data = subset[subset['ПВ'] == pv_name]
            if len(pv_data) < 3:
                continue
            
            deviations = pv_data['Разница во времени привоза (мин.)']
            result[pv_name] = {
                'orders': len(pv_data),
                'unique_orders': pv_data['№ заказа'].nunique() if '№ заказа' in pv_data.columns else len(pv_data),
                'mean_deviation': round(deviations.mean(), 1),
                'median_deviation': round(deviations.median(), 1),
                'std_deviation': round(deviations.std(), 1),
                'min_deviation': round(deviations.min(), 1),
                'max_deviation': round(deviations.max(), 1),
                'on_time_pct': round((deviations.between(-30, 30).sum() / len(pv_data)) * 100, 1),
                'early_pct': round((deviations < -30).sum() / len(pv_data) * 100, 1),
                'late_pct': round((deviations > 30).sum() / len(pv_data) * 100, 1),
                'very_late_pct': round((deviations > 60).sum() / len(pv_data) * 100, 1)
            }
        
        return result
    
    def get_best_worst_pv(self, df: pd.DataFrame, supplier: str, warehouse: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Определение лучшего и худшего ПВ по % вовремя.
        
        Returns:
            (best_pv, worst_pv)
        """
        stats = self.get_pv_statistics(df, supplier, warehouse)
        if not stats:
            return None, None
        
        # Сортируем по % вовремя
        sorted_pv = sorted(stats.items(), key=lambda x: x[1]['on_time_pct'], reverse=True)
        
        best_pv = sorted_pv[0][0] if sorted_pv else None
        worst_pv = sorted_pv[-1][0] if len(sorted_pv) > 1 else None
        
        return best_pv, worst_pv


class TrendDetector:
    """
    Детектор трендов и точек изменения во временных рядах.
    
    Использует:
    - CUSUM для обнаружения сдвигов
    - Скользящие окна для трендов
    """
    
    @staticmethod
    def detect_changepoint(values: np.ndarray, threshold: float = 5.0) -> List[int]:
        """
        Обнаружение точек изменения с помощью CUSUM.
        
        Returns:
            Список индексов точек изменения
        """
        if len(values) < 10:
            return []
        
        mean = np.mean(values)
        cumsum = np.cumsum(values - mean)
        
        changepoints = []
        for i in range(1, len(cumsum)):
            if abs(cumsum[i] - cumsum[i-1]) > threshold * np.std(values):
                changepoints.append(i)
        
        return changepoints
    
    @staticmethod
    def detect_trend_direction(values: np.ndarray) -> Tuple[str, float]:
        """
        Определение направления тренда.
        
        Returns:
            (направление, наклон)
        """
        if len(values) < 5:
            return "unknown", 0.0
        
        X = np.arange(len(values)).reshape(-1, 1)
        lr = LinearRegression()
        lr.fit(X, values)
        slope = lr.coef_[0]
        
        if slope > 2:
            return "increasing", slope
        elif slope < -2:
            return "decreasing", slope
        else:
            return "stable", slope


# Пример использования
if __name__ == "__main__":
    # Тестовые данные
    print("ML Predictor для анализа доставок загружен")
    print("Используйте DeliveryMLPredictor для обучения и предсказаний")

