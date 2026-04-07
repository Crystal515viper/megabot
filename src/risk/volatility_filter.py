"""
Модуль фильтрации волатильности.
Реализует: ATR (Уайлдер), Z-Score, SNR (через FFT).
"""
import numpy as np
import pandas as pd
from scipy.fft import fft
from dataclasses import dataclass
from typing import Optional

# CONFIG_REF: Пороговые значения для принятия решения о торговле
MIN_SNR_THRESHOLD = 2.0       # Минимальное отношение сигнал/шум
MAX_ZSCORE_THRESHOLD = 2.5    # Максимальный Z-score для входа (избегать пиков)
MIN_ATR_PERCENT = 0.001       # Минимальная волатильность (0.1%)

@dataclass
class VolatilityMetrics:
    atr: float
    atr_percent: float
    z_score: float
    snr: float
    current_price: float

def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    """
    Расчет ATR по методу Уайлдера (Wilder's Smoothing).
    Formula: TR = max(H-L, |H-C_prev|, |L-C_prev|)
             ATR = [(PrevATR * (n-1)) + CurrentTR] / n
    """
    if len(close) < period + 1:
        return 0.0

    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Wilder's Smoothing
    atr = tr.iloc[:period].sum() / period
    for i in range(period, len(tr)):
        atr = (atr * (period - 1) + tr.iloc[i]) / period
    
    return float(atr)

def calculate_z_score(prices: pd.Series, window: int = 20) -> float:
    """
    Расчет Z-Score для оценки отклонения цены от средней.
    Formula: Z = (Price - Mean) / StdDev
    """
    if len(prices) < window:
        return 0.0
    
    mean = prices.iloc[-window:].mean()
    std = prices.iloc[-window:].std()
    
    if std == 0:
        return 0.0
        
    return float((prices.iloc[-1] - mean) / std)

def calculate_snr(prices: pd.Series) -> float:
    """
    Расчет Signal-to-Noise Ratio через FFT.
    Signal = мощность низкочастотной компоненты (тренд)
    Noise = мощность высокочастотных компонент
    Formula: SNR = P_signal / P_noise
    """
    if len(prices) < 4:
        return 0.0

    # Detrend prices to focus on fluctuations
    detrended = prices - prices.mean()
    n = len(detrended)
    
    # FFT
    spectrum = np.abs(fft(detrended.values)) ** 2
    freqs = np.fft.fftfreq(n)
    
    # Разделение на сигнал (низкие частоты, исключая DC) и шум
    # Сигнал: первые 10% частот (кроме 0)
    # Шум: остальные 90%
    cutoff_idx = max(1, int(n * 0.1))
    
    signal_power = spectrum[1:cutoff_idx].sum()
    noise_power = spectrum[cutoff_idx:n//2].sum() # Только положительная часть спектра
    
    if noise_power == 0:
        return float('inf') if signal_power > 0 else 0.0
        
    return float(signal_power / noise_power)

def should_trade(metrics: VolatilityMetrics) -> tuple[bool, str]:
    """
    Принятие решения о возможности торговли на основе метрик.
    Returns: (Should Trade, Reason)
    """
    # Проверка SNR
    if metrics.snr < MIN_SNR_THRESHOLD:
        return False, f"Low SNR: {metrics.snr:.2f} < {MIN_SNR_THRESHOLD}"
    
    # Проверка Z-Score (избегаем входа на экстремумах)
    if abs(metrics.z_score) > MAX_ZSCORE_THRESHOLD:
        return False, f"High Z-Score: {metrics.z_score:.2f} > {MAX_ZSCORE_THRESHOLD}"
    
    # Проверка минимальной волатильности
    if metrics.atr_percent < MIN_ATR_PERCENT:
        return False, f"Low Volatility: {metrics.atr_percent:.4f} < {MIN_ATR_PERCENT}"
        
    return True, "Conditions met"

if __name__ == "__main__":
    # Пример использования
    dates = pd.date_range(start="2023-01-01", periods=100, freq="1h")
    np.random.seed(42)
    # Генерация синусоиды + шум + тренд
    t = np.linspace(0, 10, 100)
    prices = 100 + np.sin(t) * 5 + np.random.normal(0, 0.5, 100) + t * 0.1
    
    series = pd.Series(prices)
    highs = pd.Series(prices * 1.002)
    lows = pd.Series(prices * 0.998)
    
    atr = calculate_atr(highs, lows, series)
    z = calculate_z_score(series)
    snr = calculate_snr(series)
    
    metrics = VolatilityMetrics(
        atr=atr,
        atr_percent=atr/series.iloc[-1],
        z_score=z,
        snr=snr,
        current_price=series.iloc[-1]
    )
    
    trade, reason = should_trade(metrics)
    print(f"Metrics: {metrics}")
    print(f"Trade Decision: {trade}, Reason: {reason}")