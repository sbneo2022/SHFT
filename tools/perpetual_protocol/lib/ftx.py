import os
import sys
from decimal import Decimal
from pprint import pprint
from typing import Dict

import requests
import ciso8601

sys.path.append(os.path.abspath('../../..'))
from tools.perpetual_protocol.lib.constants import EXCHANGE, KEY

URL = 'https://ftx.com/api'

FTX_BASE = 'PERP'
EXCHANGE_NAME = EXCHANGE.FTX

class Ftx:
    def __init__(self, config: dict):
        self._config = config

    def getFundingRates(self) -> Dict[str, dict]:
        return_me = dict()

        r = requests.get(URL + '/funding_rates')

        for item in r.json()['result']:
            product = item['future']
            funding_rate = Decimal(str(item['rate']))
            _time = ciso8601.parse_datetime(item['time'])

            if product in return_me.keys():
                if _time > return_me[product]['time']:
                    return_me[product] = {
                        'fundingRate': funding_rate,
                        'time': _time
                    }
            else:
                return_me[product] = {
                    'fundingRate': funding_rate,
                    'time': _time
                }

        return return_me

    def getProductsData(self) -> Dict[str, dict]:
        return_me = dict()

        r = requests.get(URL + '/markets')
        for item in r.json()['result']:
            if item['type'] == 'future':
                return_me[item['name']] = {
                    KEY.EXCHANGE: EXCHANGE_NAME,
                    KEY.ASK_PRICE: Decimal(str(item['ask'])),
                    KEY.BID_PRICE: Decimal(str(item['bid'])),
                }

        return return_me
