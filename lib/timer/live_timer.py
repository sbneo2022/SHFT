import time
from datetime import datetime, timezone

from lib.timer import AbstractTimer


class LiveTimer(AbstractTimer):
    def Now(self) -> datetime:
        return datetime.now(tz=timezone.utc)

    def Timestamp(self) -> int:
        return time.time_ns()

    def setTimestamp(self, timestamp: int):
        pass

    def Sleep(self, seconds: float):
        time.sleep(seconds)