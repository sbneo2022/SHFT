import copy
import hashlib
import hmac
import sys
import time
import urllib.parse
from decimal import Decimal
from http import HTTPStatus
from pathlib import Path
from typing import Optional, Union, List, Dict

import requests


sys.path.append(Path(__file__).absolute().parent.parent.parent.parent.parent.as_posix())
from tools.pancake.lib.venue.base import Pair, OperationResult
from tools.pancake.lib.venue.base.bidask import Bidask
from tools.pancake.lib.helpers import load_parameters

WSS = "wss://stream.binance.com:9443"
REST = "https://api.binance.com"

SECTION = "binance"

COMMISSION = Decimal("0.0007")
TRANSFER_COMMISSION = Decimal(".00005")


class BinanceSpot(Bidask):
    def __init__(self, config: dict):
        super().__init__(config)

        # Load key/secret from SECTION or directly from config (for multiply accs)
        self.key, self._secret, self.address, self.memo = load_parameters(
            config=config, section=SECTION, keys=["key", "secret", "address", "memo"]
        )

        # Exit with message if `key` or `secret` is absent
        if not all([self.key, self._secret]):
            print(f'No "key" or "secret" found in {SECTION} section: {config}')
            exit(-1)

        self._pairs_info = self._get_pairs_info()
        self._products_info = self._get_products_info()

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
            url=REST + endpoint,
            params=params,
            headers={"X-MBX-APIKEY": self.key},
        )
        return r.json() if r.status_code == HTTPStatus.OK else r.text

    def get_prices(self):
        """
        Get midpoint for all symbols

        Returns:
            dict: The midpoint for each symbol
        """
        prices_json = self._request("GET", endpoint="/api/v3/ticker/price", sign=False)

        prices = {}
        for element in prices_json:
            prices[element["symbol"]] = Decimal(element["price"])
        return prices

    def updateOrderbooks(self, pairs: List[Pair]):
        def _fn(pair: Pair):
            symbol = self._pairs_info[pair]["symbol"]
            r = self._request(
                method="GET", endpoint="/api/v3/depth", params={"symbol": symbol,},
            )

            if isinstance(r, str):
                return

            self._orderbooks[pair] = {
                "asks": r["asks"],
                "bids": r["bids"],
            }

        for pair in pairs:
            _fn(pair)

    def transferQuote(
        self, bidask, pair: Pair, quote: Decimal, live: bool = False
    ) -> OperationResult:
        return OperationResult(value=quote * (1 - TRANSFER_COMMISSION))

    def transferBase(
        self, bidask, pair: Pair, base: Decimal, live: bool = False
    ) -> OperationResult:
        return OperationResult(value=base * (1 - TRANSFER_COMMISSION))

    def buyBase(
        self, pair: Pair, quote: Decimal, live: bool = False
    ) -> OperationResult:
        commission = quote * COMMISSION
        top_ask, _ = self._orderbooks[pair]["asks"][0]
        top_ask = Decimal(top_ask)
        base = (quote - commission) / top_ask
        return OperationResult(value=base)

    def sellBase(
        self, pair: Pair, base: Decimal, live: bool = False
    ) -> OperationResult:

        top_bid, _ = self._orderbooks[pair]["bids"][0]
        top_bid = Decimal(top_bid)
        quote = base * top_bid
        commission = quote * COMMISSION
        quote = quote - commission
        return OperationResult(value=quote)

    def getProductsInfo(self) -> Dict[str, dict]:
        return self._products_info

    def getPairsInfo(self) -> Dict[Pair, dict]:
        return self._pairs_info

    def _get_products_info(self) -> Optional[Dict[str, dict]]:
        return_me = {}
        r = self._request(
            method="GET", endpoint="/sapi/v1/capital/config/getall", sign=True
        )

        if isinstance(r, str):
            return None

        for item in r:
            for network in item["networkList"]:
                if (
                    network["network"] == "BSC"
                    and network["withdrawEnable"]
                    and network["depositEnable"]
                ):
                    return_me[item["coin"]] = {
                        "name": item["name"],
                        "fee": Decimal(network["withdrawFee"]),
                    }

        return return_me

    def _get_pairs_info(self) -> Optional[Dict[Pair, dict]]:
        return_me = {}

        r = self._request(method="GET", endpoint="/api/v3/exchangeInfo", params=dict())

        if isinstance(r, str):
            return None

        for item in r["symbols"]:
            if item["status"] == "TRADING":
                symbol = item["symbol"]
                base_asset = item["baseAsset"]
                quote_asset = item["quoteAsset"]
                straight_name = Pair(base=base_asset, quote=quote_asset)
                inverted_name = Pair(base=quote_asset, quote=base_asset)
                straight_item = {
                    "base_asset": base_asset,
                    "quote_asset": quote_asset,
                    "symbol": symbol,
                    "inverted": False,
                }
                inverted_item = {
                    "base_asset": quote_asset,
                    "quote_asset": base_asset,
                    "symbol": symbol,
                    "inverted": True,
                }

                for filter in item["filters"]:
                    if filter["filterType"] == "PRICE_FILTER":
                        straight_item["tick_size"] = Decimal(filter["tickSize"])
                        inverted_item["min_qty"] = Decimal(filter["tickSize"])
                    elif filter["filterType"] == "LOT_SIZE":
                        straight_item["min_qty"] = Decimal(filter["minQty"])
                        inverted_item["tick_size"] = Decimal(filter["minQty"])

                return_me[straight_name] = copy.deepcopy(straight_item)
                return_me[inverted_name] = copy.deepcopy(inverted_item)

        return return_me
