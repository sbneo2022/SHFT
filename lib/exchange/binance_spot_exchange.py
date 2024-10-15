import hashlib
import hmac
import json
import math
import threading
import urllib.parse
from collections import deque
from decimal import Decimal
from http import HTTPStatus
from pprint import pprint
from typing import Optional, Dict, List, Union

import requests

from lib.constants import KEY, DB, SIDE, ORDER_TYPE, TIF, MONTH_MAP
from lib.database import AbstractDatabase
from lib.defaults import DEFAULT
from lib.exchange import AbstractExchange, Order, Book, Balance
from lib.factory import AbstractFactory
from lib.helpers import custom_dump, sign
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer
from lib.vault import AbstractVault, VAULT


DEFAULT_REST_URL = "https://api.binance.com"

KLINES_LIMIT = 1500

SOFT_LIMIT_10_RATE = 200
HARD_LIMIT_10_RATE = 250

SOFT_LIMIT_ORDERS = 1200 - 120
HARD_LIMIT_ORDERS = 1200 - 60
REPLACE_LIMITS_AFTER = 15 * KEY.ONE_SECOND

REQUEST_ATTEMPT = 3
REQUEST_TIMEOUT = 0.5


class BinanceSpotExchange(AbstractExchange):
    def __init__(
        self,
        config: dict,
        factory: AbstractFactory,
        timer: AbstractTimer,
        symbol: Optional[str] = None,
    ):
        super().__init__(config, factory, timer, symbol)

        # Override exchange name
        self._config[KEY.EXCHANGE] = KEY.EXCHANGE_BINANCE_SPOT
        self._symbol, self._exchange = (
            self._config[KEY.SYMBOL],
            self._config[KEY.EXCHANGE],
        )

        self._database: AbstractDatabase = factory.Database(
            self._config, factory=factory, timer=timer
        )
        self._logger: AbstractLogger = factory.Logger(
            self._config, factory=factory, timer=timer
        )
        self._vault: AbstractVault = factory.Vault(
            self._config, factory=factory, timer=timer
        )

        self._rest_url = (
            self._config.get(self._exchange, {}).get(KEY.REST_URL, None)
            or DEFAULT_REST_URL
        )

        self._coin, self._currency = self._symbol, self._symbol
        for currency in ["USDT", "BNB", "BTC"]:
            if self._symbol.endswith(currency):
                self._coin = self._symbol[: -len(currency)]
                self._currency = currency

        api_limit = (
            self._config.get(self._exchange, {}).get(KEY.API_LIMIT, None)
            or DEFAULT.BINANCE_API_LIMIT
        )
        self._soft_api_limit = int(
            api_limit * 0.95
        )  # First we have SOFT limit 5% before API LIMIT: we pause quoting
        self._hard_api_limit = int(
            api_limit * 0.98
        )  # Nex we have HARD limit 2% before API LIMIT: we skip LIMIT orders

        self._logger.info(f"Exchange: {self._rest_url} with limit={api_limit}")

        self._key = self._vault.Get(VAULT.KEY)
        self._secret = self._vault.Get(VAULT.SECRET)

        self._requests_counter = 0
        self._orders_counter = 0
        self._orders10s_counter = 0
        self._replace_limits_after = None

        self._dry = self._key is None or self._secret is None
        if self._dry:
            self._logger.error("Exchange: No KEY/SECRET given. Running in DRY mode")

        # exchange_info = self._get_exchange_info()
        # self._tick = self._get_tick(exchange_info)
        # self._min_qty = self._get_min_qty(exchange_info)
        # self._min_notional = self._get_min_notional(exchange_info)

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
                self._orders10s_counter = 0

                self._replace_limits_after = None

        if self._requests_counter > self._soft_api_limit:
            return False

        if self._orders10s_counter > SOFT_LIMIT_10_RATE:
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

        order.qty = (
            sign(order.qty) * round(abs(order.qty) / self._min_qty) * self._min_qty
        )

        # If order is not LIQUIDATION --> check "min_notional"
        if not order.liquidation:
            if order.price is None:
                price = (
                    self._top_book.ask_price
                    if order.qty > 0
                    else self._top_book.bid_price
                )
            else:
                price = order.price

            if abs(order.qty * (price or 0)) <= self._min_notional:
                order.qty = Decimal(0)

        return order

    def getBook(self) -> Book:
        r = self._request(
            method=KEY.GET,
            endpoint="/api/v3/ticker/bookTicker",
            params=dict(symbol=self._symbol),
        )

        return Book(
            ask_price=Decimal(r[KEY.ASK_PRICE]),
            ask_qty=Decimal(r[KEY.ASK_QTY]),
            bid_price=Decimal(r[KEY.BID_PRICE]),
            bid_qty=Decimal(r[KEY.BID_QTY]),
        )

    def getBalance(self) -> Balance:
        try:
            r = self._request(
                method=KEY.GET,
                endpoint="/sapi/v1/capital/config/getall",
                params=dict(),
                signed=True,
            )

            for item in r:
                if item["coin"] == self._currency:
                    return Balance(balance=Decimal(item["free"]))
        except:
            return Balance(Decimal(0))

    def getPosition(self) -> Order:
        try:
            r = self._request(
                method=KEY.GET,
                endpoint="/sapi/v1/capital/config/getall",
                params=dict(),
                signed=True,
            )

            for item in r:
                if item["coin"] == self._coin:
                    # get current qty
                    qty = Decimal(item["free"])

                    # load history trades
                    r = self._request(
                        method=KEY.GET,
                        endpoint="/api/v3/myTrades",
                        params=dict(symbol=self._symbol),
                        signed=True,
                    )

                    # lets go latest to oldest
                    total_qty = Decimal(0)
                    total_pxq = Decimal(0)

                    for trade in r[::-1]:
                        if trade["symbol"] == self._symbol and trade["isBuyer"]:
                            traded_qty = Decimal(trade["qty"])
                            traded_price = Decimal(trade["price"])

                            total_qty += traded_qty

                            delta = traded_qty - max(0, total_qty - qty)

                            total_pxq += delta * traded_price

                            if total_qty >= qty:
                                break

                    vwap = total_pxq / qty

                    return Order(qty=qty, price=vwap)
        except:
            return Order()

    def getCandles(self, start_timestamp: int, end_timestamp: int) -> Dict[str, deque]:
        result = dict()

        timedelta = (end_timestamp - start_timestamp) // KEY.ONE_MINUTE
        fields = [KEY.TIMESTAMP, KEY.OPEN, KEY.HIGH, KEY.LOW, KEY.CLOSE, KEY.VOLUME]
        for field in fields:
            result[field] = deque(maxlen=timedelta)

        while True:
            _end_timestamp = min(
                end_timestamp, start_timestamp + KLINES_LIMIT * KEY.ONE_MINUTE
            )
            bucket = self._request(
                method=KEY.GET,
                endpoint="/api/v3/klines",
                params=dict(
                    symbol=self._symbol,
                    interval="1m",
                    startTime=start_timestamp // KEY.ONE_MS,
                    endTime=_end_timestamp // KEY.ONE_MS,
                    limit=KLINES_LIMIT,
                ),
                signed=True,
            )

            for item in bucket:
                for idx, field in enumerate(fields):
                    if field == KEY.TIMESTAMP:
                        result[field].append(int(item[idx] * KEY.ONE_MS))
                    else:
                        result[field].append(Decimal(item[idx]))

            if _end_timestamp == end_timestamp:
                break
            else:
                start_timestamp = _end_timestamp

        return result

    def Post(self, order: Order, wait=False) -> str:
        # Create "params" dicts for exchange api
        params = self._get_params(order)

        # Just return
        if not params["quantity"] > 0:
            return params["newClientOrderId"]

        # Prepare thread for order processing
        request = threading.Thread(
            target=self._request,
            kwargs=dict(
                method=KEY.POST, endpoint="/api/v3/order", params=params, signed=True
            ),
        )

        # Run order thread
        request.start()

        if wait:
            request.join()

        return params["newClientOrderId"]

    def batchPost(self, orders: List[Order], wait=False) -> List[str]:
        # Create "params" dicts for exchange api
        params = [self._get_params(order) for order in orders]

        # Filer orders and skip "zero"
        params = [x for x in params if x["quantity"] > 0]

        # Just return
        if not params:
            return []

        # Prepare thread for order processing
        request = threading.Thread(
            target=self._request,
            kwargs=dict(
                method=KEY.POST,
                endpoint="/api/v3/batchOrders",
                params=dict(batchOrders=json.dumps(params, default=custom_dump)),
                signed=True,
            ),
        )

        # Run order thread
        request.start()

        if wait:
            request.join()

        return [x["newClientOrderId"] for x in params]

    def Cancel(self, ids: Optional[Union[str, List]] = None, wait=False):
        params = dict(symbol=self._symbol)

        if isinstance(ids, str):
            ids = [ids]

        # If no orderId given --> make CANCEL ALL
        if ids is None:
            endpoint = "/api/v3/openOrders"

        else:
            # Filter None ordersId
            ids = [x for x in ids if x is not None]

            # If only one orderId given --> make CANCEL
            if len(ids) == 1:
                params["origClientOrderId"] = ids[0]
                endpoint = "/api/v3/order"

            # If several orderId given --> make BATCH CANCEL
            elif ids:
                params["origClientOrderIdList"] = json.dumps(ids)
                endpoint = "/api/v3/batchOrders"

            # Return if no one "not-null" orderId is found
            else:
                return

        # Prepare thread for order canceling
        request = threading.Thread(
            target=self._request,
            kwargs=dict(
                method=KEY.DELETE, endpoint=endpoint, params=params, signed=True
            ),
        )

        # Run thread
        request.start()

        if wait:
            request.join()

    ##############################################################################
    #
    # Private Methods
    #
    ##############################################################################

    def _get_params(self, order: Order) -> dict:
        params = dict(
            symbol=self._symbol,
            side=SIDE.BUY if order.qty > 0 else SIDE.SELL,
            quantity=abs(order.qty),
            newClientOrderId=self._get_id_tag(order.tag),
        )

        if order.price is None:  # No price given --> MARKET Order
            params["type"] = ORDER_TYPE.MARKET

        else:  # Limit Orders
            params["timeInForce"] = TIF.GTC

            if order.stopmarket:
                params["stopPrice"] = order.price
                params["type"] = ORDER_TYPE.STOP_MARKET

            else:
                params[KEY.PRICE] = order.price
                params["type"] = ORDER_TYPE.LIMIT

        return params

    def _sign(self, params) -> dict:
        if "signature" in params.keys():
            del params["signature"]
        params["timestamp"] = self._timer.Timestamp() // KEY.ONE_MS
        query = urllib.parse.urlencode([(key, value) for key, value in params.items()])
        params["signature"] = hmac.new(
            self._secret.encode(), query.encode(), digestmod=hashlib.sha256
        ).hexdigest()
        return params

    def _is_urgent_order(self, method: str, params: dict) -> bool:
        """
        Only POST LIMIT order has low priority and could be skiped
        when we are close to API limits

        :param method:
        :param params:
        :return: True if order could not be canceled; False if we can skip this order with error
        """
        if method == KEY.POST and (params or {}).get("type", None) == ORDER_TYPE.LIMIT:
            return False

        return True

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        signed: bool = False,
        **kwargs,
    ) -> dict:
        for request_counter in range(REQUEST_ATTEMPT):

            # Sign request if we need. We r using new `_params` variable
            # because we have to sign original 'params' in case of some errors
            if signed and not self._dry:
                _params = self._sign(params or {})
            else:
                _params = params

            # If we are close to HARD api limits and order is not URGENT --> skip i
            if (
                self._requests_counter > self._hard_api_limit
                or self._orders_counter > HARD_LIMIT_ORDERS
                or self._orders10s_counter > HARD_LIMIT_10_RATE
            ):

                self._logger.error(
                    f"Hit HARD API limits. Use Request Priorities",
                    event="API",
                    used_weights=self._requests_counter,
                    used_orders=self._orders_counter,
                    used_orders_10s=self._orders10s_counter,
                )

                if not self._is_urgent_order(method, params):
                    self._logger.error(f"BLOCK {method} {endpoint}", event="API")
                    return {
                        "error": "Priorities Block",
                        "code": 0,
                        "text": "Priorities Block",
                        "params": params,
                    }

            # Try to make request
            try:
                if "userDataStream" in endpoint:
                    del _params["timestamp"]
                    del _params["signature"]

                _api_result = requests.request(
                    method=method,
                    url=self._rest_url + endpoint,
                    headers={
                        "X-MBX-APIKEY": self._key if signed and not self._dry else None
                    },
                    params=_params,
                )

                # if method == KEY.POST:
                #     print(_params)
                #     print(_api_result.text)

            except:
                _api_result = requests.Response()

            """
            Retry requests for CANCEL orders (N times each 0.5s) -- they are very important
            And for POST MARKET orders which has to liquidate portfolio in case of emergency
            """
            if (
                method == KEY.POST
                and (params or {}).get("type", None) == ORDER_TYPE.MARKET
                and _api_result.status_code != HTTPStatus.OK
            ):
                if "-4164" in _api_result.text:
                    params["reduceOnly"] = "true"
                else:
                    if request_counter < (REQUEST_ATTEMPT - 1):
                        self._timer.Sleep((request_counter + 1) * REQUEST_TIMEOUT * 3)

            elif method == KEY.DELETE and _api_result.status_code != HTTPStatus.OK:
                if request_counter < (REQUEST_ATTEMPT - 1):
                    self._timer.Sleep((request_counter + 1) * REQUEST_TIMEOUT)

            elif method == KEY.DELETE and _api_result.status_code == HTTPStatus.OK:
                _result = _api_result.json()
                _result = _result if isinstance(_result, list) else [_result]
                _successfully = True
                for item in _result:
                    if item.get("code", 0) < 0:
                        _successfully = False
                if _successfully:
                    break
                else:
                    if request_counter < (REQUEST_ATTEMPT - 1):
                        self._timer.Sleep((request_counter + 1) * REQUEST_TIMEOUT)
            else:
                break

        if _api_result.status_code == HTTPStatus.OK:
            result = _api_result.json()

        else:
            result = {
                "error": _api_result.reason,
                "code": _api_result.status_code,
                "text": _api_result.text.replace('"', ""),
                "params": params,
            }

        # Get Limits from API reply
        if "X-MBX-ORDER-COUNT-1M" in _api_result.headers:
            self._orders_counter = int(_api_result.headers["X-MBX-ORDER-COUNT-1M"])

        if "X-MBX-ORDER-COUNT-10S" in _api_result.headers:
            self._orders10s_counter = int(_api_result.headers["X-MBX-ORDER-COUNT-10S"])

        if "X-MBX-USED-WEIGHT-1M" in _api_result.headers:
            self._requests_counter = int(_api_result.headers["X-MBX-USED-WEIGHT-1M"])

        if (
            self._orders_counter > SOFT_LIMIT_ORDERS
            or self._orders10s_counter > SOFT_LIMIT_10_RATE
            or self._requests_counter > self._soft_api_limit
        ):
            self._replace_limits_after = self._timer.Timestamp() + REPLACE_LIMITS_AFTER

        message = json.dumps(
            {"event": method.upper(), "endpoint": endpoint, "response": result},
            default=custom_dump,
        ).replace('"', '\\"')

        payload = self._database.Encode(
            fields={
                DB.REQUEST_ORDER: self._orders_counter,
                DB.REQUEST_ORDER10S: self._orders10s_counter,
                DB.REQUEST_USED: self._requests_counter,
                DB.REQUEST: message,
            },
            timestamp=self._timer.Timestamp(),
        )

        # error = self._database.writeEncoded([payload])

        #if error is not None:
        #    self._logger.error(f"Cant write Request result to database: {error}")

        return result

    def _get_exchange_info(self) -> dict:
        return self._request(
            method=KEY.GET, endpoint="/api/v3/exchangeInfo", params=dict()
        )

    def _get_tick(self, exchange_info: dict) -> Decimal:
        product_info = [
            x for x in exchange_info["symbols"] if x[KEY.SYMBOL] == self._symbol
        ][0]

        filter = [
            x for x in product_info["filters"] if x["filterType"] == "PRICE_FILTER"
        ][0]

        return Decimal(filter["tickSize"])

    def _get_min_qty(self, exchange_info: dict) -> Decimal:
        product_info = [
            x for x in exchange_info["symbols"] if x[KEY.SYMBOL] == self._symbol
        ][0]

        filter = [x for x in product_info["filters"] if x["filterType"] == "LOT_SIZE"][
            0
        ]

        return Decimal(filter["stepSize"])

    def _get_min_notional(self, exchange_info: dict) -> Decimal:
        product_info = [
            x for x in exchange_info["symbols"] if x[KEY.SYMBOL] == self._symbol
        ][0]

        filter = [
            x for x in product_info["filters"] if x["filterType"] == "MIN_NOTIONAL"
        ][0]

        return Decimal(filter["minNotional"])

    def _get_id_timestamp(self) -> str:
        return f"{self._id}{str(self._timer.Timestamp())[:-3]}"

    def _get_id_iso(self) -> str:
        now = self._timer.Now()
        return (
            f"{self._id}-"
            f"{now.year}{now.month:02}{now.day:02}."
            f"{now.hour:02}{now.minute:02}{now.second:02}."
            f"{now.microsecond:06}"
        )

    def _get_id_tag(self, tag: Optional[str]) -> str:
        now = self._timer.Now()
        tag = f".{tag}" if tag is not None else ""
        return (
            f"{self._id}"
            f"{now.year - 2000}{MONTH_MAP[now.month]}{now.day:02}"
            f"{now.hour:02}{now.minute:02}{now.second:02}"
            f"{now.microsecond:06}{tag}"
        )
