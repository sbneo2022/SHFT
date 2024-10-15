from collections import deque
from decimal import Decimal
from typing import Optional, List

from bot import AbstractBot
from bot.iea.modules.handle_alive import HandleAlive
from bot.iea.modules.handle_buffer import HandleBuffer
from bot.iea.modules.handle_clean_cancel import HandleCleanCancel
from bot.iea.modules.handle_exchange import HandleExchange
from bot.iea.modules.handle_inventory import HandleInventory
from bot.iea.modules.handle_state import HandleState
from bot.iea.modules.handle_warming_up import HandleWarmingUp
from bot.iea.modules.handle_watchdog import HandleWatchdog
from lib.constants import KEY
from lib.defaults import DEFAULT
from lib.exchange import Order
from lib.factory import AbstractFactory
from lib.helpers import sign
from lib.timer import AbstractTimer



class IMomentum(
    HandleWarmingUp,
    HandleInventory,
    HandleWatchdog,
    HandleCleanCancel,
    HandleState,
    HandleAlive,
    HandleBuffer,
    HandleExchange,
    AbstractBot
):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        ###########################################
        # Some math required for linear quantity scaling
        ###########################################
        schema = self._config[KEY.SCHEMA]
        low = schema[KEY.LOW]
        high = schema[KEY.HIGH]
        self._low_threshold = Decimal(str(low[KEY.THRESHOLD]))
        self._high_threshold = Decimal(str(high[KEY.THRESHOLD]))
        self._low_value = Decimal(str(low[KEY.VALUE]))
        self._high_value = Decimal(str(high[KEY.VALUE]))
        self._a_coeff = (self._high_value - self._low_value) / (self._high_threshold - self._low_threshold)
        self._b_coeff = self._low_value - self._a_coeff * self._low_threshold

        ###########################################
        # Load REQUIRED config parameters
        ###########################################
        self._max_inventory = self._config[KEY.MAX_INVENTORY]
        self._max_inventory = Decimal(str(self._max_inventory))

        self._side = self._config[KEY.SIDE]

        self._direction = self._config[KEY.DIRECTION]

        ###########################################
        # Load OPTIONAL config parameters
        ###########################################
        max_deque = int(self._config.get(KEY.DEQUE, DEFAULT.MAX_DEQUE))

        ###########################################
        # Create internal variables
        ###########################################
        self._ask_pressure = deque(maxlen=max_deque)
        self._bid_pressure = deque(maxlen=max_deque)
        self._ratio: Optional[Decimal] = None

        self._done = False


    def onTime(self, timestamp: int):
        super().onTime(timestamp)

        if all([self._ratio, self.distance]):
            if self.state.get(KEY.MODE, None) != KEY.MODE_HALT:
                self.putBuffer(fields={'quoting': 1})

    def _get_ratio(self, asks: list, bids: list) -> Optional[Decimal]:
        ask_qty = sum([x for _, x in asks[:5]])
        bid_qty = sum([x for _, x in bids[:5]])

        self._ask_pressure.append(ask_qty)
        self._bid_pressure.append(bid_qty)

        if len(self._ask_pressure) == self._ask_pressure.maxlen:
            avg_ask_pressure = sum(self._ask_pressure) / self._ask_pressure.maxlen
            avg_bid_pressure = sum(self._bid_pressure) / self._bid_pressure.maxlen

            _sign = sign(avg_ask_pressure - avg_bid_pressure)
            _ratio = _sign * max(avg_ask_pressure, avg_bid_pressure) / min(avg_ask_pressure, avg_bid_pressure)

            # Log values to database
            self.putBuffer({'avg_ask': avg_ask_pressure, 'avg_bid': avg_bid_pressure, 'ratio': _ratio})

            return _ratio

        else:
            return None

    def _isConditionsOk(self):
        # Block if `ratio` is not ready (averaging)
        if self._ratio is None:
            return False

        # Block if exchange "warming up" time is not gone by
        if not self.isWarmedUp():
            return False

        # Block if we have some "pending" inventory
        if abs(self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.PENDING, 0)) > 0:
            return False

        # Block if we reach out max inventory
        if abs(self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, 0)) >= self._max_inventory:
            return False

        # Block if we hit first/second stoploss and have some inventory with negative unrealized pnl
        if self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.STATE, KEY.STATE_NORMAL) != KEY.STATE_NORMAL:
            return False

        return True


    def _get_target_qty_scale(self, ratio: Decimal) -> Decimal:
        coeff = 0 if abs(ratio) < self._low_threshold else 1
        fn = self._a_coeff * abs(ratio) + self._b_coeff
        fn = max(self._low_value, fn)
        fn = min(self._high_value, fn) * coeff
        return fn

    def onSnapshot(self, asks: list, bids: list,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):

        super().onSnapshot(asks, bids, symbol, exchange, timestamp, latency)

        # Skip if wrong symbol/exchange pair
        if (symbol, exchange) != (self.products[KEY.DEFAULT].symbol, self.products[KEY.DEFAULT].exchange):
            return

        midpoint = (asks[0][0] + bids[0][0]) / 2
        self._ratio = self._get_ratio(asks, bids)

        # Skip if conditions are not ok
        if not self._isConditionsOk():
            return


        # Skip if ratio sign is not target
        if self._side * self._ratio < 0:
            return

        # Skip if ratio less than threshold
        if abs(self._ratio) < self._low_threshold:
            return

        target_qty_sign = sign(self._direction * self._ratio)
        current_inventory_sign = sign(self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, 0))

        # Skip if we already have inventory with different sign
        if target_qty_sign * current_inventory_sign < 0:
            return

        coeff = self._get_target_qty_scale(self._ratio)
        target_qty = self._max_inventory * coeff
        current_qty = abs(self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, 0))

        qty_delta = target_qty - current_qty

        # Skip if delta < mim qty size
        if qty_delta < self.min_qty_size:
            return

        # Ok, looks like we can send market order
        order = Order(qty=target_qty_sign * qty_delta, price=midpoint)
        order = self.products[KEY.DEFAULT].oms.applyRules(order).as_market_order()

        id = self.products[KEY.DEFAULT].oms.Post(order)
        self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.PENDING] = \
            self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.PENDING, 0) + order.qty

        self._logger.warning(f'Post MARKET order {order}', ratio=self._ratio, target_qty=target_qty,
                             qty=order.qty, id=id)
