import os
import sys
from decimal import Decimal
from pprint import pprint
from typing import Dict

import requests

sys.path.append(os.path.abspath('../../..'))
from tools.perpetual_protocol.lib.constants import EXCHANGE, KEY

URL = 'https://api.binance.com'

BINANCE_BASE = 'USDT'
EXCHANGE_NAME = EXCHANGE.BINANCE

class BinanceSpot:
    def __init__(self, config: dict):
        self._config = config

    def getProductsData(self) -> Dict[str, dict]:
        return_me = dict()

        r = requests.get(URL + '/api/v3/ticker/bookTicker')

        for item in r.json():
            symbol: str = item['symbol']
            if symbol.endswith(BINANCE_BASE):
                quote = symbol.split(BINANCE_BASE)[0]
                return_me[quote + '-' + BINANCE_BASE] = {
                    KEY.EXCHANGE: EXCHANGE_NAME,
                    KEY.ASK_PRICE: Decimal(item['askPrice']),
                    KEY.BID_PRICE: Decimal(item['bidPrice']),
                }

        return return_me
