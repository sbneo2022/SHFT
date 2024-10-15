import math
from decimal import Decimal
from typing import Optional

from lib.constants import KEY, ORDER_TAG
from lib.exchange import AbstractExchange, Order
from lib.helpers import sign

#
# self --> Bot Object
#
# value --> how many seconds do not quote
#
# tag --> str message (reason) for log
#
def pause(self, value, tag=''):
    self._stop_quoting = self._timer.Timestamp() + value * KEY.ONE_SECOND
    self._logger.error(f'Stop quoting for {value}s', event='STOP', tag=tag)


def liquidation(self, value, tag=ORDER_TAG.MARKET):
    """
    :param self: Bot Object
    :param value: how many % of inventory to liquidate: i.e. 1 --> 100% --> liquidate ALL; 0.2 --> 20% --> liq. 20% of inventory
    :param tag: str message (reason) for orderId
    :return:
    """

    # NOTE: If inventory operations are OFF globally (using `handle_inventory: no` key)
    # we will block "liquidation" action as well
    if not self._handle_inventory:
        return

    exchange: AbstractExchange = self._exchange

    qty: Decimal = self._state.get(KEY.QTY, 0)
    pending: Decimal = self._state.get(KEY.PENDING, 0)
    qty = qty + pending

    stoploss: Optional[Decimal] = self._state.get(KEY.STOPLOSS, None)
    price: Decimal = self._bid if qty > 0 else self._ask

    # Find ABS value of qty we should liquidate -->
    qty_to_liquidate = math.ceil(abs(qty) * Decimal(value) / self._min_qty_size) * self._min_qty_size

    qty_to_liquidate = -1 * sign(qty) * qty_to_liquidate

    if abs(qty_to_liquidate) > KEY.ED:
        self._state[KEY.PENDING] = pending + qty_to_liquidate

        self._state[KEY.STOPLOSS] = None

        id = exchange.Post(Order(qty=qty_to_liquidate, tag=tag, liquidation=True))

        self._logger.warning(f'Liquidation event. Send MARKET order', event='STOPLOSS',
                             orderId=id, current=price, stoploss=stoploss, pending=self._state[KEY.PENDING])
    else:
        self._logger.warning(f'Liquidation event. No inventory')


ACTIONS_MAP = {
    KEY.PAUSE: pause,
    KEY.LIQUIDATION: liquidation
}
