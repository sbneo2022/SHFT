import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pprint import pprint
from typing import Any, List

import numpy as np


sys.path.append(os.path.abspath('../../..'))
from tools.spread_autoadjust.fn import Event

class Window:
    def __init__(self, window: timedelta):
        self._window = window

        self._data: dict[datetime, Any] = {}

        self._is_ready = False

    def add(self, time: datetime, value: Any):
        oldest = time - self._window
        keys = list(self._data.keys())
        for item in keys:
            if item < oldest:
                self._is_ready = True
                del self._data[item]
        self._data[time] = value

    def get(self) -> List[Any]:
        return list(self._data.values())

    def isReady(self) -> bool:
        return self._is_ready


class MovingMax:
    def __init__(self, config: dict):
        self._config = config

        self._window = Window(timedelta(minutes=3))

        self._target_spread = self._config.get('target_spread', 0.0050)

        self._up = None
        self._down = None

        self._state = 0

        self._entry = None

        self._max = 0
        self._min = 0
        self._mean = 0

    def getEvent(self, spread: float, time: datetime) -> Event:
        self._window.add(time, spread)

        data = self._window.get()
        self._max = max(data)
        self._min = min(data)
        self._mean = np.mean(data)

        if self._entry is None:
            self._up = self._mean + 0.5 * self._target_spread
            self._down = self._mean - 0.5 * self._target_spread
        elif self._state == 1:
            self._up = self._mean + 0.5 * self._target_spread
            self._down = self._entry - self._target_spread
        else:
            self._up = self._entry + self._target_spread
            self._down = self._mean - 0.5 * self._target_spread

        if self._state == 0 and spread > self._up:
            flip = True
            self._state = 1
            self._entry = spread
        elif self._state == 1 and spread < self._down:
            flip = True
            self._state = 0
            self._entry = spread
        else:
            flip = False

        return Event(high=self._up, low=self._down, flip=flip)