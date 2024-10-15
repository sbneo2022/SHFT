from decimal import Decimal
from typing import Optional

from bot import AbstractBot
from bot.iea.modules.handle_exchange import HandleExchange
from lib.constants import KEY
from lib.factory import AbstractFactory
from lib.timer import AbstractTimer


CANDLES_DEPTH = 1 * KEY.ONE_HOUR + KEY.ONE_MINUTE

class HandleCandles(HandleExchange, AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        ################################################################
        # Public variables
        ################################################################
        self.candles: Optional[dict] = None


    def onCandle(self, open: Decimal, high: Decimal, low: Decimal, close: Decimal, volume: Decimal,
                 symbol: str, exchange: str,
                 timestamp: int, latency: int = 0, finished: bool = True):

        # We will process TARGET symbol and exchange only
        if (symbol, exchange) != (self._config[KEY.SYMBOL], self._config[KEY.EXCHANGE]):
            return

        # Initially we have to preload candles data
        if self.candles is None:
            end_time = timestamp - KEY.ONE_MINUTE
            start_time = end_time - CANDLES_DEPTH
            self.candles = self.default_oms.getCandles(start_time, end_time)

        if finished:
            self.candles[KEY.OPEN].append(open)
            self.candles[KEY.HIGH].append(high)
            self.candles[KEY.LOW].append(low)
            self.candles[KEY.CLOSE].append(close)
            self.candles[KEY.VOLUME].append(volume)
