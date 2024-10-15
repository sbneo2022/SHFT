import math
from decimal import Decimal
from typing import Tuple

from bot.helpers.solve_stoploss import get_zero_price
from lib.async_ejector import FieldsAsyncEjector
from lib.constants import KEY, ORDER_TAG
from lib.exchange import AbstractExchange, Order
from lib.helpers import sign


def _get_stoploss_price(self, entry_price: Decimal, qty: Decimal, current_price: Decimal,
                        offset: Decimal, state) -> Tuple[Decimal, Decimal]:
    if state == KEY.STATE_FIRST_HIT:
        _trailing_profit = self._stoploss_trailing_profit
        _entry_price = offset
        _fee = 0
        _distance = self._distance * Decimal('0.25')  # 1.5 - 1

    elif state == KEY.STATE_SECOND_HIT:
        _trailing_profit = self._stoploss_trailing_profit
        _entry_price = offset
        _fee = 0
        _distance = self._distance * Decimal('0.25')  # 1.5 - 1

    else:
        _trailing_profit = self._trailing_profit
        _entry_price = entry_price
        _fee = self._config[KEY.FEE]
        _distance = self._distance


    zero = get_zero_price(self._exchange, qty, _entry_price, fee=Decimal(_fee))

    adjusted_zero = zero * (1 + sign(qty) * _trailing_profit)

    if sign(qty) * (current_price - adjusted_zero) <= 0:
        distance = _distance
        break_price = adjusted_zero
    else:
        distance = _trailing_profit
        break_price = None

    stoploss = current_price * (1 - sign(qty) * distance)

    return (break_price, self._price_up(stoploss) if qty > 0 else self._price_down(stoploss))

def _estimate(self, qty: Decimal, entry: Decimal, price: Decimal) -> Decimal:
    return qty * (price - entry - self._fee * entry - self._fee * price)

def _update_state(self, qty: Decimal, entry: Decimal, current: Decimal, stoploss: Decimal, break_price: Decimal):
    estimatePnl = _estimate(self, qty, entry, stoploss)
    distance_tick = abs(stoploss - current) / self._tick_size
    self._logger.warning('Got new Stoploss Price', event='STOPLOSS',
                         qty=qty, stoploss=stoploss, entry=entry, current=current,
                         estimatePnl=estimatePnl, distance_tick=distance_tick)
    self._state[KEY.STOPLOSS] = stoploss
    self._state[KEY.ESTIMATE_PNL] = estimatePnl
    self._state[KEY.DISTANCE] = distance_tick
    self._state[KEY.BREAK_PRICE] = break_price
    if self._state.get(KEY.STATE, None) is None:
        self._state[KEY.STATE] = KEY.STATE_NORMAL
    self._state_repository.Push(self._state)
    FieldsAsyncEjector(self._database, self._timer, stoploss=stoploss, entry=entry, break_price=break_price).start()


