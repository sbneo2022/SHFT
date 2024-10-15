import os
from datetime import datetime

ROOT = os.path.dirname(__file__)
ROOT = os.path.join(ROOT, "..")
ROOT = os.path.abspath(ROOT)


class Lock:
    def __init__(self, filename=".lock.pid"):
        self._filename = os.path.join(ROOT, filename)

    def lock(self):
        with open(self._filename, "w") as fp:
            fp.write(os.getpid().__str__())

    def unlock(self):
        if self.is_lock():
            os.remove(self._filename)

    def is_lock(self) -> bool:
        return os.path.isfile(self._filename)


def handle_lock(config: dict):
    locker = Lock()
    if config.get("lock", True):
        if locker.is_lock():
            print("Lock file is found, but parallel execution is not allowed. Exit.")
            exit(-1)
    locker.lock()
