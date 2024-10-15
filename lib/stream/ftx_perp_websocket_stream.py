import copy
import hmac
import json
import os
import signal
import threading
import time
import zlib
from decimal import Decimal
from pprint import pprint
from typing import Optional, Tuple

import websocket
from apscheduler.schedulers.background import BackgroundScheduler
from websocket import WebSocketApp

from lib.constants import KEY, DB, QUEUE
from lib.database import AbstractDatabase
from lib.defaults import DEFAULT
from lib.exchange import Order
from lib.exchange.ftx_perp_exchange import FtxPerpExchange
from lib.factory import AbstractFactory
from lib.helpers import custom_dump, sign
from lib.logger import AbstractLogger
from lib.ping import get_ftx_lag
from lib.stream import AbstractStream
from lib.supervisor import AbstractSupervisor
from lib.timer import AbstractTimer
from lib.vault import AbstractVault, VAULT

DEFAULT_WSS_URL = 'wss://ftx.com/ws/'

DEFAULT_REST_URL = 'https://ftx.com'

WS_LEVEL = 'orderbook'
WS_BOOK = 'ticker'
WS_TRADES = 'trades'
WS_KLINES = 'market.{symbol}.kline.1min'

WS_ORDERS = 'orders'
WS_FILLS = 'fills'


