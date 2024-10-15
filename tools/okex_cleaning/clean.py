import os
import sys
from decimal import Decimal
from typing import Dict, List

import requests
from loguru import logger

sys.path.append(os.path.abspath('../..'))
from tools.okex_cleaning.lib.chain_config import load_chain_config
from tools.okex_cleaning.lib.okex import Okex



def clean_product(api: Okex, instrument_id: str, long: int, short: int, tick: Decimal):
    qty = min(long, short)

    logger.info(f'{instrument_id} has positions to clean: LONG {long} and SHORT {short}')

    book = api.getBook(instrument_id)

    midpoint = (book.ask_price + book.bid_price) / 2
    midpoint = round(midpoint / tick) * tick

    liq_long = {'type': '3', 'size': str(qty), 'price': str(midpoint), 'order_type': '0'}
    liq_short = {'type': '4', 'size': str(qty), 'price': str(midpoint), 'order_type': '0'}
    params = {'instrument_id': instrument_id, 'order_data': [liq_long, liq_short]}

    logger.info(f'BBO: {book.ask_price}/{book.bid_price} Liquidate {qty} at price: {midpoint}')
    r = api.Request(method='POST', endpoint='/api/swap/v3/orders', params=params)

    if r['result'] == 'true':
        logger.success(f'Ok: {r["order_info"]}')
    else:
        logger.error(f'Failed: {r["order_info"]}')

def get_tick_dict() -> Dict[str, Decimal]:
    result = dict()
    r = requests.get('https://aws.okex.com/api/swap/v3/instruments')

    for item in r.json():
        result[item['instrument_id']] = Decimal(str(item['tick_size']))
    return result


def get_positions(api: Okex) -> List[Dict[str, List[dict]]]:
    return api.Request(method='GET', endpoint='/api/swap/v3/position')


def normalize_symbol(instrument_id: str) -> str:
    a, b, _ = instrument_id.split('-')
    return a + b


if __name__ == '__main__':
    config = load_chain_config()

    symbol = config.get('symbol', '').split('.')[0]

    tick_list = get_tick_dict()

    api = Okex(config)

    positions = get_positions(api)

    logger.warning(f'Get {len(positions)} products with inventory')

    for item in get_positions(api):
        long, short = 0.0, 0.0

        holding = item.get('holding', [])
        instrument_id = None

        for side in holding:
            instrument_id = side['instrument_id']

            if side['side'] == 'long':
                long = int(side['position'])
            elif side['side'] == 'short':
                short = int(side['position'])

        if long > 0 and short > 0:
            if symbol == '' or symbol == normalize_symbol(instrument_id):
                clean_product(api, instrument_id, long, short, tick=tick_list[instrument_id])
            else:
                logger.info(f'{instrument_id} has inventory, but config let clean {symbol} only')



