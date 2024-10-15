from decimal import Decimal

from lib.async_ejector import FieldsAsyncEjector
from lib.constants import KEY, ORDER_TAG
from lib.exchange import AbstractExchange, Order
from lib.helpers import sign


def _get_stoploss_price(self, qty: Decimal, price: Decimal) -> Decimal:

    stoploss = price * (1 - sign(qty) * self._distance)

    return self._price_up(stoploss) if qty > 0 else self._price_down(stoploss)

def _estimate(self, qty: Decimal, entry: Decimal, price: Decimal) -> Decimal:
    return qty * (price - entry - self._fee * entry - self._fee * price)

def _update_state(self, qty: Decimal, entry: Decimal, current: Decimal, stoploss: Decimal):
    estimatePnl = _estimate(self, qty, entry, stoploss)
    self._logger.warning('Got new Stoploss Price', event='STOPLOSS',
                         qty=qty, stoploss=stoploss, entry=entry, current=current, estimatePnl=estimatePnl)
    self._state[KEY.STOPLOSS] = stoploss
    self._state[KEY.ESTIMATE_PNL] = estimatePnl
    self._state_repository.Push(self._state)
    FieldsAsyncEjector(self._database, self._timer, stoploss=stoploss, entry=entry).start()

def handle_inventory_static(self, ask: Decimal, bid: Decimal):
    exchange: AbstractExchange = self._exchange
    # Get current portfolio, qty and pending from State
    qty = self._state.get(KEY.QTY, 0)
    entry = self._state.get(KEY.PRICE, None)
    pending = self._state.get(KEY.PENDING, 0)

    # Basically we should not call this fn when Qty == 0 or we have no Entry price,
    # but if it happens --> handle correct: do nothing
    # Also we will do nothing while Pending non-zero -- only to increase performance
    # In general case we can handle increasing Pending
    if abs(qty) < KEY.ED or entry is None or abs(pending) > KEY.ED:
        return

    # Get previous Stoploss price from State. None means we have no Stoploss price --> will set new
    current_stoploss = self._state.get(KEY.STOPLOSS, None)

    # We will use Bid price for Long positions to liquidate, Ask for Short
    price = bid if qty > 0 else ask

    # For first call with new inventory we will use Entry price for stoploss Level,
    # else current price
    price_for_stoploss = entry if current_stoploss is None else price
    stoploss = _get_stoploss_price(self, qty, price_for_stoploss)

    # For Long positions we move Stoploss only UP, for Short -- only Down
    fn = max if qty > 0 else min
    new_stoploss = fn(current_stoploss or stoploss, stoploss)

    if new_stoploss != current_stoploss:
        _update_state(self, qty, entry, price, new_stoploss)

    # We have Stoploss Event --> prepare MARKET order, take "pending" into account
    if sign(qty) * (price - new_stoploss) <= 0:
        new_qty = -1 * sign(qty) * max(0, abs(qty) - abs(pending))
        if abs(new_qty) > KEY.ED:
            # Change pending. In general we r able to increase it.
            self._state[KEY.PENDING] = pending + new_qty
            self._state[KEY.STOPLOSS] = None
            id = exchange.Post(Order(new_qty, tag=ORDER_TAG.MARKET, liquidation=True))

            self._logger.warning(f'Hit Stoploss. Send MARKET order', event='STOPLOSS',
                                 orderId=id, current=price, stoploss=new_stoploss, pending=self._state[KEY.PENDING])

            # We r update Pending --> have to save State
            self._state_repository.Push(self._state)