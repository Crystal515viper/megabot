"""
Модуль расчета динамического левериджа.
Formula: Lev = Risk_ROI / (ATR% × K)
"""
import math
from dataclasses import dataclass
from typing import List

# CONFIG_REF: Параметры риска
BASE_RISK_ROI = 0.02          # Целевой риск на сделку (2%)
K_FACTOR = 1.5                # Коэффициент запаса безопасности
MAX_LEVERAGE = 20.0           # Абсолютный максимум плеча
MIN_LEVERAGE = 1.0            # Минимальное плечо
SNR_CORRECTION_FACTOR = 0.5   # Влияние SNR на плечо

@dataclass
class LeverageResult:
    calculated_leverage: float
    final_leverage: float
    reason: str

def calculate_dynamic_leverage(atr_percent: float, snr: float) -> LeverageResult:
    """
    Расчет оптимального плеча.
    1. Базовое плечо через ATR.
    2. Коррекция через SNR (чем выше шум, тем ниже плечо).
    3. Округление до безопасных уровней (шаг 0.5 или 1.0).
    """
    if atr_percent <= 0:
        return LeverageResult(0.0, 0.0, "Invalid ATR")

    # 1. Базовая формула
    # Lev = Risk_ROI / (ATR% * K)
    base_lev = BASE_RISK_ROI / (atr_percent * K_FACTOR)
    
    # 2. Коррекция по SNR
    # Если SNR высокий, можем увеличить плечо, если низкий - уменьшить
    # Формула коррекции: multiplier = 1 + (SNR - 1) * factor
    # Ограничиваем множитель снизу 0.5
    snr_multiplier = max(0.5, 1.0 + (snr - 1.0) * SNR_CORRECTION_FACTOR)
    
    adjusted_lev = base_lev * snr_multiplier
    
    # 3. Ограничение диапазона
    capped_lev = max(MIN_LEVERAGE, min(MAX_LEVERAGE, adjusted_lev))
    
    # 4. Округление до безопасных значений
    # До 5x шаг 0.5, выше 5x шаг 1.0
    if capped_lev <= 5.0:
        final_lev = round(capped_lev * 2) / 2.0
    else:
        final_lev = round(capped_lev)
        
    reason = f"Base:{base_lev:.2f}, SNR_Mult:{snr_multiplier:.2f}, Capped:{capped_lev:.2f}"
    
    return LeverageResult(
        calculated_leverage=adjusted_lev,
        final_leverage=final_lev,
        reason=reason
    )

if __name__ == "__main__":
    # Тестовые сценарии
    scenarios = [
        (0.01, 3.0), # Низкая волатильность, хороший сигнал -> Высокое плечо
        (0.05, 1.0), # Высокая волатильность, средний сигнал -> Низкое плечо
        (0.02, 0.5), # Средне, плохой сигнал -> Очень низкое плечо
    ]
    
    for atr, snr in scenarios:
        res = calculate_dynamic_leverage(atr, snr)
        print(f"ATR: {atr}, SNR: {snr} -> Lev: {res.final_leverage} ({res.reason})")