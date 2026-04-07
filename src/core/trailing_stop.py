"""
Менеджер трейлинг-стопа.
Режимы:
- ROI < 200%: Шаг 20% от прироста
- 200% <= ROI < 500%: Шаг 50%
- ROI >= 500%: Шаг 100% (Breakeven+ или фиксация основной прибыли)
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from decimal import Decimal

class PositionSide(Enum):
    LONG = "LONG"
    SHORT = "SHORT"

@dataclass
class PositionState:
    side: PositionSide
    entry_price: Decimal
    current_price: Decimal
    current_stop_loss: Decimal
    realized_pnl: Decimal = Decimal('0')

@dataclass
class TrailingUpdate:
    new_stop_loss: Decimal
    roi_percent: Decimal
    updated: bool
    message: str

class TrailingStopManager:
    def __init__(self):
        # CONFIG_REF: Пороги ROI (в процентах как Decimal)
        self.THRESHOLD_1 = Decimal('2.0')   # 200%
        self.THRESHOLD_2 = Decimal('5.0')   # 500%
        
        # CONFIG_REF: Шаги фиксации (доля от прироста, которую оставляем)
        self.STEP_LOW = Decimal('0.20')     # 20%
        self.STEP_MID = Decimal('0.50')     # 50%
        self.STEP_HIGH = Decimal('1.00')    # 100%

    def calculate_roi(self, pos: PositionState) -> Decimal:
        """Расчет ROI в процентах (например, 0.5 = 50%, 2.0 = 200%)"""
        if pos.entry_price == 0:
            return Decimal('0')
        
        if pos.side == PositionSide.LONG:
            diff = pos.current_price - pos.entry_price
        else:
            diff = pos.entry_price - pos.current_price
            
        return (diff / pos.entry_price) * 100

    def update_position(self, pos: PositionState, new_price: Decimal) -> TrailingUpdate:
        """
        Обновление состояния позиции и расчет нового Stop Loss.
        Логика:
        1. Считаем текущий ROI.
        2. Выбираем режим шага.
        3. Рассчитываем идеальный стоп.
        4. Двигаем стоп только если новый лучше старого (для LONG выше, для SHORT ниже).
        """
        pos.current_price = new_price
        roi = self.calculate_roi(pos)
        
        # Определение шага в зависимости от ROI
        if roi < self.THRESHOLD_1:
            step = self.STEP_LOW
            mode = "Aggressive (20%)"
        elif roi < self.THRESHOLD_2:
            step = self.STEP_MID
            mode = "Moderate (50%)"
        else:
            step = self.STEP_HIGH
            mode = "Conservative (100%)"
            
        # Расчет идеального уровня стопа
        # Для LONG: Entry + (Profit * Step)
        # Для SHORT: Entry - (Profit * Step)
        if pos.side == PositionSide.LONG:
            profit = pos.current_price - pos.entry_price
            ideal_stop = pos.entry_price + (profit * step)
            
            # Стоп не должен быть ниже текущего стопа (движение только вверх)
            if ideal_stop > pos.current_stop_loss:
                new_sl = ideal_stop
                updated = True
                msg = f"Trailing UP to {new_sl:.2f} (Mode: {mode}, ROI: {roi:.1f}%)"
            else:
                new_sl = pos.current_stop_loss
                updated = False
                msg = f"Hold SL at {new_sl:.2f} (ROI: {roi:.1f}%)"
                
        else: # SHORT
            profit = pos.entry_price - pos.current_price
            ideal_stop = pos.entry_price - (profit * step)
            
            # Стоп не должен быть выше текущего стопа (движение только вниз)
            if ideal_stop < pos.current_stop_loss:
                new_sl = ideal_stop
                updated = True
                msg = f"Trailing DOWN to {new_sl:.2f} (Mode: {mode}, ROI: {roi:.1f}%)"
            else:
                new_sl = pos.current_stop_loss
                updated = False
                msg = f"Hold SL at {new_sl:.2f} (ROI: {roi:.1f}%)"
        
        # Обновляем состояние
        pos.current_stop_loss = new_sl
        
        return TrailingUpdate(
            new_stop_loss=new_sl,
            roi_percent=roi,
            updated=updated,
            message=msg
        )

if __name__ == "__main__":
    manager = TrailingStopManager()
    
    # Сценарий LONG
    pos = PositionState(
        side=PositionSide.LONG,
        entry_price=Decimal('100.0'),
        current_price=Decimal('100.0'),
        current_stop_loss=Decimal('95.0') # Initial SL
    )
    
    prices = [105, 110, 120, 150, 200, 600] # Рост до 600%
    
    print(f"{'Price':<10} | {'ROI %':<10} | {'New SL':<10} | {'Updated'} | Message")
    print("-" * 80)
    
    for p in prices:
        price_dec = Decimal(str(p))
        res = manager.update_position(pos, price_dec)
        print(f"{price_dec:<10} | {res.roi_percent:<10.1f} | {res.new_stop_loss:<10.2f} | {str(res.updated):<7} | {res.message}")