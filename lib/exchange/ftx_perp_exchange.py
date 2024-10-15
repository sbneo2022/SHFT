import hmac
import json
import math
import threading
import time
from collections import deque
from decimal import Decimal
from pprint import pprint
from typing import Optional, Dict, List, Tuple, Union

import ccxt
import requests

from lib.constants import KEY, DB, ORDER_TYPE, MONTH_MAP, ORDER_TAG
from lib.database import AbstractDatabase
from lib.defaults import DEFAULT
from lib.exchange import AbstractExchange, Order, Book, Balance
from lib.factory import AbstractFactory
from lib.helpers import custom_dump, sign
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer
from lib.vault import AbstractVault, VAULT

DEFAULT_REST_URL = 'https://ftx.com/api'

SOFT_LIMIT_ORDERS = 1200 - 120
HARD_LIMIT_ORDERS = 1200 - 60
REPLACE_LIMITS_AFTER = 1 * KEY.ONE_MINUTE

REQUEST_ATTEMPT = 2
REQUEST_TIMEOUT = 0.5

class FtxPerpExchange(AbstractExchange):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, symbol: Optional[str] = None):
        super().__init__(config, factory, timer, symbol)

        # Override exchange name
        self._config[KEY.EXCHANGE] = KEY.EXCHANGE_FTX_PERP
        self._symbol, self._exchange = self._config[KEY.SYMBOL], self._config[KEY.EXCHANGE]

        self._database: AbstractDatabase = factory.Database(self._config, factory=factory, timer=timer)
        self._logger: AbstractLogger = factory.Logger(self._config, factory=factory, timer=timer)
        self._vault: AbstractVault = factory.Vault(self._config, factory=factory, timer=timer)

        self._rest_url = self._config.get(self._exchange, {}).get(KEY.REST_URL, None) or DEFAULT_REST_URL

        api_limit = self._config.get(self._exchange, {}).get(KEY.API_LIMIT, None) or DEFAULT.HUOBI_API_LIMIT
        self._soft_api_limit = int(api_limit * 0.95)  # First we have SOFT limit 5% before API LIMIT: we pause quoting
        self._hard_api_limit = int(api_limit * 0.98)  # Nex we have HARD limit 2% before API LIMIT: we skip LIMIT orders

        self._leverage = self._config.get(self._exchange, {}).get(KEY.LEVERAGE, DEFAULT.LEVERAGE)

        self._logger.info(f'Exchange: {self._rest_url} with limit={api_limit}')

        self._key = self._vault.Get(VAULT.KEY)
        self._secret = self._vault.Get(VAULT.SECRET)

        self._symbol = self._construct_symbol()

        self._ftx = ccxt.ftx({'apiKey': self._key, 'secret': self._secret})

        self._dry = self._key is None or self._secret is None
        if self._dry:
            self._logger.error('Exchange: No KEY/SECRET given. Running in DRY mode')

        exchange_info = self._ftx.fetch_markets()
        self._tick = self._get_tick(exchange_info)
        self._min_qty = self._get_min_qty(exchange_info)
        self._contract_value = self._get_contract_value(exchange_info)

    ##############################################################################
    #
    # Public Methods
    #
    ##############################################################################

    def isOnline(self) -> bool:
        pass

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

        return order

    def getBook(self) -> Book:
        book = self._ftx.fetch_order_book(self._symbol)

        return Book(
            ask_price=Decimal(str(book['asks'][0][0])),
            ask_qty=Decimal(str(book['asks'][0][1])),
            bid_price=Decimal(str(book['bids'][0][0])),
            bid_qty=Decimal(str(book['bids'][0][1])),
        )

    def getBalance(self) -> Balance:
        try:
            balance = self._ftx.fetch_balance()
            return Balance(
                balance=Decimal(str(balance['USD']['total'])),
                available=Decimal(str(balance['USD']['free'])),
            )
        except:
            return Balance()

    def getTick(self) -> Decimal:
        return self._tick

    def getMinQty(self) -> Decimal:
        return self._min_qty

    def _get_raw_positions(self) -> dict:
        endpoint = self._rest_url + '/positions'
        ts = int(time.time() * 1000)
        request = requests.Request('GET', url=endpoint, params={'showAvgPrice': True})
        prepared = request.prepare()
        signature_payload = f'{ts}{prepared.method}{prepared.path_url}'.encode()
        signature = hmac.new(self._secret.encode(), signature_payload, 'sha256').hexdigest()

        request.headers['FTX-KEY'] = self._key
        request.headers['FTX-SIGN'] = signature
        request.headers['FTX-TS'] = str(ts)

        r = requests.Session().send(request.prepare())

        return r.json()['result']

    def getPosition(self) -> Order:
        position = self._get_raw_positions()

        for item in position:
            if item['future'] == self._symbol:
                side = +1 if item['side'] == 'buy' else -1
                qty = Decimal(str(item['size']))
                price = item['recentAverageOpenPrice']
                price = Decimal(0) if price is None else Decimal(str(price))

                return Order(qty=qty * side, price=price)

        return Order()

    def getCandles(self, start_timestamp: int, end_timestamp: int) -> Dict[str, deque]:
        pass

    def _method_with_log(self, method, **kwargs):
        r = method(**kwargs)

        message = json.dumps({
            'event': method.__str__(),
            'response': r,
        }, default=custom_dump).replace('"', '\\"')

        payload = self._database.Encode(fields={DB.REQUEST: message}, timestamp=self._timer.Timestamp())
        error = self._database.writeEncoded([payload])

        if error is not None:
            self._logger.error(f'Cant write Request result to database: {error}')


    def Post(self, order: Order, wait=False) -> str:

        order_type = 'market' if order.price is None else 'limit'
        order_side = 'buy' if order.qty > 0 else 'sell'
        order_id = self._get_id_tag(order.tag)

        if abs(order.qty) < self._min_qty:
            return order_id
        else:
            request = threading.Thread(
                target=self._method_with_log,
                kwargs=dict(
                    method=self._ftx.create_order,
                    symbol=self._symbol,
                    type=order_type,
                    side=order_side,
                    amount=abs(order.qty),
                    price=order.price,
                    params={'clientOrderId': order_id}
                )
            )

            request.start()

            if wait:
                request.join()

            return order_id


    def batchPost(self, orders: List[Order], wait=False) -> List[str]:
        pass

    def Cancel(self, ids: Optional[Union[str, List]] = None, wait=False):
        if ids is None:
            request = threading.Thread(
                target=self._method_with_log,
                kwargs=dict(
                    method=self._ftx.cancel_all_orders,
                    symbol=self._symbol,
                )
            )

            request.start()

            if wait:
                request.join()

            return
        elif isinstance(ids, str):
            ids = [ids]

        for id in ids:
            request = threading.Thread(
                target=self._method_with_log,
                kwargs=dict(
                    method=self._ftx.cancel_order,
                    symbol=self._symbol,
                    params={'clientOrderId': id}
                )
            )

            request.start()

            if wait:
                request.join()

    ##############################################################################
    #
    # Private Methods
    #
    ##############################################################################
    """
    Return symbol name in FTX notation
    """
    def _construct_symbol(self) -> str:
        for _tail in ['USD', 'USDT']:
            if self._symbol.upper().endswith(_tail):
                return f'{self._symbol.upper()[:-len(_tail)]}-PERP'

    def _get_tick(self, exchange_info: dict) -> Decimal:
        product_info = [x for x in exchange_info if x['symbol'] == self._symbol][0]

        return Decimal(str(product_info['precision']['price']))

    def _get_min_qty(self, exchange_info: dict) -> Decimal:
        product_info = [x for x in exchange_info if x['symbol'] == self._symbol][0]

        return Decimal(str(product_info['precision']['amount']))

    def _get_contract_value(self, exchange_info: dict) -> Decimal:
        product_info = [x for x in exchange_info if x['symbol'] == self._symbol][0]

        value = product_info['limits']['cost']['min']

        return Decimal('0') if value is None else Decimal(str(value))

    def _get_id_timestamp(self) -> str:
        return f'{self._id}{str(self._timer.Timestamp())[:-3]}'

    def _get_id_iso(self) -> str:
        now = self._timer.Now()
        return f'{self._id}-' \
               f'{now.year}{now.month:02}{now.day:02}.' \
               f'{now.hour:02}{now.minute:02}{now.second:02}.' \
               f'{now.microsecond:06}'

    def _get_id_tag(self, tag: Optional[str]) -> str:
        now = self._timer.Now()
        tag = f'.{tag}' if tag is not None else ''
        return f'{self._id}-' \
               f'{now.year - 2000}{MONTH_MAP[now.month]}{now.day:02}.' \
               f'{now.hour:02}{now.minute:02}{now.second:02}.' \
               f'{now.microsecond:06}{tag}'
