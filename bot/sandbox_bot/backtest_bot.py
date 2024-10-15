from collections import deque
from datetime import datetime, timezone
from typing import Optional

from bot import AbstractBot
from lib.constants import KEY
from lib.exchange import get_exchange, AbstractExchange, Order
from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer


ORDER_DELAY = 3 * KEY.ONE_SECOND

class SandboxBot(AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, factory, timer)

        self._logger: AbstractLogger = factory.Logger(config, factory, timer)

        self._exchange: AbstractExchange = get_exchange(config)(config, factory, timer)

        self._slow_ma = deque(maxlen=200)
        self._fast_ma = deque(maxlen=100)
        self._order_timestamp: Optional[int] = None

    def onTime(self, timestamp: int):
        self._logger.info(f'onTime :: {timestamp}')

    def onMessage(self, message: dict,
                  timestamp: int, latency: int = 0):
        self._logger.info(f'onMessage :: message={message}')

        if message[KEY.VALUE] == 0:
            self._exchange.Post(Order())

    def onAccount(self, price: float, qty: float,
                  symbol: str, exchange: str,
                  timestamp: int, latency: int = 0):
        self._logger.info(f'onAccount :: qty={qty} price={price}')

    def onOrderbook(self, askPrice: float, askQty: float, bidPrice: float, bidQty: float,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        # self._logger.info(f'onOrderbook :: ask={askPrice} bid={bidPrice}')

        def midpoint(ask, bid):
            return (ask + bid) / 2

        self._slow_ma.append(midpoint(askPrice, bidPrice))
        self._fast_ma.append(midpoint(askPrice, bidPrice))

        if len(self._slow_ma) == self._slow_ma.maxlen:
            slow_ma = sum(self._slow_ma) / self._slow_ma.maxlen
            fast_ma = sum(self._fast_ma) / self._fast_ma.maxlen

            if self._order_timestamp is None:
                ratio = slow_ma / fast_ma - 1

                timestamp = self._timer.Timestamp()
                _time = datetime.fromtimestamp(timestamp / KEY.ONE_SECOND, tz=timezone.utc)

                self._logger.info(f'{_time} :: Slow/Fast Ratio: {ratio}')
                if ratio > +0.0001:
                    order = Order(qty=1)
                elif ratio < -0.0001:
                    order = Order(qty=-1)
                else:
                    order = None

                if order is not None:
                    id = self._exchange.Post(order)
                    self._logger.success(f'Post order {order} with id={id}')
                    self._order_timestamp = self._timer.Timestamp()

            elif self._timer.Timestamp() > self._order_timestamp + ORDER_DELAY:
                self._logger.success('Release Order')
                self._order_timestamp = None

    def Clean(self):
        self._logger.warning('onClean')