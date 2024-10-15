import os
import sys
import time
import hashlib
import hmac

import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from http import HTTPStatus
from pprint import pprint
from typing import Dict, Optional, Tuple, Union, List

import requests

sys.path.append(os.path.abspath("../../.."))
from tools.arbitrage_proof.lib.cex import Cex
from tools.arbitrage_proof.lib.helpers import load_parameters

SECTION = "cex"
DEFAULT_WITHDRAW_LIMIT_BTC = 2
DEFAULT_WITHDRAW_WINDOW = 24
WITHDRAW_NO_MORE = Decimal(0.9)


class CexAccounts:
    def __init__(self, config: dict, section=SECTION):
        self._config = config
        self._errors = []

        # Create CEX objects according to CEX accounts list
        cex_section = config[section]

        print(cex_section)
        if isinstance(cex_section, dict):
            self._cexs = [Cex(config)]
        elif isinstance(cex_section, list):
            self._cexs = []
            for item in cex_section:
                self._cexs.append(Cex(item))

        # Get and calculate withdrawal limits (total)
        self._withdraw_limit_btc = self._config.get(
            "withdraw_limit_btc", DEFAULT_WITHDRAW_LIMIT_BTC
        )
        self._withdraw_limit_btc = Decimal(str(self._withdraw_limit_btc))

        self._withdraw_window = self._config.get(
            "withdraw_window", DEFAULT_WITHDRAW_WINDOW
        )

        # Now lets load Withdrawal Amount for each acc and choose lowest one
        self._withdraw_amount_btc = Decimal(0)
        lowest_withdraw_amount = self._withdraw_limit_btc * WITHDRAW_NO_MORE
        self._current_idx = None
        for idx, cex in enumerate(self._cexs):
            amount, _ = cex.getWithdrawalAmountBTC(last_hours=self._withdraw_window)
            if amount is not None:
                # We will choose best account
                lowest_withdraw_amount = 99999
                if amount <= lowest_withdraw_amount:
                    lowest_withdraw_amount = amount
                    self._current_idx = idx
                else:
                    self._errors.append(
                        f"Account withdraw amount for {cex.key} is {amount} which > {lowest_withdraw_amount}"
                    )
            else:
                self._errors.append(f"Error getting Account Balance for {cex.key}")

            self._withdraw_amount_btc += amount or Decimal(0)

        # We will set logged withdraw limit as sum of all account limits
        self._withdraw_limit_btc = self._withdraw_limit_btc * len(self._cexs)

        self._latest_wallets: Optional[List[Dict[str, Decimal]]] = None

    def getErrors(self) -> Optional[str]:
        if self._current_idx is not None:
            return None
        else:
            return str(self._errors)

    def getCex(self) -> Optional[Cex]:
        if self._current_idx is not None:
            return self._cexs[self._current_idx]
        else:
            return None

    def getWallet(self) -> Tuple[Optional[Dict[str, Decimal]], Optional[str]]:
        self._latest_wallets = [x.getWallet()[0] for x in self._cexs]

        return_me = defaultdict(lambda: Decimal("0"))

        for item in self._latest_wallets:
            if item is not None:
                for key, value in item.items():
                    return_me[key] += value

        return (return_me, None)

    def getWithdrawLimit(self) -> Decimal:
        return self._withdraw_limit_btc

    def getWithdrawAmount(self) -> Decimal:
        return self._withdraw_amount_btc
