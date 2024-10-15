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

class Fixed:
    def __init__(self, config: dict):
        self._config = config

        self._target_spread = self._config.get('target_spread', 0.0050)

        self._up = self._target_spread
        self._down = 0

        self._state = 0

        self._entry = None


    def getEvent(self, spread: float, time: datetime) -> Event:

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