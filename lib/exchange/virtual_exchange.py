import hashlib
import hmac
import json
import math
import os
import threading
import urllib.parse
from collections import deque
from decimal import Decimal
from http import HTTPStatus
from typing import Optional, Dict, List, Union

import requests
import yaml

from lib.constants import KEY, DB, SIDE, ORDER_TYPE, TIF, MONTH_MAP, QUEUE, STATUS
from lib.database import AbstractDatabase
from lib.defaults import DEFAULT
from lib.exchange import AbstractExchange, Order, Book, Balance
from lib.factory import AbstractFactory
from lib.helpers import custom_dump, sign
from lib.history import AbstractHistory
from lib.logger import AbstractLogger
from lib.producer import AbstractProducer
from lib.timer import AbstractTimer
from lib.vault import AbstractVault, VAULT


DEFAULT_REST_URL = 'https://fapi.binance.com'

KLINES_LIMIT = 1500

SOFT_LIMIT_10_RATE = 200
HARD_LIMIT_10_RATE = 250

SOFT_LIMIT_ORDERS = 1200 - 120
HARD_LIMIT_ORDERS = 1200 - 60
REPLACE_LIMITS_AFTER = 15 * KEY.ONE_SECOND

REQUEST_ATTEMPT = 3
REQUEST_TIMEOUT = 0.5


class VirtualExchange(AbstractExchange):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, symbol: Optional[str] = None):
        self._store: List[dict] = config[QUEUE.QUEUE]

        super().__init__(config, factory, timer, symbol)

        self._history: AbstractHistory = factory.History(config, factory, timer)
        self._database: AbstractDatabase = factory.Database(self._config, factory=factory, timer=timer)
        self._logger: AbstractLogger = factory.Logger(self._config, factory=factory, timer=timer)

        # Override exchange name
        self._symbol, self._exchange = self._config[KEY.SYMBOL], self._config[KEY.EXCHANGE]

        exchange_info = self._get_exchange_info()
        self._tick = self._get_tick(exchange_info)
        self._min_qty = self._get_min_qty(exchange_info)
        self._min_notional = self._get_min_notional(exchange_info)


    ##############################################################################
    #
    # Public Methods
    #
    ##############################################################################

    def isOnline(self) -> bool:
        return True

    def getTick(self) -> Decimal:
        return self._tick

    def getMinQty(self) -> Decimal:
        return self._min_qty

    def applyRules(self, order: Order, rule: Optional[str] = None) -> Order:
        # Round price UP/DOWN/SIMPLE
        if order.price is not None:
            if rule == KEY.UP:
                order.price = math.ceil(order.price / self._tick) * self._tick
            elif rule == KEY.DOWN:
                order.price = math.floor(order.price / self._tick) * self._tick
            else:
                order.price = round(order.price / self._tick) * self._tick

        order.qty = sign(order.qty) * round(abs(order.qty) / self._min_qty) * self._min_qty

        # If order is not LIQUIDATION --> check "min_notional"
        if not order.liquidation:
            if order.price is None:
                price = self._top_book.ask_price if order.qty > 0 else self._top_book.bid_price
            else:
                price = order.price

            if abs(order.qty * (price or 0)) <= self._min_notional:
                order.qty = Decimal(0)

        return order

    def getBook(self) -> Book:
        pass

    def getBalance(self) -> Balance:
        return Balance()

    def getPosition(self) -> Order:
        return Order()

    def getCandles(self, start_timestamp: int, end_timestamp: int) -> Dict[str, deque]:
        result = dict()

        timedelta = (end_timestamp - start_timestamp) // KEY.ONE_MINUTE
        fields = [KEY.TIMESTAMP, KEY.OPEN, KEY.HIGH, KEY.LOW, KEY.CLOSE, KEY.VOLUME]
        for field in fields:
            result[field] = deque(maxlen=timedelta)

        candles = self._history.getHistory(start_timestamp, end_timestamp,
                                           fields=['open', 'high', 'low', 'close', 'volume'])

        for item in candles:
            for field in fields:
                result[field].append(item[field])

        return result

    def Post(self, order: Order, wait=False) -> str:
        id = self._get_id_tag(order.tag)

        payload = {
            KEY.ACTION: STATUS.NEW,
            KEY.PAYLOAD: order,
            KEY.ID: id
        }

        self._store.append(payload)

        return id

    def batchPost(self, orders: List[Order], wait=False) -> List[str]:
        pass

    def Cancel(self, ids: Optional[Union[str, List]] = None, wait=False):
        payload = {
            KEY.ACTION: STATUS.CANCELED,
            KEY.ID: ids
        }

        self._store.append(payload)

    ##############################################################################
    #
    # Private Methods
    #
    ##############################################################################

    def _get_id_tag(self, tag: Optional[str]) -> str:
        now = self._timer.Now()
        tag = f'.{tag}' if tag is not None else ''
        return f'{self._id}-' \
               f'{now.year - 2000}{MONTH_MAP[now.month]}{now.day:02}.' \
               f'{now.hour:02}{now.minute:02}{now.second:02}.' \
               f'{now.microsecond:06}{tag}'

    def _get_exchange_info(self) -> dict:
        this_folder = os.path.dirname(__file__)
        data_folder = os.path.join(this_folder, '../data')
        data_file = os.path.join(data_folder, 'binance.futures.json')

        with open(data_file, 'r') as fp:
            return {
                'symbols': yaml.load(fp, Loader=yaml.Loader)
            }

    def _get_tick(self, exchange_info: dict) -> Decimal:
        product_info = [x for x in exchange_info['symbols'] if x[KEY.SYMBOL] == self._symbol][0]

        filter = [x for x in product_info['filters'] if x ['filterType'] == 'PRICE_FILTER'][0]

        return Decimal(filter['tickSize'])

    def _get_min_qty(self, exchange_info: dict) -> Decimal:
        product_info = [x for x in exchange_info['symbols'] if x[KEY.SYMBOL] == self._symbol][0]

        filter = [x for x in product_info['filters'] if x ['filterType'] == 'LOT_SIZE'][0]

        return Decimal(filter['stepSize'])

    def _get_min_notional(self, exchange_info: dict) -> Decimal:
        product_info = [x for x in exchange_info['symbols'] if x[KEY.SYMBOL] == self._symbol][0]

        filter = [x for x in product_info['filters'] if x ['filterType'] == 'MIN_NOTIONAL'][0]

        return Decimal(filter['notional'])