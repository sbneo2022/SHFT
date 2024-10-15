from collections import deque
from decimal import Decimal
from typing import Optional

from bot import AbstractBot
from bot.clp.clp_atr import CLPATR
from bot.clp.mode.handle_inventory_dynamic_partial import handle_inventory_dynamic_partial
from bot.clp.mode.handle_quote import handle_quote
from lib.constants import KEY
from lib.defaults import DEFAULT
from lib.factory import AbstractFactory
from lib.timer import AbstractTimer


class CLPATRPartialDimbalance(CLPATR, AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):

        super().__init__(config, factory, timer)

        # Load required `max_pct` parameter: percent of top5 book to quote
        # Default value is 1(100%): quote no more than
        self._max_pct = self._config.get(KEY.MAX_PCT, 1)
        self._max_pct = Decimal(str(self._max_pct))
        self._optional[KEY.MAX_PCT] = self._max_pct

        self._max_ratio = self._config.get(KEY.MAX_RATIO, DEFAULT.MAX_RATIO)
        self._max_ratio = Decimal(str(self._max_ratio))

        self._ask_qty: Optional[Decimal] = None
        self._bid_qty: Optional[Decimal] = None

        self._ask_price: Optional[Decimal] = None
        self._bid_price: Optional[Decimal] = None
        self._midpoint: Optional[Decimal] = None

        self._ask_pressure = deque(maxlen=10)
        self._bid_pressure = deque(maxlen=10)

        self._avg_ask_pressure: Optional[Decimal] = None
        self._avg_bid_pressure: Optional[Decimal] = None

        self._ratio: Optional[Decimal] = None



    def onTime(self, timestamp: int):
        super().onTime(timestamp)


    def onAccount(self, price: Decimal, qty: Decimal,
                  symbol: str, exchange: str,
                  timestamp: int, latency: int = 0):
        super(CLPATRPartialDimbalance, self).onAccount(price, qty, symbol, exchange, timestamp, latency)

        self._producer.Send({
            KEY.TYPE: KEY.INVENTORY,
            KEY.PROJECT: self._project_name,
            KEY.QTY: qty,
            KEY.MAX_QTY: self._all_levels_qty * self._max_allocation_coeff or 0,
            KEY.TIMESTAMP: self._timer.Timestamp(),
        })

    def onSnapshot(self, asks: list, bids: list,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        if all([self._ask, self._bid]):
            self._ask_qty = sum([x for _, x in asks[:5]])
            self._bid_qty = sum([x for _, x in bids[:5]])
            self._midpoint = (self._ask + self._bid) / 2

            self._ask_pressure.append(self._ask_qty)
            self._bid_pressure.append(self._bid_qty)

            self._avg_ask_pressure = sum(self._ask_pressure) / self._ask_pressure.maxlen
            self._avg_bid_pressure = sum(self._bid_pressure) / self._bid_pressure.maxlen

            self._ratio = (self._avg_ask_pressure - self._avg_bid_pressure) / (self._avg_ask_pressure + self._avg_bid_pressure)

            fn = max(0, min(1, 1 - abs(self._ratio) / self._max_ratio))

            if self._ratio > 0:
                self._optional[KEY.RATIO + KEY.BUY] = fn
                self._optional[KEY.RATIO + KEY.SELL] = 1
            else:
                self._optional[KEY.RATIO + KEY.BUY] = 1
                self._optional[KEY.RATIO + KEY.SELL] = fn

            self._optional[KEY.QTY + KEY.BUY] = self._avg_bid_pressure
            self._optional[KEY.QTY + KEY.SELL] = self._avg_ask_pressure

            # TODO: delete debug output
            # print(self._avg_ask_pressure, self._avg_bid_pressure, self._optional)


    def _handle_new_orderbook_event(self, askPrice, bidPrice, latency):
        if self._state[KEY.MODE] == KEY.MODE_HALT:
            pass

        elif self._state[KEY.MODE] == KEY.MODE_EMPTY:
            if self._handle_quote:
                handle_quote(self, askPrice, bidPrice, latency)

        elif self._state[KEY.MODE] == KEY.MODE_INVENTORY:
            if self._handle_quote:
                handle_quote(self, askPrice, bidPrice, latency)
            if self._handle_inventory:
                handle_inventory_dynamic_partial(self, askPrice, bidPrice)
