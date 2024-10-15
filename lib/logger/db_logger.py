import copy
from typing import Optional

from lib.async_ejector import LogAsyncEjector
from lib.factory import AbstractFactory
from lib.logger.console_logger import ConsoleLogger
from lib.timer import AbstractTimer


class DbLogger(ConsoleLogger):
    def __init__(self, config: Optional[dict] = None,
                 factory: Optional[AbstractFactory] = None,
                 timer: Optional[AbstractTimer] = None):
        super().__init__(config, factory, timer)

        self._database = factory.Database(config, factory, timer)

    def _post_message(self, message: str, data: dict, level: str):
        super()._post_message(message, data, level)

        # Run async ejector to push data to database
        LogAsyncEjector(self._database, self._timer,
                        message, copy.deepcopy(data), level).start()
