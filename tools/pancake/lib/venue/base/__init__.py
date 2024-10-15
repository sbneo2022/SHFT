from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, List, Dict, Any


@dataclass
class Pair:
    base: str
    quote: str

    def __hash__(self):
        return self.__str__().__hash__()

    def __repr__(self):
        return self.base + "-" + self.quote

    __str__ = __repr__


@dataclass
class OperationResult:
    value: Optional[Decimal] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self):
        return self.value is not None


