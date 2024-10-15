import copy
import json
import os
import signal
from decimal import Decimal
from pprint import pprint
from typing import Optional

import requests
import websocket
from apscheduler.schedulers.background import BackgroundScheduler

from lib.constants import KEY, DB, STATUS, QUEUE
from lib.database import AbstractDatabase
from lib.defaults import DEFAULT
from lib.exchange.binance_futures_exchange import BinanceFuturesExchange
from lib.factory import AbstractFactory
from lib.helpers import custom_dump
from lib.logger import AbstractLogger
from lib.ping import get_binance_lag, get_binance_dex_lag
from lib.supervisor import AbstractSupervisor
from lib.timer import AbstractTimer
from lib.stream import AbstractStream

WS_BOOK = '@ticker'
WS_ALL_BOOK = '$all@allTickers'
WS_TRADES = '@trades'
WS_LEVEL = '@marketDepth'
WS_KLINES = '@kline_1m'

ALL_SYMBOL_ABBREVIATION = '*'


DEFAULT_WSS_URL = 'wss://dex.binance.org/api'
DEX = 'https://dex.binance.org'

LISTEN_KEY_EXPIRATION_MINUTES = 50

LEVEL_UPDATE_TIME = 30 * KEY.ONE_SECOND

class BinanceDexWebsocketStream(AbstractStream):
    def __init__(self, config: dict, supervisor: AbstractSupervisor, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, supervisor, factory, timer)

        # self._exchange = BinanceFuturesExchange(config, factory, timer)
        self._database: AbstractDatabase = factory.Database(config, factory=factory, timer=timer)
        self._logger: AbstractLogger = factory.Logger(config, factory=factory, timer=timer)

        self._adjust = get_binance_dex_lag()

        self._symbol = self._symbol = self._construct_symbol()
        exchange_name = self._config.get(KEY.EXCHANGE, KEY.EXCHANGE_BINANCE_FUTURES)
        self._wss_url = self._config.get(exchange_name, {}).get(KEY.WSS_URL, None) or DEFAULT_WSS_URL

        # to make code general --> get target products independently
        self._target_symbol = config[KEY.SYMBOL]
        self._target_exchange = config[KEY.EXCHANGE]

        self._streams = dict()

        self._buffer = []

        self._lock = False

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
        print(self._get_connection_string())
        ws = websocket.WebSocketApp(self._get_connection_string(), on_message=self._on_message)
        scheduler.start()
        ws.run_forever()

    ##############################################################################
    #
    # Private Methods
    #
    ##############################################################################

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

    def _get_connection_string(self) -> str:
        #  Set correct orderbook handler with "all symbols feature"
        if self._symbol == ALL_SYMBOL_ABBREVIATION:
            self._streams[WS_ALL_BOOK] = self._handle_book
        else:
            self._streams[self._symbol.upper() + WS_BOOK] = self._handle_book

            # Set correct Trades handler
            self._streams[self._symbol.upper() + WS_TRADES] = self._handle_trades

            # Set correct Level5(N) handler
            self._streams[self._symbol.upper() + WS_LEVEL] = self._handle_level

            # Set correct Candles (Klines) handler
            self._streams[self._symbol.upper() + WS_KLINES] = self._handle_klines

        # TODO: Add handler for USER data (Account)

        # Constuct websocket string
        return self._wss_url + '/stream?streams=' + '/'.join(self._streams.keys())


    def _handle_trades(self, message: dict, timestamp: int):
        print('TRADES', message)
        return
        exchange_timestamp = message["T"] * KEY.ONE_MS
        latency = timestamp - exchange_timestamp


        price, side = float(message["p"]), KEY.NONE

        if all([self._ask, self._bid]):
            if price <= self._bid:
                side = KEY.SELL,
            elif price <= self._ask:
                side = KEY.BUY

        fields = {
            KEY.PRICE: price,
            KEY.QTY: float(message["q"]),
            KEY.SIDE: side,
            'is_buyer_market_maker': message["m"],
            DB.TRADE_LATENCY: latency,
        }

        data = self._database.Encode(fields, timestamp=exchange_timestamp)
        self._buffer.append(data)

        self._supervisor.Queue.put({
            QUEUE.QUEUE: QUEUE.TRADES,
            KEY.TIMESTAMP: exchange_timestamp,
            KEY.LATENCY: latency,
            KEY.PRICE: message["p"],
            KEY.QTY: message["q"],
            KEY.SIDE: side,
            KEY.SYMBOL: self._target_symbol,
            KEY.EXCHANGE: self._target_exchange,
        })

    def _handle_level(self, message: dict, timestamp: int):
        exchange_timestamp = message["lastUpdateId"] * KEY.ONE_SECOND

        ask_5_qty = sum([float(x) for _, x in message['asks'][:5]])
        ask_10_qty = ask_5_qty + sum([float(x) for _, x in message['asks'][5:]])

        bid_5_qty = sum([float(x) for _, x in message['bids'][:5]])
        bid_10_qty = bid_5_qty + sum([float(x) for _, x in message['bids'][5:]])

        spread = Decimal(message['asks'][0][0]) - Decimal(message['bids'][0][0])

        fields = {
            KEY.SPREAD: float(spread),
            KEY.ASK_5_QTY: ask_5_qty,
            KEY.ASK_10_QTY: ask_10_qty,
            KEY.BID_5_QTY: bid_5_qty,
            KEY.BID_10_QTY: bid_10_qty,
        }

        for side in ['asks', 'bids']:
            for idx, (price, qty) in enumerate(message[side][:10]):
                fields[f'ob_{side[0]}p_{idx}'] = float(price)
                fields[f'ob_{side[0]}q_{idx}'] = float(qty)

        data = self._database.Encode(fields=fields, timestamp=exchange_timestamp)
        self._buffer.append(data)

        payload = {
            KEY.ASKS: [
                [Decimal(x[0]), Decimal(x[1])]
                for x in message['asks'][:10]
            ],
            KEY.BIDS: [
                [Decimal(x[0]), Decimal(x[1])]
                for x in message['bids'][:10]
            ]
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
        print(message)
        return
        finished = message['k']['x']
        timestamp = message['k']['t'] * KEY.ONE_MS

        fields = dict()
        for field in [KEY.OPEN, KEY.HIGH, KEY.LOW, KEY.CLOSE, KEY.VOLUME]:
            fields[field] = float(message['k'][field[0]])

        if finished:
            data = self._database.Encode(fields, timestamp=timestamp)
            self._buffer.append(data)

        self._supervisor.Queue.put({
            QUEUE.QUEUE: QUEUE.CANDLES,
            KEY.OPEN: message['k']['o'],
            KEY.HIGH: message['k']['h'],
            KEY.LOW: message['k']['l'],
            KEY.CLOSE: message['k']['c'],
            KEY.VOLUME: message['k']['v'],
            KEY.FINISHED: finished,
            KEY.TIMESTAMP: timestamp,
            KEY.SYMBOL: self._target_symbol,
            KEY.EXCHANGE: self._target_exchange,
        })

    def _handle_book(self, message: dict, timestamp: int):
        exchange_timestamp = message["E"] * KEY.ONE_SECOND
        latency = timestamp - exchange_timestamp

        # Filter ZERO products
        ask_price = Decimal(message["a"])
        bid_price = Decimal(message["b"])

        if ask_price < KEY.ED or bid_price < KEY.ED:
            return

        # Note: we are not writing ALL symbols to database
        # because it could be really a lot of data
        # We can log values we need on BOT level

        if self._symbol != ALL_SYMBOL_ABBREVIATION:
            fields = {
                KEY.BID_PRICE: float(bid_price),
                KEY.BID_QTY: float(message["B"]),
                KEY.ASK_PRICE: float(ask_price),
                KEY.ASK_QTY: float(message["A"]),
                DB.BOOK_LATENCY: latency,
            }

            data = self._database.Encode(fields, timestamp=exchange_timestamp)
            self._buffer.append(data)

        # Save ask/bid price to "Data Update Watchdog"
        self._ask = ask_price
        self._bid = bid_price

        if self._symbol == ALL_SYMBOL_ABBREVIATION:
            left, right = message['s'].split('_')
            symbol = left.split('-')[0] + right.split('-')[0]
        else:
            symbol = self._target_symbol

        self._supervisor.Queue.put({
            QUEUE.QUEUE: QUEUE.ORDERBOOK,
            KEY.TIMESTAMP: exchange_timestamp,
            KEY.LATENCY: latency,
            KEY.BID_PRICE: message["b"],
            KEY.BID_QTY: message["B"],
            KEY.ASK_PRICE: message["a"],
            KEY.ASK_QTY: message["A"],
            KEY.SYMBOL: symbol,
            KEY.EXCHANGE: self._target_exchange,
        })

    def _on_message(self, message):
        timestamp = self._timer.Timestamp() - self._adjust
        try:
            message = json.loads(message)

            if self._symbol != ALL_SYMBOL_ABBREVIATION:
                fn = self._streams.get(self._symbol.upper() + '@' + message['stream'], lambda x, y: print(x))
                fn(message['data'], timestamp)

            # Note: For ALL SYMBOLS we are handling only Orderbook now
            elif message['stream'] == 'allTickers':
                fn = self._handle_book
                for item in message['data']:
                    fn(item, timestamp)

        except Exception as e:
            self._logger.error(f'On message ', event='ERROR', error=e)

    def _construct_symbol(self) -> str:
        symbol: str = self._config[KEY.SYMBOL]

        dex_products = requests.get(DEX + '/api/v1/ticker/24hr').json()

        for item in dex_products:
            base = item['baseAssetName'].split('-')[0]
            quote = item['quoteAssetName'].split('-')[0]
            maybe_symbol = base + quote

            if maybe_symbol == symbol:
                return item['symbol']

        return symbol