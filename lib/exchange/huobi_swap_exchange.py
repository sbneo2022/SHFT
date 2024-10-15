import base64
import hmac
import json
import math
import threading
from collections import deque
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from http import HTTPStatus
from pprint import pprint
from typing import Optional, Dict, List, Tuple
from urllib import parse

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

DEFAULT_REST_URL = 'https://api.hbdm.com'


SOFT_LIMIT_ORDERS = 1200 - 120
HARD_LIMIT_ORDERS = 1200 - 60
REPLACE_LIMITS_AFTER = 1 * KEY.ONE_MINUTE

REQUEST_ATTEMPT = 2
REQUEST_TIMEOUT = 0.5

class HuobiSwapExchange(AbstractExchange):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, symbol: Optional[str] = None):
        super().__init__(config, factory, timer, symbol)

        # Override exchange name
        self._config[KEY.EXCHANGE] = KEY.EXCHANGE_HUOBI_SWAP
        self._symbol, self._exchange = self._config[KEY.SYMBOL], self._config[KEY.EXCHANGE]

        self._database: AbstractDatabase = factory.Database(self._config, factory=factory, timer=timer)
        self._logger: AbstractLogger = factory.Logger(self._config, factory=factory, timer=timer)
        self._vault: AbstractVault = factory.Vault(self._config, factory=factory, timer=timer)

        self._symbol = self._construct_symbol()
        self._target_side = self._construct_side()
        self._target_side_coeff = +1 if self._target_side == KEY.LONG else -1

        self._rest_url = self._config.get(self._exchange, {}).get(KEY.REST_URL, None) or DEFAULT_REST_URL

        api_limit = self._config.get(self._exchange, {}).get(KEY.API_LIMIT, None) or DEFAULT.HUOBI_API_LIMIT
        self._soft_api_limit = int(api_limit * 0.95)  # First we have SOFT limit 5% before API LIMIT: we pause quoting
        self._hard_api_limit = int(api_limit * 0.98)  # Nex we have HARD limit 2% before API LIMIT: we skip LIMIT orders

        self._leverage = self._config.get(self._exchange, {}).get(KEY.LEVERAGE, DEFAULT.LEVERAGE)

        self._logger.info(f'Exchange: {self._rest_url} with limit={api_limit}')

        self._key = self._vault.Get(VAULT.KEY)
        self._secret = self._vault.Get(VAULT.SECRET)

        self._dry = self._key is None or self._secret is None
        if self._dry:
            self._logger.error('Exchange: No KEY/SECRET given. Running in DRY mode')

        exchange_info = self._get_exchange_info()
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

        # Always round qty DOWN
        order.qty = sign(order.qty) * math.floor(abs(order.qty) / self._min_qty) * self._min_qty

        return order

    def getBook(self) -> Book:
        r = self._request(
            method=KEY.GET,
            endpoint='/linear-swap-ex/market/detail/merged',
            params=dict(contract_code=self._symbol),
        )

        ask_price, ask_qty = r['tick']['ask']
        bid_price, bid_qty = r['tick']['bid']

        ask_qty *= self._contract_value
        bid_qty *= self._contract_value

        return Book(
            ask_price=Decimal(str(ask_price)),
            ask_qty=Decimal(str(ask_qty)),
            bid_price=Decimal(str(bid_price)),
            bid_qty=Decimal(str(bid_qty)),
        )


    def getBalance(self) -> Balance:
        r = self._request(
            method=KEY.POST,
            endpoint='/linear-swap-api/v1/swap_cross_account_info',
            params=dict(contract_code=self._symbol),
            signed=True,
        )

        for item in r['data']:
            product = [x for x in item['contract_detail'] if x['contract_code'] == self._symbol][0]
            return Balance(
                balance=Decimal(str(product['margin_available'])),
                unrealized_pnl=Decimal(str(product['profit_unreal'])),
            )

    def getTick(self) -> Decimal:
        return self._tick

    def getMinQty(self) -> Decimal:
        return self._min_qty

    def getPosition(self) -> Order:
        r = self._request(
            method=KEY.POST,
            endpoint='/linear-swap-api/v1/swap_cross_position_info',
            params=dict(contract_code=self._symbol),
            signed=True,
        )

        for item in r.get('data', []):
            return Order(
                qty=Decimal(str(item['available'])),
                price=Decimal(str(item['cost_hold']))
            )

        return Order()

    def getCandles(self, start_timestamp: int, end_timestamp: int) -> Dict[str, deque]:
        pass

    def Post(self, order: Order, wait=False) -> str:
        params = self._get_params(order)

        order_id = params.get('client_order_id', '')
        pprint(params)

        # No API calls if QTY eq. zero
        if abs(float(params['volume'])) < KEY.E:
            return order_id

        else:

            request = threading.Thread(
                target=self._request,
                kwargs=dict(method=KEY.POST, endpoint='/linear-swap-api/v1/swap_cross_order', params=params, signed=True)
            )

        request.start()

        if wait:
            request.join()

        return order_id


    def batchPost(self, orders: List[Order], wait=False) -> List[str]:
        pass

    def Cancel(self, ids: Optional[List] = None, wait=False):
        pass

    ##############################################################################
    #
    # Private Methods
    #
    ##############################################################################

    """
    Decode normalized symbol name to Okex notation and Sise
    """
    def _parse_symbol_side(self) -> Tuple[str, str]:
        symbol = self._config[KEY.SYMBOL].upper()

        left, right = symbol.split('USD')

        if '.' in right:
            suffix, side = right.split('.')
        else:
            suffix, side = right, ''

        side = KEY.LONG if 'LONG' in side.upper() else KEY.SHORT

        return f'{left}-USD{suffix}', side

    """
    Return symbol name in Huobi notation
    """
    def _construct_symbol(self) -> str:
        symbol, _ = self._parse_symbol_side()
        return symbol

    """
    Return side parsed from normalized symbol
    """
    def _construct_side(self) -> str:
        _, side = self._parse_symbol_side()
        return side

    def _get_params(self, order: Order) -> dict:

        _qty = round(order.qty / self._contract_value) * self._contract_value

        params = dict(
            client_order_id=self._get_id_tag(order.tag),
            contract_code=self._symbol,
            volume=int(abs(_qty)),
            lever_rate=self._leverage,
        )

        if order.qty > 0 and self._target_side == KEY.LONG:
            params['direction'] = 'buy'; params['offset'] = 'open'

        elif order.qty > 0 and self._target_side == KEY.SHORT:
            params['direction'] = 'sell'; params['offset'] = 'close'

        elif order.qty < 0 and self._target_side == KEY.LONG:
            params['direction'] = 'buy';params['offset'] = 'close'

        elif order.qty < 0 and self._target_side == KEY.SHORT:
            params['direction'] = 'sell';params['offset'] = 'open'


        if order.price is None:  # No price given --> MARKET Order
            params['order_price_type'] = 'opponent'

        else:  # Limit Orders
            if not order.stopmarket:
                params[KEY.PRICE] = str(order.price)
                params['order_price_type'] = 'limit'

                # SMALL HACK FOR TURN OFF SELF LIQUIDATION
                if params['offset'] == 'close':
                    params['volume'] = '0'

            # TODO: Implement conditional order
            else:
                params['volume'] = '0'

        return params


    def _sign(self, endpoint: str) -> str:
        print(endpoint)
        timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S')
        timestamp = parse.quote(timestamp)
        suffix = f'AccessKeyId={self._key}&SignatureMethod=HmacSHA256&SignatureVersion=2&Timestamp={timestamp}'

        payload = f'POST\napi.hbdm.com\n{endpoint}\n{suffix}'

        digest = hmac.new(self._secret.encode('utf8'), payload.encode('utf8'), digestmod=sha256).digest()
        signature = base64.b64encode(digest).decode()

        suffix = f'{suffix}&Signature={parse.quote(signature)}'

        return suffix



    def _request(self, method: str, endpoint: str, params: Optional[dict] = None, signed: bool = False, **kwargs) -> dict:

        for request_counter in range(REQUEST_ATTEMPT):
            try:

                def get_headers() -> dict:
                    return {'Accept':'application/json', 'Content-type':'application/json'}

                url = self._rest_url + endpoint
                if method == KEY.GET:
                    _api_result = requests.get(url=url, headers=get_headers(), params=params)
                elif method == KEY.POST:
                    signature = self._sign(endpoint=endpoint)
                    url = f'{url}?{signature}'; print(url)
                    _api_result = requests.post(url=url, headers=get_headers(), json=params)
                elif method == KEY.DELETE:
                    _api_result = requests.delete(url=url, headers=get_headers(), params=params)

            except Exception as e:
                _api_result = requests.models.Response()
                print(e)

            break

        if _api_result.status_code == HTTPStatus.OK:
            try:
                result = _api_result.json()
            except:
                result = {
                    'error': _api_result.reason,
                    'code': _api_result.status_code,
                    'text': _api_result.text.replace('"', ''),
                    'params': params,
                }
        else:
            result = {
                'error': _api_result.reason,
                'code': _api_result.status_code,
                'text': _api_result.text.replace('"', ''),
                'params': params,
            }

        message = json.dumps({
            'event': method.upper(),
            'endpoint': endpoint,
            'response': result
        }, default=custom_dump).replace('"', '\\"')

        payload = self._database.Encode(fields={
            DB.REQUEST: message,
        }, timestamp=self._timer.Timestamp())

        error = self._database.writeEncoded([payload])

        if error is not None:
            self._logger.error(f'Cant write Request result to database: {error}')

        return result


    def _get_exchange_info(self):
        return self._request(
            method=KEY.GET,
            endpoint='/linear-swap-api/v1/swap_contract_info',
            params=dict()
        )

    def _get_tick(self, exchange_info: dict) -> Decimal:
        product_info = [x for x in exchange_info['data'] if x['contract_code'] == self._symbol][0]

        return Decimal(str(product_info['price_tick']))

    def _get_min_qty(self, exchange_info: dict) -> Decimal:
        product_info = [x for x in exchange_info['data'] if x['contract_code'] == self._symbol][0]

        return Decimal(str(product_info['contract_size']))

    def _get_contract_value(self, exchange_info: dict) -> Decimal:
        product_info = [x for x in exchange_info['data'] if x['contract_code'] == self._symbol][0]

        return Decimal(str(product_info['contract_size']))

    def _get_id_timestamp(self) -> str:
        return f'{self._id}{str(self._timer.Timestamp())[:-3]}'

    def _get_id_iso(self) -> str:
        now = self._timer.Now()
        return f'{self._id}-' \
               f'{now.year}{now.month:02}{now.day:02}.' \
               f'{now.hour:02}{now.minute:02}{now.second:02}.' \
               f'{now.microsecond:06}'

    def _get_id_tag(self, tag: Optional[str]) -> int:
        now = self._timer.Now()
        id = f'{now.year - 2000}{now.month:02}{now.day:02}' \
             f'{now.hour:02}{now.minute:02}{now.second:02}' \
             f'{now.microsecond:06}'
        if tag is not None:
            id = f'{id}{ORDER_TAG.index(tag)}'

        return int(id)
