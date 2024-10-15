import copy
import json
import os
import signal
import time
from decimal import Decimal
from pprint import pprint
from typing import Optional, Tuple, Union

import hmac
import base64

import ciso8601
import requests
import websocket
import zlib
from apscheduler.schedulers.background import BackgroundScheduler
from websocket import WebSocketApp

from lib.constants import KEY, DB, STATUS, QUEUE
from lib.database import AbstractDatabase
from lib.defaults import DEFAULT
from lib.factory import AbstractFactory
from lib.helpers import custom_dump
from lib.logger import AbstractLogger
from lib.ping import get_okex_lag
from lib.supervisor import AbstractSupervisor
from lib.timer import AbstractTimer
from lib.stream import AbstractStream
from lib.vault import AbstractVault, VAULT

WS_FUNDING_RATE = 'spot/funding_rate'
WS_BOOK = 'spot/ticker'
WS_TRADES = 'spot/trade'
WS_LEVEL = 'spot/depth5'
WS_KLINES = 'spot/candle60s'
WS_POSITION = 'spot/position'
WS_ORDER = 'spot/order'
WS_ACCOUNT = 'spot/account'

DEFAULT_WSS_URL = 'wss://real.okex.com:8443/ws/v3'

DEFAULT_REST_URL = 'https://aws.okex.com'

LISTEN_KEY_EXPIRATION_MINUTES = 50

LEVEL_UPDATE_TIME = 30 * KEY.ONE_SECOND

