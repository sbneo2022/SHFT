from collections import defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from http import HTTPStatus
from pprint import pprint
from typing import Optional, Tuple, Dict, Union, List

import requests
from binance_chain.environment import BinanceEnvironment
from binance_chain.http import HttpApiClient
from binance_chain.messages import TransferMsg
from binance_chain.wallet import Wallet

SECTION = "dex"

URL = "https://dex.binance.org"


class Dex:
    def __init__(self, config: dict):
        self._address = config[SECTION]["address"]
        self._private_key = config[SECTION]["private_key"]

        self._environment = BinanceEnvironment.get_production_env()
        self._client = HttpApiClient(env=self._environment)
        self._wallet = Wallet(self._private_key, env=self._environment)

        self.reference: Dict[str, str] = {}

    def _request(
        self, method, endpoint, params=None, sign: bool = False
    ) -> Union[dict, list, str]:
        r = requests.request(method=method, url=URL + endpoint, params=params)
        return r.json() if r.status_code == HTTPStatus.OK else r.text

    def getProducts(
        self,
    ) -> Tuple[Optional[Dict[str, Dict[str, Decimal]]], Optional[str]]:
        return_me = {}
        r = self._request("GET", "/api/v1/ticker/24hr")

        if isinstance(r, str):
            return (None, r)

        for item in r:
            ask_price, bid_price = Decimal(item["askPrice"]), Decimal(item["bidPrice"])

            if ask_price > 1e-9 and bid_price > 1e-9:
                left, right = item["symbol"].split("_")
                left_product = left.split("-")[0]
                right_product = right.split("-")[0]

                self.reference[left_product] = left
                self.reference[right_product] = right

                return_me[item["symbol"]] = {
                    "ask_price": ask_price,
                    "ask_qty": Decimal(item["askQuantity"]),
                    "bid_price": bid_price,
                    "bid_qty": Decimal(item["bidQuantity"]),
                }
        return (return_me, None)

    def getWallet(
        self,
    ) -> Tuple[Optional[Dict[str, Dict[str, Decimal]]], Optional[str]]:
        return_me = defaultdict(lambda: Decimal("0"))

        try:
            account = self._client.get_account(self._address)

            for item in account["balances"]:
                symbol = item["symbol"]  # .split('-')[0]
                return_me[symbol] = Decimal(item["free"])

            return (return_me, None)

        except Exception as e:
            return (None, e.__str__())

    def getTransactions(
        self, last_hours=1
    ) -> Tuple[Optional[List[dict]], Optional[str]]:
        end_time = int(datetime.now(tz=timezone.utc).timestamp() * 1e3)
        start_time = int(
            (datetime.now(tz=timezone.utc) - timedelta(hours=last_hours)).timestamp()
            * 1e3
        )
        try:
            transactions = self._client.get_transactions(
                address=self._address, start_time=start_time, end_time=end_time
            )
            return (transactions["tx"], None)
        except Exception as e:
            return (None, e.__str__())

    def Transfer(
        self, coin: str, qty: Decimal, address: str, memo: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        message = TransferMsg(
            wallet=self._wallet, symbol=coin, amount=qty, to_address=address, memo=memo
        )
        try:
            r = self._client.broadcast_msg(message, sync=True)
            return (r[0]["hash"], None)
        except Exception as e:
            return (None, e.__str__())
