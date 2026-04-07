"""
Модуль управления трейлинг-стопом.
Реализация пошаговой логики в зависимости от роста позиции:
- До 200% прибыли: шаги 20%
- 200-500% прибыли: шаги 50%
- 500%+ прибыли: шаги 100%
"""
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Tuple
from enum import Enum
import logging

# CONFIG_REF: Пороги прибыли и шаги трейлинга
TRAILING_TIERS = [
    {"min_roi": Decimal("0"), "max_roi": Decimal("2.0"), "step_percent": Decimal("0.20")},      # 0-200%: шаг 20%
    {"min_roi": Decimal("2.0"), "max_roi": Decimal("5.0"), "step_percent": Decimal("0.50")},    # 200-500%: шаг 50%
    {"min_roi": Decimal("5.0"), "max_roi": Decimal("999"), "step_percent": Decimal("1.00")},    # 500%+: шаг 100%
]

MIN_PROFIT_FOR_TRAILING = Decimal("0.05")  # Минимальная прибыль 5% для активации трейлинга


class TrailingMode(Enum):
    """Режимы работы трейлинг-стопа."""
    INACTIVE = "inactive"           # Трейлинг не активирован
    ACTIVE = "active"               # Трейлинг активен
    TRIGGERED = "triggered"         # Стоп сработал


@dataclass
class PositionState:
    """Состояние позиции для управления трейлинг-стопом."""
    position_id: str
    entry_price: Decimal
    current_price: Decimal
    quantity: Decimal
    side: str  # 'LONG' или 'SHORT'
    current_stop_loss: Optional[Decimal] = None
    highest_price: Optional[Decimal] = None  # Для LONG
    lowest_price: Optional[Decimal] = None   # Для SHORT
    trailing_mode: TrailingMode = TrailingMode.INACTIVE
    last_stop_update_price: Optional[Decimal] = None
    
    @property
    def unrealized_pnl(self) -> Decimal:
        """Расчет нереализованного PnL."""
        if self.side == "LONG":
            return (self.current_price - self.entry_price) * self.quantity
        else:  # SHORT
            return (self.entry_price - self.current_price) * self.quantity
    
    @property
    def roi(self) -> Decimal:
        """Расчет ROI в процентах (как десятичная дробь)."""
        if self.entry_price == 0:
            return Decimal("0")
        
        if self.side == "LONG":
            return (self.current_price - self.entry_price) / self.entry_price
        else:  # SHORT
            return (self.entry_price - self.current_price) / self.entry_price
    
    @property
    def roi_percent(self) -> Decimal:
        """ROI в процентах (для отображения)."""
        return self.roi * Decimal("100")


@dataclass
class TrailingUpdate:
    """Результат обновления позиции."""
    position_id: str
    stop_loss_updated: bool
    new_stop_loss: Optional[Decimal]
    old_stop_loss: Optional[Decimal]
    trailing_mode: TrailingMode
    current_roi: Decimal
    reason: str
    update_price: Decimal


