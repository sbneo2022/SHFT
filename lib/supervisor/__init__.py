import multiprocessing
from abc import ABC, abstractmethod

from bot import AbstractBot
from lib.factory import AbstractFactory
from lib.timer import AbstractTimer



class AbstractSupervisor(ABC):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        self._config = config
        self._factory = factory
        self._timer = timer

        self.Queue = multiprocessing.Queue()

    @abstractmethod
    def Run(self, bot: AbstractBot):
        pass