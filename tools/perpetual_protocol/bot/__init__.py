import os
import sys
from decimal import Decimal
from typing import List

sys.path.append(os.path.abspath('../../..'))
from tools.perpetual_protocol.lib.constants import KEY
from tools.perpetual_protocol.lib.message import Message


class Bot:
    def __init__(self, config: dict):
        self._config = config

    def _load_as_decimal(self, key: KEY) -> Decimal:
        value = self._config[key.name.lower()]
        return Decimal(str(value))

    def on_message(self, messages: List[Message]):
        pass



def sign(x):
    if x > 0:
        return 1
    elif x < 0:
        return -1
    else:
        return 0