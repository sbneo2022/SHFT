from datetime import datetime

from bot import AbstractBot
from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer


class SandboxBot(AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, factory, timer)

        self._logger: AbstractLogger = factory.Logger(config, factory, timer)

        self._logger.info(
            f"Starting bot at {datetime.utcnow().strftime('%Y/%m/%d, %H:%M:%S')}"
        )

    def onTime(self, timestamp: int):
        # ok
        self._logger.info(f"onTime :: {timestamp}")

    def onMessage(self, **kwargs):
        # ok
        self._logger.info(f"onMessage :: {kwargs}")

    def onAccount(self, **kwargs):
        self._logger.info(f"onAccount :: {kwargs}")

    def onOrderbook(self, **kwargs):
        self._logger.info(f"onOrderbook :: {kwargs}")

    def onTrade(self, **kwargs):
        self._logger.info(f"onTrade :: {kwargs}")

    def onCandle(self, **kwargs):
        self._logger.info(f"onCandle :: {kwargs}")

    def onSnapshot(self, **kwargs):
        self._logger.info(f"onSnapshot :: {kwargs}")

    def Clean(self):
        self._logger.warning("onClean")

        self._logger.info(
            f"Ending bot at {datetime.utcnow().strftime('%Y/%m/%d, %H:%M:%S')}"
        )

