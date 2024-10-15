import os
import signal
from decimal import Decimal
from typing import Optional

from bot import AbstractBot
from lib.async_ejector import FieldsAsyncEjector
from lib.constants import KEY, ORDER_TAG
from lib.database import AbstractDatabase
from lib.defaults import DEFAULT
from lib.exchange import get_exchange, Order
from lib.factory import AbstractFactory
from lib.helpers import sign
from lib.init import get_project_name
from lib.logger import AbstractLogger
from lib.producer import AbstractProducer
from lib.state import AbstractState
from lib.timer import AbstractTimer


class Delta(AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, factory, timer)

        ################################################################
        # Create some object using Factory
        ################################################################
        self._database: AbstractDatabase = factory.Database(config, factory, timer)
        self._logger: AbstractLogger = factory.Logger(config, factory, timer)
        self._state_repository: AbstractState = factory.State(config, factory, timer)
        self._exchange = get_exchange(config)(config, factory, timer)
        self._producer: AbstractProducer = factory.Producer(config, factory, timer)

        ################################################################
        # Load important values from Config
        ################################################################
        self._project_name = get_project_name(config)

        self._symbol = config[KEY.SYMBOL]

        # to make code general --> get target products independently
        self._target_symbol = config[KEY.SYMBOL]
        self._target_exchange = config[KEY.EXCHANGE]

        self._secondary_symbol = config[KEY.SECONDARY][KEY.SYMBOL]
        self._secondary_exchange = config[KEY.SECONDARY][KEY.EXCHANGE]

        self._interval = config[KEY.INTERVAL]
        self._qty = config[KEY.QTY]
        self._max_qty = config[KEY.MAX_QTY]
        self._threshold = config[KEY.THRESHOLD]
        self._close = config[KEY.CLOSE]
        self._direction = config[KEY.DIRECTION]
        self._side = config[KEY.SIDE]

        self._formula: str = config[KEY.FORMULA]
        self._ask_bid = 'ASK' in self._formula.upper()

        ################################################################
        # Internal variables to handle trades
        ################################################################
        self._last_order_timestamp: Optional[int] = None
        self._delta: Optional[Decimal] = None

        ################################################################
        # Internal variables to handle orderbook data
        ################################################################
        self._target_ask: Optional[Decimal] = None
        self._target_bid: Optional[Decimal] = None
        self._target_last_update_timestamp: Optional[int] = None

        self._secondary_ask: Optional[Decimal] = None
        self._secondary_bid: Optional[Decimal] = None
        self._secondary_last_update_timestamp: Optional[int] = None

        self._target_funding_rate: Optional[Decimal] = None
        self._secondary_funding_rate: Optional[Decimal] = None

        ################################################################
        # Clear Open Orders --> do it every start
        ################################################################
        self._exchange.Cancel()

        ################################################################
        # Get actual positions from Exchange
        ################################################################
        positions = self._exchange.getPosition()

        ################################################################
        # Build state from them: Empty/Inventory/From Repository
        ################################################################
        self._state = self._build_state_from_positions(positions)

        ################################################################
        # Save State to State Repository
        ################################################################
        self._state_repository.Push(self._state)

        FieldsAsyncEjector(self._database, self._timer, quoting=0).start()

    def onTime(self, timestamp: int):
        if self._state.get(KEY.MODE, None) != KEY.MODE_HALT \
                and self._delta is not None:
            FieldsAsyncEjector(self._database, self._timer,
                               quoting=1, delta=self._delta,
                               threshold=self._threshold, close_threshold=self._close).start()

        # No action until we have new ask/bid data
        if self._target_last_update_timestamp is None or self._secondary_last_update_timestamp is None:
            return

        def kill():
            os.kill(os.getpid(), signal.SIGHUP)
            self._timer.Sleep(1)
            os._exit(-1)

        if timestamp - self._target_last_update_timestamp > DEFAULT.NODATA_TIMEOUT:
            self._logger.error(f'Bot Target Watchdog: '
                               f'No new Ask/Bid data for {DEFAULT.NODATA_TIMEOUT/KEY.ONE_SECOND}s. Stop.')
            kill()

        if timestamp - self._secondary_last_update_timestamp > DEFAULT.NODATA_TIMEOUT:
            self._logger.error(f'Bot Secondary Watchdog: '
                               f'No new Ask/Bid data for {DEFAULT.NODATA_TIMEOUT/KEY.ONE_SECOND}s. Stop.')
            kill()

    def onMessage(self, message: dict,
                  timestamp: int, latency: int = 0):
        if message[KEY.TYPE] == KEY.FUNDING_RATE \
            and message[KEY.SYMBOL] == self._target_symbol \
            and message[KEY.EXCHANGE] == self._target_exchange:

            self._target_funding_rate = Decimal(message[KEY.FUNDING_RATE])

        elif message[KEY.TYPE] == KEY.FUNDING_RATE \
            and message[KEY.SYMBOL] == self._secondary_symbol \
            and message[KEY.EXCHANGE] == self._secondary_exchange:

            self._secondary_funding_rate = Decimal(message[KEY.FUNDING_RATE])

        else:
            return

    def onAccount(self, price: Decimal, qty: Decimal,
                  symbol: str, exchange: str,
                  timestamp: int, latency: int = 0):
        if not((symbol, exchange) == (self._target_symbol, self._target_exchange)):
            return

        pending = self._state.get(KEY.PENDING, 0)
        self._logger.warning(f'NEW INVENTORY: {qty}', qty=qty, pending=pending)

        delta = qty - self._state.get(KEY.QTY, 0)
        self._state[KEY.QTY] = qty

        if sign(delta) == sign(pending):
            _new_pending = max(0, abs(pending) - abs(delta))
            self._state[KEY.PENDING] = sign(pending) * _new_pending

        self._state_repository.Push(self._state)


    def _update_target_bbo(self, askPrice: Decimal, bidPrice: Decimal) -> bool:
        if self._target_ask != askPrice or self._target_bid != bidPrice:
            self._target_ask, self._target_bid = askPrice, bidPrice
            self._target_last_update_timestamp = self._timer.Timestamp()
            return True
        else:
            return False

    def _update_secondary_bbo(self, askPrice: Decimal, bidPrice: Decimal) -> bool:
        if self._secondary_ask != askPrice or self._secondary_bid != bidPrice:
            self._secondary_ask, self._secondary_bid = askPrice, bidPrice
            self._secondary_last_update_timestamp = self._timer.Timestamp()
            return True
        else:
            return False

    def _find_delta(self) -> Optional[Decimal]:
        if not all([
            self._target_funding_rate,
            self._target_ask,
            self._target_bid,
            self._secondary_funding_rate,
            self._secondary_ask,
            self._secondary_bid,
        ]):
            return

        if self._ask_bid:
            a = self._target_ask / (1 + self._target_funding_rate)
            b = self._secondary_bid / (1 + self._secondary_funding_rate)
        else:
            a = self._target_bid / (1 + self._target_funding_rate)
            b = self._secondary_ask / (1 + self._secondary_funding_rate)

        midpoint = sum([self._target_ask, self._target_bid, self._secondary_ask, self._secondary_bid]) / 4

        return Decimal(1e4) * (a - b) / midpoint

    def _increase_inventory(self):
        pending = self._state.get(KEY.PENDING, Decimal(0))
        inventory = self._state.get(KEY.QTY, Decimal(0))
        inventory += pending

        if self._last_order_timestamp is None or \
            self._last_order_timestamp + self._interval * KEY.ONE_SECOND < self._timer.Timestamp():

            if abs(inventory) < self._max_qty:
                new_qty = sign(self._delta) * sign(self._direction) * self._qty
                self._last_order_timestamp = self._timer.Timestamp()

                self._state[KEY.PENDING] = pending + new_qty
                self._state[KEY.DELTA] = self._delta

                self._logger.warning(f'Got Delta={self._delta}, Increase inventory',
                                     delta=self._delta, inventory=inventory, pending=pending)

                id = self._exchange.Post(Order(qty=new_qty, tag=ORDER_TAG.MARKET))

                self._logger.warning(
                    f'Hit Open Threshold. Send MARKET order for {new_qty}',
                    event='OPEN', orderId=id, pending=self._state[KEY.PENDING])

                self._state_repository.Push(self._state)

    def _clear_inventory(self):
        inventory_delta = self._state.get(KEY.DELTA, 0)
        if inventory_delta > 0 and self._delta < self._close \
            or inventory_delta < 0 and self._delta > -self._close:

            pending = self._state.get(KEY.PENDING, Decimal(0))
            inventory = self._state.get(KEY.QTY, Decimal(0))
            inventory += pending
            self._last_order_timestamp = None

            self._logger.warning(f'Got Delta={self._delta} < CLOSE delta, Liquidate inventory',
                                 delta=self._delta, inventory=inventory, pending=pending)

            new_qty = -1 * inventory
            self._state[KEY.PENDING] = pending + new_qty
            self._state[KEY.DELTA] = 0
            id = self._exchange.Post(Order(qty=new_qty, tag=ORDER_TAG.MARKET, liquidation=True))

            self._logger.warning(
                f'Hit Exit Threshold. Send MARKET order for {new_qty}',
                event='EXIT', orderId=id, pending=self._state[KEY.PENDING])

            self._state_repository.Push(self._state)

    def _check_should_we_open_position(self):
        if self._side == 0 or sign(self._side) == sign(self._delta):
            if abs(self._delta) > abs(self._threshold):
                self._increase_inventory()


    def onOrderbook(self, askPrice: Decimal, askQty: Decimal, bidPrice: Decimal, bidQty: Decimal,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):

        if self._state.get(KEY.MODE, None) == KEY.MODE_HALT:
            return

        if (symbol, exchange) == (self._target_symbol, self._target_exchange):
            new = self._update_target_bbo(askPrice, bidPrice)

        elif (symbol, exchange) == (self._secondary_symbol, self._secondary_exchange):
            new = self._update_secondary_bbo(askPrice, bidPrice)

        else:
            return

        if new:
            self._delta = self._find_delta()

            if self._delta is not None:
                self._check_should_we_open_position()

            inventory = self._state.get(KEY.QTY, Decimal(0))
            pending = self._state.get(KEY.PENDING, Decimal(0))
            qty = inventory + pending

            if abs(qty) > KEY.ED:
                self._clear_inventory()


    def Clean(self):
        self._state[KEY.MODE] = KEY.MODE_HALT

        self._logger.warning(f'Cleaning all open orders')

        # Cancel ALL open orders
        self._exchange.Cancel(wait=True)

        # Get list of current positions (we cant trust websocket data because
        # reason of this cleaning could be websocket connection error
        # Also we r quering current ask/bid
        positions = self._exchange.getPosition()

        if abs(positions.qty) > KEY.ED:
            self._logger.warning(f'Inventory found: {positions}. Clean', event='INVENTORY')

            self._exchange.Post(Order(
                qty=-1 * positions.qty,
                tag=ORDER_TAG.MARKET,
                liquidation=True,
            ), wait=True)

        FieldsAsyncEjector(self._database, self._timer, quoting=-1).start()
        self._timer.Sleep(1)

    def _build_state_from_positions(self, position: Order) -> dict:
        """
        Using current Qty/Price from exchange (open positions) and saved state buiuld initial state

        - If we have no inventory --> return empty State with mode EMPTY

        - If we have inventory -- return State in INVENTORY mode, with/without STOPLOSS price (from saved State)

        :param positions: dict with fields "positionAmt"  and "entryPrice" as str
        :return: dict
        """

        if abs(position.qty) < KEY.ED:  # never compare float values with zero, even Decimals as best-practice
            self._logger.warning(f'Portfolio empty --> continue with EMPTY State')
            state = self._build_empty_state()
        else:
            self._logger.warning(f'Current portfolio for {self._symbol}: {position.qty}@{position.price}')
            state = self._state_repository.Pop() or {}
            if state.get(KEY.QTY, None) == position.qty:
                if state.get(KEY.STATE, KEY.STATE_STOP_QUOTING) == KEY.STATE_STOP_QUOTING:
                    state[KEY.STATE] = KEY.STATE_NORMAL
                    self._logger.warning(f'Clear STOP_QUOTING state -> NORMAL')

                state[KEY.PENDING] = 0

                self._logger.warning(f'Continue with State', state=state)
            else:
                state = self._build_inventory_state()
                state[KEY.QTY] = position.qty
                state[KEY.PRICE] = position.price
                self._logger.warning(f'Qty not equal to Repository State. Continue with Inventory State', state=state)

        return state


    def _build_empty_state(self) -> dict:
        """
        :return: dict: New empty State with EMPTY Mode
        """
        return {KEY.MODE: KEY.MODE_EMPTY}

    def _build_inventory_state(self) -> dict:
        """

        :return: dict: New empty State with INVENTORY Mode
        """
        return {
            KEY.MODE: KEY.MODE_INVENTORY,
            KEY.STATE: KEY.STATE_NORMAL,
        }
