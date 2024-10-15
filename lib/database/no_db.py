from typing import Mapping, Optional

from lib.database import AbstractDatabase

class NoDb(AbstractDatabase):

    def Encode(self, fields: Mapping[str, any], timestamp: int, tags: Optional[Mapping[str, any]] = None):
        return f'{fields} {int(timestamp)}'

    def writeEncoded(self, data: list):
        pass

    def readLast(self, field: str):
        pass

