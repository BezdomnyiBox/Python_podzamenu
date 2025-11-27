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
    weekday: str
    order_time_start: str          # Начало временного окна заказа
    order_time_end: str            # Конец временного окна заказа
    current_expected_time: str     # Текущее ожидаемое время привоза
    recommended_time: str          # Рекомендуемое время привоза
    shift_minutes: int             # Сдвиг в минутах
    confidence: float              # Уверенность в рекомендации
    reason: str                    # Причина рекомендации
    trend_detected: str            # Обнаруженный тренд
    effective_from: str            # Рекомендуемая дата начала применения
    example_orders: List[Dict] = field(default_factory=list)  # Примеры заказов


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
        df = self.add_rolling_features(df, ['Поставщик', 'Склад', 'day_of_week', 'hour'])
        
        # Признаки для модели
        feature_cols = [
            'hour', 'day_of_week', 'week_of_year', 'day_of_month', 'month',
            'is_weekend', 'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos',
            'rolling_mean_3', 'rolling_mean_7', 'rolling_mean_14',
            'rolling_std_3', 'rolling_std_7', 'rolling_std_14', 'trend_7d'
        ]
        
        target_col = 'Разница во времени привоза (мин.)'
        
        # Обучаем модель для каждого поставщика-склада
        for (supplier, warehouse), group_df in df.groupby(['Поставщик', 'Склад']):
            if len(group_df) < 10:  # Минимум 10 записей для обучения
                continue
            
            key = f"{supplier}_{warehouse}"
            
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
                    weekday: int, hour: int, lookback_days: int = 30) -> Tuple[TrendType, float]:
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
               weekday: int, hour: int) -> Optional[DeliveryPrediction]:
        """
        Предсказание времени привоза для заданных параметров.
        """
        if not self.is_fitted:
            raise ValueError("Модель не обучена. Сначала вызовите fit()")
        
        key = f"{supplier}_{warehouse}"
        if key not in self.models:
            return None
        
        # Подготовка признаков для предсказания
        df = self.prepare_features(df)
        df = self.add_rolling_features(df, ['Поставщик', 'Склад', 'day_of_week', 'hour'])
        
        # Фильтруем данные для этого поставщика
        mask = (
            (df['Поставщик'] == supplier) &
            (df['Склад'] == warehouse) &
            (df['day_of_week'] == weekday) &
            (df['hour'] == hour)
        )
        subset = df[mask]
        
        if subset.empty:
            return None
        
        # Берем последние значения скользящих признаков
        latest = subset.iloc[-1]
        
        feature_cols = [
            'hour', 'day_of_week', 'week_of_year', 'day_of_month', 'month',
            'is_weekend', 'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos',
            'rolling_mean_3', 'rolling_mean_7', 'rolling_mean_14',
            'rolling_std_3', 'rolling_std_7', 'rolling_std_14', 'trend_7d'
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
        trend, _ = self.detect_trend(df, supplier, warehouse, weekday, hour)
        
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
            weekday=weekday_name,
            order_hour=hour,
            predicted_delivery_time=prediction,
            confidence=confidence,
            trend=trend,
            recommendation=recommendation,
            shift_minutes=shift_minutes
        )
    
    def get_example_orders(self, df: pd.DataFrame, supplier: str, warehouse: str,
                           weekday: int, hour: int, limit: int = 5) -> List[Dict]:
        """
        Получение примеров заказов для обоснования рекомендации.
        
        Returns:
            Список словарей с данными заказов
        """
        mask = (
            (df['Поставщик'] == supplier) &
            (df['Склад'] == warehouse)
        )
        
        if 'day_of_week' in df.columns:
            mask &= (df['day_of_week'] == weekday)
        if 'hour' in df.columns:
            mask &= (df['hour'] == hour)
        
        subset = df[mask].copy()
        
        if subset.empty:
            return []
        
        # Берем последние заказы
        subset = subset.sort_values('Время заказа позиции', ascending=False).head(limit)
        
        examples = []
        for _, row in subset.iterrows():
            dev = row.get('Разница во времени привоза (мин.)', 0)
            examples.append({
                'order_id': row.get('№ заказа', ''),
                'order_date': row['Время заказа позиции'].strftime('%d.%m.%Y') if pd.notna(row['Время заказа позиции']) else '',
                'order_time': row['Время заказа позиции'].strftime('%H:%M') if pd.notna(row['Время заказа позиции']) else '',
                'plan_time': row['Рассчетное время привоза'].strftime('%H:%M') if pd.notna(row.get('Рассчетное время привоза')) else '',
                'fact_time': row['Время поступления на склад'].strftime('%H:%M') if pd.notna(row.get('Время поступления на склад')) else '',
                'deviation': int(dev) if pd.notna(dev) else 0
            })
        
        return examples
    
    def remove_outliers(self, df: pd.DataFrame, column: str, n_std: float = 3.0) -> pd.DataFrame:
        """Удаление выбросов по правилу n стандартных отклонений"""
        mean = df[column].mean()
        std = df[column].std()
        return df[(df[column] >= mean - n_std * std) & (df[column] <= mean + n_std * std)]
    
    def generate_recommendations(self, df: pd.DataFrame, 
                                 min_samples: int = 5,
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
        df_prep = self.add_rolling_features(df_prep, ['Поставщик', 'Склад', 'day_of_week', 'hour'])
        
        recommendations = []
        
        # Удаляем строки с NaN в ключевых полях
        df_prep = df_prep.dropna(subset=['Разница во времени привоза (мин.)', 'Поставщик', 'Склад'])
        
        # Группируем по поставщик-склад-день-час
        grouped = df_prep.groupby(['Поставщик', 'Склад', 'day_of_week', 'hour'])
        
        for (supplier, warehouse, weekday, hour), group in grouped:
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
            trend, slope = self.detect_trend(df_prep, supplier, warehouse, weekday, hour)
            
            # Улучшенный расчет уверенности
            std = recent['Разница во времени привоза (мин.)'].std()
            count_factor = min(1.0, len(recent) / 20)  # Больше данных = выше уверенность
            std_factor = max(0, min(1, 1 - std / 60))
            confidence = 0.5 + 0.25 * count_factor + 0.25 * std_factor
            confidence = round(min(0.95, confidence), 2)
            
            # Формируем рекомендацию
            weekday_name = self.DAYS_RU[weekday]
            
            # Рекомендуемое время
            shift_minutes = int(round(recent_median))
            
            if abs(recent_median) > 30:
                # Значительное отклонение - рекомендуем изменить
                reason = self._generate_reason(trend, shift_minutes, weekday_name, hour)
                
                # Получаем примеры заказов
                examples = self.get_example_orders(df_prep, supplier, warehouse, weekday, hour, limit=5)
                
                rec = ScheduleRecommendation(
                    supplier=supplier,
                    warehouse=warehouse,
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
                                  warehouse: str) -> Dict:
        """
        Комплексный анализ паттернов поставщика.
        
        Returns:
            Словарь с анализом по дням недели и часам
        """
        # Очистка NaN
        df = df.dropna(subset=['Время заказа позиции', 'Разница во времени привоза (мин.)'])
        df = self.prepare_features(df)
        
        mask = (df['Поставщик'] == supplier) & (df['Склад'] == warehouse)
        subset = df[mask]
        
        if subset.empty:
            return {}
        
        analysis = {
            'supplier': supplier,
            'warehouse': warehouse,
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
            'recommendations': []
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

