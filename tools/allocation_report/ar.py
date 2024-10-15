import sys
from pathlib import Path

import requests
import yaml

URL = 'https://fapi.binance.com'
USAGE = f'Usage example: {__file__} ./*.yaml'
COEFF = 2

def get_all_prices() -> dict:
    result = {}
    for item in requests.get(URL + '/fapi/v1/ticker/price').json():
        result[item['symbol']] = float(item['price'])
    return result


if __name__ == '__main__':

    if len(sys.argv) < 2:
        print(USAGE)
        exit()

    prices = get_all_prices()
    table = ['product,ltp,qty,allocation,2x']
    total = 0

    for item in Path().glob(sys.argv[1]):
        with item.open('r') as fp:
            config = yaml.load(fp, Loader=yaml.Loader)

        if 'spread' in config.keys():
            _sum = 0
            for key, value in config['spread'].items():
                _qty = value['qty'] if isinstance(value['qty'], list) else [value['qty']]
                _sum += sum(_qty)

            _product: str = config['symbol'].split('.')[0]

            _price = prices[_product]

            _allocation = _price * _sum

            table.append(f'{_product},{_price},{_sum},{_allocation},{_allocation * COEFF}')

            total += _allocation

    print('\n'.join(table))
    print(f',,,{total},{total * COEFF}')