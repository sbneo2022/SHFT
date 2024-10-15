import copy
import json
import time
from decimal import Decimal
from pprint import pprint
from typing import Optional, Tuple

from apscheduler.schedulers.background import BackgroundScheduler

from lib.constants import KEY, DB, QUEUE
from lib.database import AbstractDatabase
from lib.defaults import DEFAULT
from lib.exchange import Order, Book
from lib.exchange.perpetual_protocol_exchange import PerpetualProtocolExchange
from lib.factory import AbstractFactory
from lib.helpers import custom_dump, sign
from lib.logger import AbstractLogger
from lib.ping import get_ftx_lag
from lib.stream import AbstractStream
from lib.supervisor import AbstractSupervisor
from lib.timer import AbstractTimer
from lib.vault import AbstractVault, VAULT

TRANSACTION_FEE = Decimal('0.0010')

class PerpetualProtocolWebsocketStream(AbstractStream):
    def __init__(self, config: dict, supervisor: AbstractSupervisor, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, supervisor, factory, timer)

        self._exchange = PerpetualProtocolExchange(config, factory, timer)

        self._database: AbstractDatabase = factory.Database(config, factory=factory, timer=timer)
        self._logger: AbstractLogger = factory.Logger(config, factory=factory, timer=timer)
        self._vault: AbstractVault = factory.Vault(config, factory=factory, timer=timer)

        self._symbol = self._config[KEY.SYMBOL]
        self._symbol = self._construct_symbol()

        # to make code general --> get target products independently
        self._target_symbol = config[KEY.SYMBOL]
        self._target_exchange = config[KEY.EXCHANGE]
        self._target_tags = {KEY.SYMBOL: self._target_symbol, KEY.EXCHANGE: self._target_exchange}

        self._buffer = []

        # Variables for realizedPnl calculations
        self._current_position: Order = self._exchange.getPosition()

        self._current_book: Optional[Book] = None

    def Run(self, start_timestamp: int = 0, end_timestamp: int = 0):
        scheduler = BackgroundScheduler()
        scheduler.add_job(self._flush_and_update, 'interval', seconds=1, max_instances=5)

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
        for _tail in ['USD', 'USDT', 'USDC']:
            if self._symbol.upper().endswith(_tail):
                return f'{self._symbol.upper()[:-len(_tail)]}USDC'

    def _flush(self):
        ########################################################################
        # Lets make data snapshot first and clear old one
        ########################################################################
        snapshot = copy.deepcopy(self._buffer)
        self._buffer.clear()

        ########################################################################
        # Flush data to database
        ########################################################################
        if snapshot:
            self._database.writeEncoded(snapshot)

    def _update_book(self):
        self._current_book = self._exchange.getBook()
        timestamp = self._timer.Timestamp()

        fields = {
            KEY.BID_PRICE: self._current_book.ask_price,
            KEY.BID_QTY: 0.0,

            KEY.ASK_PRICE: self._current_book.bid_price,
            KEY.ASK_QTY: 0.0,

            DB.BOOK_LATENCY: 0,
        }

        data = self._database.Encode(fields, tags=self._target_tags, timestamp=timestamp)
        self._buffer.append(data)

        self._supervisor.Queue.put({
            QUEUE.QUEUE: QUEUE.ORDERBOOK,
            KEY.TIMESTAMP: timestamp,
            KEY.LATENCY: 0,
            KEY.BID_PRICE: str(fields[KEY.BID_PRICE]),
            KEY.BID_QTY: str(fields[KEY.BID_QTY]),
            KEY.ASK_PRICE: str(fields[KEY.ASK_PRICE]),
            KEY.ASK_QTY: str(fields[KEY.ASK_QTY]),
            KEY.SYMBOL: self._target_symbol,
            KEY.EXCHANGE: self._target_exchange,
        })

    def _update_positions(self):
        position = self._exchange.getPosition()

        # Case 1: no changes. Do nothing
        if position.qty == self._current_position.qty:
            return

        # Case 2: Some changes, but abs(position.qty) increase --> no PNL
        elif sign(position.qty) == sign(self._current_position.qty) \
                and abs(position.qty) > abs(self._current_position.qty):
            pnl = Decimal('0')
            delta = position.qty - self._current_position.qty
            commission = -1 * self._current_book.ask_price * abs(delta) * TRANSACTION_FEE
            entry_price = position.price
            qty = position.qty

        # Case 3: postition was 0 --> no PNL
        elif abs(self._current_position.qty) < KEY.ED:
            pnl = Decimal('0')
            commission = -1 * self._current_book.ask_price * abs(position.qty) * TRANSACTION_FEE
            entry_price = position.price
            qty = position.qty

        else:
            delta = position.qty - self._current_position.qty
            commission = -1 * self._current_book.ask_price * abs(delta) * TRANSACTION_FEE
            delta_for_pnl = min([abs(self._current_position.qty), abs(delta)])
            pnl = -1 * delta_for_pnl * sign(delta) * (self._current_book.ask_price - self._current_position.price)
            entry_price = position.price
            qty = position.qty

        self._current_position = position

        data = self._database.Encode(
            fields={
                KEY.REALIZED_PNL: pnl,
                KEY.COMMISSION: commission,
                KEY.ENTRY: entry_price,
                KEY.PORTFOLIO: qty
            },
            tags=self._target_tags,
            timestamp=self._timer.Timestamp())

        self._buffer.append(data)

        self._supervisor.Queue.put({
            QUEUE.QUEUE: QUEUE.ACCOUNT,
            KEY.PRICE: str(entry_price),
            KEY.QTY: str(qty),
            KEY.SYMBOL: self._target_symbol,
            KEY.EXCHANGE: self._target_exchange,
        })

        self._logger.warning(f'ACCOUNT UPDATE event registered', event='ACCOUNT',
                             portfolio=qty, entry=entry_price, pnl=pnl)


    def _update_funding_rate(self):
        timestamp = self._timer.Timestamp()

        funding_rate = self._exchange.getFundingRate()

        data = self._database.Encode(fields={KEY.FUNDING_RATE: funding_rate}, timestamp=timestamp)
        self._buffer.append(data)

        self._supervisor.Queue.put({
            QUEUE.QUEUE: QUEUE.MESSAGE,
            KEY.PAYLOAD: json.dumps({
                KEY.TYPE: KEY.FUNDING_RATE,
                KEY.SYMBOL: self._target_symbol,
                KEY.EXCHANGE: self._target_exchange,
                KEY.FUNDING_RATE: funding_rate,
            }, default=custom_dump),
            KEY.TIMESTAMP: timestamp,
            KEY.LATENCY: 0,
        })

    def _update(self):
        self._update_book()
        self._update_positions()
        self._update_funding_rate()

    def _flush_and_update(self):
        self._update()
        self._flush()