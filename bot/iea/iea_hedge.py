from decimal import Decimal
from typing import Optional, List, Union

from bot import AbstractBot
from bot.iea.modules.handle_alive import HandleAlive
from bot.iea.modules.handle_buffer import HandleBuffer
from bot.iea.modules.handle_clean_cancel import HandleCleanCancel
from bot.iea.modules.handle_delta import HandleDelta
from bot.iea.modules.handle_exchange import HandleExchange
from bot.iea.modules.handle_hedge_exchange import HandleHedgeExchange
from bot.iea.modules.handle_positions import HandlePositions
from bot.iea.modules.handle_spread import HandleSpread
from bot.iea.modules.handle_watchdog import HandleWatchdog
from lib.constants import KEY, ORDER_TAG
from lib.exchange import Order
from lib.factory import AbstractFactory
from lib.timer import AbstractTimer



class IeaHedge(
    HandleWatchdog,
    HandleCleanCancel,
    HandleSpread,
    HandleAlive,
    HandleDelta,
    HandleBuffer,
    HandlePositions,
    HandleHedgeExchange,
    HandleExchange,
    AbstractBot
):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        ###########################################
        # Load REQUIRED config parameters
        ###########################################
        self._threshold = {
            KEY.LONG: self._config[KEY.THRESHOLD][KEY.LONG],
            KEY.SHORT: self._config[KEY.THRESHOLD][KEY.SHORT],
        }

        self._hold = self._config[KEY.HOLD] * KEY.ONE_SECOND
        self._max_pct = Decimal(str(config[KEY.MAX_PCT]))
        self._max_qty = Decimal(str(config[KEY.MAX_QTY]))

        ###########################################
        # Load OPTIONAL config parameters
        ###########################################
        self._side: int = self._config.get(KEY.SIDE, 0)
        self._direction: int = self._config.get(KEY.DIRECTION, +1)

        ###########################################
        # Create internal variables
        ###########################################
        self._ask_qty: Optional[Decimal] = None
        self._bid_qty: Optional[Decimal] = None

        self._open_orders_ids: Optional[List[str]] = None
        self._open_orders_timestamp: Optional[int] = None
        self._open_orders_side: Optional[str] = None

        self._default_qty = self.state.get(KEY.INVENTORY, {}).get(KEY.DEFAULT, {}).get(KEY.QTY, 0)
        self._hedge_qty = self.state.get(KEY.INVENTORY, {}).get(KEY.HEDGE, {}).get(KEY.QTY, 0)

    def onTime(self, timestamp: int):
        super().onTime(timestamp)

        if all([self._ask_qty, self._bid_qty, self.delta]):
            self.putBuffer(fields={'quoting': 1})

    def onAccount(self, price: Decimal, qty: Decimal, symbol: str, exchange: str, timestamp: int, latency: int = 0):
        super().onAccount(price, qty, symbol, exchange, timestamp, latency)

        def post_order(posted_qty: Union[Decimal, int], target: str):
            order = Order(posted_qty, tag=ORDER_TAG.HEDGE)

            id = self.products[target].oms.Post(order)
            self._logger.warning(f'POST Hedge order to {target.upper()}', qty=qty, posted_qty=order.qty, id=id)

            if KEY.INVENTORY not in self.state:
                self.state[KEY.INVENTORY] = {}

            if target not in self.state[KEY.INVENTORY]:
                self.state[KEY.INVENTORY][target] = {}

            self.state[KEY.INVENTORY][target][KEY.PENDING] = order.qty

        current_default_inventory = self.state.get(KEY.INVENTORY, {}).get(KEY.DEFAULT, {}).get(KEY.QTY, 0)
        current_hedge_inventory = self.state.get(KEY.INVENTORY, {}).get(KEY.HEDGE, {}).get(KEY.QTY, 0)

        if (symbol, exchange) == (self.products[KEY.DEFAULT].symbol, self.products[KEY.DEFAULT].exchange):
            delta = qty - self._default_qty
            self._default_qty = qty

            if delta > 0:
                if abs(current_hedge_inventory - delta) <= abs(current_default_inventory):
                    post_order(-1 * delta, KEY.HEDGE)

        if (symbol, exchange) == (self.products[KEY.HEDGE].symbol, self.products[KEY.HEDGE].exchange):
            delta = qty - self._hedge_qty
            self._hedge_qty = qty

            if delta < 0:
                if abs(current_default_inventory - delta) <= abs(current_hedge_inventory):
                    post_order(-1 * delta, KEY.DEFAULT)


    def onSnapshot(self, asks: list, bids: list,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):

        super().onSnapshot(asks, bids, symbol, exchange, timestamp, latency)

        # Save current/latest top5 ask/bid qty
        if (symbol, exchange) == (self._config[KEY.SYMBOL], self._config[KEY.EXCHANGE]):
            self._ask_qty = sum([x for _, x in asks[:5]])
            self._bid_qty = sum([x for _, x in bids[:5]])

    def onOrderbook(self, askPrice: Decimal, askQty: Decimal, bidPrice: Decimal, bidQty: Decimal,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        super().onOrderbook(askPrice, askQty, bidPrice, bidQty, symbol, exchange, timestamp, latency)

        # We cant post LIMIT orders till we have TOP5 Qty and Delta and Distance
        if not all([self._ask_qty, self._bid_qty, self.delta]):
            return

        hit_threshold = self._check_threshold()

        if self._open_orders_ids is None:
            if hit_threshold:
                inventory = [
                        abs(x.get(KEY.QTY, 0))
                        for x in self.state.get(KEY.INVENTORY, {}).values()
                    ]

                if not inventory or \
                    inventory and max(inventory) <= self._max_qty:
                    self._open_limit_orders()
        else:
            if not hit_threshold:
                holding_time = self._timer.Timestamp() - self._open_orders_timestamp
                if holding_time > self._hold:
                    self._cancel_limit_orders()

    def _check_threshold(self) -> bool:
        # filter by "delta" sign using self._side parameter
        if self._side >= 0 and self.delta > self._threshold[KEY.LONG]:
            return True

        if self._side <= 0 and self.delta < self._threshold[KEY.SHORT]:
            return True

        return False

    def _open_limit_orders(self):

        direction = +1 if self.delta > self._threshold[KEY.LONG] else -1
        direction = direction * self._direction
        side = KEY.BUY if direction > 0 else KEY.SELL
        target = KEY.DEFAULT if side == KEY.BUY else KEY.HEDGE


        used_qty = self._bid_qty if side == KEY.BUY else self._ask_qty

        max_qty = used_qty * self._max_pct

        self._logger.warning(f'Delta={self.delta} :: OPEN limit with qty={max_qty} (top5={used_qty}) on {target.upper()}',
                             qty=max_qty, top5=used_qty, side=side)

        self._open_orders_ids = []
        for spread_name in self.spread.keys():
            orders = self.getMultilevelPrices(spread_name, side=side, max_qty=max_qty)
            self._open_orders_ids.extend(self.products[target].oms.batchPost(orders))

        self._open_orders_timestamp = self._timer.Timestamp()
        self._open_orders_side = target


    def _cancel_limit_orders(self):
        self._logger.warning(f'Delta={self.delta} :: CANCEL open orders on {self._open_orders_side.upper()}')

        self.products[self._open_orders_side].oms.Cancel(self._open_orders_ids)

        self._open_orders_ids = None
        self._open_orders_timestamp = None
        self._open_orders_side = None





