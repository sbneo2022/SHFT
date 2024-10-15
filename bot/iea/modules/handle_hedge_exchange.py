import math
from decimal import Decimal

from bot import AbstractBot
from bot.iea.modules.handle_exchange import HandleExchange, Product
from lib.constants import KEY
from lib.exchange import get_exchange, Book
from lib.factory import AbstractFactory
from lib.timer import AbstractTimer


class HandleHedgeExchange(HandleExchange, AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        ################################################################
        # Create hedge exchange and add to products
        ################################################################
        self.hedge_symbol: str = self._config[KEY.HEDGE][KEY.SYMBOL]
        self.hedge_exchange: str = self._config[KEY.HEDGE][KEY.EXCHANGE]

        self.products_map[(self.hedge_symbol, self.hedge_exchange)] = KEY.HEDGE
        self.products[KEY.HEDGE] = Product(
            symbol=self.hedge_symbol,
            exchange=self.hedge_exchange,
            oms=get_exchange(config, exchange=self.hedge_exchange)(config, factory, timer, symbol=self.hedge_symbol)
        )

        ################################################################
        # Create public link to default exchange (for legacy/simple code)
        ################################################################
        self.hedge_oms = self.products[KEY.HEDGE].oms
        self.hedge_tick_size = self.products[KEY.HEDGE].oms.getTick()
        self.hedge_min_qty_size = self.products[KEY.HEDGE].oms.getMinQty()

        self._logger.success(f'Create {KEY.HEDGE.upper()} OMS for product {self.hedge_symbol}@{self.hedge_exchange}')


    def hedgePriceUp(self, value: Decimal) -> Decimal:
        """
        Round price UP using exchange rules (tick size)
        :param value:
        :return:
        """
        return math.ceil(value / self.hedge_tick_size) * self.hedge_tick_size

    def hedgePriceDown(self, value: Decimal) -> Decimal:
        """
        Round price DOWN using exchange rules (tick size)
        :param value:
        :return:
        """
        return math.floor(value / self.hedge_tick_size) * self.hedge_tick_size

    def onOrderbook(self, askPrice: Decimal, askQty: Decimal, bidPrice: Decimal, bidQty: Decimal,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        super().onOrderbook(askPrice, askQty, bidPrice, bidQty, symbol, exchange, timestamp, latency)

        if (symbol, exchange) == (self.hedge_symbol, self.hedge_exchange):
            self.products[KEY.HEDGE].oms.updateBook(Book(
                ask_price=askPrice, ask_qty=askQty,
                bid_price=bidPrice, bid_qty=bidQty,
            ))

    def onStatus(self, orderId: str, status: str, price: Decimal, qty: Decimal, pct: Decimal,
                 symbol: str, exchange: str,
                 timestamp: int, latency: int = 0):
        super().onStatus(orderId, status, price, qty, pct, symbol, exchange, timestamp, latency)

        if (symbol, exchange) == (self.hedge_symbol, self.hedge_exchange):
            self.products[KEY.HEDGE].oms.updateOrder(orderId, status, price, qty, pct)