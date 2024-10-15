from collections import deque
from decimal import Decimal
from typing import Optional

from bot import AbstractBot
from bot.clp.clp import CLP
from bot.clp.mode.handle_inventory_dynamic import handle_inventory_dynamic
from bot.clp.mode.handle_quote import handle_quote
from lib.async_ejector import FieldsAsyncEjector
from lib.constants import KEY
from lib.defaults import DEFAULT
from lib.factory import AbstractFactory
from lib.timer import AbstractTimer

CANDLES_DEPTH = 1 * KEY.ONE_HOUR + KEY.ONE_MINUTE

ATR_CANDLES = {
    '30m': 30,
    '1h': 60,
}

class CLPATR(CLP, AbstractBot):

    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, factory, timer)

        ################################################################
        # Internal variables to handle candle data
        ################################################################
        self._candles: Optional[dict] = None

        self._atr: Optional[dict] = None

        self._stoploss_coeff = config.get(KEY.STOPLOSS_COEFF, DEFAULT.STOPLOSS_COEFF)
        self._logger.info(f'Used ATR/Stoploss Coeff = {self._stoploss_coeff}', stoploss_coeff=self._stoploss_coeff)

        self._distance = None  # Make default distance None --> do not quote till we have right one

        self._used_atr = None  # Also we will save "used_atr" -- it could be 1h ATR or different

    ##############################################################################
    #
    # Public Methods
    #
    ##############################################################################
    def onCandle(self, open: Decimal, high: Decimal, low: Decimal, close: Decimal, volume: Decimal,
                 symbol: str, exchange: str,
                 timestamp: int, latency: int = 0, finished: bool = True):

        # Initially we have to preload candles data
        if self._candles is None:
            end_time = timestamp - KEY.ONE_MINUTE
            start_time = end_time - CANDLES_DEPTH
            self._candles = self._exchange.getCandles(start_time, end_time)
            self._update_atr()

        if finished:
            self._candles[KEY.OPEN].append(open)
            self._candles[KEY.HIGH].append(high)
            self._candles[KEY.LOW].append(low)
            self._candles[KEY.CLOSE].append(close)
            self._candles[KEY.VOLUME].append(volume)
            self._update_atr()

    ##############################################################################
    #
    # Private Methods
    #
    ##############################################################################
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
                handle_inventory_dynamic(self, askPrice, bidPrice)

    def _update_atr(self):
        self._atr = self._atr or dict()

        def _atr(high: deque, low: deque, close: deque, current: Optional[Decimal], tail: int):
            _tail = tail + 1 # we r getting 1 minute more to handle first TR

            _high = list(high)[-_tail:]
            _low = list(low)[-_tail:]
            _close = list(close)[-_tail:]

            # True Range calculations for given index. Return H-L for index = 0
            def tr(idx: int) -> Decimal:
                if idx == 0:
                    return _high[idx] - _low[idx]
                else:
                    return max(
                        _high[idx] - _low[idx],
                        abs(_high[idx] - _close[idx - 1]),
                        abs(_low[idx] - _close[idx - 1])
                    )

            # Average of list help function
            def mean(obj: list) -> Decimal:
                return sum(obj) / len(obj)

            # If we have no previous value --> find mean(TR) as fist
            if current is None:
                atr = []
                for idx in range(tail):
                    atr.append(tr(idx))
                current = mean(atr)

            # "tail" true ATR counter. _tail --> len of List object, so "_tail-1" is idx of last item in a List
            return (current * (tail - 1) + tr(_tail - 1)) / tail

        for key, value in ATR_CANDLES.items():
            self._atr[key] = _atr(
                high=self._candles[KEY.HIGH],
                low=self._candles[KEY.LOW],
                close=self._candles[KEY.CLOSE],
                current=self._atr.get(key, None), tail=value)

        pct = {f'atr_{key}': float(value / self._candles[KEY.CLOSE][-1]) for key, value in self._atr.items()}

        FieldsAsyncEjector(self._database, self._timer, **pct).start()

        atr_1h = self._atr['1h'] / self._candles[KEY.CLOSE][-1]

        self._used_atr = atr_1h

        self._distance = self._stoploss_coeff * atr_1h

        self._logger.warning(f'Set new stoploss Distance={self._distance}', event='STOPLOSS',
                             distance=self._distance, atr=atr_1h)


