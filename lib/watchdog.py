import atexit
import os
import signal
import sys
import traceback

import psutil

from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer


class Watchdog:
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        self._config = config
        self._logger: AbstractLogger = factory.Logger(config, factory, timer)

        self._handlers = []

        atexit.register(self.Shutdown)
        signal.signal(signal.SIGINT, self._on_break)
        signal.signal(signal.SIGHUP, self._on_error)

        self.shutdown_in_progress = False


    def addHandler(self, fn):
        self._handlers.append(fn)

    def _on_error(self, signal, frame):
        self.Shutdown(-1, 'Error Signal Event')

    def _on_break(self, signal, frame):
        self.Shutdown(0, 'Key Break Event')

    def Shutdown(self, code: int = -1, message: str = 'Unknown Reason'):
        if self.shutdown_in_progress:
            return
        else:
            self.shutdown_in_progress = True

        self._logger.warning('Shutdown', reason=message)
        for handler in self._handlers:
            try:
                handler()
            except Exception as e:
                sys.stderr.write(f'Shutdown Error: {e}, Traceback: {traceback.format_exc()}')

        pid = os.getpid()
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for process in children:
            print(f'Killing child pid={process.pid}')
            process.send_signal(signal.SIGTERM)
        print(f'Killing parent pid={pid}')
        os._exit(code)
