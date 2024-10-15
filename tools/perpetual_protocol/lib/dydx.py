import os
import sys
from decimal import Decimal
from pprint import pprint
from typing import Dict
import concurrent.futures

import requests

sys.path.append(os.path.abspath('../../..'))
from tools.perpetual_protocol.lib.constants import KEY, EXCHANGE

URL = 'https://api.dydx.exchange'

DYDX_BASE = 'USD'
EXCHANGE_NAME = EXCHANGE.DYDX

class DyDx:
    def __init__(self, config: dict):
        self._config = config


    def getProductsData(self) -> Dict[str, dict]:
        return_me = dict()

        r = requests.get(URL + '/v3/markets')

        markets = [x['market'] for x in r.json()['markets'].values()]

        def fn(market):
            r = requests.get(URL + f'/v3/orderbook/{market}').json()
            return_me[market] = {
                KEY.EXCHANGE: EXCHANGE_NAME,
                KEY.ASK_PRICE: Decimal(r['asks'][0]['price']),
                KEY.BID_PRICE: Decimal(r['bids'][0]['price']),
            }

        with concurrent.futures.ThreadPoolExecutor() as executor:
            for market in markets:
                executor.submit(fn, market)

        return return_me
