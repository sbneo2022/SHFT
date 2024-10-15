import os
import signal
from decimal import Decimal
from typing import Dict, Tuple

from bot import AbstractBot
from lib.constants import KEY
from lib.defaults import DEFAULT
from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer


class HandleWatchdog(AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        self._logger: AbstractLogger = factory.Logger(config, factory, timer)

        self._footprint: Dict[Tuple[str, str], Tuple[int, str]] = {}

    def onTime(self, timestamp: int):
        super().onTime(timestamp)

        for product, item in self._footprint.items():
            item_timestamp, _ = item
            age = timestamp - item_timestamp

            if age > DEFAULT.NODATA_TIMEOUT:
                self._logger.error(f'Bot Watchdog for product {product}: '
                                   f'No new Ask/Bid data for {DEFAULT.NODATA_TIMEOUT / KEY.ONE_SECOND}s. Stop.')
                self._kill()

    def onOrderbook(self, askPrice: Decimal, askQty: Decimal, bidPrice: Decimal, bidQty: Decimal,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        super().onOrderbook(askPrice, askQty, bidPrice, bidQty, symbol, exchange, timestamp, latency)

        product = (symbol, exchange)

        footprint = f'{askPrice}-{askQty}-{bidPrice}-{bidQty}'
        _, previous_footprint = self._footprint.get(product, (None, None))

        if footprint != previous_footprint:
            self._footprint[product] = (timestamp, footprint)

    def _kill(self):
        os.kill(os.getpid(), signal.SIGHUP)
        self._timer.Sleep(1)
        os._exit(-1)