class TrailingStopManager:
    """
    Менеджер управления трейлинг-стопом с пошаговой логикой.
    
    Логика работы:
    1. При достижении прибыли MIN_PROFIT_FOR_TRAILING активируется трейлинг
    2. При движении цены в прибыль пересчитывается уровень стопа
    3. Шаг пересчета зависит от текущего ROI (20%, 50%, 100%)
    4. Стоп только повышается (для LONG) / понижается (для SHORT)
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Инициализация менеджера.
        
        Args:
            logger: Логгер для записи событий
        """
        self.logger = logger or logging.getLogger(__name__)
        self.position_states: dict[str, PositionState] = {}
    
    def register_position(
        self,
        position_id: str,
        entry_price: Decimal,
        quantity: Decimal,
        side: str,
        initial_stop_loss: Optional[Decimal] = None
    ) -> PositionState:
        """
        Регистрация новой позиции для отслеживания.
        
        Args:
            position_id: Уникальный идентификатор позиции
            entry_price: Цена входа
            quantity: Количество актива
            side: Направление ('LONG' или 'SHORT')
            initial_stop_loss: Начальный стоп-лосс
        
        Returns:
            Созданное состояние позиции
        """
        state = PositionState(
            position_id=position_id,
            entry_price=entry_price,
            current_price=entry_price,
            quantity=quantity,
            side=side.upper(),
            current_stop_loss=initial_stop_loss,
            highest_price=entry_price if side.upper() == "LONG" else None,
            lowest_price=entry_price if side.upper() == "SHORT" else None,
            trailing_mode=TrailingMode.INACTIVE
        )
        
        self.position_states[position_id] = state
        self.logger.info(f"Зарегистрирована позиция {position_id}: {side} @ {entry_price}")
        
        return state
    
    def _get_trailing_step(self, roi: Decimal) -> Decimal:
        """
        Определение шага трейлинга на основе текущего ROI.
        
        Args:
            roi: Текущий ROI позиции (как десятичная дробь)
        
        Returns:
            Процент шага (например, 0.20 для 20%)
        """
        for tier in TRAILING_TIERS:
            if tier["min_roi"] <= roi < tier["max_roi"]:
                return tier["step_percent"]
        
        # По умолчанию последний тир
        return TRAILING_TIERS[-1]["step_percent"]
    
    def _calculate_new_stop_loss(
        self,
        state: PositionState,
        step_percent: Decimal
    ) -> Decimal:
        """
        Расчет нового уровня стоп-лосса.
        
        Для LONG: Stop = HighestPrice × (1 - Step%)
        Для SHORT: Stop = LowestPrice × (1 + Step%)
        
        Args:
            state: Состояние позиции
            step_percent: Процент шага трейлинга
        
        Returns:
            Новый уровень стоп-лосса
        """
        if state.side == "LONG":
            if state.highest_price is None:
                return state.current_stop_loss or Decimal("0")
            
            new_stop = state.highest_price * (Decimal("1") - step_percent)
        else:  # SHORT
            if state.lowest_price is None:
                return state.current_stop_loss or Decimal("0")
            
            new_stop = state.lowest_price * (Decimal("1") + step_percent)
        
        # Округление до 8 знаков после запятой
        return new_stop.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    
    def update_position(
        self,
        position_id: str,
        new_price: Decimal
    ) -> Optional[TrailingUpdate]:
        """
        Обновление позиции новой ценой. Пересчет трейлинг-стопа.
        
        Логика:
        1. Обновляем текущую цену
        2. Обновляем экстремум (highest/lowest price)
        3. Проверяем, нужно ли активировать трейлинг
        4. Если активен, пересчитываем стоп с учетом шага
        5. Проверяем, не сработал ли стоп
        
        Args:
            position_id: Идентификатор позиции
            new_price: Новая цена актива
        
        Returns:
            TrailingUpdate с результатами обновления или None если позиция не найдена
        """
        if position_id not in self.position_states:
            self.logger.warning(f"Позиция {position_id} не найдена")
            return None
        
        state = self.position_states[position_id]
        old_stop = state.current_stop_loss
        old_price = state.current_price
        
        # Обновляем текущую цену
        state.current_price = new_price
        
        # Обновляем экстремумы
        if state.side == "LONG":
            if state.highest_price is None or new_price > state.highest_price:
                state.highest_price = new_price
        else:  # SHORT
            if state.lowest_price is None or new_price < state.lowest_price:
                state.lowest_price = new_price
        
        # Расчет ROI
        current_roi = state.roi
        
        # Проверка активации трейлинга
        if state.trailing_mode == TrailingMode.INACTIVE:
            if current_roi >= MIN_PROFIT_FOR_TRAILING:
                state.trailing_mode = TrailingMode.ACTIVE
                self.logger.info(
                    f"Трейлинг активирован для {position_id}. ROI: {state.roi_percent:.2f}%"
                )
        
        # Если трейлинг не активен, возвращаемся
        if state.trailing_mode != TrailingMode.ACTIVE:
            return TrailingUpdate(
                position_id=position_id,
                stop_loss_updated=False,
                new_stop_loss=old_stop,
                old_stop_loss=old_stop,
                trailing_mode=state.trailing_mode,
                current_roi=current_roi,
                reason="Трейлинг еще не активирован (прибыль < 5%)",
                update_price=new_price
            )
        
        # Получаем шаг трейлинга
        step_percent = self._get_trailing_step(current_roi)
        
        # Рассчитываем новый стоп
        new_stop = self._calculate_new_stop_loss(state, step_percent)
        
        # Проверяем, нужно ли обновлять стоп
        stop_updated = False
        update_reason = ""
        
        if state.side == "LONG":
            # Для LONG стоп только повышается
            if old_stop is None or new_stop > old_stop:
                state.current_stop_loss = new_stop
                state.last_stop_update_price = new_price
                stop_updated = True
                update_reason = f"LONG: Повышение стопа с {old_stop} до {new_stop} (шаг {step_percent*100:.0f}%)"
        else:  # SHORT
            # Для SHORT стоп только понижается
            if old_stop is None or new_stop < old_stop:
                state.current_stop_loss = new_stop
                state.last_stop_update_price = new_price
                stop_updated = True
                update_reason = f"SHORT: Понижение стопа с {old_stop} до {new_stop} (шаг {step_percent*100:.0f}%)"
        
        if stop_updated:
            self.logger.info(
                f"Стоп обновлен для {position_id}: {update_reason}"
            )
        else:
            update_reason = f"Стоп не изменился (текущий: {old_stop}, расчетный: {new_stop})"
        
        # Проверка срабатывания стопа
        if state.current_stop_loss is not None:
            if state.side == "LONG" and new_price <= state.current_stop_loss:
                state.trailing_mode = TrailingMode.TRIGGERED
                update_reason += " | СТОП СРАБОТАЛ!"
                self.logger.warning(f"СТОП СРАБОТАЛ для {position_id} @ {new_price}")
            elif state.side == "SHORT" and new_price >= state.current_stop_loss:
                state.trailing_mode = TrailingMode.TRIGGERED
                update_reason += " | СТОП СРАБОТАЛ!"
                self.logger.warning(f"СТОП СРАБОТАЛ для {position_id} @ {new_price}")
        
        return TrailingUpdate(
            position_id=position_id,
            stop_loss_updated=stop_updated,
            new_stop_loss=state.current_stop_loss,
            old_stop_loss=old_stop,
            trailing_mode=state.trailing_mode,
            current_roi=current_roi,
            reason=update_reason,
            update_price=new_price
        )
    
    def get_position_state(self, position_id: str) -> Optional[PositionState]:
        """Получение состояния позиции по ID."""
        return self.position_states.get(position_id)
    
    def remove_position(self, position_id: str) -> bool:
        """Удаление позиции из отслеживания."""
        if position_id in self.position_states:
            del self.position_states[position_id]
            self.logger.info(f"Позиция {position_id} удалена из отслеживания")
            return True
        return False
    
    def get_active_positions(self) -> List[PositionState]:
        """Получение всех активных позиций."""
        return [
            state for state in self.position_states.values()
            if state.trailing_mode == TrailingMode.ACTIVE
        ]