def handle_inventory_dynamic_partial(self, ask: Decimal, bid: Decimal):
    # Get current portfolio, qty and pending from State
    exchange: AbstractExchange = self._exchange
    qty = self._state.get(KEY.QTY, 0)
    offset = self._state.get(KEY.OFFSET, 0)
    entry = self._state.get(KEY.PRICE, 0)
    pending = self._state.get(KEY.PENDING, 0)
    state = self._state.get(KEY.STATE, KEY.STATE_NORMAL)

    # Basically we should not call this fn when Qty == 0 or we have no Entry price,
    # but if it happens --> handle correct: do nothing
    if abs(qty) < KEY.ED or entry is None \
            or self._distance is None:
        return

    # Get previous Stoploss price from State. None means we have no Stoploss price --> will set new
    current_stoploss = self._state.get(KEY.STOPLOSS, None)

    # We will use Bid price for Long positions to liquidate, Ask for Short
    price = bid if qty > 0 else ask

    # For first call with new inventory we will use Entry price for stoploss Level,
    # else current price
    price_for_stoploss = entry if current_stoploss is None else price
    # break_price, stoploss = _get_stoploss_price(self, entry, qty, price_for_stoploss, offset, state)
    break_price, stoploss = _get_stoploss_price(self, entry, qty, price, offset, state)

    # For Long positions we move Stoploss only UP, for Short -- only Down
    fn = max if qty > 0 else min
    new_stoploss = fn(current_stoploss or stoploss, stoploss)

    if new_stoploss != current_stoploss:
        _update_state(self, qty, entry, price, new_stoploss, break_price)

    # We have Stoploss Event --> prepare MARKET order, take "pending" into account
    if sign(qty) * (price - new_stoploss) <= 0:
        if self._state[KEY.BREAK_PRICE] is None:
            new_qty = -1 * sign(qty) * max(0, abs(qty) - abs(pending))
            original_state = self._state[KEY.STATE]  # We have to save STATE to decide later pu
            if abs(new_qty) > KEY.ED:
                # Change pending. In general we r able to increase it.
                self._state[KEY.PENDING] = pending + new_qty
                self._state[KEY.STATE] = KEY.STATE_NORMAL
                self._state[KEY.STOPLOSS] = None

                id = exchange.Post(Order(qty=new_qty, tag=ORDER_TAG.TAKE_PROFIT, liquidation=True))

                self._logger.warning(f'Liquidate with profit. Send MARKET order',
                                     event='STOPLOSS', orderId=id, current=price, stoploss=new_stoploss, pending=self._state[KEY.PENDING],
                                     break_price=break_price)

                # We r update Pending --> have to save State
                self._state_repository.Push(self._state)

            tag = KEY.LIQUIDATION if original_state in [KEY.STATE_FIRST_HIT, KEY.STATE_SECOND_HIT] else KEY.TAKE_PROFIT
            self._producer.Send(
                self._iterative_messages.Add(
                    {
                        KEY.TYPE: KEY.INVENTORY,
                        tag: 1,
                        KEY.PROJECT: self._project_name,
                        KEY.TIMESTAMP: self._timer.Timestamp()
                    }
                )
            )

        elif self._state[KEY.STATE] == KEY.STATE_NORMAL:
            self._quoting = False
            self._state[KEY.STATE] = KEY.STATE_FIRST_HIT
            self._state[KEY.OFFSET] = new_stoploss
            qty_for_liquidation = math.ceil(self._first_liquidation * abs(qty) / self._min_qty_size) * self._min_qty_size
            new_qty = -1 * sign(qty) * max(0, abs(qty_for_liquidation) - abs(pending))

            if abs(new_qty) > KEY.ED:
                # Change pending. In general we r able to increase it.
                self._state[KEY.PENDING] = pending + new_qty
                self._state[KEY.STOPLOSS] = None

                id = exchange.Post(Order(qty=new_qty, tag=ORDER_TAG.STOP_LOSSES_1, liquidation=True))

                self._logger.warning(f'Hit FIRST Stoploss. Send MARKET order for {self._first_liquidation * 100}% of inventory',
                                     event='STOPLOSS', orderId=id, current=price, stoploss=new_stoploss, pending=self._state[KEY.PENDING],
                                     break_price=break_price)

                # We r update Pending --> have to save State
                self._state_repository.Push(self._state)

            self._producer.Send({KEY.TYPE: KEY.INVENTORY, KEY.LIQUIDATION: self._first_liquidation,
                                 KEY.PROJECT: self._project_name, KEY.TIMESTAMP: self._timer.Timestamp()})

        elif self._state[KEY.STATE] == KEY.STATE_FIRST_HIT:
            self._quoting = False
            self._state[KEY.STATE] = KEY.STATE_SECOND_HIT
            self._state[KEY.OFFSET] = new_stoploss
            qty_for_liquidation = math.ceil(self._second_liquidation * abs(qty) / self._min_qty_size) * self._min_qty_size
            new_qty = -1 * sign(qty) * max(0, abs(qty_for_liquidation) - abs(pending))

            if abs(new_qty) > KEY.ED:
                # Change pending. In general we r able to increase it.
                self._state[KEY.PENDING] = pending + new_qty
                self._state[KEY.STOPLOSS] = None

                id = exchange.Post(Order(qty=new_qty, tag=ORDER_TAG.STOP_LOSSES_2, liquidation=True))

                self._logger.warning(f'Hit SECOND Stoploss. Send MARKET order for {self._second_liquidation * 100}% of inventory',
                                     event='STOPLOSS', orderId=id, current=price, stoploss=new_stoploss, pending=self._state[KEY.PENDING],
                                     break_price=break_price)

                # We r update Pending --> have to save State
                self._state_repository.Push(self._state)

            self._producer.Send({KEY.TYPE: KEY.INVENTORY, KEY.LIQUIDATION: self._second_liquidation,
                                 KEY.PROJECT: self._project_name, KEY.TIMESTAMP: self._timer.Timestamp()})

        elif self._state[KEY.STATE] == KEY.STATE_SECOND_HIT:
            self._quoting = False
            self._state[KEY.STATE] = KEY.STATE_STOP_QUOTING
            new_qty = -1 * sign(qty) * max(0, abs(qty) - abs(pending))
            if abs(new_qty) > KEY.ED:
                # Change pending. In general we r able to increase it.
                self._state[KEY.PENDING] = pending + new_qty
                self._state[KEY.STOPLOSS] = None

                id = exchange.Post(Order(qty=new_qty, tag=ORDER_TAG.STOP_LOSSES_3, liquidation=True))

                self._logger.warning(f'Liquidate Rest. Send MARKET order and STOP',
                                     event='STOPLOSS', orderId=id, current=price, stoploss=new_stoploss, pending=self._state[KEY.PENDING],
                                     break_price=break_price)

                # We r update Pending --> have to save State
                self._state_repository.Push(self._state)

            self._producer.Send(
                self._iterative_messages.Add(
                    {
                        KEY.TYPE: KEY.INVENTORY,
                        KEY.LIQUIDATION: 1,
                        KEY.PROJECT: self._project_name,
                        KEY.TIMESTAMP: self._timer.Timestamp()
                    }
                )
            )
