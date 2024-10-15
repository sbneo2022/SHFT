from abc import ABC
from decimal import Decimal

from lib.factory import AbstractFactory
from lib.timer import AbstractTimer


class AbstractBot(ABC):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        self._config = config
        self._factory = factory
        self._timer = timer

    def onTime(self, timestamp: int):
        pass

    def onMessage(self, message: dict,
                  timestamp: int, latency: int = 0):
        pass

    def onAccount(self, price: Decimal, qty: Decimal,
                  symbol: str, exchange: str,
                  timestamp: int, latency: int = 0):
        pass

    def onStatus(self, orderId: str, status: str, price: Decimal, qty: Decimal, pct: Decimal,
                 symbol: str, exchange: str,
                 timestamp: int, latency: int = 0):
        pass

    def onOrderbook(self, askPrice: Decimal, askQty: Decimal, bidPrice: Decimal, bidQty: Decimal,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        pass

    def onSnapshot(self, asks: list, bids: list,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        pass

    def onTrade(self, price: Decimal, qty: Decimal, side: str,
                symbol: str, exchange: str,
                timestamp: int, latency: int = 0):
        pass

    def onCandle(self, open: Decimal, high: Decimal, low: Decimal, close: Decimal, volume: Decimal,
                 symbol: str, exchange: str,
                 timestamp: int, latency: int = 0, finished: bool = True):
        pass

    def Clean(self):
        pass
