import sys
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import List

sys.path.append(Path(__file__).absolute().parent.parent.parent.parent.as_posix())
from tools.pancake.lib.venue.base import Pair
from tools.pancake.lib.venue.base.bidask import Bidask
from tools.pancake.lib.venue.base.xyk import Xyk


class Case(Enum):
    ONE = "Swap->Transfer->Exchange->Transfer"
    TWO = "Exchange->Transfer->Swap->Transfer"


class Arbitrage:
    def __init__(self, config: dict, bidask: Bidask, xyk: Xyk):
        self._config = config

        self._bidask = bidask
        self._xyk = xyk

    def getReport(self, pair: Pair, capital: Decimal) -> List[dict]:
        return_me = []

        ################################################################################################################
        # Case_1: 1) Swap Quote -> Base on XYK 2) Transfer Base -> Bidask 3) Sell Base -> Quote 4) Transfer Quote -> XYK
        ################################################################################################################
        report = {"capital": capital, "pair": pair, "case": Case.ONE, "steps": {}}
        report["steps"]["1. we_got_base"] = self._xyk.swapQuote(
            pair, quote=capital
        ).value
        report["steps"]["2. we_received_on_bidask"] = self._xyk.transferBase(
            self._bidask, pair, report["steps"]["1. we_got_base"]
        ).value
        report["steps"]["3. we_got_quote"] = self._bidask.sellBase(
            pair, base=report["steps"]["2. we_received_on_bidask"]
        ).value
        report["steps"]["4. output"] = self._bidask.transferQuote(
            self._xyk, pair, report["steps"]["3. we_got_quote"]
        ).value
        report["roc"] = report["steps"]["4. output"] / capital - 1
        report["revenue"] = report["steps"]["4. output"] - capital
        return_me.append(report)

        ################################################################################################################
        # Case_2: 1) Buy Base on Bidask 2) Transfer Base -> Xyk 3) Swap Base -> Quote on Xyk 4) Transfer Quote -> Bidask
        ################################################################################################################
        report = {"capital": capital, "pair": pair, "case": Case.TWO, "steps": {}}
        report["steps"]["1. we_got_base"] = self._bidask.buyBase(pair, capital).value
        report["steps"]["2. we_received_on_xyk"] = self._bidask.transferBase(
            self._xyk, pair, report["steps"]["1. we_got_base"]
        ).value
        report["steps"]["3. we_got_quote"] = self._xyk.swapBase(
            pair, base=report["steps"]["2. we_received_on_xyk"]
        ).value
        report["steps"]["4. output"] = self._xyk.transferQuote(
            self._bidask, pair, report["steps"]["3. we_got_quote"]
        ).value
        report["roc"] = report["steps"]["4. output"] / capital - 1
        report["revenue"] = report["steps"]["4. output"] - capital
        return_me.append(report)

        return return_me

