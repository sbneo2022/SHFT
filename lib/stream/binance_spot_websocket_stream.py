import copy
import json
import os
import signal
from decimal import Decimal
from pprint import pprint
from typing import Optional, Tuple, Union

import websocket
from apscheduler.schedulers.background import BackgroundScheduler

from lib.constants import KEY, DB, STATUS, QUEUE
from lib.database import AbstractDatabase
from lib.defaults import DEFAULT
from lib.exchange.binance_spot_exchange import BinanceSpotExchange
from lib.factory import AbstractFactory
from lib.helpers import custom_dump
from lib.logger import AbstractLogger
from lib.ping import get_binance_lag
from lib.supervisor import AbstractSupervisor
from lib.timer import AbstractTimer
from lib.stream import AbstractStream

WS_FUNDING_RATE = "@markPrice@1s"
WS_BOOK = "@bookTicker"
WS_TRADES = "@aggTrade"
WS_LEVEL = "@depth10@100ms"
WS_KLINES = "@kline_1m"

DEFAULT_WSS_URL = "wss://stream.binance.com:9443"

LISTEN_KEY_EXPIRATION_MINUTES = 50

LEVEL_UPDATE_TIME = 30 * KEY.ONE_SECOND


class BinanceSpotWebsocketStream(AbstractStream):
    def __init__(
        self,
        config: dict,
        supervisor: AbstractSupervisor,
        factory: AbstractFactory,
        timer: AbstractTimer,
    ):
        super().__init__(config, supervisor, factory, timer)

        self._exchange = BinanceSpotExchange(self._config, factory, timer)
        self._database: AbstractDatabase = factory.Database(
            self._config, factory=factory, timer=timer
        )
        self._logger: AbstractLogger = factory.Logger(
            self._config, factory=factory, timer=timer
        )

        self._adjust = get_binance_lag()

        if KEY.SYMBOLS in self._config.keys():
            self._symbols = self._config[KEY.SYMBOLS]
        else:
            self._symbols = self._config[KEY.SYMBOL]
        exchange_name = self._config.get(KEY.EXCHANGE, KEY.EXCHANGE_BINANCE_SPOT)
        self._wss_url = (
            self._config.get(exchange_name, {}).get(KEY.WSS_URL, None)
            or DEFAULT_WSS_URL
        )

        self._coins = {}
        self._currencies = {}

        for symbol in self._symbols:
            self._coins[symbol], self._currencies[symbol] = symbol, symbol
            for currency in ["USDT", "BNB", "BTC"]:
                if symbol.endswith(currency):
                    self._coins[symbol] = symbol[: -len(currency)]
                    self._currencies[symbol] = currency

        # to make code general --> get target products independently
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

        # Variables for pnl tracking
        self._current = self._exchange.getPosition()

    ##############################################################################
    #
    # Public Methods
    #
    ##############################################################################

    def Run(self, start_timestamp: int = 0, end_timestamp: int = 0):
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            self._get_listen_key, "interval", minutes=LISTEN_KEY_EXPIRATION_MINUTES,
        )
        scheduler.add_job(self._flush, "interval", seconds=1, max_instances=15)
        ws = websocket.WebSocketApp(
            self._get_connection_string(), on_message=self._on_message
        )
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
            self._logger.error(
                f"Websocket Watchdog: No ask/bid update for {DEFAULT.NODATA_TIMEOUT/KEY.ONE_SECOND}s. Stop."
            )
            os.kill(os.getppid(), signal.SIGHUP)
            self._timer.Sleep(1)
            os._exit(-1)

        ########################################################################
        # Flush data to database
        ########################################################################
        #if snapshot:
        #    self._database.writeEncoded(snapshot)

    def _get_listen_key(self):
        listen_key = self._exchange._request(
            method=KEY.POST, endpoint="/api/v3/userDataStream", signed=True
        ).get("listenKey", None)

        self._logger.info("New Listen Key", event="LISTEN_KEY", listen_key=listen_key)

        return listen_key

    def _get_connection_string(self) -> str:

        for symbol in self._symbols:
            self._streams[symbol.lower() + WS_TRADES] = self._handle_trades
            self._streams[symbol.lower() + WS_BOOK] = self._handle_book
            self._streams[symbol.lower() + WS_LEVEL] = self._handle_level
            self._streams[symbol.lower() + WS_KLINES] = self._handle_klines

        listen_key = self._get_listen_key()
        if listen_key is not None:
            self._streams[listen_key] = self._handle_order

        self._logger.warning(
            "Connecting to websocket: "
            + self._wss_url
            + "/stream?streams="
            + "/".join(self._streams.keys())
        )

        return self._wss_url + "/stream?streams=" + "/".join(self._streams.keys())

    def _handle_trades(self, message: dict, timestamp: int):
        exchange_timestamp = message["T"] * KEY.ONE_MS
        latency = timestamp - exchange_timestamp

        price, side = float(message["p"]), KEY.NONE

        if all([self._ask, self._bid]):
            if price <= self._bid:
                side = (KEY.SELL,)
            elif price <= self._ask:
                side = KEY.BUY

        fields = {
            KEY.PRICE: price,
            KEY.SYMBOL: message["s"],
            KEY.QTY: float(message["q"]),
            KEY.SIDE: side,
            "is_buyer_market_maker": message["m"],
            DB.TRADE_LATENCY: latency,
        }

        data = self._database.Encode(fields, timestamp=exchange_timestamp)
        self._buffer.append(data)

        self._supervisor.Queue.put(
            {
                QUEUE.QUEUE: QUEUE.TRADES,
                KEY.SYMBOL: message["s"],
                KEY.TIMESTAMP: exchange_timestamp,
                KEY.LATENCY: latency,
                KEY.PRICE: message["p"],
                KEY.QTY: message["q"],
                KEY.SIDE: side,
                KEY.EXCHANGE: self._target_exchange,
            }
        )

    def _handle_level(self, message: dict, timestamp: int):
        ask_5_qty = sum([float(x) for _, x in message["asks"][:5]])
        ask_10_qty = ask_5_qty + sum([float(x) for _, x in message["asks"][5:]])

        bid_5_qty = sum([float(x) for _, x in message["bids"][:5]])
        bid_10_qty = bid_5_qty + sum([float(x) for _, x in message["bids"][5:]])

        spread = Decimal(message["asks"][0][0]) - Decimal(message["bids"][0][0])

        fields = {
            KEY.SPREAD: float(spread),
            KEY.ASK_5_QTY: ask_5_qty,
            KEY.ASK_10_QTY: ask_10_qty,
            KEY.BID_5_QTY: bid_5_qty,
            KEY.BID_10_QTY: bid_10_qty,
        }

        for side, field in [("asks", "a"), ("bids", "b")]:
            for idx, (price, qty) in enumerate(message[side][:10]):
                fields[f"ob_{field}p_{idx}"] = float(price)
                fields[f"ob_{field}q_{idx}"] = float(qty)

        data = self._database.Encode(fields=fields, timestamp=timestamp)
        self._buffer.append(data)

        payload = {
            KEY.ASKS: [[Decimal(x[0]), Decimal(x[1])] for x in message["asks"][:10]],
            KEY.BIDS: [[Decimal(x[0]), Decimal(x[1])] for x in message["bids"][:10]],
        }

        self._supervisor.Queue.put(
            {
                QUEUE.QUEUE: QUEUE.LEVEL,
                KEY.SYMBOL: message["s"],
                KEY.PAYLOAD: json.dumps(payload, default=custom_dump),
                KEY.EXCHANGE: self._target_exchange,
                KEY.TIMESTAMP: timestamp,
                KEY.LATENCY: 0,
            }
        )

    def _handle_klines(self, message: dict, timestamp: int):
        finished = message["k"]["x"]
        timestamp = message["k"]["t"] * KEY.ONE_MS

        fields = dict()
        for field in [KEY.OPEN, KEY.HIGH, KEY.LOW, KEY.CLOSE, KEY.VOLUME]:
            fields[field] = float(message["k"][field[0]])

        if finished:
            data = self._database.Encode(fields, timestamp=timestamp)
            self._buffer.append(data)

        self._supervisor.Queue.put(
            {
                QUEUE.QUEUE: QUEUE.CANDLES,
                KEY.SYMBOL: message["s"],
                KEY.OPEN: message["k"]["o"],
                KEY.HIGH: message["k"]["h"],
                KEY.LOW: message["k"]["l"],
                KEY.CLOSE: message["k"]["c"],
                KEY.VOLUME: message["k"]["v"],
                KEY.FINISHED: finished,
                KEY.TIMESTAMP: timestamp,
                KEY.EXCHANGE: self._target_exchange,
            }
        )

    def _handle_book(self, message: dict, timestamp: int):
        exchange_timestamp = timestamp
        latency = 0

        fields = {
            KEY.BID_PRICE: float(message["b"]),
            KEY.SYMBOL: message["s"],
            KEY.BID_QTY: float(message["B"]),
            KEY.ASK_PRICE: float(message["a"]),
            KEY.ASK_QTY: float(message["A"]),
            DB.BOOK_LATENCY: latency,
        }

        # Save ask/bid price to "Data Update Watchdog"
        self._ask = fields[KEY.ASK_PRICE]
        self._bid = fields[KEY.BID_PRICE]

        data = self._database.Encode(fields, timestamp=exchange_timestamp)
        self._buffer.append(data)

        self._supervisor.Queue.put(
            {
                QUEUE.QUEUE: QUEUE.ORDERBOOK,
                KEY.SYMBOL: message["s"],
                KEY.TIMESTAMP: exchange_timestamp,
                KEY.LATENCY: latency,
                KEY.BID_PRICE: message["b"],
                KEY.BID_QTY: message["B"],
                KEY.ASK_PRICE: message["a"],
                KEY.ASK_QTY: message["A"],
                KEY.EXCHANGE: self._target_exchange,
            }
        )

    def _get_price_pnl(
        self, price: Decimal, qty: Decimal
    ) -> Tuple[Decimal, Union[Decimal, int]]:
        if qty < 0:
            _price, _pnl = price, qty * (self._current.price - price)
        else:
            px = price * qty + (self._current.price or 0) * (self._current.qty or 0)
            _price, _pnl = px / (qty + (self._current.qty or 0)), 0
            self._current.price = _price

        self._current.qty += qty
        return _price, Decimal(_pnl)

    def _handle_order(self, message: dict, timestamp: int):
        if message["e"] == "executionReport":
            exchange_timestamp = message["T"] * KEY.ONE_MS
            ts = self._timer.Timestamp()
            exchange_timestamp += ts - int(ts / KEY.ONE_MS) * KEY.ONE_MS

            if message["x"] == "TRADE":
                traded_qty = Decimal(message["l"])
                traded_price = Decimal(message["L"])

                side = message["S"]
                side_coeff = -1 if side == "SELL" else +1
                commission = Decimal(message["n"])

                price, pnl = self._get_price_pnl(traded_price, traded_qty * side_coeff)

                if message["N"] == self._coin:
                    self._current.qty -= commission
                    commission = commission * traded_price

                order_id = message["c"]

                data = self._database.Encode(
                    fields={
                        KEY.SYMBOL: message["s"],
                        KEY.REALIZED_PNL: pnl,
                        KEY.COMMISSION: commission,
                        KEY.ENTRY: self._current.price,
                        KEY.PORTFOLIO: self._current.qty,
                    },
                    timestamp=exchange_timestamp,
                )
                self._buffer.append(data)

                self._supervisor.Queue.put(
                    {
                        QUEUE.QUEUE: QUEUE.ACCOUNT,
                        KEY.SYMBOL: message["s"],
                        KEY.PRICE: self._current.price,
                        KEY.QTY: self._current.qty,
                        KEY.EXCHANGE: self._target_exchange,
                    }
                )

                self._logger.warning(
                    f'{message["X"]} event registered',
                    event=message["X"],
                    pnl=pnl,
                    commission=commission,
                    orderId=order_id,
                    traded_price=traded_price,
                    side=side,
                    qty=traded_qty,
                    payload=message,
                )

                self._logger.warning(
                    f"ACCOUNT UPDATE event registered",
                    event="ACCOUNT",
                    portfolio=self._current.qty,
                    entry=self._current.price,
                    payload=message,
                )

    def _on_message(self, message):
        timestamp = self._timer.Timestamp() - self._adjust
        try:
            message = json.loads(message)

            fn = self._streams.get(message["stream"], lambda x, y: print(x))
            fn(message["data"], timestamp)

        except Exception as e:
            self._logger.error(f"On message ", event="ERROR", error=e)

    def _handle_listen_key_expiration(self):
        self._listen_key = self._get_listen_key()
        self._logger.warning(
            "Listen key renew", event="NEW_LISTEN_KEY", key=self._listen_key
        )

