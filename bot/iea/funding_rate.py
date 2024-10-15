import os
import signal
from collections import deque, defaultdict
from decimal import Decimal
from typing import Optional, List, Dict, Union

from bot import AbstractBot
from bot.iea.modules.handle_buffer import HandleBuffer
from bot.iea.modules.handle_clean_cancel import HandleCleanCancel
from bot.iea.modules.handle_exchange import HandleExchange
from bot.iea.modules.handle_hedge_exchange import HandleHedgeExchange
from bot.iea.modules.handle_qty_limit import HandleQtyLimit
from bot.iea.modules.handle_qty_market import HandleQtyMarket
from bot.iea.modules.handle_state import HandleState
from bot.iea.modules.handle_warming_up import HandleWarmingUp
from bot.iea.modules.handle_watchdog import HandleWatchdog
from lib.constants import KEY
from lib.defaults import DEFAULT
from lib.exchange import Order, Book
from lib.factory import AbstractFactory
from lib.helpers import sign
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer

LOG_PNL_EVERY = 1 * KEY.ONE_MINUTE

WAIT_BEFORE_HOLD_AFTER_TASK_DONE = 1 * KEY.ONE_MINUTE

FULLY_HEDGED_THRESHOLD = 0.0001  # 1bps

AVAILABLE_ACTIONS = [KEY.DEFAULT, KEY.SCALE, KEY.LIQUIDATION, KEY.SINGLE]

