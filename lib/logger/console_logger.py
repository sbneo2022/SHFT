import json
import sys
from typing import Optional

from loguru import logger

from lib.constants import LEVEL
from lib.factory import AbstractFactory
from lib.helpers import custom_dump
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer

DEFAULT_LEVEL = 0

DEFAULT_FORMAT = "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | " \
                 "<level>{level: <8}</level> | " \
                 "<level>{message}</level>"

class ConsoleLogger(AbstractLogger):
    def __init__(self, config: Optional[dict] = None,
                 factory: Optional[AbstractFactory] = None,
                 timer: Optional[AbstractTimer] = None):
        super().__init__(config, factory, timer)

        logger.remove()

        logger.add(sys.stdout, format=DEFAULT_FORMAT, level=DEFAULT_LEVEL)

    def _post_message(self, message: str, data: dict, level: str):
        payload = json.dumps(data, default=custom_dump)
        logger.log(level.upper(), f'{message} | {payload}')

    def trace(self, message: str, **kwargs):
        self._post_message(message, data=kwargs, level=LEVEL.TRACE)

    def debug(self, message: str, **kwargs):
        self._post_message(message, data=kwargs, level=LEVEL.DEBUG)

    def info(self, message: str, **kwargs):
        self._post_message(message, data=kwargs, level=LEVEL.INFO)

    def success(self, message: str, **kwargs):
        self._post_message(message, data=kwargs, level=LEVEL.SUCCESS)

    def warning(self, message: str, **kwargs):
        self._post_message(message, data=kwargs, level=LEVEL.WARNING)

    def error(self, message: str, **kwargs):
        self._post_message(message, data=kwargs, level=LEVEL.ERROR)

    def critical(self, message: str, **kwargs):
        self._post_message(message, data=kwargs, level=LEVEL.CRITICAL)

