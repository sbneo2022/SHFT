from abc import ABC, abstractmethod

from lib.constants import KEY
from lib.factory import AbstractFactory
from lib.timer import AbstractTimer


class AbstractProducer(ABC):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        self._config = config
        self._factory = factory
        self._timer = timer

    @abstractmethod
    def Send(self, message: dict, channel=KEY.PRODUCT):
        pass
