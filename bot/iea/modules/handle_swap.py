import threading
import time
from concurrent.futures.thread import ThreadPoolExecutor
from decimal import Decimal
from pprint import pprint
from typing import Dict, List, Tuple, Union

import requests

from bot import AbstractBot
from bot.iea.modules.handle_dex import HandleDex
from lib.constants import KEY
from lib.factory import AbstractFactory
from lib.timer import AbstractTimer

DEX = 'https://dex.binance.org'

SWAP_PRODUCTS = {
    'BNB': {
        'thor': 'BNB.BNB',
        'dex': 'BNB_BUSD-BD1',
    },
    'RUNE': {
        'thor': 'BNB.RUNE-67C',
        'dex': 'RUNE-B1A_BNB'
    },
    'USD': {
        'thor': 'BNB.BUSD-BAF',
        'dex': 'RUNE-B1A_BNB',
    }
}

class ThorchainMonitor(threading.Thread):
    URL = 'https://chaosnet-midgard.bepswap.com'

    def __init__(self):
        super().__init__(daemon=True)
        self.products = {}

    def get_products(self):
        r = requests.get(self.URL + '/v1/pools')
        return r.json()

    def _get_details(self, products: list):

        return_me = {x: {} for x in products}

        def get_depth(product, grid):
            while True:
                try:
                    details = requests.get(self.URL + '/v1/pools/detail', params={'asset': product})
                    details = details.json()[0]
                    grid[product]['assetDepth'] = Decimal(details['assetDepth'])
                    grid[product]['runeDepth'] = Decimal(details['runeDepth'])
                    return
                except Exception as e:
                    print('ERROR', e)
                    time.sleep(0.5)

        with ThreadPoolExecutor(max_workers=16) as executor:
            for item in return_me.keys():
                executor.submit(get_depth, item, return_me)

        return return_me

    def run(self):
        products = self.get_products()

        while True:
            self.products = self._get_details(products).copy()


class HandleSwap(
    HandleDex,
    AbstractBot
):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        self._section = self._config[KEY.THORCHAIN]
        self._api = self._section[KEY.API]

        self._thorchain_monitor = ThorchainMonitor()

        self._thorchain_products = self._thorchain_monitor.get_products()

        self._dex_products = self.getDexProducts()

        self.swap_products = {
            **SWAP_PRODUCTS,
            **self._create_products_list(self._thorchain_products, self._dex_products)
        }

        self._swap_destination = self._get_swap_address()

        self._thorchain_monitor.start()

        # pprint(self.swap_products)

    def _get_thorchain_symbols(self) -> list:
        # pprint(requests.get('http://thorb.sccn.nexain.com:1317/thorchain/pools').json())
        # pprint(requests.get('https://chaosnet-midgard.bepswap.com/v1/pools/detail', params=dict(asset='BNB.BNB')).json())
        r = requests.get(self._api + '/v1/pools').json()
        return r

    def getThorchainDetails(self) -> dict:
        return self._thorchain_monitor.products

    def _get_thorchain_detail(self, asset: str) -> dict:
        r = requests.get(self._api + '/v1/pools/detail', params={'asset': asset})
        return r.json()

    def _get_dex_products(self) -> Dict[str, Decimal]:
        r = requests.get(DEX + '/api/v1/ticker/24hr').json()

        result = {}

        for item in r:
            result[item['symbol']] = Decimal(item['lastPrice'])

        return result

    def _decode_dex_base_quote_symbol(self, name: str) -> Tuple[str, str, str]:
        base, quote = name.split('_')
        symbol = base.split('-')[0]
        return (base, quote, symbol)

    def _create_products_list(self, thorchain: List[str], dex: Dict[str, Decimal]) -> Dict[str, Dict[str, str]]:
        result = {}

        # decode dex products
        dex_products = {}
        for item in dex.keys():
            left, right = item.split('_')
            if right == 'BNB':
                dex_products[left.split('-')[0]] = item
            elif left == 'BNB':
                dex_products[right.split('-')[0]] = item

        for item in thorchain:
            thor_quote, symbol = item.split('.')
            name = symbol.split('-')[0]

            if name in dex_products.keys():
                result[name] = {
                    'thor': item,
                    'dex': dex_products[name]
                }

        return result

    @staticmethod
    def calc_swap_asset(assetDepth, runeDepth, asset):
        asset = asset * int(1e8)
        value = (asset * runeDepth * assetDepth) / pow(asset + assetDepth, 2)
        return value / int(1e8)

    @staticmethod
    def calc_swap_rune(assetDepth, runeDepth, rune):
        rune = rune * int(1e8)
        value = (rune * runeDepth * assetDepth) / pow(rune + runeDepth, 2)
        return value / int(1e8)


    def Swap(self, source: str, destination: str, amount: Decimal) -> Union[bool, str]:
        if source not in self.swap_products.keys():
            return f'Product {source} not found!'

        source_pair: str = self.swap_products[source]['dex']
        source_symbol, _ = source_pair.split('_')
        destination_symbol = self.swap_products[destination]['thor']

        memo = f'SWAP:{destination_symbol}'

        self.makeDexTransaction(source_symbol, amount, memo, self._swap_destination)

        return True

    def updateSwapEngine(self):
        self._swap_destination = self._get_swap_address()

    def _get_swap_address(self) -> str:
        r = requests.get(self._api + '/v1/thorchain/pool_addresses').json()
        for item in r['current']:
            if not item['halted'] and item['chain'] == 'BNB':
                return item['address']