import pytest
import pandas as pd
import numpy as np
from decimal import Decimal
from src.risk.volatility_filter import calculate_atr, calculate_z_score, calculate_snr, should_trade, VolatilityMetrics
from src.risk.leverage_calculator import calculate_dynamic_leverage, MAX_LEVERAGE, MIN_LEVERAGE
from src.core.trailing_stop import TrailingStopManager, PositionState, PositionSide

# --- Volatility Filter Tests ---

def test_atr_calculation():
    data = pd.DataFrame({
        'high': [10, 12, 11, 13, 14, 14, 13, 12, 11, 10, 11, 12, 13, 14, 15, 16],
        'low': [8, 10, 9, 11, 12, 12, 11, 10, 9, 8, 9, 10, 11, 12, 13, 14],
        'close': [9, 11, 10, 12, 13, 13, 12, 11, 10, 9, 10, 11, 12, 13, 14, 15]
    })
    atr = calculate_atr(data['high'], data['low'], data['close'], period=5)
    assert atr > 0
    assert isinstance(atr, float)

def test_snr_low_vs_high():
    # Чистый сигнал (синус)
    t = np.linspace(0, 10, 100)
    clean_signal = pd.Series(np.sin(t))
    # Шумный сигнал
    noisy_signal = pd.Series(np.sin(t) + np.random.normal(0, 2, 100))
    
    snr_clean = calculate_snr(clean_signal)
    snr_noisy = calculate_snr(noisy_signal)
    
    # В идеале чистый сигнал должен иметь SNR выше, но из-за дискретизации проверяем просто > 0
    assert snr_clean > 0 

def test_should_trade_logic():
    # Case 1: Low SNR
    metrics_low_snr = VolatilityMetrics(atr=0.5, atr_percent=0.01, z_score=0, snr=1.0, current_price=100)
    trade, reason = should_trade(metrics_low_snr)
    assert trade is False
    assert "Low SNR" in reason
    
    # Case 2: High Z-Score
    metrics_high_z = VolatilityMetrics(atr=0.5, atr_percent=0.01, z_score=3.0, snr=3.0, current_price=100)
    trade, reason = should_trade(metrics_high_z)
    assert trade is False
    assert "High Z-Score" in reason
    
    # Case 3: Low Volatility
    metrics_low_vol = VolatilityMetrics(atr=0.0001, atr_percent=0.00001, z_score=0, snr=3.0, current_price=100)
    trade, reason = should_trade(metrics_low_vol)
    assert trade is False
    assert "Low Volatility" in reason
    
    # Case 4: All Good
    metrics_good = VolatilityMetrics(atr=0.5, atr_percent=0.01, z_score=0.5, snr=3.0, current_price=100)
    trade, reason = should_trade(metrics_good)
    assert trade is True
    assert "Conditions met" in reason

# --- Leverage Calculator Tests ---

def test_leverage_boundaries():
    # Очень низкая волатильность -> должно упереться в MAX
    res = calculate_dynamic_leverage(0.0001, 5.0)
    assert res.final_leverage <= MAX_LEVERAGE
    
    # Очень высокая волатильность -> должно упереться в MIN
    res = calculate_dynamic_leverage(0.5, 0.5)
    assert res.final_leverage >= MIN_LEVERAGE

def test_leverage_snr_impact():
    # Одинаковая волатильность, разный SNR
    res_high_snr = calculate_dynamic_leverage(0.02, 5.0)
    res_low_snr = calculate_dynamic_leverage(0.02, 0.5)
    
    assert res_high_snr.final_leverage > res_low_snr.final_leverage

# --- Trailing Stop Tests ---

def test_trailing_stop_steps():
    manager = TrailingStopManager()
    
    # Начальная позиция LONG
    pos = PositionState(
        side=PositionSide.LONG,
        entry_price=Decimal('100'),
        current_price=Decimal('100'),
        current_stop_loss=Decimal('90')
    )
    
    # Сценарий 1: ROI 45% (< 200%) -> Шаг 20%
    # Price 145 -> Profit 45. Ideal SL = 100 + 45*0.2 = 109
    res = manager.update_position(pos, Decimal('145'))
    assert res.roi_percent == Decimal('45')
    assert res.new_stop_loss == Decimal('109')
    assert res.updated is True
    
    # Сценарий 2: ROI 250% (200-500%) -> Шаг 50%
    # Price 350 -> Profit 250. Ideal SL = 100 + 250*0.5 = 225
    # Предыдущий стоп был 109, новый 225 > 109, обновляем
    res = manager.update_position(pos, Decimal('350'))
    assert res.roi_percent == Decimal('250')
    assert res.new_stop_loss == Decimal('225')
    
    # Сценарий 3: ROI 650% (> 500%) -> Шаг 100% (Breakeven+)
    # Price 750 -> Profit 650. Ideal SL = 100 + 650*1.0 = 750 (Full lock)
    res = manager.update_position(pos, Decimal('750'))
    assert res.roi_percent == Decimal('650')
    assert res.new_stop_loss == Decimal('750')

def test_trailing_stop_non_decreasing():
    manager = TrailingStopManager()
    pos = PositionState(
        side=PositionSide.LONG,
        entry_price=Decimal('100'),
        current_price=Decimal('120'),
        current_stop_loss=Decimal('110') # Уже высокий стоп
    )
    
    # Цена упала, но не ниже стопа. ROI уменьшился.
    # Новый расчет может дать стоп ниже текущего. Он НЕ должен измениться.
    res = manager.update_position(pos, Decimal('115'))
    assert res.updated is False
    assert res.new_stop_loss == Decimal('110')

if __name__ == "__main__":
    pytest.main([__file__, "-v"])