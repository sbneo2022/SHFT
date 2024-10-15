import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import List, Dict

import requests

FOLDER = os.path.dirname(__file__)
FRAMEWORK = os.path.join(FOLDER, '../..')
sys.path.append(os.path.abspath(FRAMEWORK))

from lib.constants import KEY

SORT_KEY = 'fundingRate'

def get_report_filename() -> str:
    utc = datetime.utcnow()
    logs_folder = os.path.join(FOLDER, 'log')
    os.makedirs(logs_folder, exist_ok=True)
    filename = f'{utc.strftime("%Y%m%d_%H%M%S")}.json'
    return os.path.join(logs_folder, filename)

def get_24h_metrics() -> Dict[str, dict]:
    r = requests.get('https://fapi.binance.com/fapi/v1/ticker/24hr')
    result = dict()
    for item in r.json():
        symbol: str = item[KEY.SYMBOL]
        if symbol.endswith('USDT'):
            result[symbol] = {
                KEY.VOLUME: float(item['quoteVolume']),
            }
    return result

def get_funding_rates() -> Dict[str, dict]:
    r = requests.get('https://fapi.binance.com/fapi/v1/premiumIndex')
    result = dict()
    for item in r.json():
        symbol: str = item[KEY.SYMBOL]
        if symbol.endswith('USDT'):
            result[symbol] = {
                KEY.FUNDING_RATE: float(item['lastFundingRate']),
                KEY.TIMESTAMP: item['nextFundingTime']
            }
    return result


def get_vwfr(funding_rate: Dict[str, dict], metrics: Dict[str, dict]) -> List[dict]:
    result = []
    n = len(funding_rate)
    volume_sum = sum([x[KEY.VOLUME] for x in metrics.values()])

    for symbol in funding_rate.keys():
        if symbol in funding_rate and symbol in metrics:
            funding_rate_value = funding_rate[symbol][KEY.FUNDING_RATE]
            volume_value = metrics[symbol][KEY.VOLUME]
            result.append({
                KEY.SYMBOL: symbol,
                KEY.FUNDING_RATE: funding_rate_value,
                KEY.VOLUME: volume_value,
                'vwfr': n * funding_rate_value * volume_value / volume_sum
            })

    return result


if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--number", type=int, help="Number of products", required=True)
    parser.add_argument("-t", "--threshold", type=float, help="Custom filtering threshold",
                        required=False, default=0.0001)
    args = parser.parse_args()

    metrics = get_24h_metrics()

    funding_rate = get_funding_rates()

    data = get_vwfr(funding_rate, metrics)

    # Sort by funding rate
    data.sort(key=lambda x: x[SORT_KEY], reverse=True)

    # Save raw data
    with open(get_report_filename(), 'w') as fp:
        json.dump(data, fp, indent=2)

    # Filter by threshold
    data = [x for x in data if x[SORT_KEY] > args.threshold]

    # Get N top
    data = data[:args.number]

    for item in data:
        sys.stdout.write(item[KEY.SYMBOL] + '\n')

    sys.stdout.flush()