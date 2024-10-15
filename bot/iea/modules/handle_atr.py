from collections import deque
from decimal import Decimal
from typing import Optional

from bot.iea.modules.handle_candles import HandleCandles
from lib.async_ejector import FieldsAsyncEjector
from lib.constants import KEY
from lib.database import AbstractDatabase
from lib.defaults import DEFAULT
from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer

ATR = {
    KEY.VALUE: 60,
    KEY.TAG: '1h'
}

class HandleATR(HandleCandles):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        # Create utility objects
        self._database: AbstractDatabase = factory.Database(config, factory, timer)

        self._abs_atr_value: Optional[Decimal] = None

        ################################################################
        # Public variables
        ################################################################
        self.atr: Optional[Decimal] = None


    def onCandle(self, open: Decimal, high: Decimal, low: Decimal, close: Decimal, volume: Decimal,
                 symbol: str, exchange: str,
                 timestamp: int, latency: int = 0, finished: bool = True):
        super().onCandle(open, high, low, close, volume, symbol, exchange, timestamp, latency, finished)

        if (symbol, exchange) == (self._config[KEY.SYMBOL], self._config[KEY.EXCHANGE]):
            if self.candles is not None:
                if self._abs_atr_value is None or finished:
                    self.atr = self._get_atr()


    ##############################################################################
    #
    # Private Methods
    #
    ##############################################################################

    def _get_atr(self) -> Decimal:

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


        self._abs_atr_value = _atr(
            high=self.candles[KEY.HIGH],
            low=self.candles[KEY.LOW],
            close=self.candles[KEY.CLOSE],
            current=self._abs_atr_value,
            tail=ATR[KEY.VALUE]
        )

        atr_pct = self._abs_atr_value / self.candles[KEY.CLOSE][-1]

        FieldsAsyncEjector(self._database, self._timer, **{f'atr_{ATR[KEY.TAG]}': atr_pct}).start()

        return atr_pct