class FtxPerpWebsocketStream(AbstractStream):
    def __init__(self, config: dict, supervisor: AbstractSupervisor, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, supervisor, factory, timer)


        self._exchange = FtxPerpExchange(config, factory, timer)
        self._database: AbstractDatabase = factory.Database(config, factory=factory, timer=timer)
        self._logger: AbstractLogger = factory.Logger(config, factory=factory, timer=timer)
        self._vault: AbstractVault = factory.Vault(config, factory=factory, timer=timer)

        self._adjust = get_ftx_lag()

        self._symbol = self._config[KEY.SYMBOL]
        self._symbol = self._construct_symbol()

        # to make code general --> get target products independently
        self._target_symbol = config[KEY.SYMBOL]
        self._target_exchange = config[KEY.EXCHANGE]
        self._target_tags = {KEY.SYMBOL: self._target_symbol, KEY.EXCHANGE: self._target_exchange}

        exchange_name = self._config.get(KEY.EXCHANGE, KEY.EXCHANGE_FTX_PERP)
        self._wss_url = self._config.get(exchange_name, {}).get(KEY.WSS_URL, None) or DEFAULT_WSS_URL

        self._key = self._vault.Get(VAULT.KEY)
        self._secret = self._vault.Get(VAULT.SECRET)

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

        # Variables for realizedPnl calculations
        self._position = self._exchange.getPosition()


    def Run(self, start_timestamp: int = 0, end_timestamp: int = 0):
        scheduler = BackgroundScheduler()
        scheduler.add_job(self._flush, 'interval', seconds=1, max_instances=5)
        scheduler.add_job(self._on_ping, 'interval', seconds=15, max_instances=1)

        # Subscribe to public market data
        self._wss = websocket.WebSocketApp(self._wss_url,
                                           on_message=self._on_message,
                                           on_open=self._on_open,
                                           on_close=self._on_close,
                                           on_pong=self._on_pong,
                                           )

        # Run websocket apps
        threading.Thread(target=self._wss.run_forever).start()

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
    """
    Return symbol name in FTX notation
    """
    def _construct_symbol(self) -> str:
        for _tail in ['USD', 'USDT']:
            if self._symbol.upper().endswith(_tail):
                return f'{self._symbol.upper()[:-len(_tail)]}-PERP'

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

    def _on_message(self, message):
        timestamp = self._timer.Timestamp() - self._adjust

        message = json.loads(message)

        fn = self._streams.get(message['channel'], lambda x, y: print('UNDEFINED', message))
        fn(message, timestamp)

    def _handle_funding_rate(self, message: dict, timestamp: int):
        return

    def _handle_level(self, message: dict, timestamp: int):
        return

    def _handle_trade(self, message: dict, timestamp: int):
        return

    def _handle_book(self, message: dict, timestamp: int):
        if 'data' not in message:
            return

        exchange_timestamp = message['data']['time']
        exchange_timestamp = int(exchange_timestamp * KEY.ONE_SECOND)
        latency = timestamp - exchange_timestamp

        fields = {
            KEY.BID_PRICE: float(message['data']['bid']),
            KEY.BID_QTY: float(message['data']['bidSize']),

            KEY.ASK_PRICE: float(message['data']['ask']),
            KEY.ASK_QTY: float(message['data']['askSize']),

            DB.BOOK_LATENCY: int(latency),
        }

        # Save ask/bid price to "Data Update Watchdog"
        self._ask = fields[KEY.ASK_PRICE]
        self._bid = fields[KEY.BID_PRICE]

        data = self._database.Encode(fields, tags=self._target_tags, timestamp=exchange_timestamp)
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
        return

    def _handle_orders(self, message: dict, timestamp: int):
        return

    def _handle_fills(self, message: dict, timestamp: int):
        # skip messages without 'data' key
        if 'data' not in message:
            return

        data = message['data']

        # We will process messages for current symbol only
        if data['future'] != self._symbol:
            return

        coeff = +1 if data['side'] == 'buy' else -1
        qty = Decimal(str(data['size'])) * coeff

        fee = data['fee']

        if abs(self._position.qty) < KEY.ED:
            pnl = Decimal('0.0')

        elif sign(self._position.qty) == sign(qty):
            pnl = Decimal('0.0')

        else:
            delta = min([abs(self._position.qty), abs(qty)])
            pnl = -1 * delta * coeff * (Decimal(str(data['price'])) - self._position.price)

        self._logger.warning(f'FILL event registered', event='FILLED', commission=fee,
                             price=data['price'], filled_qty=data['size'], realizedPnl=pnl,
                             side=(KEY.BUY if qty > 0 else KEY.SELL), qty=qty, payload=data)

        # Get account positions usign REST interface and publish message to queue
        success = False
        raw_positions = []
        for _ in range(5):
            try:
                raw_positions = self._exchange._get_raw_positions()
                success = True
            except:
                self._timer.Sleep(1)

        if not success:
            self._logger.error('FTX: get_raw_positions ERROR')

        for item in raw_positions:
            if item['future'] == self._symbol:
                entry = Decimal(str(item['recentAverageOpenPrice']))
                portfolio = Decimal(str(item['netSize']))
                self._position = Order(qty=portfolio, price=entry)

                data = self._database.Encode(
                    fields={
                        KEY.REALIZED_PNL: pnl,
                        KEY.COMMISSION: fee,
                        KEY.ENTRY: entry,
                        KEY.PORTFOLIO: portfolio
                    },
                    tags=self._target_tags,
                    timestamp=self._timer.Timestamp())

                self._buffer.append(data)

                self._supervisor.Queue.put({
                    QUEUE.QUEUE: QUEUE.ACCOUNT,
                    KEY.PRICE: str(item['recentAverageOpenPrice']),
                    KEY.QTY: str(item['netSize']),
                    KEY.SYMBOL: self._target_symbol,
                    KEY.EXCHANGE: self._target_exchange,
                })
                self._logger.warning(f'ACCOUNT UPDATE event registered', event='ACCOUNT',
                                     portfolio=item['netSize'], entry=item['recentAverageOpenPrice'], payload=item)

    def _make_login(self):
        if all([self._key, self._secret]):
            ts = int(time.time() * 1000)
            message = {
                'op': 'login',
                'args': {
                    'key': self._key,
                    'sign': hmac.new(
                        self._secret.encode(),
                        f'{ts}websocket_login'.encode(),
                        'sha256').hexdigest(),
                    'time': ts,
                }
            }
            message = json.dumps(message)
            self._wss.send(message)

    def _make_subscriptions(self):

        def subscribe(channel: str):
            subscription = {'channel': channel, 'market': self._symbol.lower()}
            message = json.dumps({'op': 'subscribe', **subscription})
            self._wss.send(message)

        self._make_login()
        for stream, fn in [
            (WS_BOOK, self._handle_book),
            (WS_LEVEL, self._handle_level),
            (WS_TRADES, self._handle_trade),
            (WS_ORDERS, self._handle_orders),
            (WS_FILLS, self._handle_fills),
        ]:
            subscribe(stream)
            self._streams[stream] = fn

    def _on_open(self, *args):
        self._make_subscriptions()


    def _on_close(self, *args):
        self._logger.error(
            f'Websocket Watchdog: Close event. Stop.')

        os.kill(os.getppid(), signal.SIGHUP)
        self._timer.Sleep(1)
        os._exit(-1)

    def _on_ping(self, *args):
        self._wss.send(json.dumps({'op': 'ping'}), opcode=websocket.ABNF.OPCODE_PING)

    def _on_pong(self, *args):
        print('Pong event', args)
