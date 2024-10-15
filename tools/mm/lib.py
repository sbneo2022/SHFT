import copy
from pprint import pprint
from typing import Optional, Tuple
import requests

class KEY:
    SYMBOL = 'symbol'
    INNER_VALUE = 'inner_value'
    INNER_QTY = 'inner_qty'
    OUTER_VALUE = 'outer_value'
    OUTER_QTY = 'outer_qty'

    MAX_ALLOCATION = 'max_allocation'
    DISTANCE = 'distance'
    MIN_DISTANCE = 'min_distance'


class Binance:
    def __init__(self):
        pass

    def _request(self, endpoint, params=None) -> dict:
        r = requests.get('https://fapi.binance.com' + endpoint, params=params)
        return r.json()

    def getTick(self, symbol: str) -> float:
        data = self._request('/fapi/v1/exchangeInfo')['symbols']
        product_info = [x for x in data if x[KEY.SYMBOL] == symbol][0]
        filter = [x for x in product_info['filters'] if x['filterType'] == 'PRICE_FILTER'][0]
        return float(filter['tickSize'])

    def getBidAsk(self, symbol: str) -> Tuple[float, float]:
        data = self._request('/fapi/v1/ticker/bookTicker', params=dict(symbol=symbol))
        return (float(data['bidPrice']), float(data['askPrice']))

class Parser:
    def __init__(self):
        self._current = dict()
        self._counter = 0

    def _is_ready(self) -> bool:
        for key in [KEY.SYMBOL, KEY.INNER_QTY, KEY.INNER_VALUE, KEY.OUTER_QTY, KEY.OUTER_VALUE]:
            if key not in self._current:
                return False
        return True

    def Next(self, value: str) -> Optional[dict]:
        if value.replace(' ', '').replace('\n', '') == '':
            return

        if 'USD' in value:
            self._current[KEY.SYMBOL] = value.replace('\n', '')
        elif '%' in value and KEY.INNER_VALUE not in self._current:
            self._current[KEY.INNER_VALUE] = float(value.replace('%','')) * 0.01
        elif '%' in value and KEY.OUTER_VALUE not in self._current:
            self._current[KEY.OUTER_VALUE] = float(value.replace('%','')) * 0.01
        elif KEY.INNER_QTY not in self._current and KEY.INNER_VALUE in self._current:
            self._current[KEY.INNER_QTY] = float(value.replace(',', '').replace(' ', ''))
            self._current[KEY.OUTER_QTY] = self._current[KEY.INNER_QTY] * 2

        self._counter += 1

        if self._is_ready() and self._counter > 5:
            new = copy.deepcopy(self._current)
            self._current = dict()
            self._counter = 0
            return new


def load_products(filename: str) -> dict:
    with open(filename, 'r') as fp:
        s = fp.readlines()

    all_products = dict()

    parser = Parser()
    for item in s:
        splited = item.split(' ')
        for value in splited:
            if value != '':
                result = parser.Next(value)
                if result is not None:
                    all_products[result[KEY.SYMBOL]] = {
                        KEY.INNER_VALUE: result[KEY.INNER_VALUE],
                        KEY.INNER_QTY: result[KEY.INNER_QTY],
                        KEY.OUTER_VALUE: result[KEY.OUTER_VALUE],
                        KEY.OUTER_QTY: result[KEY.OUTER_QTY],
                    }

    return all_products