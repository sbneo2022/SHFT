import math
from collections import defaultdict
from decimal import Decimal
from pprint import pprint
from typing import Optional, List, Dict, Tuple, Union

from lib.constants import KEY, DB, STATUS, QUEUE
from lib.exchange import Order, Book
from lib.factory import AbstractFactory
from lib.history import AbstractHistory
from lib.logger import AbstractLogger
from lib.supervisor import AbstractSupervisor
from lib.timer import AbstractTimer
from lib.stream import AbstractStream


ORDER_LAG = 200 * KEY.ONE_MS

class VirtualStream(AbstractStream):
    def __init__(self, config: dict, supervisor: AbstractSupervisor, factory: AbstractFactory, timer: AbstractTimer):
        self._store: List[dict] = config[QUEUE.QUEUE]
        super().__init__(config, supervisor, factory, timer)

        self._logger: AbstractLogger = factory.Logger(config, factory, timer)

        self._history: AbstractHistory = factory.History(config, factory, timer)

        self._symbol, self._exchange = self._config[KEY.SYMBOL], self._config[KEY.EXCHANGE]

        self._open_orders: Dict[Tuple[str, str], dict] = defaultdict(lambda: {})

        self._portfolio: Dict[Tuple[str, str], Dict[str, Union[Decimal, int]]] = defaultdict(
            lambda: {
                KEY.QTY: 0,
                KEY.PRICE: 0,
            }
        )


    ##############################################################################
    #
    # Public Methods
    #
    ##############################################################################

    def Run(self, start_timestamp: int = 0, end_timestamp: int = 0):

        self._timer.setTimestamp(start_timestamp)

        block = 10 * KEY.ONE_MINUTE

        length = end_timestamp - start_timestamp

        n_of_blocks = math.ceil(length / block)

        for block_idx in range(n_of_blocks):
            _start = start_timestamp + block_idx * block
            _end = _start + block

            product = (self._symbol, self._exchange)
            data = self._history.getHistory(_start, _end,
                                            fields=[
                                                KEY.ASK_PRICE, KEY.ASK_QTY, KEY.BID_PRICE, KEY.BID_QTY, DB.BOOK_LATENCY,  # Order book
                                                KEY.PRICE, KEY.QTY, KEY.SIDE, DB.TRADE_LATENCY,  # Trades
                                                KEY.OPEN, KEY.HIGH, KEY.LOW, KEY.CLOSE, KEY.VOLUME, # Klines
                                            ])
            for item in data:

                items = []

                if self._store:
                    for payload in self._store:
                        id = payload[KEY.ID]

                        if payload[KEY.ACTION] == STATUS.NEW:
                            self._add_new_order(product, id, payload[KEY.PAYLOAD])

                        elif payload[KEY.ACTION] == STATUS.CANCELED:
                            self._cancel_open_order(product, id)

                    self._store.clear()

                    pprint(self._open_orders)


                if item[KEY.ASK_PRICE] is not None:
                    _timestamp = item[KEY.TIMESTAMP] + item[DB.BOOK_LATENCY]
                    if self._open_orders:
                        book = Book(
                            ask_price=item[KEY.ASK_PRICE],
                            ask_qty=item[KEY.ASK_QTY],
                            bid_price=item[KEY.ASK_PRICE],
                            bid_qty=item[KEY.ASK_QTY],
                        )

                        order_items = self._handle_open_orders_and_create_items(product, book, _timestamp)
                        items.extend(order_items)

                    self._timer.setTimestamp(_timestamp)

                    items.append({
                        QUEUE.QUEUE: QUEUE.ORDERBOOK,
                        KEY.ASK_PRICE: str(item[KEY.ASK_PRICE]),
                        KEY.ASK_QTY: str(item[KEY.ASK_QTY]),
                        KEY.BID_PRICE: str(item[KEY.BID_PRICE]),
                        KEY.BID_QTY: str(item[KEY.BID_QTY]),
                        KEY.TIMESTAMP: item[KEY.TIMESTAMP],
                        KEY.LATENCY: item[DB.BOOK_LATENCY],
                        KEY.SYMBOL: self._symbol,
                        KEY.EXCHANGE: self._exchange,
                    })

                if item[KEY.CLOSE] is not None:
                    self._timer.setTimestamp(item[KEY.TIMESTAMP])

                    items.append({
                        QUEUE.QUEUE: QUEUE.CANDLES,
                        KEY.OPEN: str(item[KEY.OPEN]),
                        KEY.HIGH: str(item[KEY.HIGH]),
                        KEY.LOW: str(item[KEY.LOW]),
                        KEY.CLOSE: str(item[KEY.CLOSE]),
                        KEY.VOLUME: str(item[KEY.VOLUME]),
                        KEY.SYMBOL: self._symbol,
                        KEY.EXCHANGE: self._exchange,
                        KEY.TIMESTAMP: item[KEY.TIMESTAMP],
                    })

                if item[KEY.PRICE] is not None:
                    self._timer.setTimestamp(item[KEY.TIMESTAMP] + item[DB.TRADE_LATENCY])

                    items.append({
                        QUEUE.QUEUE: QUEUE.TRADES,
                        KEY.PRICE: str(item[KEY.PRICE]),
                        KEY.QTY: str(item[KEY.QTY]),
                        KEY.SIDE: str(item[KEY.SIDE]),
                        KEY.TIMESTAMP: item[KEY.TIMESTAMP],
                        KEY.LATENCY: item[DB.TRADE_LATENCY],
                        KEY.SYMBOL: self._symbol,
                        KEY.EXCHANGE: self._exchange,
                    })

                for element in items:
                    yield element

    ##############################################################################
    #
    # Private Methods
    #
    ##############################################################################

    def _handle_open_orders_and_create_items(self, product: Tuple[str, str], book: Book, timestamp: int) -> List[dict]:
        delete_me = []
        return_me = []
        symbol, exchange = product  # decode Tuple to symbol and exchange

        for id in self._open_orders[product].keys():

            _timestamp = self._open_orders[product][id][KEY.TIMESTAMP]

            # We check orders only after ORDER_LAG timedelta
            if self._timer.Timestamp() > _timestamp + ORDER_LAG:

                _order: Order = self._open_orders[product][id][KEY.PAYLOAD]

                # Handle market orders
                if _order.price is None:

                    # Handle BUY orders using Best Ask price
                    if _order.qty > 0:
                        execution_price = book.ask_price

                        current_price = self._portfolio[product][KEY.PRICE]
                        current_qty = self._portfolio[product][KEY.QTY]

                        # simplest case: we are zero or positive and have to increase qty
                        # New average price will be: (price x qty + new_price x new_qty) / (qty + new_qty)
                        if current_qty >= 0:
                            new_price = (current_price * current_qty + execution_price * _order.qty) / (_order.qty + current_qty)
                        else:
                            increase = max(0, current_qty + _order.qty)
                            new_price = current_qty if increase == 0 else execution_price

                        self._portfolio[product][KEY.PRICE] = new_price
                        self._portfolio[product][KEY.QTY] = current_qty + _order.qty

                        # Create message
                        return_me.append({
                                QUEUE.QUEUE: QUEUE.ACCOUNT,
                                KEY.PRICE: str(self._portfolio[product][KEY.PRICE]),
                                KEY.QTY: str(self._portfolio[product][KEY.QTY]),
                                KEY.SYMBOL: symbol,
                                KEY.EXCHANGE: exchange,
                            })

                        # We will delete this order from open orders list
                        delete_me.append(id)

        for item in delete_me:
            del self._open_orders[product][item]

        return return_me

    def _add_new_order(self, product: Tuple[str, str],  id: str, order: Order):
        self._logger.info(f'New OPEN ORDER :: {id} :: {order}')
        self._open_orders[product][id] = {
            KEY.STATUS: STATUS.NEW,
            KEY.TIMESTAMP: self._timer.Timestamp(),
            KEY.PAYLOAD: order,
        }

    def _cancel_open_order(self, product: Tuple[str, str], id: str):
        if id in self._open_orders[product]:
            self._logger.info(f'CANCEL id ::: {id}')
            del self._open_orders[product][id]
        elif id is None:
            self._open_orders[product].clear()
