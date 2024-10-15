import os
import json
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
from lib.helpers import load_parameters

SECTION = "cex"

URL = "https://api.binance.com"

MONTH_MAP = {
    1: "F",
    2: "G",
    3: "H",
    4: "J",
    5: "K",
    6: "M",
    7: "N",
    8: "Q",
    9: "U",
    10: "V",
    11: "X",
    12: "Z",
}


class Cex:
    def __init__(self, config):

        # Load key/secret from SECTION or directly from config (for multiply accs)
        self.key, self._secret, self.address, self.memo = load_parameters(
            config=config, section=SECTION, keys=["key", "secret", "address", "memo"]
        )

        # Exit with message if `key` or `secret` is absent
        if not all([self.key, self._secret]):
            print(f'No "key" or "secret" found in {SECTION} section: {config}')
            exit(-1)

        self._exchange_info = self._get_exchange_info()

        self.reference = self._get_reference(self._exchange_info)

    def _get_reference(self, exchange_info: dict) -> Dict[str, Dict[str, Decimal]]:
        return_me = {}
        for item in exchange_info["symbols"]:
            return_me[item["symbol"]] = {}
            for filter in item["filters"]:
                if filter["filterType"] == "PRICE_FILTER":
                    return_me[item["symbol"]]["min_price"] = Decimal(filter["tickSize"])
                if filter["filterType"] == "LOT_SIZE":
                    return_me[item["symbol"]]["min_qty"] = Decimal(filter["minQty"])
                if filter["filterType"] == "MIN_NOTIONAL":
                    return_me[item["symbol"]]["min_notional"] = Decimal(
                        filter["minNotional"]
                    )

        return return_me

    def _get_coins_info(self) -> dict:
        return self._request(
            method="GET", endpoint="/sapi/v1/capital/config/getall", sign=True,
        )

    def _get_exchange_info(self) -> dict:
        with open("tools/arbitrage_proof/media/binance_reference.json", "r") as f:
            return json.loads(f.read())

    def _sign(self, params) -> dict:
        if "signature" in params.keys():
            del params["signature"]
        params["timestamp"] = time.time_ns() // 1_000_000
        query = urllib.parse.urlencode([(key, value) for key, value in params.items()])
        params["signature"] = hmac.new(
            self._secret.encode(), query.encode(), digestmod=hashlib.sha256
        ).hexdigest()
        return params

    def _request(
        self, method, endpoint, params=None, sign: bool = False
    ) -> Union[dict, list, str]:
        params = self._sign(params or {}) if sign else params
        r = requests.request(
            method=method,
            url=URL + endpoint,
            params=params,
            headers={"X-MBX-APIKEY": self.key},
        )

        return r.json() if r.status_code == HTTPStatus.OK else r.text

    def getStatus(self, id: str) -> Tuple[Optional[dict], Optional[str]]:
        # {'clientOrderId': 'AVABNB_21M17071347562355',
        #  'cummulativeQuoteQty': '3.78826200',
        #  'executedQty': '394.20000000',
        #  'icebergQty': '0.00000000',
        #  'isWorking': True,
        #  'orderId': 38073977,
        #  'orderListId': -1,
        #  'origQty': '394.20000000',
        #  'origQuoteOrderQty': '0.00000000',
        #  'price': '0.00000000',
        #  'side': 'SELL',
        #  'status': 'FILLED',
        #  'stopPrice': '0.00000000',
        #  'symbol': 'AVABNB',
        #  'time': 1623914027581,
        #  'timeInForce': 'GTC',
        #  'type': 'MARKET',
        #  'updateTime': 1623914027581}

        symbol, _ = id.split("_")

        r = self._request(
            "GET",
            endpoint="/api/v3/order",
            params=dict(symbol=symbol, origClientOrderId=id),
            sign=True,
        )

        return (None, r) if isinstance(r, str) else (r, None)

    def getTransactions(
        self, last_hours=1
    ) -> Tuple[Optional[List[dict]], Optional[str]]:
        # {'address': 'bnb136ns6lfw4zs5hg4n85vdthaad7hq5m4gtkgf23',
        #  'addressTag': '120880303',
        #  'amount': '0.00813517',
        #  'coin': 'BNB',
        #  'confirmTimes': '1/1',
        #  'insertTime': 1623089958000,
        #  'network': 'BNB',
        #  'status': 1,
        #  'transferType': 0,
        #  'txId': '484EBF150E9E5AE8AF359D52ED6A3F04CCD46BEDC635C9571720AC99EDD5D498'},

        start_time = int(
            (datetime.now(tz=timezone.utc) - timedelta(hours=last_hours)).timestamp()
            * 1e3
        )
        params = {"startTime": start_time}
        r = self._request(
            "GET", endpoint="/sapi/v1/capital/deposit/hisrec", params=params, sign=True
        )

        return (None, r) if isinstance(r, str) else (r, None)

    def getWithdrawalAmountBTC(
        self, last_hours=24
    ) -> Tuple[Optional[Decimal], Optional[str]]:
        start_time = int(
            (datetime.now(tz=timezone.utc) - timedelta(hours=last_hours)).timestamp()
            * 1e3
        )
        params = {"startTime": start_time}

        withdraw_history = self._request(
            "GET",
            endpoint="/sapi/v1/capital/withdraw/history",
            params=params,
            sign=True,
        )

        if isinstance(withdraw_history, str):
            return (None, withdraw_history)

        prices = self._request("GET", endpoint="/api/v3/ticker/price", sign=False)

        if isinstance(prices, str):
            return (None, prices)

        price_reference: Dict[str, Decimal] = {}

        for item in prices:
            price_reference[item["symbol"]] = Decimal(item["price"])

        bnb_btc = price_reference["BNBBTC"]

        total_btc_withdraw = Decimal(0)

        for item in withdraw_history:
            coin_bnb = Decimal(price_reference.get(item["coin"] + "BNB", 1))
            bnb_amount = Decimal(item["amount"]) * coin_bnb
            btc_amount = bnb_amount * bnb_btc
            total_btc_withdraw += btc_amount

        return (total_btc_withdraw, None)

    def getWallet(self) -> Tuple[Optional[Dict[str, Decimal]], Optional[str]]:
        return_me = defaultdict(lambda: Decimal("0"))
        r = self._request("GET", endpoint="/sapi/v1/capital/config/getall", sign=True)

        if isinstance(r, str):
            return (None, r)

        for item in r:
            free = Decimal(item["free"])
            if free > 1e-9:
                return_me[item["coin"]] = free

        return (return_me, None)

    def getProducts(
        self,
    ) -> Tuple[Optional[Dict[str, Dict[str, Decimal]]], Optional[str]]:
        return_me = {}
        r = self._request("GET", "/api/v3/ticker/24hr")

        if isinstance(r, str):
            return (None, r)

        for item in r:
            ask_price, bid_price = Decimal(item["askPrice"]), Decimal(item["bidPrice"])
            symbol: str = item["symbol"]
            if not symbol.startswith("LIT"):
                if ask_price > 1e-9 and bid_price > 1e-9:
                    return_me[symbol] = {
                        "ask_price": ask_price,
                        "ask_qty": Decimal(item["askQty"]),
                        "bid_price": bid_price,
                        "bid_qty": Decimal(item["bidQty"]),
                    }

        return (return_me, None)

    def Transfer(
        self, coin: str, qty: Decimal, address: str, memo: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        params = {
            "coin": coin,
            "address": address,
            "amount": qty,
            "network": "BNB",
        }

        if memo is not None:
            params["addressTag"] = memo

        r = self._request(
            "POST", endpoint="/sapi/v1/capital/withdraw/apply", params=params, sign=True
        )

        if isinstance(r, str):
            return (None, r)

        return (r["id"], None)

    def Cancel(self, id: Optional[str] = None) -> Optional[str]:
        symbol, _ = id.split("_")
        params = dict(symbol=symbol)

        if id is None:
            endpoint = "/api/v3/openOrders"
        else:
            params["origClientOrderId"] = id
            endpoint = "/api/v3/order"

        r = self._request("DELETE", endpoint=endpoint, params=params, sign=True)

        if isinstance(r, str):
            return r
        else:
            return None

    def Post(
        self, symbol: str, qty: Decimal, price: Optional[Decimal] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        now = datetime.now(tz=timezone.utc)

        id = (
            f"{symbol}_"
            f"{now.year - 2000}{MONTH_MAP[now.month]}{now.day:02}"
            f"{now.hour:02}{now.minute:02}{now.second:02}"
            f"{now.microsecond:06}"
        )

        params = dict(
            symbol=symbol,
            side="BUY" if qty > 0 else "SELL",
            quantity=abs(qty),
            newClientOrderId=id,
        )

        if price is None:
            params["type"] = "MARKET"

        else:  # Limit Orders
            params["timeInForce"] = "GTC"
            params["price"] = price
            params["type"] = "LIMIT"

        r = self._request("POST", endpoint="/api/v3/order", params=params, sign=True)

        return (None, r) if isinstance(r, str) else (id, None)
