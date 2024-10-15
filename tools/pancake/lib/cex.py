import hashlib
import hmac
import math
import time
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http import HTTPStatus
from typing import Dict, List, Optional, Tuple, Union

import requests
from tools.pancake.lib.constants import CONSTANTS, KEY, ExecutionReport
from tools.pancake.lib.lib import execute_order, timeit

from tools.pancake.lib.helpers import load_parameters, sign

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

        self._config = config

        # Exit with message if `key` or `secret` is absent
        if not all([self.key, self._secret]):
            print(f'No "key" or "secret" found: {config}')
            exit(-1)

        self._exchange_info = self._get_exchange_info()

        self.reference = self._get_reference(self._exchange_info)

    def _get_reference(self, exchange_info: dict) -> Dict[str, Dict[str, float]]:
        return_me = {}
        for item in exchange_info["symbols"]:
            return_me[item["symbol"]] = {}

            return_me[item["symbol"]][KEY.QUOTE_PRECISION] = int(
                item[KEY.QUOTE_PRECISION]
            )
            return_me[item["symbol"]][KEY.BASE_PRECISION] = int(
                item[KEY.BASE_PRECISION]
            )

            for filter in item["filters"]:

                if filter["filterType"] == "PRICE_FILTER":
                    return_me[item["symbol"]]["min_price"] = float(filter["tickSize"])

                if filter["filterType"] == "LOT_SIZE":
                    return_me[item["symbol"]]["min_qty"] = float(filter["minQty"])

                if filter["filterType"] == "MIN_NOTIONAL":
                    return_me[item["symbol"]]["min_notional"] = float(
                        filter["minNotional"]
                    )

        return return_me

    def _get_coins_info(self) -> dict:
        return self._request(
            method="GET", endpoint="/sapi/v1/capital/config/getall", sign=True,
        )

    def _get_exchange_info(self) -> dict:
        return self._request(
            method="GET", endpoint="/api/v3/exchangeInfo", params=dict()
        )

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
            price_reference[item["symbol"]] = float(item["price"])

        bnb_btc = price_reference["BNBBTC"]

        total_btc_withdraw = float(0)

        for item in withdraw_history:
            coin_bnb = float(price_reference.get(item["coin"] + "BNB", 1))
            bnb_amount = float(item["amount"]) * coin_bnb
            btc_amount = bnb_amount * bnb_btc
            total_btc_withdraw += btc_amount

        return (total_btc_withdraw, None)

    def getWallet(self) -> Tuple[Optional[Dict[str, Decimal]], Optional[str]]:
        return_me = defaultdict(lambda: float("0"))
        r = self._request("GET", endpoint="/sapi/v1/capital/config/getall", sign=True)

        if isinstance(r, str):
            return (None, r)

        for item in r:
            free = float(item["free"])
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
            ask_price, bid_price = float(item["askPrice"]), float(item["bidPrice"])
            symbol: str = item["symbol"]
            if not symbol.startswith("LIT"):
                if ask_price > 1e-9 and bid_price > 1e-9:
                    return_me[symbol] = {
                        "ask_price": ask_price,
                        "ask_qty": float(item["askQty"]),
                        "bid_price": bid_price,
                        "bid_qty": float(item["bidQty"]),
                    }

        return (return_me, None)

    def Transfer(
        self, coin: str, qty: Decimal, address: str, memo: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        params = {
            "coin": coin,
            "address": address,
            "amount": qty,
            "network": "BSC",
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
        self,
        symbol: str,
        qty: Optional[Decimal] = None,
        quote_order_quantity: Optional[Decimal] = None,
        price: Optional[Decimal] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        now = datetime.now(tz=timezone.utc)

        id = (
            f"{symbol}_"
            f"{now.year - 2000}{MONTH_MAP[now.month]}{now.day:02}"
            f"{now.hour:02}{now.minute:02}{now.second:02}"
            f"{now.microsecond:06}"
        )

        params = dict(symbol=symbol, newClientOrderId=id,)

        if quote_order_quantity is None:
            params["quantity"] = abs(qty)
            params["side"] = "BUY" if qty > 0 else "SELL"
        else:
            params["quoteOrderQty"] = abs(quote_order_quantity)
            params["side"] = "BUY" if quote_order_quantity > 0 else "SELL"

        if price is None:
            params["type"] = "MARKET"

        else:  # Limit Orders
            params["timeInForce"] = "GTC"
            params["price"] = price
            params["type"] = "LIMIT"

        r = self._request("POST", endpoint="/api/v3/order", params=params, sign=True)

        return (None, r) if isinstance(r, str) else (id, None)

    @timeit
    def market_order(
        self, coin_from: str, coin_to: str, quantity: Decimal
    ) -> ExecutionReport:
        """
        Search for the market pair and execute a sell/buy order to get the coin to from
        the coin from.

        Args:
            coin_from (str): The name of the coin_from
            coin_to (str): The name of the coin_to
            quantity (Decimal): The amount of coin_from to swap for the coin_to

        Returns:
            (ExecutionReport) The report about the run of the execution
        """

        quote_order_quantity = None

        if coin_from + coin_to in self.reference:
            # base to quote.
            market_pair = coin_from + coin_to
            precision = self.reference[market_pair][KEY.QUOTE_PRECISION] - 1

            quantity = math.floor(quantity * 10 ** precision) / 10 ** (precision)
            quantity *= -1

        elif coin_to + coin_from in self.reference:
            # quote to base
            market_pair = coin_to + coin_from
            precision = self.reference[market_pair][KEY.BASE_PRECISION] - 1

            quantity = math.floor(quantity * 10 ** precision) / 10 ** (precision)
            quote_order_quantity = quantity

        min_qty = self.reference[market_pair][KEY.MIN_QTY]

        report = ExecutionReport()
        report.SYMBOL = coin_to

        original_qty = self.getWallet()[0].get(coin_to, 0)

        if quote_order_quantity is not None:
            quote_order_quantity = (
                sign(quote_order_quantity)
                * math.floor(quote_order_quantity / min_qty)
                * min_qty
            )

            order_id, error = self.Post(
                symbol=market_pair, quote_order_quantity=quote_order_quantity
            )
        else:
            quantity = sign(quantity) * math.floor(abs(quantity) / min_qty) * min_qty
            order_id, error = self.Post(symbol=market_pair, qty=quantity)

        if error is not None:
            report.SUCCESS = False
            report.ERROR_STR = (
                f"Error when posting the order for {round(quantity,2)} "
                f"of {coin_from} {error}"
            )
            return report

        while True:
            status, _ = self.getStatus(order_id)
            if status is not None and status["status"] == "FILLED":

                while True:
                    new_qty, _ = self.getWallet()
                    if new_qty is not None and new_qty[coin_to] != original_qty:
                        executed_qty = new_qty[coin_to] - original_qty
                        report.EXECUTED_QTY = executed_qty
                        return report

                    time.sleep(CONSTANTS.TIME_DELAY / 2)

            time.sleep(CONSTANTS.TIME_DELAY / 2)

    @timeit
    def transfer(self, coin: str, quantity: Decimal, dex) -> ExecutionReport:
        """
        Transfer the coin from the CEX to the DEX

        Args:
            coin (str): The name of the coin
            quantity (Decimal): The amount of coin_from to swap for the coin_to

        Returns:
            (ExecutionReport) The report about the run of the execution
        """
        previous_qty = dex.check_balance(coin)

        address = dex._address
        _, err = self.Transfer(coin, quantity, address=address)

        report = ExecutionReport()
        report.SYMBOL = coin

        if err is not None:
            report.SUCCESS = False
            report.ERROR_STR = f"Failed transfer with error: {err}"

            return report

        while True:
            time.sleep(CONSTANTS.TIME_DELAY)
            actual_qty = dex.check_balance(coin)

            if actual_qty != previous_qty:
                report.EXECUTED_QTY = actual_qty - previous_qty
                return report

