import base64
import concurrent.futures
import copy
import hmac
import time
from datetime import datetime, timezone
from typing import Tuple, List

import requests
from deepmerge import Merger
import urllib.parse

import argparse
import json
import sys

import yaml

from lib.helpers import custom_dump
from lib.constants import KEY
from lib.vault import VAULT

URL = 'https://www.okex.com'

class Okex:
    def __init__(self, config):
        self._key = config[KEY.EXCHANGE_OKEX_PERP][VAULT.KEY]
        self._secret = config[KEY.EXCHANGE_OKEX_PERP][VAULT.SECRET]
        self._passphrase = str(config[KEY.EXCHANGE_OKEX_PERP][VAULT.PASSPHRASE])

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

def get_config(filename: str) -> dict:
    with open(filename, 'r') as fp:
        config = yaml.load(fp, Loader=yaml.Loader)
    return config

def print_json(payload: dict):
    message = json.dumps(payload, indent=2, default=custom_dump)
    sys.stdout.write(message + '\n')
    sys.stdout.flush()

def balance(config: dict):
    r = Okex(config).Request(
            method='GET',
            endpoint='/api/swap/v3/accounts',
    )
    for item in r['info']:
        if abs(float(item['equity'])) > KEY.E:
            print_json(item)


def chunk(a: list, n: int) -> List[list]:
    source, result = copy.copy(a), []

    while source:
        sub = []
        for _ in range(min(n, len(source))):
            sub.append(source.pop(0))
        result.append(sub)

    return result if result else [[]]

def clear(config: dict, symbol: str, side: str):
    if symbol is None:
        open_orders_dict = open_orders(config, silent=True)
    else:
        open_orders_dict = {
            symbol: []
        }

        r = Okex(config).Request(
            method='GET',
            endpoint=f'/api/swap/v3/orders/{symbol}',
            params=dict(state='0'),
        )

        for item in r['order_info']:
            if side == KEY.LONG and item[KEY.TYPE] in ['1', '3'] \
                or side == KEY.SHORT and item[KEY.TYPE] in ['2', '4'] \
                    or side is None:
                open_orders_dict[symbol].append(item)


    for symbol, orders in open_orders_dict.items():
        splited = chunk(orders, 10)
        for item in splited:
            ids = [x['order_id'] for x in item]
            print('Cancel', ids)
            r = Okex(config).Request(
                        method='POST',
                        endpoint=f'/api/swap/v3/cancel_batch_orders/{symbol}',
                        params={'ids': ids},
                    )
            print_json(r)


def get_products_list() -> list:
    return [
        x['instrument_id']
        for x in Okex(config).Request(
            method='GET',
            endpoint=f'/api/swap/v3/instruments'
        )
    ]

def open_orders(config: dict, silent=False) -> dict:
    sys.stdout.write('Loading all open orders...\n')
    sys.stdout.flush()

    open_orders_dict = dict()

    def fn(symbol: str, grid: dict):
        r = Okex(config).Request(
            method='GET',
            endpoint=f'/api/swap/v3/orders/{symbol}',
            params=dict(state='0'),
        )

        if r['order_info']:
            grid[symbol] = r['order_info']

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        for item in get_products_list():
            executor.submit(fn, item, open_orders_dict)

    if not silent:
        print_json(open_orders_dict)

    return open_orders_dict

def all_positions(config: dict, silent=False) -> list:
    r = Okex(config).Request(
        method='GET',
        endpoint='/api/swap/v3/position',
    )

    if not silent:
        print_json(r)

    return r


def liquidate(config: dict, symbol: str, side: str):
    if symbol is None:
        print('You should set SYMBOL for market inventory clear. Exit')
        exit(-1)


    def close_all(side: str):
        r = Okex(config).Request(
            method='POST',
            endpoint='/api/swap/v3/close_position',
            params=dict(
                instrument_id=symbol,
                direction=side,
            )
        )
        print_json(r)

    if side is None:
        close_all(KEY.LONG)
        close_all(KEY.SHORT)
    else:
        close_all(side)


def init(adds, symbol) -> Tuple[dict, str, str]:
    config = get_config('config.yaml')
    if adds is not None:
        merger = Merger([(list, "override"),(dict, "merge")], ["override"],["override"])
        for add in adds:
            config = merger.merge(config, get_config(add))

    side = None

    if symbol is not None:
        symbol = symbol.upper()

        if 'LONG' in symbol:
            side = KEY.LONG
            symbol, _ = symbol.split('.')

        elif 'SHORT' in symbol:
            side = KEY.SHORT
            symbol, _ = symbol.split('.')

        else:
            side = None

        symbol = symbol if '-USDT-SWAP' in symbol else symbol + '-USDT-SWAP'
        print(f'Product: {symbol} \t Side: {side}')


    return config, symbol, side

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--add", type=str, help="Additional YAML config", action='append')
    parser.add_argument("-s", "--symbol", type=str, help="symbol for liquidation")
    parser.add_argument("-b", "--balance", action='store_true', help="show account balance")
    parser.add_argument("-c", "--clear", action='store_true', help="clear open orders")
    parser.add_argument("-p", "--positions", action='store_true', help="show positions")
    parser.add_argument("-o", "--open", action='store_true', help="show open orders")
    parser.add_argument("-l", "--liquidate", action='store_true', help="liquidate all positions using market price")
    args = parser.parse_args()


    config, symbol, side = init(args.add, args.symbol)

    if args.balance:
        balance(config)
    elif args.clear:
        clear(config, symbol, side)
    elif args.positions:
        all_positions(config)
    elif args.open:
        open_orders(config)
    elif args.liquidate:
        liquidate(config, symbol, side)
    else:
        print('Use HELP with -h/--help key')