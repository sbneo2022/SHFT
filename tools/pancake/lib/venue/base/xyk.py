import sys
from abc import abstractmethod, ABC
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Union

sys.path.append(Path(__file__).absolute().parent.parent.parent.parent.parent.parent.as_posix())
from tools.pancake.lib.venue.base import Pair, OperationResult

E18 = Decimal(str(1e18))


class Xyk(ABC):
    def __init__(self, config: dict):
        self._config = config

        self._reference = self.loadReference()
        self._reserves: Dict[Pair, Dict[str, Decimal]] = defaultdict(
            lambda: defaultdict(lambda: Decimal("0"))
        )

    @abstractmethod
    def loadReference(self) -> Dict[Pair, dict]:
        pass

    @abstractmethod
    def updateReserves(self, pairs: List[Pair]):
        pass

    @abstractmethod
    def transferQuote(self, bidask, pair: Pair, quote: Decimal, live: bool = False) -> OperationResult:
        pass

    @abstractmethod
    def transferBase(self, bidask, pair: Pair, base: Decimal, live: bool = False) -> OperationResult:
        pass

    @abstractmethod
    def swapBase(self, pair: Pair, base: Decimal, live: bool = False) -> OperationResult:
        pass

    @abstractmethod
    def swapQuote(self, pair: Pair, quote: Decimal, live: bool = False) -> OperationResult:
        pass

    def getReserves(self, pair: Pair) -> Dict[str, Decimal]:
        return self._reserves[pair]

    def _calc_swap_base(self, pair: Pair, qty: Union[int, Decimal]) -> Decimal:
        base_reserve = self._reserves[pair]["reserve0"]
        quote_reserve = self._reserves[pair]["reserve1"]

        qty = qty * Decimal(10 ** self._reference[pair]["base_decimals"])

        value = (qty * base_reserve * quote_reserve) / pow(qty + base_reserve, 2)

        return value / Decimal(10 ** self._reference[pair]["quote_decimals"])

    def _calc_swap_quote(self, pair: Pair, qty: Union[int, Decimal]) -> Decimal:
        base_reserve = self._reserves[pair]["reserve0"]
        quote_reserve = self._reserves[pair]["reserve1"]

        qty = qty * Decimal(10 ** self._reference[pair]["quote_decimals"])

        value = (qty * base_reserve * quote_reserve) / pow(qty + quote_reserve, 2)

        return value / Decimal(10 ** self._reference[pair]["base_decimals"])
