from decimal import Decimal
from pprint import pprint
from typing import Optional, List

from bot import AbstractBot
from bot.iea.modules.handle_buffer import HandleBuffer
from bot.iea.modules.handle_clean_cancel import HandleCleanCancel
from bot.iea.modules.handle_clean_force import HandleCleanForce
from bot.iea.modules.handle_delta import HandleDelta
from bot.iea.modules.handle_exchange import HandleExchange
from bot.iea.modules.handle_hedge_exchange import HandleHedgeExchange
from bot.iea.modules.handle_inventory import HandleInventory
from bot.iea.modules.handle_spread import HandleSpread
from bot.iea.modules.handle_watchdog import HandleWatchdog
from lib.constants import KEY
from lib.factory import AbstractFactory
from lib.helpers import sign
from lib.timer import AbstractTimer



class Iea(
    HandleInventory,
    HandleWatchdog,
    HandleCleanCancel,
    HandleSpread,
    # HandleAlive,
    HandleDelta,
    HandleBuffer,
    HandleHedgeExchange,
    HandleExchange,
    AbstractBot
):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        ###########################################
        # Load REQUIRED config parameters
        ###########################################
        self._side = self._config[KEY.SIDE]
        self._direction = self._config[KEY.DIRECTION]
        self._threshold = self._config[KEY.THRESHOLD]
        self._close = self._config[KEY.CLOSE]

        ###########################################
        # Load OPTIONAL config parameters
        ###########################################
        self._hold = self._config[KEY.HOLD] * KEY.ONE_SECOND
        self._max_pct = Decimal(str(config[KEY.MAX_PCT]))

        ###########################################
        # Create internal variables
        ###########################################
        self._ask_qty: Optional[Decimal] = None
        self._bid_qty: Optional[Decimal] = None

        self._open_orders_ids: Optional[List[str]] = None
        self._open_orders_timestamp: Optional[int] = None

    def onTime(self, timestamp: int):
        super().onTime(timestamp)

        if all([self._ask_qty, self._bid_qty, self.delta, self.distance]):
            self.putBuffer(fields={'quoting': 1})

        print(self.delta)

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
        if not all([self._ask_qty, self._bid_qty, self.delta, self.distance]):
            return

        if self._open_orders_ids is None:
            if self._check_threshold():
                self._open_limit_orders()
        else:
            if self._check_close():
                holding_time = self._timer.Timestamp() - self._open_orders_timestamp
                if holding_time > self._hold:
                    self._cancel_limit_orders()

    def _check_threshold(self) -> bool:
        if self._side == 0 or sign(self._side) == sign(self.delta):
            if abs(self.delta) > abs(self._threshold):
                return True
        return False

    def _check_close(self) -> bool:
        if self._side == 0 or sign(self._side) == sign(self.delta):
            if abs(self.delta) > abs(self._close):
                return False
        return True

    def _open_limit_orders(self):

        max_qty = self._bid_qty * self._max_pct

        self._logger.warning(f'Delta={self.delta} :: OPEN limit with qty={max_qty} (top5={self._bid_qty})')

        orders = self.getMultilevelPrices('inner', side=KEY.BUY, max_qty=max_qty)

        for item in orders:
            print(item, end=' ')
        print()

        self._open_orders_ids = []
        self._open_orders_timestamp = self._timer.Timestamp()

    def _cancel_limit_orders(self):
        self._logger.warning(f'Delta={self.delta} :: CANCEL open orders')
        self._open_orders_ids = None
        self._open_orders_timestamp = None





