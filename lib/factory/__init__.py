from abc import ABC, abstractmethod
from typing import Optional

class AbstractFactory(ABC):
    def __init__(self, config: Optional[dict] = None, *args, **kwargs):
        self._config = config or {}

    @property
    @abstractmethod
    def Vault(self):
        pass

    @property
    @abstractmethod
    def Database(self):
        pass

    @property
    @abstractmethod
    def Timer(self):
        pass

    @property
    @abstractmethod
    def Logger(self):
        pass

    @property
    @abstractmethod
    def State(self):
        pass

    @property
    @abstractmethod
    def Consumer(self):
        pass

    @property
    @abstractmethod
    def Producer(self):
        pass

    @property
    @abstractmethod
    def History(self):
        pass
