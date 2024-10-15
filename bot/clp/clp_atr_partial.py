from decimal import Decimal

from bot import AbstractBot
from bot.clp.clp_atr import CLPATR
from bot.clp.mode.handle_inventory_dynamic_partial import handle_inventory_dynamic_partial
from bot.clp.mode.handle_quote import handle_quote
from lib.constants import KEY


class CLPATRPartial(CLPATR, AbstractBot):

    def onTime(self, timestamp: int):
        super().onTime(timestamp)


    def onAccount(self, price: Decimal, qty: Decimal,
                  symbol: str, exchange: str,
                  timestamp: int, latency: int = 0):
        super(CLPATRPartial, self).onAccount(price, qty, symbol, exchange, timestamp, latency)

        self._producer.Send({
            KEY.TYPE: KEY.INVENTORY,
            KEY.PROJECT: self._project_name,
            KEY.QTY: qty,
            KEY.MAX_QTY: self._all_levels_qty * self._max_allocation_coeff or 0,
            KEY.TIMESTAMP: self._timer.Timestamp(),
        })

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
