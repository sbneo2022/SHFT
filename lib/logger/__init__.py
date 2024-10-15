from abc import ABC, abstractmethod
from typing import Optional

from lib.factory import AbstractFactory
from lib.timer import AbstractTimer
from lib.timer.live_timer import LiveTimer


class AbstractLogger(ABC):
    def __init__(self, config: Optional[dict] = None,
                 factory: Optional[AbstractFactory] = None,
                 timer: Optional[AbstractTimer] = None):
        self._config = config or {}
        self._factory = factory
        self._timer = timer or LiveTimer()

    @abstractmethod
    def trace(self, message: str, **kwargs):
        pass

    @abstractmethod
    def debug(self, message: str, **kwargs):
        pass

    @abstractmethod
    def info(self, message: str, **kwargs):
        pass

    @abstractmethod
    def success(self, message: str, **kwargs):
        pass

    @abstractmethod
    def warning(self, message: str, **kwargs):
        pass

    @abstractmethod
    def error(self, message: str, **kwargs):
        pass

    @abstractmethod
    def critical(self, message: str, **kwargs):
        pass
