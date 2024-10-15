import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from pprint import pprint

import requests
from loguru import logger

sys.path.append(os.path.abspath('../../..'))
from tools.dydx_sandbox.lib.db import Db

URL = 'https://api.dydx.exchange'

ACCOUNTS = '/v1/accounts'
MARKETS = '/v1/markets'

class Worker:
    def __init__(self, config: dict):
        self._config = config

        self._db = Db(config)

    def _get_markets(self) -> dict:
        return_me = {}

        r = requests.get(URL + MARKETS).json()

        for item in r['markets']:
            decimals = item['currency']['decimals']
            return_me[str(item['id'])] = {
                'symbol': item['currency']['symbol'],
                'decimals': decimals,
            }

        return return_me

    def _get_test_data(self, filename: str) -> dict:
        with open(filename, 'r') as fp:
            return json.load(fp)

    def run_test(self):
        pass

    def run(self):
        now = datetime.utcnow().replace(microsecond=0)
        markets = self._get_markets()

        # data = self._get_test_data('data.json')

        r = requests.get(URL + ACCOUNTS, params={'isLiquidatable': 'true'})
        data = r.json()['accounts']

        if len(data) > 0:
            logger.success(f'Got {len(data)} liquidation records')


            for account in data:
                fields = {'owner': account['owner']}
                for id, item in account['balances'].items():
                    info = markets[id]
                    fields[info['symbol']] = Decimal(item['wei']) / Decimal(pow(10, info['decimals']))

                self._db.addPoint(fields=fields, time=now)
                logger.debug(f'{fields}')
        else:
            logger.info(f'No accounts for liquidation')
