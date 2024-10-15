import math
from decimal import Decimal

from lib.constants import KEY
from lib.exchange import AbstractExchange, Order


def get_zero_price(self, entry_price: Decimal, qty: float) -> Decimal:
    price = int(entry_price / self._tick_size)

    fee = math.ceil(self._config[KEY.FEE] * price)

    if qty > 0:
        return (price + fee) * self._tick_size
    else:
        return (price - fee) * self._tick_size


def handle_inventory(self, ask: Decimal, bid: Decimal):
    exchange: AbstractExchange = self._exchange
    # Do nothing if we are already sent MARKET order
    if self._state[KEY.MODE] == KEY.MODE_LIQUIDATION:
        return

    if self._state.get(KEY.PRICE, None) is None:
        self._state[KEY.MODE] = KEY.MODE_EMPTY
        self._state_repository.Push(self._state)
        return

    entry, qty = self._state[KEY.PRICE], self._state[KEY.QTY]

    price = bid if qty > 0 else ask

    distance = self._state.get(KEY.DISTANCE, None)

    if distance is None:
        distance = self._distance * entry / self._tick_size
        half_distance = math.floor(distance / 2) * self._tick_size
        distance = math.floor(distance) * self._tick_size
        self._state[KEY.DISTANCE] = distance
        self._state[KEY.HALF] = half_distance
        self._logger.info(f'We got new STOPLOSS distance', event='STOPLOSS', distance=distance)

        zero = get_zero_price(self, entry, qty)
        zero = zero + half_distance if qty > 0 else zero - half_distance
        self._logger.info(f'Find ZERO price when we HALF distance', event='STOPLOSS', zero=zero)
        self._state[KEY.ZERO] = zero
        self._state_repository.Push(self._state)

    # Half Distance after ZERO Level
    if self._state[KEY.ZERO] is not None:
        if qty > 0:
            if price >= self._state[KEY.ZERO]:
                distance = self._state[KEY.HALF]
                self._state[KEY.DISTANCE] = distance
                self._logger.warning(f'We got ZERO level + HALF distance', event='INVENTORY')
                self._state[KEY.ZERO] = None
                self._state_repository.Push(self._state)
        else:
            if price <= self._state[KEY.ZERO]:
                distance = self._state[KEY.HALF]
                self._state[KEY.DISTANCE] = distance
                self._logger.warning(f'We got ZERO level + HALF distance', event='INVENTORY')
                self._state[KEY.ZERO] = None
                self._state_repository.Push(self._state)

    # Solve possible Stoploss as FN from SIDE
    if qty > 0:
        possible_stoploss = price - distance
        current_stoploss = self._state.get(KEY.STOPLOSS, possible_stoploss)
        possible_stoploss = max(possible_stoploss, current_stoploss)
    else:
        possible_stoploss = price + distance
        current_stoploss = self._state.get(KEY.STOPLOSS, possible_stoploss)
        possible_stoploss = min(possible_stoploss, current_stoploss)

    current_stoploss = self._state.get(KEY.STOPLOSS, None)

    if current_stoploss != possible_stoploss:
        self._logger.info(f'NEW stoploss PRICE for {("LONG" if qty > 0 else "SHORT")}',
                          event='STOPLOSS', stoploss=possible_stoploss, entry=entry, price=price)
        self._state[KEY.STOPLOSS] = possible_stoploss
        self._state_repository.Push(self._state)

    if qty > 0:
        if price <= self._state[KEY.STOPLOSS]:
            exchange.Post(Order(-1 * qty))
            self._logger.warning(f'Hit LONG STOPLOSS. Post MARKET', event='STOPLOSS', ltp=price,
                                 stoploss=possible_stoploss)
            self._state[KEY.MODE] = KEY.MODE_LIQUIDATION
            self._state[KEY.TIMESTAMP] = self._timer.Timestamp()
            self._state_repository.Push(self._state)

    else:
        if price >= self._state[KEY.STOPLOSS]:
            exchange.Post(Order(-1 * qty))
            self._logger.warning(f'Hit SHORT STOPLOSS. Post MARKET', event='STOPLOSS', ltp=price,
                                 stoploss=possible_stoploss)
            self._state[KEY.MODE] = KEY.MODE_LIQUIDATION
            self._state[KEY.TIMESTAMP] = self._timer.Timestamp()
            self._state_repository.Push(self._state)
