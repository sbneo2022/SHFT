import hashlib
import hmac
import time
from datetime import datetime
from pprint import pprint
from typing import Tuple, Optional

import requests
from deepmerge import Merger
import urllib.parse

import argparse
import json
import sys
from decimal import Decimal

import yaml

from lib.helpers import custom_dump
from lib.constants import KEY, ORDER_TYPE, SIDE

URL = 'https://fapi.binance.com'

class Binance:
    def __init__(self, config):
        self._key = config[KEY.EXCHANGE_BINANCE_FUTURES][KEY.KEY]
        self._secret = config[KEY.EXCHANGE_BINANCE_FUTURES][KEY.SECRET]

    def _sign(self, params) -> dict:
        if 'signature' in params.keys():
            del params['signature']
        params['timestamp'] = time.time_ns() // KEY.ONE_MS
        query = urllib.parse.urlencode([(key, value) for key, value in params.items()])
        params['signature'] = hmac.new(self._secret.encode(), query.encode(),  digestmod=hashlib.sha256).hexdigest()
        return params

    def Request(self, method, endpoint, params=None):
        params = self._sign(params or {})
        r = requests.request(
                method=method,
                url=URL + endpoint,
                params=params,
                headers={'X-MBX-APIKEY': self._key }
        )
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
    r = Binance(config).Request(
            method='GET',
            endpoint='/fapi/v2/balance',
    )
    print_json(r)

def clear(config: dict, symbol: str):
    if symbol is None:
        open = open_orders(config)
    else:
        open = [dict(symbol=symbol)]

    for item in open:
        symbol = item['symbol']
        r = Binance(config).Request(
            method='DELETE',
            endpoint='/fapi/v1/allOpenOrders',
            params=dict(symbol=symbol)
        )
        print_json({**r, 'symbol': symbol})

def open_orders(config: dict) -> list:
    r = Binance(config).Request(
        method='GET',
        endpoint='/fapi/v1/openOrders'
    )

    print_json(r)
    return r

def info(config: dict):
    r = Binance(config).Request(
        method='GET',
        endpoint='/fapi/v2/account'
    )

    result = {"assets": [], "positions": []}

    for section, key in [('assets', 'walletBalance'), ('positions', 'positionAmt')]:
        for item in r[section]:
            value = float(item[key])
            if abs(value) > 0:
                result[section].append(item.copy())

    print_json(result)

def all_positions(config: dict) -> list:
    r = Binance(config).Request(
        method='GET',
        endpoint='/fapi/v2/positionRisk',
    )
    non_zero = [x for x in r if abs(float(x['positionAmt'])) > KEY.E]
    print_json(non_zero)
    return non_zero

def liquidate(config: dict, symbol: str):
    if symbol is None:
        print('You should set SYMBOL for market inventory clear. Exit')
        exit(-1)

    positions = all_positions(config)
    for item in positions:
        if item['symbol'] == symbol:
            qty = Decimal(item['positionAmt'])
            print(f'Liquidate {symbol} {qty} with MARKET price')
            qty = -1 * qty
            r = Binance(config).Request(
                method='POST',
                endpoint='/fapi/v1/order',
                params=dict(
                    symbol=symbol,
                    type=ORDER_TYPE.MARKET,
                    side=SIDE.BUY if qty > 0 else SIDE.SELL,
                    quantity=abs(qty)
                )
            )
            print_json(r)

def report(config: dict, title: Optional[str] = None):
    balance = Binance(config).Request(method='GET',  endpoint='/fapi/v2/balance')
    positions = Binance(config).Request(method='GET', endpoint='/fapi/v2/positionRisk')
    info = Binance(config).Request(method='GET', endpoint='/fapi/v2/account')


    payload = []

    key = config[KEY.EXCHANGE_BINANCE_FUTURES][KEY.KEY]
    now = datetime.utcnow()

    if title is None:
        title_message = f'*Key: {key}*'
        payload.append(title_message)
    else:
        title_message = f'*{title}*'
        payload.append(title_message)

    payload.append('-' * len(title_message))
    payload.append(f'Datetime: {now.strftime("%b %d, %Y UTC %H:%M")}\n')

    for item in info['assets']:
        if item['asset'] == 'USDT':
            maintMargin = float(item['maintMargin'])
            if maintMargin > 0:
                margin_ratio = float(item['availableBalance']) / maintMargin
                payload.append(f'*USDT Margin Ratio: {margin_ratio:0.1f}*')
                payload.append('')

    for item in balance:
        current_balance = float(item["balance"])
        if current_balance > 0:
            payload.append(f'{item["asset"]}:')
            payload.append(f'    Balance: {item["balance"]}')
            payload.append(f'    Available Balance: {item["availableBalance"]}')
            payload.append(f'    Unrealized Pnl: {item["crossUnPnl"]}')

    products_data = []
    for item in positions:
        product = item['symbol']
        positionAmt = float(item['positionAmt'])

        if abs(positionAmt) > 0:
            products_data.append(f'{product}:\n'
                                 f'    Position: {item["positionAmt"]}\n'
                                 f'    Entry Price: {item["entryPrice"]}\n'
                                 f'    Notional: {item["notional"]}\n'
                                 f'    Unrealized Pnl: {item["unRealizedProfit"]}\n')

    if products_data:
        payload.append(f'\n*{len(products_data)} products has inventory:*\n')
        payload.extend(products_data)
    else:
        payload.append('\n*No inventory*')

    payload.append('')
    print('\n'.join(payload))



def init(adds, symbol) -> Tuple[dict, str]:
    config = get_config('config.yaml')
    if adds is not None:
        merger = Merger([(list, "override"),(dict, "merge")], ["override"],["override"])
        for add in adds:
            config = merger.merge(config, get_config(add))

    if symbol is not None:
        symbol = symbol.upper()
        symbol = symbol if 'USDT' in symbol else symbol + 'USDT'

    return config, symbol

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--add", type=str, help="Additional YAML config", action='append')
    parser.add_argument("-s", "--symbol", type=str, help="symbol for liquidation")
    parser.add_argument("-b", "--balance", action='store_true', help="show account balance")
    parser.add_argument("-c", "--clear", action='store_true', help="clear open orders")
    parser.add_argument("-p", "--positions", action='store_true', help="show positions")
    parser.add_argument("-o", "--open", action='store_true', help="show open orders")
    parser.add_argument("-l", "--liquidate", action='store_true', help="liquidate all positions using market price")
    parser.add_argument("-r", "--report", action='store_true', help="print account report")
    parser.add_argument("-i", "--info", action='store_true', help="print account info")
    parser.add_argument("-t", "--title", type=str, help="optional report title")
    args = parser.parse_args()

    config, symbol = init(args.add, args.symbol)

    if args.balance:
        balance(config)
    elif args.clear:
        clear(config, symbol)
    elif args.positions:
        all_positions(config)
    elif args.open:
        open_orders(config)
    elif args.liquidate:
        liquidate(config, symbol)
    elif args.report:
        report(config, args.title)
    elif args.info:
        info(config)
    else:
        print('Use HELP with -h/--help key')