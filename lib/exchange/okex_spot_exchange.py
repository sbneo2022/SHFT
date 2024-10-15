import base64
import copy
import hmac
import json
import math
import threading
import urllib.parse
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
from http import HTTPStatus
from typing import Optional, Dict, List, Tuple, Union

import ciso8601
import requests

from lib.constants import KEY, DB, ORDER_TYPE, MONTH_MAP
from lib.database import AbstractDatabase
from lib.defaults import DEFAULT
from lib.exchange import AbstractExchange, Order, Book, Balance
from lib.factory import AbstractFactory
from lib.helpers import custom_dump, sign
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer
from lib.vault import AbstractVault, VAULT


REQUEST_FN_MAP = {
    KEY.GET: requests.get,
    KEY.POST: requests.post,
    KEY.DELETE: requests.delete,
}


class OKEX_TYPE:
    OPEN_LONG = '1'
    OPEN_SHORT = '2'
    CLOSE_LONG = '3'
    CLOSE_SHORT = '4'
    FIELD = 'type'

class OKEX_ORDER_TYPE:
    NORMAL = '0'
    MARKET = '4'
    FIELD = 'order_type'

DEFAULT_REST_URL = 'https://aws.okex.com'


MARKET_ORDER_LIMIT_DEFAULT = 1000
MARKET_ORDER_LIMITS = {
    'BTC-USD-SWAP': 400,
    'LTC-USD-SWAP': 500,
    'ETH-USD-SWAP': 1500,
    'ETC-USD-SWAP': 500,
    'BSV-USD-SWAP': 100,
    'TRX-USD-SWAP': 1500,
    'LINK-USD-SWAP': 3000,
    'DASH-USD-SWAP': 3000,
    'NEO-USD-SWAP': 3000,
}

KLINES_LIMIT = 10

SOFT_LIMIT_ORDERS = 1200 - 120
HARD_LIMIT_ORDERS = 1200 - 60
REPLACE_LIMITS_AFTER = 1 * KEY.ONE_MINUTE

REQUEST_ATTEMPT = 2
REQUEST_TIMEOUT = 0.5

