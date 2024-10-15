from typing import Optional

from bot import AbstractBot
from lib.database import AbstractDatabase
from lib.factory import AbstractFactory
from lib.timer import AbstractTimer


class HandleBuffer(AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        self._database: AbstractDatabase = factory.Database(config, factory, timer)

        ################################################################
        # Public variables
        ################################################################
        self._data_buffer = []

    def onTime(self, timestamp: int):
        super().onTime(timestamp)

        if self._data_buffer:
            self._database.writeEncoded(self._data_buffer)
            self._data_buffer = []

    def putBuffer(self, fields: dict, tags: Optional[dict] = None):
        self._data_buffer.append(
            self._database.Encode(
                fields=fields,
                timestamp=self._timer.Timestamp(),
                tags=tags,
            )
        )
