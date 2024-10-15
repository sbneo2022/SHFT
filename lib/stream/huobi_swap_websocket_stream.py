import base64
import copy
import hashlib
import hmac
import json
import os
import signal
import threading
import time
import urllib
import uuid
import zlib
from datetime import datetime
from decimal import Decimal
from typing import Optional, Tuple
import urllib.parse

import requests
import websocket
from apscheduler.schedulers.background import BackgroundScheduler
from websocket import WebSocketApp

from lib.constants import KEY, DB, QUEUE
from lib.database import AbstractDatabase
from lib.defaults import DEFAULT
from lib.exchange.huobi_swap_exchange import HuobiSwapExchange
from lib.factory import AbstractFactory
from lib.helpers import custom_dump
from lib.logger import AbstractLogger
from lib.ping import get_huobi_lag
from lib.stream import AbstractStream
from lib.supervisor import AbstractSupervisor
from lib.timer import AbstractTimer
from lib.vault import AbstractVault, VAULT

DEFAULT_WSS_URL = 'wss://api.hbdm.com'

DEFAULT_REST_URL = 'https://api.hbdm.com'

WS_LEVEL = 'market.{symbol}.depth.step0'
WS_BOOK = 'market.{symbol}.bbo'
WS_TRADES = 'market.{symbol}.trade.detail'
WS_KLINES = 'market.{symbol}.kline.1min'
WS_FUNDING_RATE = 'public.{symbol}.funding_rate'
WS_ORDER = 'orders_cross.{symbol}'

WS_POSITION = 'positions_cross.{symbol}'
WS_ACCOUNT = 'accounts_cross.{symbol}'


