import sys
from typing import Mapping, Optional

from lib.database import AbstractDatabase

class FakeDb(AbstractDatabase):

    def Encode(self, fields: Mapping[str, any], timestamp: int, tags: Optional[Mapping[str, any]] = None):
        return f'{fields} {int(timestamp)}'

    def writeEncoded(self, data: list):
        sys.stdout.write(f'FakeDb: {data}\n')
        sys.stdout.flush()

    def readLast(self, field: str):
        pass

