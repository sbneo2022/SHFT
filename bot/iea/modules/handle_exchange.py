import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Tuple

from bot import AbstractBot
from lib.constants import KEY
from lib.exchange import get_exchange, AbstractExchange, Book
from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer

@dataclass
class Product:
    symbol: str
    exchange: str
    oms: AbstractExchange

class HandleExchange(AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        # Create utility objects
        self._logger: AbstractLogger = factory.Logger(config, factory, timer)

        ################################################################
        # Create public dict with trading products
        ################################################################
        self.products: Dict[str, Product] = {}
        self.products_map: Dict[Tuple[str, str], str] = {}

        ################################################################
        # Create default exchange and add to products
        ################################################################
        self.default_symbol: str = self._config[KEY.SYMBOL]
        self.default_exchange: str = self._config[KEY.EXCHANGE]

        self.products_map[(self.default_symbol, self.default_exchange)] = KEY.DEFAULT
        self.products[KEY.DEFAULT] = Product(
            symbol=self.default_symbol,
            exchange=self.default_exchange,
            oms=get_exchange(config)(config, factory, timer)
        )

        ################################################################
        # Create public link to default exchange (for legacy/simple code)
        ################################################################
        self.default_oms = self.products[KEY.DEFAULT].oms
        self.tick_size = self.products[KEY.DEFAULT].oms.getTick()
        self.min_qty_size = self.products[KEY.DEFAULT].oms.getMinQty()

        self._logger.success(f'Create {KEY.DEFAULT.upper()} OMS for product {self.default_symbol}@{self.default_exchange}')

    def priceUp(self, value: Decimal) -> Decimal:
        """
        Round price UP using exchange rules (tick size)
        :param value:
        :return:
        """
        return math.ceil(value / self.tick_size) * self.tick_size

    def priceDown(self, value: Decimal) -> Decimal:
        """
        Round price DOWN using exchange rules (tick size)
        :param value:
        :return:
        """
        return math.floor(value /self.tick_size) * self.tick_size

    def onOrderbook(self, askPrice: Decimal, askQty: Decimal, bidPrice: Decimal, bidQty: Decimal,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        super().onOrderbook(askPrice, askQty, bidPrice, bidQty, symbol, exchange, timestamp, latency)

        if (symbol, exchange) == (self.default_symbol, self.default_exchange):
            self.products[KEY.DEFAULT].oms.updateBook(Book(
                ask_price=askPrice, ask_qty=askQty,
                bid_price=bidPrice, bid_qty=bidQty,
            ))

    def onStatus(self, orderId: str, status: str, price: Decimal, qty: Decimal, pct: Decimal,
                 symbol: str, exchange: str,
                 timestamp: int, latency: int = 0):
        super().onStatus(orderId, status, price, qty, pct, symbol, exchange, timestamp, latency)

        if (symbol, exchange) == (self.default_symbol, self.default_exchange):
            self.products[KEY.DEFAULT].oms.updateOrder(orderId, status, price, qty, pct)