if __name__ == "__main__":
    # Пример использования
    logging.basicConfig(level=logging.INFO)
    
    manager = TrailingStopManager()
    
    # Создаем позицию LONG
    entry_price = Decimal("45000.00")
    quantity = Decimal("0.1")
    initial_sl = Decimal("44000.00")
    
    state = manager.register_position(
        position_id="pos_001",
        entry_price=entry_price,
        quantity=quantity,
        side="LONG",
        initial_stop_loss=initial_sl
    )
    
    print(f"Начальное состояние:")
    print(f"  Entry: {state.entry_price}")
    print(f"  Initial SL: {state.current_stop_loss}")
    print(f"  Mode: {state.trailing_mode.value}")
    print()
    
    # Симуляция движения цены
    test_prices = [
        Decimal("45500"),   # +1.1% - еще не активирован
        Decimal("47250"),   # +5% - активация
        Decimal("49500"),   # +10% - первый шаг
        Decimal("54000"),   # +20% - рост
        Decimal("67500"),   # +50% - переход на шаг 50%
        Decimal("90000"),   # +100% - переход на шаг 100%
        Decimal("85000"),   # Коррекция - проверка стопа
    ]
    
    for price in test_prices:
        update = manager.update_position("pos_001", price)
        if update:
            print(f"Цена: {price}")
            print(f"  ROI: {update.current_roi*100:.2f}%")
            print(f"  SL Updated: {update.stop_loss_updated}")
            if update.new_stop_loss:
                print(f"  New SL: {update.new_stop_loss}")
            print(f"  Mode: {update.trailing_mode.value}")
            print(f"  Reason: {update.reason}")
            print()
