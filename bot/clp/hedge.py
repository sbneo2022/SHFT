import copy
from decimal import Decimal
from typing import Optional

from bot import AbstractBot
from bot.clp.clp_atr import CLPATR
from bot.clp.mode.handle_inventory_dynamic_partial import handle_inventory_dynamic_partial
from lib.constants import KEY, ORDER_TAG
from lib.exchange import Order
from lib.factory import AbstractFactory
from lib.helpers import sign
from lib.timer import AbstractTimer

MAX_LATENCY = 500 * KEY.ONE_MS

class Hedge(CLPATR, AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, factory, timer)

        ################################################################
        # Hedging-specific parameters
        ################################################################

        self._source = self._config[KEY.SOURCE]

        self._side = int(self._config[KEY.SIDE])

        self._direction = int(self._config[KEY.DIRECTION])

        self._hedge_levels = []

        for item in self._config[KEY.HEDGE]:
            self._hedge_levels.append(copy.deepcopy(item))

        self._hedge_levels.sort(key=lambda x: x[KEY.THRESHOLD], reverse=True)

        self._remote_qty: Optional[Decimal] = None
        self._remote_max_qty: Optional[Decimal] = None

    def _is_message_valid(self, message: dict, timestamp: int, latency: int) -> bool:
        # filter message by several conditions
        if message.get(KEY.TYPE, None) != KEY.INVENTORY:
            return False

        if message.get(KEY.PROJECT, None) != self._source:
            return False

        if message.get(KEY.QTY, None) is None:
            return False

        if message.get(KEY.MAX_QTY, None) is None:
            return False

        if latency > MAX_LATENCY:
            return False

        return True

    def onMessage(self, message: dict,
                  timestamp: int, latency: int = 0):

        # Skip non-valid messages
        if not self._is_message_valid(message, timestamp, latency):
            return

        # Load remote Qty and Max Qty
        remote_qty = Decimal(message[KEY.QTY])
        remote_max_qty = Decimal(message[KEY.MAX_QTY])

        # Skip if remote values are not changes
        if (remote_qty, remote_max_qty) == (self._remote_qty, self._remote_max_qty):
            return

        self._remote_qty = remote_qty
        self._remote_max_qty = remote_max_qty

        self._logger.info(f'Receive new valid broadcasting message', payload=message)

        # "A x B" >= 0 if A (self._side) is ZERO or have the same
        # sign as B (remote_qty)
        if sign(self._side * remote_qty) >= 0:

            pct = abs(remote_qty) / remote_max_qty

            for item in self._hedge_levels:
                if pct > Decimal(item[KEY.THRESHOLD]):
                    qty = self._state.get(KEY.QTY, 0)
                    pending = self._state.get(KEY.PENDING, 0)

                    if KEY.MAX_PCT in item:
                        qty_to_be = abs(remote_qty) * Decimal(item[KEY.MAX_PCT])
                    else:
                        qty_to_be = Decimal(str(item[KEY.MAX_QTY]))

                    qty_to_be = self._direction * sign(remote_qty) * qty_to_be

                    if qty_to_be > 0:
                        delta = max(0, qty_to_be - (qty + pending))
                    elif qty_to_be < 0:
                        delta = min(0, qty_to_be - (qty + pending))
                    else:
                        delta = 0

                    midpoint = (self._ask + self._bid) / 2
                    order = self._exchange.applyRules(
                        Order(qty=delta, price=midpoint, tag=f'{ORDER_TAG.HEDGE}')
                    ).as_market_order()

                    if abs(order.qty) > 0:
                        id = self._exchange.Post(order)
                        self._state[KEY.PENDING] = pending + order.qty
                    else:
                        id = None

                    self._logger.warning(
                        f'POST Hedge order',
                        event='HEDGE', orderId=id,
                        should_be=qty_to_be, qty=order.qty, threshold=item[KEY.THRESHOLD],
                        side=self._side, direction=self._direction,
                        remote_qty=remote_qty, remote_max_qty=remote_max_qty,
                        pending=pending,
                    )

                    self._state_repository.Push(self._state)

                    break  # Handle only MAX level

    def _handle_new_orderbook_event(self, askPrice, bidPrice, latency):
        if self._state[KEY.MODE] == KEY.MODE_HALT:
            pass

        elif self._state[KEY.MODE] == KEY.MODE_INVENTORY:
            if self._handle_inventory:
                handle_inventory_dynamic_partial(self, askPrice, bidPrice)
