import copy
import json
import os
import signal
from decimal import Decimal
from typing import Optional

import websocket
from apscheduler.schedulers.background import BackgroundScheduler

from lib.constants import KEY, DB, STATUS, QUEUE
from lib.database import AbstractDatabase
from lib.defaults import DEFAULT
from lib.exchange.binance_futures_exchange import BinanceFuturesExchange
from lib.factory import AbstractFactory
from lib.helpers import custom_dump
from lib.logger import AbstractLogger
from lib.ping import get_binance_lag
from lib.supervisor import AbstractSupervisor
from lib.timer import AbstractTimer
from lib.stream import AbstractStream

WS_FUNDING_RATE = '@markPrice'
WS_BOOK = '@bookTicker'
WS_TRADES = '@aggTrade'
WS_LEVEL = '@depth10@100ms'
WS_KLINES = '@kline_1m'

DEFAULT_WSS_URL = 'wss://fstream.binance.com'

LISTEN_KEY_EXPIRATION_MINUTES = 50

LEVEL_UPDATE_TIME = 30 * KEY.ONE_SECOND

class BinanceFuturesWebsocketStream(AbstractStream):
    def __init__(self, config: dict, supervisor: AbstractSupervisor, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, supervisor, factory, timer)

        self._exchange = BinanceFuturesExchange(config, factory, timer)
        self._database: AbstractDatabase = factory.Database(config, factory=factory, timer=timer)
        self._logger: AbstractLogger = factory.Logger(config, factory=factory, timer=timer)

        self._adjust = get_binance_lag()

        self._symbol = self._config[KEY.SYMBOL]
        exchange_name = self._config.get(KEY.EXCHANGE, KEY.EXCHANGE_BINANCE_FUTURES)
        self._wss_url = self._config.get(exchange_name, {}).get(KEY.WSS_URL, None) or DEFAULT_WSS_URL

        # to make code general --> get target products independently
        self._target_symbol = config[KEY.SYMBOL]
        self._target_exchange = config[KEY.EXCHANGE]
        self._target_tags = {KEY.SYMBOL: self._target_symbol, KEY.EXCHANGE: self._target_exchange}

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
        scheduler.add_job(self._get_listen_key, 'interval', minutes=LISTEN_KEY_EXPIRATION_MINUTES)
        scheduler.add_job(self._flush, 'interval', seconds=1, max_instances=5)
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

    def _get_listen_key(self):
        listen_key =  self._exchange._request(
            method=KEY.POST,
            endpoint='/fapi/v1/listenKey',
            signed=True
        ).get('listenKey', None)

        self._logger.info('New Listen Key', event='LISTEN_KEY', listen_key=listen_key)

        return listen_key



    def _get_connection_string(self) -> str:
        self._streams[self._symbol.lower() + WS_TRADES] = self._handle_trades
        self._streams[self._symbol.lower() + WS_BOOK] = self._handle_book
        self._streams[self._symbol.lower() + WS_LEVEL] = self._handle_level
        self._streams[self._symbol.lower() + WS_KLINES] = self._handle_klines
        self._streams[self._symbol.lower() + WS_FUNDING_RATE] = self._handle_funding_rate

        listen_key = self._get_listen_key()
        if listen_key is not None:
            self._streams[listen_key] = self._handle_order

        return self._wss_url + '/stream?streams=' + '/'.join(self._streams.keys())

    def _handle_funding_rate(self, message: dict, timestamp: int):
        data = self._database.Encode(
            fields={
                KEY.MARK_PRICE: float(message["p"]),
                KEY.INDEX_PRICE: float(message["i"]),
                KEY.FUNDING_RATE: float(message["r"]),
            },
            timestamp=timestamp)
        self._buffer.append(data)

        self._supervisor.Queue.put({
            QUEUE.QUEUE: QUEUE.MESSAGE,
            KEY.PAYLOAD: json.dumps({
                KEY.TYPE: KEY.FUNDING_RATE,
                KEY.SYMBOL: self._target_symbol,
                KEY.EXCHANGE: self._target_exchange,
                KEY.FUNDING_RATE: float(message["r"]),
            }, default=custom_dump),
            KEY.TIMESTAMP: timestamp,
            KEY.LATENCY: 0,
        })

    def _handle_trades(self, message: dict, timestamp: int):
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
        exchange_timestamp = message["T"] * KEY.ONE_MS

        ask_5_qty = sum([float(x) for _, x in message['a'][:5]])
        ask_10_qty = ask_5_qty + sum([float(x) for _, x in message['a'][5:]])

        bid_5_qty = sum([float(x) for _, x in message['b'][:5]])
        bid_10_qty = bid_5_qty + sum([float(x) for _, x in message['b'][5:]])

        spread = Decimal(message['a'][0][0]) - Decimal(message['b'][0][0])

        fields = {
            KEY.SPREAD: float(spread),
            KEY.ASK_5_QTY: ask_5_qty,
            KEY.ASK_10_QTY: ask_10_qty,
            KEY.BID_5_QTY: bid_5_qty,
            KEY.BID_10_QTY: bid_10_qty,
        }

        for side in ['a', 'b']:
            for idx, (price, qty) in enumerate(message[side][:10]):
                fields[f'ob_{side}p_{idx}'] = float(price)
                fields[f'ob_{side}q_{idx}'] = float(qty)

        data = self._database.Encode(fields=fields, timestamp=exchange_timestamp)
        self._buffer.append(data)

        payload = {
            KEY.ASKS: [
                [Decimal(x[0]), Decimal(x[1])]
                for x in message['a'][:10]
            ],
            KEY.BIDS: [
                [Decimal(x[0]), Decimal(x[1])]
                for x in message['b'][:10]
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
        exchange_timestamp = message["T"] * KEY.ONE_MS
        latency = timestamp - exchange_timestamp

        fields = {
            KEY.BID_PRICE: float(message["b"]),
            KEY.BID_QTY: float(message["B"]),
            KEY.ASK_PRICE: float(message["a"]),
            KEY.ASK_QTY: float(message["A"]),
            DB.BOOK_LATENCY: int(latency),
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
            KEY.BID_PRICE: message["b"],
            KEY.BID_QTY: message["B"],
            KEY.ASK_PRICE: message["a"],
            KEY.ASK_QTY: message["A"],
            KEY.SYMBOL: self._target_symbol,
            KEY.EXCHANGE: self._target_exchange,
        })

    def _handle_order(self, message: dict, timestamp: int):
        exchange_timestamp = message["T"] * KEY.ONE_MS
        ts = self._timer.Timestamp()
        exchange_timestamp += ts - int(ts / KEY.ONE_MS) * KEY.ONE_MS

        if message['e'] == 'ORDER_TRADE_UPDATE':
            order = message['o']
            status = order['X']
            if status in [STATUS.FILLED, STATUS.PARTIALLY_FILLED]:
                if order['s'] == self._symbol:
                    pnl = float(order['rp'])
                    commission = float(order.get('n', '0'))
                    order_id = order['c']
                    average_price = float(order['ap'])
                    side = order['S']
                    qty = float(order['q'])

                    data = self._database.Encode(fields={
                        KEY.REALIZED_PNL: pnl,
                        KEY.COMMISSION: commission
                    }, timestamp=exchange_timestamp)
                    self._buffer.append(data)

                    self._logger.warning(f'{status} event registered', event=status, pnl=pnl, commission=commission,
                                         orderId=order_id, price=average_price, side=side, qty=qty, payload=message)

        elif message['e'] == 'ACCOUNT_UPDATE':
            self._logger.info(f'Account message: {message["a"]["m"]}')
            for item in message['a']['B']:
                currency = item['a'].lower()
                fields = {
                    f'{currency}_balance': Decimal(item['wb']),
                    f'{currency}_cross': Decimal(item['cw']),
                    f'{currency}_delta': Decimal(item['bc']),
                }
                print(f'ACCOUNT: {fields}')
                data = self._database.Encode(fields=fields, timestamp=exchange_timestamp)
                self._buffer.append(data)


            for item in message['a']['P']:
                if item['s'] == self._symbol:
                    portfolio = float(item['pa'])
                    entry = float(item['ep'])

                    fields = {KEY.ENTRY: entry, KEY.PORTFOLIO: portfolio}
                    data = self._database.Encode(fields=fields, timestamp=exchange_timestamp)
                    self._buffer.append(data)

                    self._supervisor.Queue.put({
                        QUEUE.QUEUE: QUEUE.ACCOUNT,
                        KEY.PRICE: item['ep'],
                        KEY.QTY: item['pa'],
                        KEY.SYMBOL: self._target_symbol,
                        KEY.EXCHANGE: self._target_exchange,
                    })

                    self._logger.warning(f'ACCOUNT UPDATE event registered', event='ACCOUNT',
                                      portfolio=portfolio, entry=entry, payload=item)

    def _on_message(self, message):
        timestamp = self._timer.Timestamp() - self._adjust
        try:
            message = json.loads(message)

            fn = self._streams.get(message['stream'], lambda x, y: print(x))
            fn(message['data'], timestamp)

        except Exception as e:
            self._logger.error(f'On message ', event='ERROR', error=e)

    def _handle_listen_key_expiration(self):
        self._listen_key = self._get_listen_key()
        self._logger.warning('Listen key renew', event='NEW_LISTEN_KEY', key=self._listen_key)

