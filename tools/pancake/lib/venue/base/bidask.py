import sys
from abc import ABC, abstractmethod
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

sys.path.append(Path(__file__).absolute().parent.parent.parent.parent.parent.parent.as_posix())
from tools.pancake.lib.venue.base import Pair, OperationResult


class Bidask(ABC):
    def __init__(self, config: dict):
        self._config = config

        self._orderbooks: Dict[Pair, dict] = {}

    @abstractmethod
    def updateOrderbooks(self, pairs: List[Pair]):
        pass

    def getOrderbook(self, pair: Pair):
        return self._orderbooks[pair]

    def transferQuote(self, bidask, pair: Pair, quote: Decimal, live: bool = False) -> OperationResult:
        """
        Make or calculate transferring Quote side of Pair from Bidask Exchange to Xyk Swap (wallet)
        :param bidask: exchange implementation (Bidask child)
        :param pair: target Pair
        :param quote: Quote qty to transfer
        :param live: by default False -> make caclulations only; make transfer if True, wait for 'done'
        :return: Actual transferred qty after all fees
        """
        pass

    def transferBase(self, bidask, pair: Pair, base: Decimal, live: bool = False) -> OperationResult:
        """
        Make or calculate transferring Base side of Pair from Bidask Exchange to Xyk Swap (wallet)
        :param bidask: exchange implementation (Bidask child)
        :param pair: target Pair
        :param quote: Quote qty to transfer
        :param live: by default False -> make calculations only; make transfer if True
        :return: Actual transferred qty after all fees
        """
        pass

    def buyBase(self, pair: Pair, quote: Decimal, live: bool = False) -> OperationResult:
        """
        Buy Base side of Pair on Bidask Exchange
        :param pair: target Pair
        :param quote: How many Quote coins we want to use. For excample for coin $25/coin with quote=$100 we will buy 4
        :param live:  by default False -> make calculations only; make MARKET order if True, wait for 'done'
        :return: Actual amount of Base coins we bought
        """
        pass

    def sellBase(self, pair: Pair, base: Decimal, live: bool = False) -> OperationResult:
        """
        Sell Base side of Pair on Bidask Exchange
        :param pair: target Pair
        :param quote: How many Base coins we want to use for SELL order (we should be sure that we have that amount)
        :param live:  by default False -> make calculations only; make MARKET order if True, wait for 'done'
        :return: Actual amount of Quote coins we get
        """
        pass
