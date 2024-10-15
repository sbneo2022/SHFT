import time
from datetime import datetime, timezone
from typing import Optional

from lib.constants import KEY
from lib.timer import AbstractTimer


class VirtualTimer(AbstractTimer):
    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        self._timestamp: int = 0

    def Now(self) -> datetime:
        return datetime.fromtimestamp(self._timestamp / KEY.ONE_SECOND, tz=timezone.utc)

    def Timestamp(self) -> int:
        return self._timestamp

    def setTimestamp(self, timestamp: int):
        self._timestamp = max([self._timestamp, timestamp])

    def Sleep(self, seconds: float):
        self._timestamp += int(seconds * KEY.ONE_SECOND)
