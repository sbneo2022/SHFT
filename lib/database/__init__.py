from abc import ABC, abstractmethod
from typing import Optional, Mapping

from lib.factory import AbstractFactory
from lib.timer import AbstractTimer


class AbstractDatabase(ABC):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        self._config = config
        self._factory = factory
        self._timer = timer

    @abstractmethod
    def Encode(self, fields: Mapping[str, any], timestamp: int, tags: Optional[Mapping[str, any]] = None):
        pass

    @abstractmethod
    def writeEncoded(self, data: list):
        pass

    @abstractmethod
    def readLast(self, field: str):
        pass