class FundingRate(
    HandleQtyMarket,
    HandleQtyLimit,
    HandleWarmingUp,
    HandleWatchdog,
    HandleCleanCancel,
    HandleState,
    HandleHedgeExchange,
    HandleExchange,
    # HandleAlive,
    HandleBuffer,
    AbstractBot
):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)


        self._logger: AbstractLogger = factory.Logger(config, factory, timer)

        ###########################################
        # Load REQUIRED config parameters
        ###########################################

        def _get_decimal(key: str, default=None) -> Decimal:
            value = self._config.get(key, default)
            self._logger.info(f'SET "{key}"={value}')
            return None if value is None else Decimal(str(value))

        self._max_inventory = _get_decimal(KEY.MAX_INVENTORY)

        self._usd = _get_decimal(KEY.USD)

        self._threshold = _get_decimal(KEY.THRESHOLD)

        self._action = self._config.get(KEY.ACTION, KEY.DEFAULT)
        if self._action not in AVAILABLE_ACTIONS:
            self._logger.error(f'Action "{self._action}" is not available ({AVAILABLE_ACTIONS}). Stop')
            exit(0)
        else:
            self._logger.info(f'Action: {self._action.upper()}')

        ###########################################
        # Load OPTIONAL config parameters
        ###########################################


        ###########################################
        # Create internal variables
        ###########################################
        self._next_pnl_log = self._timer.Timestamp() + LOG_PNL_EVERY

        self._is_started = False

        self._top_book: Dict[str, Book] = defaultdict(lambda: Book(Decimal(0),Decimal(0),Decimal(0),Decimal(0)))

        self._mode = KEY.MODE_HALT

        self._funding_rate: Optional[Decimal] = None

        self._hedge_inventory: Union[int, Decimal] = 0

        self._wait_before_hold: Optional[int] = None

    def onMessage(self, message: dict,
                  timestamp: int, latency: int = 0):
        super().onMessage(message, timestamp, latency)

        if message[KEY.TYPE] == KEY.FUNDING_RATE and self._mode == KEY.MODE_HALT:
            symbol, exchange = message[KEY.SYMBOL], message[KEY.EXCHANGE]

            if (symbol, exchange) == (self.default_symbol, self.default_exchange):

                self._funding_rate = message[KEY.FUNDING_RATE]

                if self._funding_rate < self._threshold:

                    if self._is_hedged():

                        self._liquidation_event()



    def onTime(self, timestamp: int):
        super().onTime(timestamp)

        print(self._funding_rate, self._mode)

        # Only ONE time after bot starter we are running "action" tasks
        if self.isWarmedUp() and not self._is_started:
            self._is_started = True
            self._make_basis()

        # After we are starting bot we are in HALT state. We change this
        # state according to "action" after initialization
        if self._mode != KEY.MODE_HALT:
            self._follow_hedge()

        if self._wait_before_hold is None:
            if self._mode == KEY.MODE_INVENTORY:
                if not self.get_limit_queue_length(target=KEY.HEDGE):
                    self._wait_before_hold = self._timer.Timestamp() + WAIT_BEFORE_HOLD_AFTER_TASK_DONE
                    self._logger.warning(f'Hedge task is completed, wait for some time to set HOLD mode')

        else:
            if self._timer.Timestamp() > self._wait_before_hold:
                self._logger.warning(f'Set HALT mode: DEFAULT portfolio will not follow HEDGE now')
                self._wait_before_hold = None
                self._mode = KEY.MODE_HALT

        if self._mode == KEY.MODE_LIQUIDATION:
            inventory = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, 0)
            if abs(inventory) < KEY.ED:
                self._logger.warning(f'Looks like inventory is 0 in LIQUIDATION state. Safe stop')
                self._safe_stop()

        if not self.get_limit_queue_length(target=KEY.DEFAULT):
            self.unlock_qty_limit(KEY.HEDGE)

        self._track_pnl()

    def onOrderbook(self, askPrice: Decimal, askQty: Decimal, bidPrice: Decimal, bidQty: Decimal,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        super().onOrderbook(askPrice, askQty, bidPrice, bidQty, symbol, exchange, timestamp, latency)

        target = self.products_map[symbol, exchange]
        self._top_book[target].ask_price = askPrice
        self._top_book[target].bid_price = bidPrice


    def _is_hedged(self) -> bool:
        """
        This function checks DEFAULT and HEDGE inventory

        If delta of ABSOLUTE value less than `FULLY_HEDGED_THRESHOLD` --> we can call inventory as "fully hedged"

        :return: True if inventory is fully hedged
        """
        default_inventory = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, 0)
        hedge_inventory = self.state[KEY.INVENTORY][KEY.HEDGE].get(KEY.QTY, 0)

        if abs(default_inventory) < KEY.ED and abs(hedge_inventory) < KEY.ED:
            return True

        elif abs(hedge_inventory) > KEY.ED:
            return False

        elif (abs(default_inventory / hedge_inventory) - 1) < FULLY_HEDGED_THRESHOLD:
            return True

        else:
            return False

    def _track_pnl(self):
        pnl = defaultdict(lambda: Decimal(0))
        basis_pnl, basis_qty = 0, 0
        for side in [KEY.HEDGE, KEY.DEFAULT]:
            entry_price = self.state[KEY.INVENTORY][side].get(KEY.PRICE, 0)
            inventory = self.state[KEY.INVENTORY][side].get(KEY.QTY, 0)
            if abs(inventory) > KEY.ED:
                midpoint = (self._top_book[side].ask_price + self._top_book[side].bid_price) / 2
                if midpoint > 0:
                    _pnl = inventory * (midpoint - entry_price)

                    basis_pnl += _pnl
                    basis_qty += inventory

                    pnl[f'{side}_pnl'] = float(_pnl)
                    pnl[f'{side}_qty'] = float(inventory)

        pnl['basis_pnl'], pnl['basis_qty'] = float(basis_pnl), float(basis_qty)

        self.putBuffer(pnl)

        if self._timer.Timestamp() > self._next_pnl_log:
            self._next_pnl_log = self._timer.Timestamp() + LOG_PNL_EVERY
            pnl_report = [f'{key}={value}' for key, value in pnl.items()]
            self._logger.info(f'Current PNL: {pnl_report}')

        print(pnl)

    def _liquidation_event(self):
        self._mode = KEY.MODE_LIQUIDATION
        self._logger.warning(f'Funding Rate below threshold or LIQUIDATION action. Liquidate all',
                             funding_rate=self._funding_rate, threshold=self._threshold)
        self.make_qty_limit(qty=0, target=KEY.HEDGE, tick=1)

    def _follow_hedge(self):
        # Update current hedge inventory
        hedge_inventory = self.state[KEY.INVENTORY][KEY.HEDGE].get(KEY.QTY, 0)
        if hedge_inventory != self._hedge_inventory:
            self._hedge_inventory = hedge_inventory

            # Looks like hedge inventory changes
            print(f'hedge inventory changes: {hedge_inventory}')

            inventory = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, 0)

            target_inventory = -1 * hedge_inventory

            if self._mode != KEY.MODE_LIQUIDATION and abs(target_inventory - inventory) > 0:
                self.lock_qty_limit(target=KEY.HEDGE)
                self.make_qty_limit(target_inventory, target=KEY.DEFAULT, tick=1)

            elif self._mode == KEY.MODE_LIQUIDATION and (target_inventory - inventory) > 0:
                self.lock_qty_limit(target=KEY.HEDGE)
                self.make_qty_limit(target_inventory, target=KEY.DEFAULT, tick=1)

    def _safe_stop(self):
        self._logger.success(f'Safe stop')
        os.kill(os.getpid(), signal.SIGINT)
        self._timer.Sleep(1)

    def _get_target_qty(self) -> Decimal:
        if self._usd is not None:
            midpoint = (self._top_book[KEY.HEDGE].ask_price + self._top_book[KEY.HEDGE].bid_price) / 2
            qty = self._usd / midpoint
            order = Order(qty)
            order = self.products[KEY.DEFAULT].oms.applyRules(order)
            self._logger.info(f'USD based qty = {order.qty}', midpoint=midpoint, qty=qty)
            return order.qty
        else:
            return self._max_inventory

    def _set_spot_inventory(self):
        self._mode = KEY.MODE_INVENTORY
        qty = self._get_target_qty()
        self._logger.info(f'Making target inventory using LIMIT orders on HEDGE', qty=qty)
        self.make_qty_limit(qty=qty, target=KEY.HEDGE, lock=True)

    def _make_basis(self):
        # Check default inventory
        current_qty = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, 0)
        price = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.PRICE, 0)

        if self._action == KEY.DEFAULT:
            if abs(current_qty) > 0:
                self._logger.warning(f'Inventory found: {current_qty}@{price}. Continue with tracking')
            else:
                self._set_spot_inventory()

        if self._action == KEY.SINGLE:
            if abs(current_qty) > 0:
                self._logger.warning(f'Inventory found: {current_qty}@{price}. Safe exit')
                self._safe_stop()
            else:
                self._set_spot_inventory()

        elif self._action == KEY.LIQUIDATION:
            self._liquidation_event()

        elif self._action == KEY.SCALE:
            self._set_spot_inventory()



