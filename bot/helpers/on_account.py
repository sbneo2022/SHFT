from decimal import Decimal

from lib.constants import KEY
from lib.helpers import sign

LIQUIDATION_TIME = 1 * KEY.ONE_SECOND


def handle_stop_mode(self):
    if self._state.get(KEY.STATE, None) != KEY.STATE_STOP_QUOTING:
        self._quoting = True
    elif not self._quoting:
        self._quoting = True
        self._stop_quoting = self._timer.Timestamp() + self._high_losses_pause
        self._logger.error(f'PAUSE quoting for {self._high_losses_pause // KEY.ONE_SECOND}s', event='STOP')


def onAccount(self, price: Decimal, qty: Decimal,
              timestamp: int, latency: int = 0):

    pending = self._state.get(KEY.PENDING, 0)
    self._logger.warning(f'NEW INVENTORY: {qty}', qty=qty, pending=pending)

    delta = qty - self._state.get(KEY.QTY, 0)
    self._state[KEY.QTY] = qty

    if sign(delta) == sign(pending):
        _new_pending = max(0, abs(pending) - abs(delta))
        self._state[KEY.PENDING] = sign(pending) * _new_pending

    if self._state[KEY.MODE] == KEY.MODE_EMPTY:
        if abs(qty) > KEY.ED:
            self._logger.warning(f'Change MODE: EMPTY->INVENTORY', entry=price, qty=qty)
            self._state[KEY.MODE] = KEY.MODE_INVENTORY
            self._state[KEY.PRICE] = price
            self._state[KEY.STOPLOSS] = None

    elif self._state[KEY.MODE] == KEY.MODE_INVENTORY:
        if abs(qty) < KEY.E:
            self._logger.warning(f'FORCE change MODE: INVENTORY->EMPTY', entry=price, qty=qty)
            handle_stop_mode(self)
            self._state = self._build_empty_state()
        else:
            self._logger.warning(f'Inventory change; Reset Stoploss price', entry=price, qty=qty)
            self._state[KEY.PRICE] = price
            self._state[KEY.STOPLOSS] = None

    self._state_repository.Push(self._state)