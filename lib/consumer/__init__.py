from abc import ABC, abstractmethod

from lib.factory import AbstractFactory
from lib.supervisor import AbstractSupervisor
from lib.timer import AbstractTimer


class AbstractConsumer(ABC):
    def __init__(self, config: dict, supervisor: AbstractSupervisor, factory: AbstractFactory, timer: AbstractTimer):
        self._config = config
        self._supervisor = supervisor
        self._factory = factory
        self._timer = timer

    @abstractmethod
    def Run(self):
        pass

    @abstractmethod
    def Close(self):
        pass