"""
Модуль расчета динамического плеча (левериджа).
Формула: Lev = Risk_ROI / (ATR% × K), с коррекцией по SNR.
"""
import numpy as np
from dataclasses import dataclass
from typing import Optional
from enum import Enum

# CONFIG_REF: Параметры расчета плеча
BASE_RISK_ROI = 0.02       # Целевой риск на сделку (2%)
K_FACTOR = 1.5             # Коэффициент запаса безопасности
MAX_LEVERAGE = 20          # Максимальное плечо биржи
MIN_LEVERAGE = 1           # Минимальное плечо
SNR_CORRECTION_FACTOR = 0.8  # Множитель коррекции по SNR


class LeverageTier(Enum):
    """Уровни безопасного плеча для округления."""
    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3
    TIER_4 = 5
    TIER_5 = 7
    TIER_6 = 10
    TIER_7 = 15
    TIER_8 = 20


@dataclass
class LeverageResult:
    """Результат расчета плеча."""
    raw_leverage: float         # Расчетное значение до округления
    safe_leverage: int          # Округленное до безопасного уровня
    snr_correction: float       # Примененная коррекция по SNR
    reason: str                 # Пояснение расчета
    is_valid: bool              # Валидно ли для торговли


def get_safe_leverage_tier(raw_value: float) -> int:
    """
    Округление плеча до ближайшего безопасного уровня.
    
    Логика: выбираем ближайшее меньшее значение из фиксированных тиров.
    Это предотвращает использование пограничных значений, которые могут
    привести к ликвидации при небольшом движении рынка.
    
    Args:
        raw_value: Рассчитанное значение плеча
    
    Returns:
        Безопасный уровень плеча
    """
    if raw_value < 1:
        return 1
    
    tiers = [t.value for t in LeverageTier]
    
    # Находим наибольший тир, который меньше или равен raw_value
    safe_tier = 1
    for tier in tiers:
        if tier <= raw_value:
            safe_tier = tier
        else:
            break
    
    return safe_tier


def calculate_leverage(
    atr_percent: float,
    snr: float,
    risk_roi: float = BASE_RISK_ROI,
    k_factor: float = K_FACTOR,
    max_leverage: int = MAX_LEVERAGE
) -> LeverageResult:
    """
    Расчет динамического плеча на основе волатильности и качества сигнала.
    
    Формула:
    1. Base_Lev = Risk_ROI / (ATR% × K)
    2. SNR_Correction = 1.0 если SNR >= 1.0, иначе SNR ^ SNR_CORRECTION_FACTOR
    3. Final_Lev = Base_Lev × SNR_Correction
    4. Safe_Lev = округление до ближайшего безопасного тира
    
    Args:
        atr_percent: ATR в процентах от цены (например, 0.015 для 1.5%)
        snr: Signal-to-Noise Ratio из модуля volatility_filter
        risk_roi: Целевой процент риска на сделку (по умолчанию 2%)
        k_factor: Коэффициент запаса безопасности (по умолчанию 1.5)
        max_leverage: Максимально допустимое плечо
    
    Returns:
        LeverageResult с рассчитанными значениями
    """
    # Проверка входных данных
    if atr_percent <= 0:
        return LeverageResult(
            raw_leverage=0.0,
            safe_leverage=0,
            snr_correction=0.0,
            reason="Невалидный ATR (должен быть > 0)",
            is_valid=False
        )
    
    if snr < 0:
        return LeverageResult(
            raw_leverage=0.0,
            safe_leverage=0,
            snr_correction=0.0,
            reason="Невалидный SNR (не может быть отрицательным)",
            is_valid=False
        )
    
    # Базовый расчет плеча
    # Чем выше волатильность (ATR%), тем меньше плечо
    base_leverage = risk_roi / (atr_percent * k_factor)
    
    # Коррекция по SNR
    # Если SNR >= 1.0 (сигнал сильнее шума), коррекция = 1.0 (полное плечо)
    # Если SNR < 1.0 (шум преобладает), уменьшаем плечо
    if snr >= 1.0:
        snr_correction = 1.0
    else:
        # Нелинейная коррекция: чем меньше SNR, тем сильнее уменьшение
        snr_correction = max(0.1, pow(snr, SNR_CORRECTION_FACTOR))
    
    # Финальное плечо с коррекцией
    raw_leverage = base_leverage * snr_correction
    
    # Ограничение максимумом
    raw_leverage = min(raw_leverage, max_leverage)
    
    # Округление до безопасного уровня
    safe_leverage = get_safe_leverage_tier(raw_leverage)
    
    # Формирование пояснения
    reason_parts = [
        f"ATR%={atr_percent:.4f}",
        f"SNR={snr:.2f}",
        f"Base={base_leverage:.2f}x",
        f"SNR_corr={snr_correction:.2f}",
        f"Raw={raw_leverage:.2f}x",
        f"Safe={safe_leverage}x"
    ]
    
    return LeverageResult(
        raw_leverage=raw_leverage,
        safe_leverage=safe_leverage,
        snr_correction=snr_correction,
        reason=", ".join(reason_parts),
        is_valid=True
    )


