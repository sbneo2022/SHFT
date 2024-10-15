import os
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Union

sys.path.append(os.path.abspath('../../..'))
from tools.perpetual_protocol.lib.constants import Product


@dataclass
class Message:
    product: Product
    time: datetime


@dataclass
class MessageBestBook(Message):
    best_ask: Union[Decimal, int]
    best_bid: Union[Decimal, int]


@dataclass
class MessageDepth(Message):
    pool_price: Union[Decimal, int]
    base_depth: Union[Decimal, int]
    quote_depth: Union[Decimal, int]
