import base64
import hmac
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal

import requests
import urllib.parse

import json
sys.path.append(os.path.abspath('../../..'))
from tools.okex_cleaning.lib.constants import VAULT, KEY, Book

URL = 'https://www.okex.com'


class OKEX_TYPE:
    OPEN_LONG = '1'
    OPEN_SHORT = '2'
    CLOSE_LONG = '3'
    CLOSE_SHORT = '4'
    FIELD = 'type'

class OKEX_ORDER_TYPE:
    NORMAL = '0'
    MARKET = '4'
    FIELD = 'order_type'


class Okex:
    def __init__(self, config):
        self._key = config[KEY.EXHANGE_OKEX_PERP][VAULT.KEY]
        self._secret = config[KEY.EXHANGE_OKEX_PERP][VAULT.SECRET]
        self._passphrase = str(config[KEY.EXHANGE_OKEX_PERP][VAULT.PASSPHRASE])

    def _sign(self, timestamp: str, method: str, endpoint: str, params: dict) -> str:
        if method in [KEY.GET, KEY.DELETE]:
            query = urllib.parse.urlencode([(key, value) for key, value in params.items()])
            query = f'{timestamp}{method.upper()}{endpoint}{("?" if query != "" else "" )}{query}'
        else:
            _params = json.dumps(params) if params != {} else ''
            query = f'{timestamp}{method.upper()}{endpoint}{_params}'
        signature = hmac.new(bytes(self._secret, encoding='utf8'), bytes(query, encoding='utf-8'), digestmod='sha256').digest()
        return base64.b64encode(signature)

    def _timestamp2str(self, timestamp: int) -> str:
        dt = datetime.fromtimestamp(timestamp / KEY.ONE_SECOND, tz=timezone.utc).replace(tzinfo=None)
        return dt.isoformat("T", "milliseconds") + "Z"

    def Request(self, method, endpoint, params=None):
        timestamp = self._timestamp2str(time.time_ns())

        signature = self._sign(timestamp, method, endpoint, params or {})

        def get_headers() -> dict:
            return {
                'OK-ACCESS-KEY': self._key,
                'OK-ACCESS-PASSPHRASE': self._passphrase,
                'OK-ACCESS-TIMESTAMP': timestamp,
                'OK-ACCESS-SIGN': signature,
                'Content-Type': 'application/json',
            }

        if method == KEY.GET:
            r = requests.get(url=URL + endpoint, headers=get_headers(), params=params)
        elif method == KEY.POST:
            r = requests.post(url=URL + endpoint, headers=get_headers(), json=params)
        elif method == KEY.DELETE:
            r = requests.delete(url=URL + endpoint, headers=get_headers(), params=params)

        return r.json()

    def getBook(self, symbol: str) -> Book:
        # { 'bidPrice': '0.05404', 'bidQty': '107996', 'askPrice': '0.05405' ...

        all_products = self.Request(method=KEY.GET, endpoint='/api/swap/v3/instruments/ticker')

        current_product = [x for x in all_products if x['instrument_id'] == symbol][0]

        return Book(
            ask_price=Decimal(current_product['best_ask']),
            ask_qty=Decimal(current_product['best_ask_size']),
            bid_price=Decimal(current_product['best_bid']),
            bid_qty=Decimal(current_product['best_bid_size']),
        )

