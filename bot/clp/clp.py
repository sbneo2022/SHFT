import copy
import math
import os
import signal
from collections import deque
from decimal import Decimal
from pathlib import Path
from typing import Optional

import typing

from bot import AbstractBot
from bot.helpers.iterative_messages import IterativeMessages
from bot.helpers.solve_stoploss import get_stoploss_price, get_zero_price, is_profit
from bot.clp.mode.handle_inventory_static import handle_inventory_static
from bot.clp.mode.handle_quote import handle_quote
from bot.helpers.on_account import onAccount
from bot.iea.modules.handle_spread import HandleSpread
from lib.async_ejector import FieldsAsyncEjector
from lib.constants import KEY, ORDER_TAG
from lib.database import AbstractDatabase
from lib.defaults import DEFAULT
from lib.exchange import get_exchange, Order
from lib.factory import AbstractFactory
from lib.init import get_project_name
from lib.logger import AbstractLogger
from lib.producer import AbstractProducer
from lib.state import AbstractState
from lib.timer import AbstractTimer

class CLP(HandleSpread, AbstractBot):

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

        # Get flag from config "do we handle quote mode, default is YES
        # Also make warning if status is NO
        self._handle_quote: bool = config.get(KEY.HANDLE_QUOTE, True)
        if not self._handle_quote:
            self._logger.warning('QUOTE mode is blocked')

        # Get flag from config "do we handle inventory mode, default is YES
        # Also make warning if status is NO
        self._handle_inventory: bool = config.get(KEY.HANDLE_INVENTORY, True)
        if not self._handle_inventory:
            self._logger.warning('INVENTORY mode is blocked')

        # Get Minimum Holding time from config
        self._hold = config[KEY.HOLD] * KEY.ONE_SECOND

        # Get fees value from config
        # TODO: get from Exchange API --> Make new method
        self._fee = Decimal(str(config.get(KEY.FEE, 0)))

        # Get STOPLOSS DISTANCE from config. Set as None if not found
        # TODO: Make DISTANCE some `fn` from matketdata
        self._distance = config.get(KEY.DISTANCE, None)
        self._distance = self._distance if self._distance is None else Decimal(str(self._distance))

        self._trailing_profit = config.get(KEY.TRAILING_PROFIT, DEFAULT.TRAILING_PROFIT)
        self._trailing_profit = Decimal(str(self._trailing_profit))

        self._stoploss_trailing_profit = config.get(KEY.STOPLOSS_TRAILING_PROFIT, DEFAULT.STOPLOSS_TRAILING_PROFIT)
        self._stoploss_trailing_profit = Decimal(str(self._stoploss_trailing_profit))

        self._first_liquidation = config.get(KEY.FIRST_LIQUIDATION, DEFAULT.FIRST_LIQUIDATION)
        self._first_liquidation = Decimal(str(self._first_liquidation))

        self._second_liquidation = config.get(KEY.SECOND_LIQUIDATION, DEFAULT.SECOND_LIQUIDATION)
        self._second_liquidation = Decimal(str(self._second_liquidation))

        self._high_ratio_spread_pause = KEY.ONE_SECOND * config[KEY.HIGH_RATIO_SPREAD_PAUSE]  # Pause when Spread/AvgSpread - 1 > max_ratio_spread
        self._high_api_pause = KEY.ONE_SECOND * config[KEY.HIGH_API_PAUSE]  # Pause when we are close to API limits
        self._high_losses_pause = KEY.ONE_SECOND * config[KEY.HIGH_LOSSES_PAUSE]  # Pause when we hit all Stoploss Levels
        self._high_atr_pause = KEY.ONE_SECOND * config.get(KEY.HIGH_ATR_PAUSE, 0)  # Pause when ATR value too high

        self._max_ratio_spread = config[KEY.MAX_RATIO_SPREAD]
        self._max_spread_count = int(config[KEY.MAX_SPREAD_COUNT])
        self._max_atr = config.get(KEY.MAX_ATR, None) or DEFAULT.MAX_ATR

        ################################################################
        # Internal variables to handle orderbook data
        ################################################################
        self._ask: Optional[Decimal] = None
        self._bid: Optional[Decimal] = None
        self._latency: Optional[int] = None
        self._last_update_timestamp: Optional[int] = None

        ################################################################
        # Flag to stop quoting. "None" means all ok,
        #  - int value means timestamp when we should check conditions again
        ################################################################
        self._stop_quoting: Optional[int] = None
        self._spread_buffer = deque(maxlen=self._max_spread_count)

        ################################################################
        # Build spread-related Coeffs on top of Config
        ################################################################
        self._config[KEY.SPREAD] = copy.deepcopy(self.spread)
        self._add_clp_fields_to_config()

        ################################################################
        # Find Max Available Allocation
        ################################################################
        self._all_levels_qty = 0
        for level in self._config[KEY.SPREAD].values():
            if KEY.QTY in level.keys():
                self._all_levels_qty += sum([Decimal(str(x)) for x in level[KEY.QTY]])
            else:
                self._all_levels_qty += level.get(KEY.MAX_QTY, None) or 0

        self._max_allocation_coeff: Optional[Decimal] = None

        ################################################################
        # Load Tick Size and Min Qty from Exchange
        ################################################################
        self._tick_size = self._exchange.getTick()

        self._min_qty_size = self._exchange.getMinQty()

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
        self._state = self._build_state_from_positions_legacy(positions)

        ################################################################
        # Save State to State Repository
        ################################################################
        self._state_repository.Push(self._state)

        ################################################################
        # Quoting Status. Default True. Used for "pause" quoting
        ################################################################
        self._quoting = True

        self._conditions = self._load_conditions(self._config.get(KEY.CONDITIONS, {}))

        self._iterative_messages = IterativeMessages()

        ################################################################
        # Various optional parameters through dict
        ################################################################
        self._optional = dict()


    ##############################################################################
    #
    # Public Methods
    #
    ##############################################################################

    def onTime(self, timestamp: int):
        super().onTime(timestamp)

        # Update current Inventory
        inventory = self._state.get(KEY.QTY, Decimal(0))

        if all([self._ask, self._bid]):
            midpoint = (self._ask + self._bid) / 2
            usd = inventory * midpoint
            inventory_max = (self._max_allocation_coeff or 0) * self._all_levels_qty * midpoint
            FieldsAsyncEjector(self._database, self._timer,
                               inventory=usd,
                               inventory_max=inventory_max,
                               ).start()

            alive_message = f'{self._project_name}:{self._symbol}:{self._config[KEY.EXCHANGE]}'
            self._producer.Send({
                KEY.ID: alive_message,
            }, channel=KEY.ALIVE)

        # if we have some non-zero inventory --> make regular public update
        self._producer.Send({
            KEY.TYPE: KEY.INVENTORY,
            KEY.PROJECT: self._project_name,
            KEY.QTY: inventory,
            KEY.MAX_QTY: self._all_levels_qty * (self._max_allocation_coeff or 0),
            KEY.TIMESTAMP: self._timer.Timestamp(),
        })

        # We could have some messages that we should repeat N times
        for item in self._iterative_messages.Get():
            self._producer.Send(item)

        # No action until we have new ask/bid data
        if self._last_update_timestamp is None:
            return

        if timestamp - self._last_update_timestamp > DEFAULT.NODATA_TIMEOUT:
            self._logger.error(f'Bot Watchdog: No new Ask/Bid data for {DEFAULT.NODATA_TIMEOUT/KEY.ONE_SECOND}s. Stop.')
            os.kill(os.getpid(), signal.SIGHUP)
            self._timer.Sleep(1)
            os._exit(-1)

        try:
            if self._exchange._portfolio != self._state.get(KEY.QTY, 0):
                print(f'IMBALANCE {self._exchange._portfolio} {self._state}')
        except Exception as e:
            print(e)


    def onAccount(self, price: Decimal, qty: Decimal,
                  symbol: str, exchange: str,
                  timestamp: int, latency: int = 0):
        onAccount(self, price, qty, timestamp, latency)

    def onOrderbook(self, askPrice: Decimal, askQty: Decimal, bidPrice: Decimal, bidQty: Decimal,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        super().onOrderbook(askPrice, askQty, bidPrice, bidQty, symbol, exchange, timestamp, latency)

        # We r receive events when price OR qty change, but lets make actions on PRICE change only
        if askPrice != self._ask or bidPrice != self._bid:
            self._ask, self._bid, self._latency = askPrice, bidPrice, latency
            self._last_update_timestamp = self._timer.Timestamp()
            self._handle_new_orderbook_event(askPrice, bidPrice, latency)

    def onStatus(self, orderId: str, status: str, price: Decimal, qty: Decimal, pct: Decimal,
                 symbol: str, exchange: str,
                 timestamp: int, latency: int = 0):
        super().onStatus(orderId, status, price, qty, pct, symbol, exchange, timestamp, latency)

        self._exchange.updateOrder(orderId, status, price, qty, pct)

    def Clean(self):
        """
        Cleaning procedure whe Bot Stop

        1. Make mode HALT (to make sure no new quotes async)

        2. Cancel all Open Order at Exchange (with "wait=True" key, NOT async)

        3. If current QTY (get from State) != 0 --> post Contitional Stoploss order with Stoploss price

        :return:
        """
        self._state[KEY.MODE] = KEY.MODE_HALT

        self._logger.warning(f'Cleaning all open orders')

        # Cancel ALL open orders
        self._exchange.Cancel(wait=True)

        # Get list of current positions (we cant trust websocket data because
        # reason of this cleaning could be websocket connection error
        # Also we r quering current ask/bid
        positions = self._exchange.getPosition()
        book = self._exchange.getBook()

        if abs(positions.qty) > KEY.ED:
            self._logger.warning(f'Inventory found: keep STOPLOSS order', event='INVENTORY')

            midpoint = (book.ask_price + book.bid_price) / 2
            zero_price = get_zero_price(self._exchange, positions.qty, positions.price, self._fee)
            if is_profit(positions.qty, midpoint, zero_price):
                distance = self._trailing_profit  # Static "take_profit" distance from config
            else:
                distance = self._distance  # ATR-based stoploss distance
            worst_stoploss_price = get_stoploss_price(self._exchange, positions.qty, midpoint, distance)

            stoploss_price = self._state.get(KEY.STOPLOSS, None)

            if stoploss_price is None or \
                positions.qty > 0 and stoploss_price < worst_stoploss_price or \
                positions.qty < 0 and stoploss_price > worst_stoploss_price:
                stoploss_price = worst_stoploss_price

            self._exchange.Post(Order(
                qty=-1 * positions.qty,
                price=stoploss_price,
                stopmarket=True,
                tag=ORDER_TAG.CONDITIONAL,
                liquidation=True,
            ), wait=True)

        FieldsAsyncEjector(self._database, self._timer, quoting=-1).start()
        self._timer.Sleep(1)

    ##############################################################################
    #
    # Private Methods
    #
    ##############################################################################

    @staticmethod
    def _get_callable_from_file(filename: str) -> typing.Callable:
        import importlib.util
        path = Path(__file__).parent / Path(filename)
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for key, value in module.__dict__.items():
            if key == path.stem:
                return value

    def _load_conditions(self, conditions: dict) -> list:
        result = []
        for item in conditions:
            result.append({
                KEY.FN: self._get_callable_from_file(item[KEY.FN]),
                KEY.PARAMS: copy.deepcopy(item)
            })
        return result

    def _handle_new_orderbook_event(self, askPrice, bidPrice, latency):
        if self._state[KEY.MODE] == KEY.MODE_HALT:
            pass

        elif self._state[KEY.MODE] == KEY.MODE_EMPTY:
            if self._handle_quote:
                handle_quote(self, askPrice, bidPrice, latency)

        elif self._state[KEY.MODE] == KEY.MODE_INVENTORY:
            if self._handle_quote:
                handle_quote(self, askPrice, bidPrice, latency)

            if self._handle_inventory:
                handle_inventory_static(self, askPrice, bidPrice)

    def _inside_holding_period(self, level: dict):
        """
        :param level: dictionary with given LEVEL parameters (Will use timestamp when we replace Quotes)
        :return: True if Holding Period (from config) not gones by, else False
        """
        return self._timer.Timestamp() - (level[KEY.WAS_UPDATE] or 0) < self._hold

    def _build_state_from_positions_legacy(self, position: Order) -> dict:
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

    def _add_clp_fields_to_config(self):
        for key, item in self._config[KEY.SPREAD].items():
            item[KEY.WAS_UPDATE] = None
            item[KEY.BUY] = None
            item[KEY.SELL] = None
            item[KEY.ORDER_ID] = []
            item[KEY.DISTANCE] = {KEY.BUY: None, KEY.SELL: None}

    def _build_spread(self, spread: dict) -> dict:
        """
        Caclulate constants for spread calculations and create dict for Distance
        :param spread: dict, parameters from Config
        :return: dict, same as "input" cut with additional fields
        """

        # Check spread levels and delete "empty"
        spread_levels = list(spread.keys())
        for spread_name in spread_levels:
            if spread[spread_name].get(KEY.VALUE, None) is None or \
               spread[spread_name].get(KEY.QTY, None) is None:
                self._logger.warning(f'Delete spread level "{spread_name}" because of no data')
                del spread[spread_name]

        for key, item in spread.items():
            item[KEY.WAS_UPDATE] = None
            item[KEY.BUY] = None
            item[KEY.SELL] = None
            item[KEY.ORDER_ID] = []
            item[KEY.DISTANCE] = {KEY.BUY: None, KEY.SELL: None}

            # For legacy config handle single "qty" correctly
            if not isinstance(item[KEY.QTY], list):
                item[KEY.QTY] = [item[KEY.QTY]]

            item[KEY.QTY] = [Decimal(str(x)) for x in item[KEY.QTY]]
            item[KEY.GAP] = Decimal(str(item.get(KEY.GAP, 0)))
            item[KEY.VALUE] = Decimal(str(item.get(KEY.VALUE)))
            item[KEY.MIN] = Decimal(str(item.get(KEY.MIN, 0)))

            self._logger.info(f'Build spread level "{key}"', value=item[KEY.VALUE], qty=item[KEY.QTY])
        return spread

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

    def _price_up(self, value: Decimal) -> Decimal:
        """
        Round price UP using exchange rules (tick size)
        :param value:
        :return:
        """
        return math.ceil(value / self._tick_size) * self._tick_size

    def _price_down(self, value: Decimal) -> Decimal:
        """
        Round price DOWN using exchange rules (tick size)
        :param value:
        :return:
        """
        return math.floor(value / self._tick_size) * self._tick_size
