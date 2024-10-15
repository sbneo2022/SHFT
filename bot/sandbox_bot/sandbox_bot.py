from bot import AbstractBot
from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer


class SandboxBot(AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, factory, timer)

        self._logger: AbstractLogger = factory.Logger(config, factory, timer)


    def onTime(self, timestamp: int):
        self._logger.info(f'onTime :: {timestamp}')

    def onAccount(self, price: float, qty: float, timestamp: int, latency: int = 0):
        self._logger.info(f'onAccount :: qty={qty} price={price}')

    def onOrderbook(self, askPrice: float, askQty: float, bidPrice: float, bidQty: float, timestamp: int,
                    latency: int = 0):
        self._logger.info(f'onOrderbook :: ask={askPrice} bid={bidPrice}')

    def onTrade(self, price: float, qty: float, timestamp: int, latency: int = 0):
        self._logger.info(f'onTrade :: price={price} qty={qty}')

    def onCandle(self, open: float, high: float, low: float, close: float, volume: float, timestamp: int,
                 finished: bool = True, latency: int = 0):
        self._logger.info(f'onCandle :: open={open} high={high} low={low} close={close} volume={volume} finished={finished}')

    def onMessage(self, message: dict,
                  timestamp: int, latency: int = 0):
        self._logger.info(f'onMessage :: message={message}')

    def Clean(self):
        self._logger.warning('onClean')