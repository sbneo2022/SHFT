from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

"""
NOTES:

  1. Datetime in UTC
  
  2. Timestamp in nanoseconds

"""
class AbstractTimer(ABC):
    def __init__(self, config: Optional[dict] = None):
        self._config = config or {}

    @abstractmethod
    def Now(self) -> datetime:
        pass

    @abstractmethod
    def Timestamp(self) -> int:
        pass

    @abstractmethod
    def setTimestamp(self, timestamp: int):
        pass

    @abstractmethod
    def Sleep(self, seconds: float):
        pass