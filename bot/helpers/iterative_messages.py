import uuid
from typing import List


class IterativeMessages:
    MAX = 10
    def __init__(self):
        self._data = dict()

    def Add(self, message: dict) -> dict:
        uid = uuid.uuid4().__str__()
        self._data[uid] = {'counter': self.MAX, **message}
        return {'uuid': uid, **message}

    def Get(self) -> List[dict]:
        result = []

        for uid in list(self._data.keys()):
            if not self._data[uid]['counter']:
                del self._data[uid]
            else:
                self._data[uid]['counter'] -=1

        for key, value in self._data.items():
            item = value.copy()
            del item['counter']
            result.append({'uuid': key, **item})

        return result