class OkexSpotExchange(AbstractExchange):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, symbol: Optional[str] = None):
        super().__init__(config, factory, timer, symbol)

        # Override exchange name
        self._config[KEY.EXCHANGE] =  KEY.EXCHANGE_OKEX_SPOT
        self._symbol, self._exchange = self._config[KEY.SYMBOL], self._config[KEY.EXCHANGE]

        self._database: AbstractDatabase = factory.Database(self._config, factory=factory, timer=timer)
        self._logger: AbstractLogger = factory.Logger(self._config, factory=factory, timer=timer)
        self._vault: AbstractVault = factory.Vault(self._config, factory=factory, timer=timer)

        self._symbol = self._construct_symbol()
        self._max_market_qty = MARKET_ORDER_LIMITS.get(self._symbol, MARKET_ORDER_LIMIT_DEFAULT)

        self._target_side = self._construct_side()
        self._target_side_coeff = +1 if self._target_side == KEY.LONG else -1

        self._rest_url = self._config.get(self._exchange, {}).get(KEY.REST_URL, None) or DEFAULT_REST_URL

        api_limit = self._config.get(self._exchange, {}).get(KEY.API_LIMIT, None) or DEFAULT.OKEX_API_LIMIT
        self._soft_api_limit = int(api_limit * 0.95)  # First we have SOFT limit 5% before API LIMIT: we pause quoting
        self._hard_api_limit = int(api_limit * 0.98)  # Nex we have HARD limit 2% before API LIMIT: we skip LIMIT orders

        self._logger.info(f'Exchange: {self._rest_url} with limit={api_limit}')

        self._key = self._vault.Get(VAULT.KEY)
        self._secret = self._vault.Get(VAULT.SECRET)
        self._passphrase = self._vault.Get(VAULT.PASSPHRASE)

        self._requests_counter = 0
        self._orders_counter = 0
        self._replace_limits_after = None

        self._dry = self._key is None or self._secret is None
        if self._dry:
            self._logger.error('Exchange: No KEY/SECRET given. Running in DRY mode')

        self._contract_val = self._get_contract_val()

        self._tick = self._get_tick()

        self._min_qty_contracts = self._get_min_qty()
        self._min_qty = self._min_qty_contracts * self._contract_val

        position = self.getPosition()
        self._portfolio = position.qty

   ##############################################################################
    #
    # Public Methods
    #
    ##############################################################################

    def isOnline(self) -> bool:
        """
        This function handle only API/Order limits as online tag

        All limits are clear if `self._replace_limits_after` has
        timestamp and that timestamp > current_timestamp

        :return:
        """
        if self._replace_limits_after is not None:
            if self._timer.Timestamp() > self._replace_limits_after:
                self._requests_counter = 0
                self._orders_counter = 0
                self._replace_limits_after = None

        if self._requests_counter > self._soft_api_limit:
            return False

        if self._orders_counter > SOFT_LIMIT_ORDERS:
            return False

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

        return order

    def getBook(self) -> Book:
        # { 'bidPrice': '0.05404', 'bidQty': '107996', 'askPrice': '0.05405' ...

        all_products = self._request(
            method=KEY.GET,
            endpoint='/api/spot/v3/instruments/ticker',
            signed=True
        )

        current_product = [x for x in all_products if x['instrument_id'] == self._symbol][0]

        return Book(
            ask_price=Decimal(current_product['best_ask']),
            ask_qty=Decimal(current_product['best_ask_size']),
            bid_price=Decimal(current_product['best_bid']),
            bid_qty=Decimal(current_product['best_bid_size']),
        )

    # TODO: Create `Balance` object
    def getBalance(self) -> Balance:
        r = self._request(method=KEY.GET, endpoint=f'/api/swap/v3/{self._symbol}/accounts', signed=True)

        if 'info' in r:
            return Balance(
                balance=Decimal(r['info']['equity']),
                unrealized_pnl=Decimal(r['info']['unrealized_pnl']),
            )
        else:
            return Balance()

    def getPosition(self) -> Order:
        try:
            positions = self._request(KEY.GET, '/api/swap/v3/position', signed=True)
            for item in positions:
                for product in item['holding']:
                    qty = Decimal(product['position'])
                    if abs(qty) > 0:
                        coeff = +1 if product['side'] == 'long' else -1
                        return Order(
                            qty=qty * self._contract_val * coeff,
                            price=Decimal(product['avg_cost']),
                        )
            return Order()
        except Exception as e:
            print(e)
            return Order()

    def getCandles(self, start_timestamp: int, end_timestamp: int) -> Dict[str, deque]:
        result = dict()

        timedelta = (end_timestamp - start_timestamp) // KEY.ONE_MINUTE
        fields = [KEY.TIMESTAMP, KEY.OPEN, KEY.HIGH, KEY.LOW, KEY.CLOSE, None, KEY.VOLUME]
        for field in fields:
            result[field] = deque(maxlen=timedelta)

        while True:
            _end_timestamp = min(end_timestamp, start_timestamp + KLINES_LIMIT * KEY.ONE_MINUTE)
            bucket = self._request(
                method=KEY.GET,
                endpoint=f'/api/swap/v3/instruments/{self._symbol}/candles',
                params=dict(
                    granularity='60',
                    start=self._timestamp2str(start_timestamp),
                    end=self._timestamp2str(_end_timestamp),
                    limit=str(KLINES_LIMIT),
                ),
                signed=True
            )

            for item in bucket[::-1]:
                for idx, field in enumerate(fields):
                    if field == KEY.TIMESTAMP:
                        result[field].append(
                            int(
                                ciso8601.parse_datetime(item[idx]).timestamp() * 1e3
                            ) * KEY.ONE_MS
                        )
                    elif field is not None:
                        result[field].append(Decimal(item[idx]))

            if _end_timestamp == end_timestamp:
                break
            else:
                start_timestamp = _end_timestamp

        return result

    def _cancel_and_post_thread(self, params: dict):
        endpoint = f'/api/swap/v3/cancel_batch_orders/{self._symbol}'
        open_orders_list = self._get_open_orders_list()
        if ''.join(open_orders_list) != '':
            cancel_params = {'client_oids': open_orders_list}
            self._request(method=KEY.POST, endpoint=endpoint, params=cancel_params, signed=True)

        # Check max limit order qty
        order_qty = int(params['size'])
        if order_qty <= self._max_market_qty:
            self._request(method=KEY.POST, endpoint='/api/swap/v3/order', params=params, signed=True)
        else:
            def chunks(value, step):
                while value > step:
                    value -= step
                    yield step
                yield value

            new_params = []

            for item in list(chunks(order_qty, self._max_market_qty)):
                new_item = copy.deepcopy(params)
                new_item['size'] = str(item)
                new_params.append(new_item)

            self._request(
                method=KEY.POST,
                endpoint='/api/swap/v3/orders',
                params=dict(instrument_id=self._symbol,
                            order_data=new_params),
                signed=True
            )

    @staticmethod
    def adjust_orders(portfolio: Union[Decimal, int], orders: List[Order]) -> List[Order]:
        result = []
        for item in orders:
            # If orders could close inventory --> we have to change orders direction
            if item.qty * portfolio < 0:
                delta = min(abs(item.qty), abs(portfolio))
                portfolio -= sign(portfolio) * delta
                # print(f'delta={delta}    portfolio={portfolio}')

                if delta > 0:
                    result.append(Order(
                        qty=-1 * sign(item.qty) * delta,
                        price=item.price,
                        liquidation=True,
                        tag=item.tag,
                        stopmarket=item.stopmarket,
                    ))

                    order_delta = abs(item.qty) - abs(delta)

                    if order_delta > 0:
                        result.append(Order(
                            qty=sign(item.qty) * order_delta,
                            price=item.price,
                            stopmarket=item.stopmarket,
                            tag=item.tag,
                        ))

                else:
                    result.append(item)
            else:
                if item.liquidation:
                    portfolio += -1 * item.qty

                result.append(Order(
                    qty=item.qty,
                    price=item.price,
                    stopmarket=item.stopmarket,
                    liquidation=False,
                    tag=item.tag,
                ))

        return result

    def Post(self, order: Order, wait=False) -> str:
        print('>>>>', order)
        print(self._portfolio)

        adjusted_orders = self.adjust_orders(self._portfolio, [order])
        print('<<<<', adjusted_orders)

        if len(adjusted_orders) > 1:
            new_ids = self._batch_post_without_adjustments(adjusted_orders, wait=wait)
            return new_ids[0]

        params = self._get_params(adjusted_orders[0])

        order_id = params.get('client_oid', '')

        # No API calls if QTY eq. zero
        if abs(float(params['size'])) < KEY.E:
            return order_id

        print(f'POST {params}')

        # return order_id

        if order.price is None:  # For Okex and Market order we have to cancel everything first
            request = threading.Thread(
                target=self._cancel_and_post_thread,
                kwargs=dict(params=params)
            )
        else:
            request = threading.Thread(
                target=self._request,
                kwargs=dict(method=KEY.POST, endpoint='/api/swap/v3/order', params=params, signed=True)
            )

        request.start()

        if wait:
            request.join()

        return order_id


    def _batch_post_without_adjustments(self, orders: List[Order], wait=False) -> List[str]:
        print('<<<<<', orders)

        params = [self._get_params(order) for order in orders]

        non_zero_orders = [x for x in params if float(x['size']) > KEY.E]

        print(f'POST {non_zero_orders}')

        if non_zero_orders:
            request = threading.Thread(
                target=self._request,
                kwargs=dict(
                    method=KEY.POST,
                    endpoint='/api/swap/v3/orders',
                    params=dict(instrument_id=self._symbol,
                                order_data=non_zero_orders),
                    signed=True
                )
            )

            request.start()

            if wait:
                request.join()

        return [x['client_oid'] for x in params]

    def batchPost(self, orders: List[Order], wait=False) -> List[str]:
        print('>>>>', orders)
        print(self._portfolio)

        adjusted_orders = self.adjust_orders(self._portfolio, orders)

        return self._batch_post_without_adjustments(adjusted_orders)


    def Cancel(self, ids: Optional[Union[str, List]] = None, wait=False):
        if isinstance(ids, str) and ids is not None:
            endpoint = f'/api/swap/v3/cancel_order/{self._symbol}/{ids}'
            params = None
        else:
            if ids is None:  # load ids from
                ids = self._get_open_orders_list()

            open_orders = [x for x in ids if x is not None]

            if open_orders:
                params = {'client_oids': open_orders}
                endpoint = f'/api/swap/v3/cancel_batch_orders/{self._symbol}'
            else:
                endpoint = None

        if endpoint is not None:
            request = threading.Thread(
                target=self._request,
                kwargs=dict(method=KEY.POST, endpoint=endpoint, params=params, signed=True)
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

        return f'{left}-USD{suffix}-SWAP', side

    """
    Return symbol name in Okex notation
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

    """
    Return list of NEW (not filled) orders on exchange
    """
    def _get_open_orders_list(self) -> list:
        orders = self._request(
            method=KEY.GET,
            endpoint=f'/api/swap/v3/orders/{self._symbol}',
            params=dict(state='0'),
            signed=True
        )

        result = []

        for item in orders.get('order_info', []):
            result.append(item['client_oid'])

        return result

    def _get_params(self, order: Order) -> dict:
        print('ORDER >>> ', order)
        if order.liquidation:
            if order.qty > 0:
                _type = OKEX_TYPE.CLOSE_LONG
            else:
                _type = OKEX_TYPE.CLOSE_SHORT
        else:
            if order.qty > 0:
                _type = OKEX_TYPE.OPEN_LONG
            else:
                _type = OKEX_TYPE.OPEN_SHORT

        _qty = abs(order.qty) / self._contract_val
        _qty = round(_qty / self._min_qty_contracts) * self._min_qty_contracts

        params = dict(
            instrument_id=self._symbol,
            type=_type,
            size=str(_qty),
            client_oid=self._get_id_tag(order.tag)
        )

        if order.price is None:  # No price given --> MARKET Order
            params[OKEX_ORDER_TYPE.FIELD] = OKEX_ORDER_TYPE.MARKET

        else:  # Limit Orders
            if not order.stopmarket:
                params[KEY.PRICE] = str(order.price)
                params[OKEX_ORDER_TYPE.FIELD] = OKEX_ORDER_TYPE.NORMAL

            # TODO: Implement conditional order
            else:
                params['size'] = '0'

        return params

    def _sign(self, timestamp: str, method: str, endpoint: str, params: dict) -> str:
        if self._dry:
            return ''

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

    def _is_urgent_order(self, method: str, params: dict) -> bool:
        """
        Only POST LIMIT order has low priority and could be skiped
        when we are close to API limits

        :param method:
        :param params:
        :return: True if order could not be canceled; False if we can skip this order with error
        """
        if method == KEY.POST and (params or {}).get('type', None) == ORDER_TYPE.LIMIT:
            return False

        return True

    def _request(self, method: str, endpoint: str, params: Optional[dict] = None, signed: bool = False, **kwargs) -> dict:
        timestamp = self._timestamp2str(self._timer.Timestamp())

        for request_counter in range(REQUEST_ATTEMPT):
            signature = self._sign(timestamp, method, endpoint, params or {})

            try:

                def get_headers() -> dict:
                    return {
                            'OK-ACCESS-KEY': self._key,
                            'OK-ACCESS-PASSPHRASE': self._passphrase,
                            'OK-ACCESS-TIMESTAMP': timestamp,
                            'OK-ACCESS-SIGN': signature,
                            'Content-Type': 'application/json',
                           }

                url = self._rest_url + endpoint
                if method == KEY.GET:
                    _api_result = requests.get(url=url, headers=get_headers(), params=params)
                elif method == KEY.POST:
                    _api_result = requests.post(url=url, headers=get_headers(), json=params)
                elif method == KEY.DELETE:
                    _api_result = requests.delete(url=url, headers=get_headers(), params=params)

            except Exception as e:
                _api_result = requests.models.Response()
                print(e)

            """
            Retry requests for CANCEL orders (N times each 0.5s) -- they are very important
            And for POST MARKET orders which has to liquidate portfolio in case of emergency
            """
            if method == KEY.POST \
                    and (params or {}).get('order_data', None) is not None \
                    and len(params['order_data']) > 0 \
                    and params['order_data'][0]['order_type'] == OKEX_ORDER_TYPE.MARKET \
                    and _api_result.status_code != HTTPStatus.OK:
                if request_counter < (REQUEST_ATTEMPT - 1):
                    self._timer.Sleep((request_counter + 1) * REQUEST_TIMEOUT)
            elif method == KEY.POST \
                    and (params or {}).get('order_type', None) == OKEX_ORDER_TYPE.MARKET \
                    and _api_result.status_code != HTTPStatus.OK:
                if request_counter < (REQUEST_ATTEMPT - 1):
                    self._timer.Sleep((request_counter + 1) * REQUEST_TIMEOUT)
            elif method == KEY.POST \
                    and 'cancel' in endpoint \
                    and _api_result.status_code != HTTPStatus.OK:
                """
                Repeat CANCEL if status != 200
                """
                if request_counter < (REQUEST_ATTEMPT - 1):
                    self._timer.Sleep((request_counter + 1) * REQUEST_TIMEOUT)

            elif method == KEY.POST \
                    and 'cancel' in endpoint \
                    and _api_result.status_code == HTTPStatus.OK:
                """
                If CANCEL and status == 200 --> check orders ids
                """
                _result = _api_result.json()

                _successfully = True
                if 'client_oids' in _result:
                    for item in params['client_oids']:
                        if item not in _result['client_oids']:
                            _successfully = False
                else:
                    if _result['order_id'] == '-1':
                        _successfully = False

                if _successfully:
                    break
                else:
                    if request_counter < (REQUEST_ATTEMPT - 1):
                        self._timer.Sleep((request_counter + 1) * REQUEST_TIMEOUT)
            else:
                break

        if _api_result.status_code == HTTPStatus.OK:
            try:
                result = _api_result.json()
            except:
                result = {
                    'error': _api_result.reason,
                    'code': _api_result.status_code,
                    'text': _api_result.text.replace('"', ''),
                }
        else:
            result = {
                'error': _api_result.reason,
                'code': _api_result.status_code,
                'text': _api_result.text.replace('"', ''),
            }

        message = json.dumps({
            'event': method.upper(),
            'endpoint': endpoint,
            'response': result,
            'params': params,
        }, default=custom_dump).replace('"', '\\"')

        payload = self._database.Encode(fields={
            DB.REQUEST: message,
        }, timestamp=self._timer.Timestamp())

        error = self._database.writeEncoded([payload])

        if error is not None:
            self._logger.error(f'Cant write Request result to database: {error}')

        return result

    def _get_exchange_info(self) -> dict:
        return self._request(
            method=KEY.GET,
            endpoint='/api/swap/v3/instruments',
            params=dict()
        )

    def _get_contract_val(self) -> Decimal:
        symbols = self._get_exchange_info()

        product_info = [x for x in symbols if x['instrument_id'] == self._symbol][0]

        return Decimal(product_info['contract_val'])

    def _get_tick(self) -> Decimal:
        symbols = self._get_exchange_info()

        product_info = [x for x in symbols if x['instrument_id'] == self._symbol][0]

        return Decimal(product_info['tick_size'])

    def _get_min_qty(self) -> Decimal:
        symbols = self._get_exchange_info()

        product_info = [x for x in symbols if x['instrument_id'] == self._symbol][0]

        return Decimal(product_info['size_increment'])

    def _get_top_book(self) -> dict:
        return self._request(
            method=KEY.GET,
            endpoint='/fapi/v1/ticker/bookTicker',
            params=dict(symbol=self._symbol)
        )

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
        return f'{self._id}' \
               f'{now.year - 2000}{MONTH_MAP[now.month]}{now.day:02}' \
               f'{now.hour:02}{now.minute:02}{now.second:02}' \
               f'{now.microsecond:06}{tag or ""}'
