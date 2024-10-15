import json
import threading
from typing import Mapping

from lib.constants import LEVEL, KEY, DB
from lib.database import AbstractDatabase
from lib.helpers import custom_dump
from lib.timer import AbstractTimer


class LogAsyncEjector(threading.Thread):
    def __init__(self, database: AbstractDatabase, timer: AbstractTimer,
                 message: str, data: dict, level: str):
        super().__init__()
        self._database = database
        self._timer = timer
        self._message = message
        self._data = data
        self._level = level

    def run(self) -> None:
        if self._level == LEVEL.SUCCESS:
            self._data[KEY.LEVEL] = LEVEL.INFO
        elif self._level != LEVEL.INFO:
            self._data[KEY.LEVEL] = self._level

        self._data[KEY.MESSAGE] = self._message
        try:
            data = json.dumps(self._data, default=custom_dump).replace('"', '\\"')
            payload = self._database.Encode(
                fields={DB.MESSAGE: data},
                timestamp=self._timer.Timestamp(),
            )

            self._database.writeEncoded([payload])
        except Exception as e:
            print(f'{__file__}: {e}')


class FieldsAsyncEjector(threading.Thread):
    def __init__(self, database: AbstractDatabase, timer: AbstractTimer, **kwargs):
        super().__init__()
        self._database = database
        self._timer = timer
        self._fields: Mapping[str, any] = kwargs

    def run(self) -> None:
        try:
            payload = self._database.Encode(
                fields=self._fields,
                timestamp=self._timer.Timestamp(),
            )

            self._database.writeEncoded([payload])
        except Exception as e:
            print(f'{__file__}: {e}')