class HuobiSwapWebsocketStream(AbstractStream):
    def __init__(self, config: dict, supervisor: AbstractSupervisor, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, supervisor, factory, timer)

        self._exchange = HuobiSwapExchange(config, factory, timer)
        self._database: AbstractDatabase = factory.Database(config, factory=factory, timer=timer)
        self._logger: AbstractLogger = factory.Logger(config, factory=factory, timer=timer)
        self._vault: AbstractVault = factory.Vault(config, factory=factory, timer=timer)

        self._adjust = get_huobi_lag()

        self._symbol = self._construct_symbol()
        self._target_side = self._construct_side()
        self._target_side_coeff = +1 if self._target_side == KEY.LONG else -1

        # to make code general --> get target products independently
        self._target_symbol = config[KEY.SYMBOL]
        self._target_exchange = config[KEY.EXCHANGE]

        exchange_name = self._config.get(KEY.EXCHANGE, KEY.EXCHANGE_BINANCE_FUTURES)
        self._wss_url = self._config.get(exchange_name, {}).get(KEY.WSS_URL, None) or DEFAULT_WSS_URL

        self._key = self._vault.Get(VAULT.KEY)
        self._secret = self._vault.Get(VAULT.SECRET)

        self._contract_value = self._get_contract_value()

        self._wss: Optional[WebSocketApp] = None

        self._streams = dict()

        self._buffer = []

        self._lock = False

        self._previous_candle: Optional[dict] = None

        # Variables for "Data Update Watchdog"
        self._ask: Optional[float] = None
        self._bid: Optional[float] = None
        self._previous_ask: Optional[float] = None
        self._previous_bid: Optional[float] = None
        self._last_update_timestamp: Optional[int] = None

    def Run(self, start_timestamp: int = 0, end_timestamp: int = 0):
        scheduler = BackgroundScheduler()
        scheduler.add_job(self._flush, 'interval', seconds=1, max_instances=5)

        # Subscribe to public market data
        self._wss_market = websocket.WebSocketApp(self._wss_url + '/linear-swap-ws',
                                                  on_message=self._on_message_market,
                                                  on_open=self._on_open_market,
                                                  on_close=self._on_close)

        # Subscribe to private trade data and funding rate
        self._wss_notifications = websocket.WebSocketApp(self._wss_url + '/linear-swap-notification',
                                                  on_message=self._on_message_notifications,
                                                  on_open=self._on_open_notifications,
                                                  on_close=self._on_close)

        # Run websocket apps
        threading.Thread(target=self._wss_market.run_forever).start()
        threading.Thread(target=self._wss_notifications.run_forever).start()

        # Run scheduler
        scheduler.start()

        # Block thread
        while True:
            time.sleep(5)


    ##############################################################################
    #
    # Private Methods
    #
    ##############################################################################

    def _get_contract_value(self):
        r = requests.get(DEFAULT_REST_URL + '/linear-swap-api/v1/swap_contract_info',
                         params=dict(contract_code=self._symbol))

        for item in r.json()['data']:
            return Decimal(str(item['contract_size']))

    def _parse_symbol_side(self) -> Tuple[str, str]:
        symbol = self._config[KEY.SYMBOL].upper()

        left, right = symbol.split('USD')

        if '.' in right:
            suffix, side = right.split('.')
        else:
            suffix, side = right, ''

        side = KEY.LONG if 'LONG' in side else KEY.SHORT

        return f'{left}-USD{suffix}', side

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
            os.kill(os.getppid(), signal.SIGHUP)
            self._timer.Sleep(1)
            os._exit(-1)

        ########################################################################
        # Flush data to database
        ########################################################################
        if snapshot:
            self._database.writeEncoded(snapshot)

    def _inflate(self, data):
        return zlib.decompress(data, 16+zlib.MAX_WBITS)

    def _on_message_market(self, message):
        timestamp = self._timer.Timestamp() - self._adjust
        message = self._inflate(message).decode('utf-8')
        message = json.loads(message)

        if 'ch' in message:
            fn = self._streams.get(message['ch'], lambda x, y: print(message))
            fn(message, timestamp)

        elif 'ping' in message:
            self._wss_market.send(json.dumps({'pong': message['ping']}))

        else:
            print(message)

    def _on_message_notifications(self, message):
        timestamp = self._timer.Timestamp() - self._adjust
        message = self._inflate(message).decode('utf-8')
        message = json.loads(message)

        if 'topic' in message:
            fn = self._streams.get(message['topic'], lambda x, y: print(message))
            fn(message, timestamp)

        elif message.get('op', None) == 'ping':
            reply = json.dumps({'op': 'pong', 'ts': message['ts']})
            self._wss_notifications.send(reply)

        else:
            print(message)


    def _handle_funding_rate(self, message: dict, timestamp: int):
        for item in message['data']:
            data = self._database.Encode(
                fields={
                    KEY.FUNDING_RATE: float(item["funding_rate"]),
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

    def _handle_level(self, message: dict, timestamp: int):
        exchange_timestamp = message['ts'] * KEY.ONE_MS
        latency = timestamp - exchange_timestamp

        bids = message['tick']['bids'][0:5]
        asks = message['tick']['asks'][0:5]

        ask_5_qty = sum([Decimal(x) for _, x, in asks]) * self._contract_value

        bid_5_qty = sum([Decimal(x) for _, x, in bids]) * self._contract_value

        spread = Decimal(str(asks[0][0])) - Decimal(str(bids[0][0]))

        fields = {
            KEY.SPREAD: spread,
            KEY.ASK_5_QTY: ask_5_qty,
            KEY.BID_5_QTY: bid_5_qty,
        }

        for side, key in [('a', 'asks'), ('b', 'bids')]:
            for idx, (price, qty) in enumerate(message['tick'][key][:10]):
                fields[f'ob_{side}p_{idx}'] = float(price)
                fields[f'ob_{side}q_{idx}'] = float(qty) * float(self._contract_value)

        data = self._database.Encode(fields=fields, timestamp=exchange_timestamp)
        self._buffer.append(data)

        payload = {
            KEY.ASKS: [[Decimal(str(x[0])), Decimal(str(x[1])) * self._contract_value] for x in asks],
            KEY.BIDS: [[Decimal(str(x[0])), Decimal(str(x[1])) * self._contract_value] for x in bids]
        }

        self._supervisor.Queue.put({
            QUEUE.QUEUE: QUEUE.LEVEL,
            KEY.PAYLOAD: json.dumps(payload, default=custom_dump),
            KEY.SYMBOL: self._target_symbol,
            KEY.EXCHANGE: self._target_exchange,
            KEY.TIMESTAMP: exchange_timestamp,
            KEY.LATENCY: 0,
        })

    def _handle_trade(self, message: dict, timestamp: int):
        exchange_timestamp = message['ts'] * KEY.ONE_MS
        latency = timestamp - exchange_timestamp

        price, qty, side = 0.0, 0.0, ''
        for item in message['tick']['data']:
            price = item['price']
            qty += item['amount']
            side = item['direction']

        fields = {
            KEY.PRICE: price,
            KEY.QTY: qty,
            KEY.SIDE: side,
            DB.TRADE_LATENCY: latency,
        }

        data = self._database.Encode(fields, timestamp=exchange_timestamp)
        self._buffer.append(data)

        self._supervisor.Queue.put({
            QUEUE.QUEUE: QUEUE.TRADES,
            KEY.TIMESTAMP: exchange_timestamp,
            KEY.LATENCY: latency,
            KEY.PRICE: str(price),
            KEY.QTY: str(qty),
            KEY.SIDE: side,
            KEY.SYMBOL: self._target_symbol,
            KEY.EXCHANGE: self._target_exchange,
        })

    def _handle_book(self, message: dict, timestamp: int):
        exchange_timestamp = message['ts'] * KEY.ONE_MS
        latency = timestamp - exchange_timestamp

        fields = {
            KEY.BID_PRICE: float(message['tick']['bid'][0]),
            KEY.BID_QTY: float(message['tick']['bid'][1]),

            KEY.ASK_PRICE: float(message['tick']['ask'][0]),
            KEY.ASK_QTY: float(message['tick']['ask'][1]),

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
            KEY.BID_PRICE: str(fields[KEY.BID_PRICE]),
            KEY.BID_QTY: str(fields[KEY.BID_QTY]),
            KEY.ASK_PRICE: str(fields[KEY.ASK_PRICE]),
            KEY.ASK_QTY: str(fields[KEY.ASK_QTY]),
            KEY.SYMBOL: self._target_symbol,
            KEY.EXCHANGE: self._target_exchange,
        })

    def _handle_klines(self, message: dict, timestamp: int):
        _timestamp = message['ts']
        _open = float(message['tick'][KEY.OPEN])
        _high = float(message['tick'][KEY.HIGH])
        _low = float(message['tick'][KEY.LOW])
        _close = float(message['tick'][KEY.CLOSE])
        _volume = float(message['tick']['vol'])

        exchange_timestamp = int(_timestamp / 60_000) * 60_000 * KEY.ONE_MS

        if self._previous_candle is None:
            _finished = False
        elif _volume < self._previous_candle[KEY.VOLUME]:
            _finished = True
        else:
            _finished = False

        if self._previous_candle is not None:
            if _finished:
                fields = dict()
                for field in [KEY.OPEN, KEY.HIGH, KEY.LOW, KEY.CLOSE, KEY.VOLUME]:
                    fields[field] = self._previous_candle[field]

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

    def _handle_orders(self, message: dict, timestamp: int):
        print('_orders', message)

    def _handle_positions(self, message: dict, timestamp: int):
        print('_positions', message)

    def _handle_account(self, message: dict, timestamp: int):
        print('_account', message)


    def _generate_signature(self, host, method, params, request_path, secret_key):
        host_url = urllib.parse.urlparse(host).hostname or urllib.parse.urlparse(host).path
        host_url = host_url.lower()
        sorted_params = sorted(params.items(), key=lambda d: d[0], reverse=False)
        encode_params = urllib.parse.urlencode(sorted_params)
        print(encode_params)
        payload = [method, host_url, request_path, encode_params]
        payload = "\n".join(payload)
        payload = payload.encode(encoding="UTF8")
        secret_key = secret_key.encode(encoding="utf8")
        digest = hmac.new(secret_key, payload, digestmod=hashlib.sha256).digest()
        signature = base64.b64encode(digest)
        signature = signature.decode()
        return signature


    def _make_login(self, host, path):

        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        data = {
            "AccessKeyId": self._key,
            "SignatureMethod": "HmacSHA256",
            "SignatureVersion": "2",
            "Timestamp": timestamp
        }

        print(data)
        sign = self._generate_signature(host, "GET", data, path, self._secret)

        data["op"] = "auth"
        data["type"] = "api"
        data["Signature"] = sign
        msg_str = json.dumps(data)

        print(msg_str)

        self._wss_notifications.send(msg_str)


    def _make_subscriptions_notifications(self):
        for stream, fn in [
           (WS_FUNDING_RATE, self._handle_funding_rate),
           (WS_ORDER, self._handle_orders),
           (WS_POSITION, self._handle_positions),
            ]:
            sub = stream.format(symbol=self._symbol.lower())
            self._streams[sub] = fn
            message = json.dumps({'op': 'sub', 'topic': sub, 'cid': uuid.uuid4().__str__()})
            self._logger.info(f'Subscribe to {sub}')
            self._wss_notifications.send(message)

    def _make_subscriptions_market(self):
        for stream, fn in [
           (WS_LEVEL, self._handle_level),
           (WS_TRADES, self._handle_trade),
           (WS_BOOK, self._handle_book),
           (WS_KLINES, self._handle_klines),
            ]:

            sub = stream.format(symbol=self._symbol)
            self._streams[sub] = fn
            message = json.dumps({'sub': sub, 'id': uuid.uuid4().__str__()})
            self._logger.info(f'Subscribe to {sub}')
            self._wss_market.send(message)

    def _on_open_market(self):
        self._make_subscriptions_market()

    def _on_open_notifications(self):
        if all([self._key, self._secret]):
            self._make_login(host='api.hbdm.com', path='/linear-swap-notification')

        self._make_subscriptions_notifications()


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
