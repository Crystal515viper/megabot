"""
Модуль фильтрации волатильности.
Расчет ATR (Уайлдер), Z-score, SNR (через FFT).
"""
import numpy as np
import pandas as pd
from scipy.fft import fft
from dataclasses import dataclass
from typing import Optional

# CONFIG_REF: Пороговые значения для торговли
VOLATILITY_THRESHOLD = 0.0005  # Минимальный ATR % для входа
ZSCORE_THRESHOLD = 2.0         # Порог отклонения цены
SNR_MIN_THRESHOLD = 0.5        # Минимальное отношение сигнал/шум


@dataclass
class VolatilityMetrics:
    """Результаты расчета метрик волатильности."""
    atr: float                # Average True Range (в ценах)
    atr_percent: float        # ATR в процентах от цены
    z_score: float            # Z-score текущего закрытия
    snr: float                # Signal-to-Noise Ratio (FFT)
    should_trade: bool        # Итоговое решение
    reason: str               # Причина решения


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    """
    Расчет ATR по методу Уайлдера.
    
    Формула:
    TR = max(H-L, |H-C_prev|, |L-C_prev|)
    ATR = SMA(TR, period) [для первого раза], далее EMA
    
    Args:
        high: Серия максимумов
        low: Серия минимумов
        close: Серия закрытий
        period: Период сглаживания (по умолчанию 14)
    
    Returns:
        Текущее значение ATR
    """
    if len(close) < period + 1:
        return 0.0
    
    # True Range
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Первый ATR как простое среднее
    atr = tr.iloc[:period].mean()
    
    # Остальные как EMA (Уайлдер)
    for i in range(period, len(tr)):
        atr = (atr * (period - 1) + tr.iloc[i]) / period
    
    return float(atr)


def calculate_zscore(prices: pd.Series, period: int = 20) -> float:
    """
    Расчет Z-score для определения отклонения цены от средней.
    
    Формула: Z = (Price - Mean) / StdDev
    
    Args:
        prices: Серия цен (закрытия)
        period: Период для расчета скользящей средней и stddev
    
    Returns:
        Текущий Z-score
    """
    if len(prices) < period:
        return 0.0
    
    mean = prices.iloc[-period:].mean()
    std = prices.iloc[-period:].std()
    
    if std == 0:
        return 0.0
    
    return float((prices.iloc[-1] - mean) / std)


def calculate_snr(prices: pd.Series, period: int = 64) -> float:
    """
    Расчет Signal-to-Noise Ratio через быстрое преобразование Фурье (FFT).
    
    Логика:
    1. Применяем FFT к ценам
    2. Сигнал = низкочастотные компоненты (тренд)
    3. Шум = высокочастотные компоненты
    4. SNR = Power_signal / Power_noise
    
    Args:
        prices: Серия цен
        period: Количество точек для анализа (должно быть степенью 2 для эффективности)
    
    Returns:
        Отношение сигнал/шум
    """
    if len(prices) < period:
        data = prices.iloc[-period:].values
    else:
        data = prices.iloc[-period:].values
    
    # Детрендим данные (убираем среднее)
    data = data - np.mean(data)
    
    # FFT
    spectrum = fft(data)
    power = np.abs(spectrum) ** 2
    
    # Разделяем на сигнал (низкие частоты, первые 20%) и шум (остальное)
    n = len(power)
    split_idx = int(n * 0.2)
    
    signal_power = np.sum(power[:split_idx])
    noise_power = np.sum(power[split_idx:])
    
    if noise_power == 0 or np.isnan(noise_power):
        return 0.0
    
    snr = signal_power / noise_power
    
    # Защита от NaN и бесконечности
    if np.isnan(snr) or np.isinf(snr):
        return 0.0
    
    return float(snr)


def should_trade(metrics: VolatilityMetrics) -> bool:
    """
    Принятие решения о возможности торговли на основе метрик.
    
    Критерии:
    1. ATR% > VOLATILITY_THRESHOLD (достаточная волатильность)
    2. SNR > SNR_MIN_THRESHOLD (сигнал преобладает над шумом)
    3. |Z-score| < ZSCORE_THRESHOLD (цена не в экстремуме)
    
    Args:
        metrics: Объект с рассчитанными метриками
    
    Returns:
        True если можно торговать
    """
    if metrics.atr_percent < VOLATILITY_THRESHOLD:
        return False  # Недостаточная волатильность
    
    if metrics.snr < SNR_MIN_THRESHOLD:
        return False  # Слишком много шума
    
    if abs(metrics.z_score) >= ZSCORE_THRESHOLD:
        return False  # Цена в экстремуме, возможен разворот
    
    return True


def analyze_market(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series
) -> VolatilityMetrics:
    """
    Полный анализ рынка: расчет всех метрик и принятие решения.
    
    Args:
        high: Серия максимумов
        low: Серия минимумов
        close: Серия закрытий
    
    Returns:
        VolatilityMetrics с итоговым решением
    """
    if len(close) < 20:
        return VolatilityMetrics(
            atr=0.0,
            atr_percent=0.0,
            z_score=0.0,
            snr=0.0,
            should_trade=False,
            reason="Недостаточно данных"
        )
    
    current_price = close.iloc[-1]
    
    # Расчет метрик
    atr = calculate_atr(high, low, close)
    atr_percent = atr / current_price if current_price > 0 else 0.0
    z_score = calculate_zscore(close)
    snr = calculate_snr(close)
    
    metrics = VolatilityMetrics(
        atr=atr,
        atr_percent=atr_percent,
        z_score=z_score,
        snr=snr,
        should_trade=False,
        reason=""
    )
    
    # Принятие решения
    if not should_trade(metrics):
        if atr_percent < VOLATILITY_THRESHOLD:
            metrics.reason = f"Низкая волатильность: {atr_percent:.6f} < {VOLATILITY_THRESHOLD}"
        elif snr < SNR_MIN_THRESHOLD:
            metrics.reason = f"Высокий шум: SNR={snr:.2f} < {SNR_MIN_THRESHOLD}"
        elif abs(z_score) >= ZSCORE_THRESHOLD:
            metrics.reason = f"Экстремум цены: Z={z_score:.2f}"
    else:
        metrics.reason = "Все фильтры пройдены"
        metrics.should_trade = True
    
    return metrics


if __name__ == "__main__":
    # Пример использования
    np.random.seed(42)
    n = 100
    
    # Генерация тестовых данных (случайное блуждание)
    returns = np.random.randn(n) * 0.02
    prices = 100 * np.cumprod(1 + returns)
    
    df = pd.DataFrame({
        'close': prices,
        'high': prices * (1 + np.abs(np.random.randn(n) * 0.01)),
        'low': prices * (1 - np.abs(np.random.randn(n) * 0.01))
    })
    
    metrics = analyze_market(df['high'], df['low'], df['close'])
    
    print(f"ATR: {metrics.atr:.4f}")
    print(f"ATR%: {metrics.atr_percent:.4%}")
    print(f"Z-Score: {metrics.z_score:.2f}")
    print(f"SNR: {metrics.snr:.2f}")
    print(f"Should Trade: {metrics.should_trade}")
    print(f"Reason: {metrics.reason}")