class OkexSpotWebsocketStream(AbstractStream):
    def __init__(self, config: dict, supervisor: AbstractSupervisor, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, supervisor, factory, timer)

        self._database: AbstractDatabase = factory.Database(self._config, factory=factory, timer=timer)
        self._logger: AbstractLogger = factory.Logger(self._config, factory=factory, timer=timer)
        self._vault: AbstractVault = factory.Vault(self._config, factory=factory, timer=timer)

        self._adjust = get_okex_lag()

        self._symbol = self._construct_symbol()
        self._target_side = self._construct_side()
        self._target_side_coeff = +1 if self._target_side == KEY.LONG else -1

        # to make code general --> get target products independently
        self._target_symbol = config[KEY.SYMBOL]
        self._target_exchange = config[KEY.EXCHANGE]

        exchange_name = self._config.get(KEY.EXCHANGE, KEY.EXCHANGE_OKEX_PERP)
        self._wss_url = self._config.get(exchange_name, {}).get(KEY.WSS_URL, None) or DEFAULT_WSS_URL

        self._wss: Optional[WebSocketApp] = None

        self._key = self._vault.Get(VAULT.KEY)
        self._secret = self._vault.Get(VAULT.SECRET)
        self._passphrase = self._vault.Get(VAULT.PASSPHRASE)

        self._contract_value = self._get_contract_value()

        self._account: Optional[Decimal] = None

        self._streams = dict()

        self._buffer = []

        self._lock = False

        self._is_login = False  # This flag became True when login is successful

        self._total_avail_balance: Optional[Decimal] = None

        self._previous_candle: Optional[dict] = None

        self._previous_portfolio: Optional[Decimal] = None
        self._previous_entry: Optional[Decimal] = None

        # Variables for "Data Update Watchdog"
        self._ask: Optional[float] = None
        self._bid: Optional[float] = None
        self._previous_ask: Optional[float] = None
        self._previous_bid: Optional[float] = None
        self._last_update_timestamp: Optional[int] = None


    ##############################################################################
    #
    # Public Methods
    #
    ##############################################################################

    def Run(self, start_timestamp: int = 0, end_timestamp: int = 0):
        scheduler = BackgroundScheduler()
        scheduler.add_job(self._flush, 'interval', seconds=1, max_instances=5)
        self._wss = websocket.WebSocketApp(self._wss_url,
                                            on_message=self._on_message,
                                            on_open=self._on_open,
                                            on_close=self._on_close,
                                            on_ping=self._on_ping,
                                            on_pong=self._on_pong,
                                            )
        scheduler.start()
        self._wss.run_forever(ping_interval=20)

    ##############################################################################
    #
    # Private Methods
    #
    ##############################################################################
    def _get_contract_value(self) -> Union[int, Decimal]:
        r = requests.get(DEFAULT_REST_URL + '/api/swap/v3/instruments')

        for item in r.json():
            if item['instrument_id'] == self._symbol:
                return Decimal(item['contract_val'])


    def _parse_symbol_side(self) -> Tuple[str, str]:
        symbol = self._config[KEY.SYMBOL].upper()

        left, right = symbol.split('USD')

        if '.' in right:
            suffix, side = right.split('.')
        else:
            suffix, side = right, ''

        side = KEY.LONG if 'LONG' in side else KEY.SHORT

        return f'{left}-USD{suffix}-SWAP', side

    def _construct_symbol(self) -> str:
        symbol, _ = self._parse_symbol_side()
        return symbol

    def _construct_side(self) -> str:
        _, side = self._parse_symbol_side()
        return side

    def _flush(self):
        ########################################################################
        # Lets make data snapshot first and clear old one
        ########################################################################
        snapshot = copy.deepcopy(self._buffer)
        self._buffer.clear()

        ########################################################################
        # Data Update Watchdog
        ########################################################################
        if self._ask != self._previous_ask or self._bid != self._previous_bid:
            self._previous_ask = self._ask
            self._previous_bid = self._bid
            self._last_update_timestamp = self._timer.Timestamp()

        now = self._timer.Timestamp()
        if now - (self._last_update_timestamp or now) > DEFAULT.NODATA_TIMEOUT:
            self._logger.error(f'Websocket Watchdog: No ask/bid update for {DEFAULT.NODATA_TIMEOUT/KEY.ONE_SECOND}s. Stop.')
            self._on_close()

        ########################################################################
        # Flush data to database
        ########################################################################
        if snapshot:
            self._database.writeEncoded(snapshot)

    def _handle_funding_rate(self, message: dict, timestamp: int):
        for item in message:
            data = self._database.Encode(
                fields={
                    KEY.FUNDING_RATE: float(item["funding_rate"]),
                    KEY.ESTIMATED_RATE: float(item["estimated_rate"]),
                },
                timestamp=timestamp)
            self._buffer.append(data)

            self._supervisor.Queue.put({
                QUEUE.QUEUE: QUEUE.MESSAGE,
                KEY.PAYLOAD: json.dumps({
                    KEY.TYPE: KEY.FUNDING_RATE,
                    KEY.SYMBOL: self._target_symbol,
                    KEY.EXCHANGE: self._target_exchange,
                    KEY.FUNDING_RATE: float(item["funding_rate"]),
                }, default=custom_dump),
                KEY.TIMESTAMP: timestamp,
                KEY.LATENCY: 0,
            })



    def _handle_trades(self, message: dict, timestamp: int):

        for item in message:
            exchange_timestamp = ciso8601.parse_datetime(item['timestamp'])
            exchange_timestamp = int(exchange_timestamp.timestamp() * 1e3) * KEY.ONE_MS
            latency = timestamp - exchange_timestamp

            fields = {
                KEY.PRICE: float(item["price"]),
                KEY.QTY: Decimal(item["size"]) *  self._contract_value,
                KEY.SIDE: item["side"],
                DB.TRADE_LATENCY: latency,
            }

            data = self._database.Encode(fields, timestamp=exchange_timestamp)
            self._buffer.append(data)

            self._supervisor.Queue.put({
                QUEUE.QUEUE: QUEUE.TRADES,
                KEY.TIMESTAMP: exchange_timestamp,
                KEY.LATENCY: latency,
                KEY.PRICE: item["price"],
                KEY.QTY: item["size"],
                KEY.SIDE: item["side"],
                KEY.SYMBOL: self._target_symbol,
                KEY.EXCHANGE: self._target_exchange,
            })


    def _handle_level(self, message: dict, timestamp: int):
        for item in message:
            exchange_timestamp = ciso8601.parse_datetime(item['timestamp'])
            exchange_timestamp = int(exchange_timestamp.timestamp() * 1e3) * KEY.ONE_MS
            latency = timestamp - exchange_timestamp

            ask_5_qty = sum([Decimal(x) for _, x, _, _ in item['asks'][:5]]) * self._contract_value

            bid_5_qty = sum([Decimal(x) for _, x, _, _ in item['bids'][:5]]) * self._contract_value

            spread = Decimal(item['asks'][0][0]) - Decimal(item['bids'][0][0])

            fields = {
                KEY.SPREAD: float(spread),
                KEY.ASK_5_QTY: ask_5_qty,
                KEY.BID_5_QTY: bid_5_qty,
            }

            for side, key in [('a', 'asks'), ('b', 'bids')]:
                for idx, (price, qty, _, _) in enumerate(item[key][:5]):
                    fields[f'ob_{side}p_{idx}'] = float(price)
                    fields[f'ob_{side}q_{idx}'] = float(qty) * float(self._contract_value)

            data = self._database.Encode(fields=fields, timestamp=exchange_timestamp)
            self._buffer.append(data)

            payload = {
                KEY.ASKS: [[Decimal(x[0]), Decimal(x[1]) * self._contract_value] for x in item['asks']],
                KEY.BIDS: [[Decimal(x[0]), Decimal(x[1]) * self._contract_value] for x in item['bids']]
            }

            self._supervisor.Queue.put({
                QUEUE.QUEUE: QUEUE.LEVEL,
                KEY.PAYLOAD: json.dumps(payload, default=custom_dump),
                KEY.SYMBOL: self._target_symbol,
                KEY.EXCHANGE: self._target_exchange,
                KEY.TIMESTAMP: exchange_timestamp,
                KEY.LATENCY: 0,
            })

    def _handle_klines(self, message: dict, timestamp: int):
        for item in message:
            _timestamp, _open, _high, _low, _close, _, _volume = item['candle']

            exchange_timestamp = ciso8601.parse_datetime(_timestamp)
            exchange_timestamp = int(exchange_timestamp.timestamp() * 1e3) * KEY.ONE_MS

            if self._previous_candle is None:
                _finished = False
            elif exchange_timestamp > self._previous_candle[KEY.TIMESTAMP]:
                _finished = True
            else:
                _finished = False

            if self._previous_candle is not None:
                if _finished:
                    fields = dict()
                    for field in [KEY.OPEN, KEY.HIGH, KEY.LOW, KEY.CLOSE, KEY.VOLUME]:
                        fields[field] = float(self._previous_candle[field])

                    data = self._database.Encode(fields, timestamp=self._previous_candle[KEY.TIMESTAMP])
                    self._buffer.append(data)

                self._supervisor.Queue.put({
                    QUEUE.QUEUE: QUEUE.CANDLES,
                    KEY.OPEN: self._previous_candle[KEY.OPEN],
                    KEY.HIGH: self._previous_candle[KEY.HIGH],
                    KEY.LOW: self._previous_candle[KEY.LOW],
                    KEY.CLOSE: self._previous_candle[KEY.CLOSE],
                    KEY.VOLUME: self._previous_candle[KEY.VOLUME],
                    KEY.FINISHED: _finished,
                    KEY.TIMESTAMP: self._previous_candle[KEY.TIMESTAMP],
                    KEY.SYMBOL: self._target_symbol,
                    KEY.EXCHANGE: self._target_exchange,
                })

            self._previous_candle = {
                KEY.TIMESTAMP: exchange_timestamp,
                KEY.OPEN: _open,
                KEY.HIGH: _high,
                KEY.LOW: _low,
                KEY.CLOSE: _close,
                KEY.VOLUME: _volume,
            }


    def _handle_book(self, message: dict, timestamp: int):
        for item in message:
            exchange_timestamp = ciso8601.parse_datetime(item['timestamp'])
            exchange_timestamp = int(exchange_timestamp.timestamp() * 1e3) * KEY.ONE_MS
            latency = timestamp - exchange_timestamp

            fields = {
                KEY.BID_PRICE: float(item["best_bid"]),
                KEY.BID_QTY: Decimal(item["best_bid_size"]) * self._contract_value,
                KEY.ASK_PRICE: float(item["best_ask"]),
                KEY.ASK_QTY: Decimal(item["best_ask_size"]) * self._contract_value,
                DB.BOOK_LATENCY: latency,
            }

            # Save ask/bid price to "Data Update Watchdog"
            self._ask = fields[KEY.ASK_PRICE]
            self._bid = fields[KEY.BID_PRICE]

            data = self._database.Encode(fields, timestamp=exchange_timestamp)
            self._buffer.append(data)

            self._supervisor.Queue.put({
                QUEUE.QUEUE: QUEUE.ORDERBOOK,
                KEY.TIMESTAMP: exchange_timestamp,
                KEY.LATENCY: latency,
                KEY.BID_PRICE: item["best_bid"],
                KEY.BID_QTY: str(Decimal(item["best_bid_size"]) * self._contract_value),
                KEY.ASK_PRICE: item["best_ask"],
                KEY.ASK_QTY: str(Decimal(item["best_ask_size"]) * self._contract_value),
                KEY.SYMBOL: self._target_symbol,
                KEY.EXCHANGE: self._target_exchange,
            })

    def _handle_order(self, message: dict, timestamp: int):
        for item in message:
            exchange_timestamp = ciso8601.parse_datetime(item['timestamp'])
            exchange_timestamp = int(exchange_timestamp.timestamp() * 1e3) * KEY.ONE_MS
            latency = timestamp - exchange_timestamp

            STATE_MAP = {
                '-1': STATUS.CANCELED,
                '0': STATUS.OPEN,
                '1': STATUS.PARTIALLY_FILLED,
                '2': STATUS.FILLED,
            }

            status = STATE_MAP.get(item['state'], None)

            if status is not None:
                # Get `client_oid` as order_d
                order_id = item['client_oid']
                order_id = order_id if order_id != '' else item['order_id']

                # Get commission
                commission = float(item['fee'])

                # Get price
                price = float(item['price'])

                # decode side
                side = {'1': +1, '2': -1, '3': -1, '4': +1}[item['type']]
                qty = Decimal(item['size']) * self._contract_value
                filled_qty = Decimal(item['filled_qty']) * self._contract_value

                # publish to Hazelcast
                self._supervisor.Queue.put({
                    QUEUE.QUEUE: QUEUE.STATUS,
                    KEY.ORDER_ID: order_id,
                    KEY.STATUS: status,
                    KEY.PRICE: str(price),
                    KEY.QTY: str(side * qty),
                    KEY.PCT: str(filled_qty / qty),
                    KEY.SYMBOL: self._target_symbol,
                    KEY.EXCHANGE: self._target_exchange,
                })


                self._logger.warning(f'{status} event registered', event=status, commission=commission,
                                     orderId=order_id, price=price, filled_qty=filled_qty,
                                     side=(KEY.BUY if side > 0 else KEY.SELL), qty=qty, payload=item)

                # Write commission to db if commission not zero
                if abs(commission) > 0:
                    data = self._database.Encode(fields={
                        KEY.COMMISSION: commission
                    }, timestamp=exchange_timestamp)
                    self._buffer.append(data)

    def _handle_account(self, message: dict, timestamp: int):
        for item in message:
            exchange_timestamp = ciso8601.parse_datetime(item['timestamp'])
            exchange_timestamp = int(exchange_timestamp.timestamp() * 1e3) * KEY.ONE_MS
            latency = timestamp - exchange_timestamp

            if self._account is None:
                self._account = Decimal(item['equity'])

            pnl = Decimal(item['equity']) - self._account
            self._account = Decimal(item['equity'])

            data = self._database.Encode(fields={
                KEY.REALIZED_PNL: pnl
            }, timestamp=exchange_timestamp)
            self._buffer.append(data)

    def _handle_position(self, message: dict, timestamp: int):
        for item in message:
            exchange_timestamp = ciso8601.parse_datetime(item['timestamp'])
            exchange_timestamp = int(exchange_timestamp.timestamp() * 1e3) * KEY.ONE_MS
            latency = timestamp - exchange_timestamp

            holding = item.get('holding', [])

            biggest_side = sorted(holding, key=lambda x: Decimal(x['position']), reverse=True)[0]

            coeff = +1 if biggest_side['side'] == 'long' else -1

            portfolio = Decimal(biggest_side['position']) * self._contract_value * coeff

            entry = Decimal(biggest_side['avg_cost'])

            if portfolio != self._previous_portfolio or entry != self._previous_entry:
                self._previous_portfolio = portfolio
                self._previous_entry = entry

                data = self._database.Encode(
                    fields={KEY.ENTRY: entry, KEY.PORTFOLIO: portfolio},
                    timestamp=exchange_timestamp)
                self._buffer.append(data)

                self._supervisor.Queue.put({
                    QUEUE.QUEUE: QUEUE.ACCOUNT,
                    KEY.PRICE: entry,
                    KEY.QTY: portfolio,
                    KEY.SYMBOL: self._target_symbol,
                    KEY.EXCHANGE: self._target_exchange,
                })

                self._logger.warning(f'ACCOUNT UPDATE event registered', event='ACCOUNT',
                                     portfolio=portfolio, entry=entry, payload=holding)


    def _inflate(self, data):
        decompress = zlib.decompressobj(-zlib.MAX_WBITS)
        inflated = decompress.decompress(data)
        inflated += decompress.flush()
        return inflated


    def _on_login(self, message: dict, timestamp: int):
        success = message.get('success')
        if success:
            self._logger.warning(f'Successfully login to account', event='LOGIN')
            self._make_subscriptions()

    def _on_message(self, message):
        timestamp = self._timer.Timestamp() - self._adjust
        try:
            message = self._inflate(message).decode('utf-8')
            message = json.loads(message)

            if message.get('event', None) == 'login':
                stream = 'login'
                data = message
            else:
                stream = message.get('table', None)
                data = message.get('data', None)

            fn = self._streams.get(stream, lambda x, y: print(message))

            fn(data, timestamp)
        except Exception as e:
            self._logger.error(f'On message ', event='ERROR', error=e)

    def _sign(self, timestamp, method, endpoint) -> str:
        query = f'{timestamp}{method.upper()}{endpoint}'
        signature = hmac.new(bytes(self._secret, encoding='utf8'), bytes(query, encoding='utf-8'), digestmod='sha256').digest()
        return base64.b64encode(signature)

    def _make_login(self):
        # Make user login for websocket data
        timestamp = str(round(time.time() * 1000) / 1000)
        signature = self._sign(timestamp, 'GET', '/users/self/verify')
        args = [self._key, self._passphrase, timestamp, signature.decode("utf-8")]
        self._streams['login'] = self._on_login
        self._wss.send(json.dumps(dict(op='login', args=args)))

    def _make_subscriptions(self):
        subscriptions = []

        for stream, fn in [
            (WS_FUNDING_RATE, self._handle_funding_rate),
            (WS_BOOK, self._handle_book),
            (WS_KLINES, self._handle_klines),
            (WS_LEVEL, self._handle_level),
            (WS_TRADES, self._handle_trades),
            (WS_POSITION, self._handle_position),
            (WS_ORDER, self._handle_order),
            (WS_ACCOUNT, self._handle_account),
        ]:
            self._streams[stream] = fn
            subscriptions.append(f'{stream}:{self._symbol}')

        self._wss.send(json.dumps(dict(op='subscribe', args=subscriptions)))

    def _on_open(self):
        if all([self._key, self._secret, self._passphrase]):
            self._make_login()
        else:
            self._make_subscriptions()

    def _on_close(self):
        self._logger.error(
            f'Websocket Watchdog: Close event. Stop.')

        os.kill(os.getppid(), signal.SIGHUP)
        self._timer.Sleep(1)
        os._exit(-1)

    def _on_ping(self, ws):
        print('Ping event', self, ws)

    def _on_pong(self, ws):
        print('Pong event', self, ws)
