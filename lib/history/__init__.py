from abc import ABC, abstractmethod

from lib.factory import AbstractFactory
from lib.timer import AbstractTimer


class AbstractHistory(ABC):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        self._config = config
        self._factory = factory
        self._timer = timer

    @abstractmethod
    def getHistory(self, start_timestamp: int, end_timestamp: int, fields: list) -> list:
        pass