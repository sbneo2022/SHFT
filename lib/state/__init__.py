from abc import ABC, abstractmethod

from lib.factory import AbstractFactory
from lib.timer import AbstractTimer


class AbstractState(ABC):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        self._config = config
        self._factory = factory
        self._timer = timer

    @abstractmethod
    def Push(self, state: dict):
        pass

    @abstractmethod
    def Pop(self) -> dict:
        pass
