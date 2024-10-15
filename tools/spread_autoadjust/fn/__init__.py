from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

@dataclass
class Event:
    high: float
    low: float
    flip: bool = False