import copy

from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.state import AbstractState
from lib.timer import AbstractTimer


class MemoryState(AbstractState):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, factory, timer)

        self._state = dict()

        self._logger: AbstractLogger = factory.Logger(config, factory, timer)

    def Push(self, state: dict):
        self._state = copy.deepcopy(state)
        self._logger.trace(f'Save STATE: {state}')

    def Pop(self) -> dict:
        self._logger.trace(f'Load STATE: {self._state}')
        return self._state