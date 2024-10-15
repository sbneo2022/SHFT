from bot import AbstractBot
from lib.constants import KEY
from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer


class NoBot(AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, factory, timer)

    def onTime(self, timestamp: int):
        pass

    def onMessage(self, message: dict,
                  timestamp: int, latency: int = 0):
        pass

    def onAccount(self, price: float, qty: float,
                  symbol: str, exchange: str,
                  timestamp: int, latency: int = 0):
        pass

    def onSnapshot(self, asks: list, bids: list,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        pass

    def onOrderbook(self, askPrice: float, askQty: float, bidPrice: float, bidQty: float,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        pass

    def onTrade(self, price: float, qty: float, side: str,
                symbol: str, exchange: str,
                timestamp: int, latency: int = 0):
        pass

    def onCandle(self, open: float, high: float, low: float, close: float, volume: float,
                 symbol: str, exchange: str,
                 timestamp: int, finished: bool = True, latency: int = 0):
        pass

    def Clean(self):
        pass