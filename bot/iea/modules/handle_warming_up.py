from typing import Optional

from bot import AbstractBot
from lib.constants import KEY
from lib.factory import AbstractFactory
from lib.init import get_project_name
from lib.logger import AbstractLogger
from lib.producer import AbstractProducer
from lib.timer import AbstractTimer


class HandleWarmingUp(AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        self._logger: AbstractLogger = factory.Logger(config, factory, timer)

        self._warm_up = self._config.get(KEY.WARMING_UP, 0) * KEY.ONE_SECOND

        self._warming_timestamp: Optional[int] = None

        self._already_warmed_up = False

    def isWarmedUp(self) -> bool:
        if self._already_warmed_up:
            return True

        if self._warming_timestamp is None:
            return False
        else:
            age = self._timer.Timestamp() - self._warming_timestamp
            if age > self._warm_up:
                self._already_warmed_up = True
                if self._warm_up > 0:
                    self._logger.info(f'Warmed-Up time is ended')
                return True
            else:
                return False

    # We will wait N seconds on first `onTime` message
    def onTime(self, timestamp: int):
        super().onTime(timestamp)

        if self._warming_timestamp is None:
            self._logger.info(f'Warming up for {self._warm_up // KEY.ONE_SECOND} seconds')
            self._warming_timestamp = self._timer.Timestamp()