def validate_leverage_for_trade(
    leverage_result: LeverageResult,
    min_acceptable_leverage: int = 2
) -> bool:
    """
    Проверка, подходит ли рассчитанное плечо для открытия позиции.
    
    Критерии:
    1. Результат валиден (is_valid=True)
    2. Плечо не меньше минимально приемлемого
    3. Плечо не превышает максимальное
    
    Args:
        leverage_result: Результат расчета плеча
        min_acceptable_leverage: Минимальное допустимое плечо
    
    Returns:
        True если плечо подходит для торговли
    """
    if not leverage_result.is_valid:
        return False
    
    if leverage_result.safe_leverage < min_acceptable_leverage:
        return False  # Слишком низкое плечо, сделка неэффективна
    
    if leverage_result.safe_leverage > MAX_LEVERAGE:
        return False  # Превышение максимума биржи
    
    return True


if __name__ == "__main__":
    # Примеры использования для разных сценариев
    
    print("=== Сценарий 1: Нормальные условия ===")
    result1 = calculate_leverage(atr_percent=0.015, snr=2.5)
    print(f"ATR: 1.5%, SNR: 2.5")
    print(f"Результат: {result1.safe_leverage}x")
    print(f"Причина: {result1.reason}")
    print(f"Валидно: {result1.is_valid}")
    print()
    
    print("=== Сценарий 2: Высокая волатильность ===")
    result2 = calculate_leverage(atr_percent=0.05, snr=1.8)
    print(f"ATR: 5.0%, SNR: 1.8")
    print(f"Результат: {result2.safe_leverage}x")
    print(f"Причина: {result2.reason}")
    print()
    
    print("=== Сценарий 3: Низкий SNR (шумный рынок) ===")
    result3 = calculate_leverage(atr_percent=0.02, snr=0.3)
    print(f"ATR: 2.0%, SNR: 0.3")
    print(f"Результат: {result3.safe_leverage}x")
    print(f"Причина: {result3.reason}")
    print()
    
    print("=== Сценарий 4: Очень низкая волатильность ===")
    result4 = calculate_leverage(atr_percent=0.003, snr=3.0)
    print(f"ATR: 0.3%, SNR: 3.0")
    print(f"Результат: {result4.safe_leverage}x")
    print(f"Причина: {result4.reason}")
    print()
    
    print("=== Проверка на пригодность для торговли ===")
    print(f"Сценарий 1: {validate_leverage_for_trade(result1)}")
    print(f"Сценарий 2: {validate_leverage_for_trade(result2)}")
    print(f"Сценарий 3: {validate_leverage_for_trade(result3)}")
    print(f"Сценарий 4: {validate_leverage_for_trade(result4)}")
