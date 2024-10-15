import time
from datetime import datetime
from decimal import Decimal
from pprint import pprint
from random import random
from subprocess import Popen, PIPE
from typing import Optional

import ciso8601
import loguru
import requests

from lib.constants import KEY
from lib.logger import AbstractLogger

BINANCE_PING_URL = 'fapi.binance.com'
BINANCE_TIME_ENDPOINT = 'https://fapi.binance.com/fapi/v1/time'

BINANCE_DEX_PING_URL = 'dex.binance.org'
BINANCE_DEX_TIME_ENDPOINT = 'https://dex.binance.org/api/v1/time'

OKEX_PING_URL = 'okex.com'
OKEX_TIME_ENDPOINT = 'https://aws.okex.com/api/general/v3/time'

HUOBI_PING_URL = 'api.hbdm.com'
HUOBI_TIME_ENDPOINT = 'https://api.hbdm.com/api/v1/timestamp'

FTX_PING_URL = 'ftx.com'
FTX_TIME_ENDPOINT = None


TIME_AVERAGING_COUNT = 5

def ping(url: str) -> float:
    with Popen(["ping", '-c', '1', url], stdout=PIPE) as proc:
        stdout = proc.stdout.read()

    stdout = stdout.decode()

    ping_value = stdout.split('\n')[1].split('=')[-1].split(' ')[0]

    try:
        return float(ping_value) * 1e3
    except:
        return 0

def get_binance_lag(logger: Optional[AbstractLogger] = None):
    logger = logger or loguru.logger

    delays = []

    ping_us = ping(BINANCE_PING_URL)
    logger.info(f'Ping to Exchange {ping_us}us')
    for _ in range(TIME_AVERAGING_COUNT):
        r = requests.get(BINANCE_TIME_ENDPOINT)
        now = time.time_ns()
        delay = now - r.json()['serverTime'] * KEY.ONE_MS
        delays.append(delay)

    return int(sum(delays) / len(delays) - 0.5 * ping_us)


def get_binance_dex_lag(logger: Optional[AbstractLogger] = None):
    logger = logger or loguru.logger

    delays = []

    ping_us = ping(BINANCE_DEX_PING_URL)
    logger.info(f'Ping to Exchange {ping_us}us')
    for _ in range(TIME_AVERAGING_COUNT):
        r = requests.get(BINANCE_DEX_TIME_ENDPOINT)
        now = time.time_ns()
        try:
            remote_time = ciso8601.parse_datetime(r.json()['ap_time']).timestamp() * KEY.ONE_SECOND
            delay = now - remote_time
            delays.append(delay)
        except:
            time.sleep(1 + 2 * random())


    return int(sum(delays) / len(delays) - 0.5 * ping_us)


def get_huobi_lag(logger: Optional[AbstractLogger] = None):
    logger = logger or loguru.logger

    delays = []

    ping_us = ping(HUOBI_PING_URL)
    logger.info(f'Ping to Exchange {ping_us}us')
    for _ in range(TIME_AVERAGING_COUNT):
        r = requests.get(HUOBI_TIME_ENDPOINT)
        now = time.time_ns()
        delay = now - r.json()['ts'] * KEY.ONE_MS
        delays.append(delay)

    return int(sum(delays) / len(delays) - 0.5 * ping_us)

def get_okex_lag(logger: Optional[AbstractLogger] = None):
    logger = logger or loguru.logger

    delays = []

    ping_us = ping(OKEX_PING_URL)
    logger.info(f'Ping to Exchange {ping_us}us')
    for _ in range(TIME_AVERAGING_COUNT):
        r = requests.get(OKEX_TIME_ENDPOINT)
        now = time.time_ns()
        try:
            timestamp = Decimal(r.json()['epoch']) * KEY.ONE_SECOND
            delay = now - int(timestamp)
            delays.append(delay)
        except:
            time.sleep(1 + 2 * random())

    try:
        return int(sum(delays) / len(delays) - 0.5 * ping_us)
    except:
        return 0

def get_ftx_lag(logger: Optional[AbstractLogger] = None):
    logger = logger or loguru.logger

    ping_us = ping(FTX_PING_URL)
    logger.info(f'Ping to Exchange {ping_us}us')

    try:
        return 0.5 * ping_us
    except:
        return 0