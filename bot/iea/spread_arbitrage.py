import threading
from collections import defaultdict
from decimal import Decimal
from enum import Enum
from pprint import pprint
from typing import Optional, List, Dict

from bot import AbstractBot
from bot.iea.modules.handle_alive import HandleAlive
from bot.iea.modules.handle_buffer import HandleBuffer
from bot.iea.modules.handle_clean_cancel import HandleCleanCancel
from bot.iea.modules.handle_clean_force import HandleCleanForce
from bot.iea.modules.handle_delta import HandleDelta
from bot.iea.modules.handle_exchange import HandleExchange
from bot.iea.modules.handle_hedge_exchange import HandleHedgeExchange
from bot.iea.modules.handle_inventory import HandleInventory
from bot.iea.modules.handle_spread import HandleSpread
from bot.iea.modules.handle_state import HandleState
from bot.iea.modules.handle_watchdog import HandleWatchdog
from lib.constants import KEY
from lib.exchange import Book, Order
from lib.factory import AbstractFactory
from lib.helpers import sign
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer



class BotState:
    Empty = 'Empty State'
    Up = 'Inital State'
    Down = 'Flipped State'

KEY_BOT_STATE = 'bot_state'
KEY_INIT_SPREAD = 'init_spread'

MAX_PENDING = Decimal('0.1')

ALERT_TIMEOUT = 10 * KEY.ONE_SECOND


class SpreadArbitrage(
    HandleInventory,
    HandleWatchdog,
    HandleCleanCancel,
    HandleAlive,
    HandleBuffer,
    HandleState,
    HandleHedgeExchange,
    HandleExchange,
    AbstractBot
):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        self._logger: AbstractLogger = factory.Logger(config, factory, timer)

        ###########################################################################
        # Load `decimal`-type parameters from configuration
        ###########################################################################

        def _get_decimal(key: str, default=None) -> Decimal:
            value = self._config.get(key, default)
            self._logger.info(f'SET "{key}"={value}')
            return None if value is None else Decimal(str(value))

        self._high_threshold = _get_decimal(KEY.HIGH_THRESHOLD)
        self._low_threshold = _get_decimal(KEY.LOW_THRESHOLD)
        self._direction = _get_decimal(KEY.DIRECTION)
        self._capital = _get_decimal(KEY.CAPITAL)

        ###########################################################################
        # Create internal flags and variables
        ###########################################################################

        self._restore_bot_state()

        self._restore_init_spread()

        self._check_inventory()

        self._spread: Optional[Decimal] = None

        self._midpoint: Optional[Decimal] = None

        self._current: Dict[str, Optional[Book]] = defaultdict(lambda: None)

        self._alert_timestamp: Optional[int] = None
        ###########################################################################
        # Test variables. TODO: remove them
        ###########################################################################
        self._logger.info(f'Used state: {self.state}')
        self._test_mode_no_trades = False
        if self._test_mode_no_trades:
            self._logger.warning('TEST MODE: NO TRADES')

    def _check_inventory(self):
        if abs(self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, 0)) < KEY.ED and \
            abs(self.state[KEY.INVENTORY][KEY.HEDGE].get(KEY.QTY, 0)) < KEY.ED:
            if self.state[KEY_INIT_SPREAD] is not None:
                self._logger.warning(f'Found ZERO inventory but not EMPTY BotState: reset BotState')
                self._reset_bot_state()
                self._reset_init_spread()
                self.saveState()

    def _reset_bot_state(self):
        self.state[KEY_BOT_STATE] = BotState.Empty

    def _reset_init_spread(self):
        self.state[KEY_INIT_SPREAD] = None

    def _restore_bot_state(self):
        """
        Check current BotState value in saved State
        If no value --> create a key with "Empty" value
        :return:
        """
        bot_state = self.state.get(KEY_BOT_STATE, None)
        if bot_state is None:
            self._reset_bot_state()

    def _restore_init_spread(self):
        """
        Check current Init Spread value in saved State
        If no value --> create a key with None value
        :return:
        """
        init_spread = self.state.get(KEY_INIT_SPREAD, None)
        if init_spread is None:
            self._reset_init_spread()


    def _track_balances(self):
        balance_a = self.products[KEY.DEFAULT].oms.getBalance()
        balance_b = self.products[KEY.HEDGE].oms.getBalance()

        self.updateStatus(
            balance_a=balance_a.balance,
            balance_b=balance_b.balance,
            gas_a=balance_a.gas,
            gas_b=balance_b.gas,
        )

        self.putBuffer(
            fields={
                'balance_a': balance_a.balance,
                'balance_b': balance_b.balance,
                'available_a': balance_a.available,
                'available_b': balance_b.available,
                'gas_a': balance_a.gas,
                'gas_b': balance_b.gas,
                'balance_total': (balance_a.balance or Decimal('0')) + (balance_b.balance or Decimal('0')),
                'available_total': (balance_a.available or Decimal('0')) + (balance_b.available or Decimal('0')),
                'gas_total': (balance_a.gas or Decimal('0')) + (balance_b.gas or Decimal('0'))
            }
        )

    def onTime(self, timestamp: int):
        super().onTime(timestamp)
        print(self._spread, self.state)

        # Track current positions for both exchanges
        fields = {
            'position_a': self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, Decimal('0.0')),
            'position_b': self.state[KEY.INVENTORY][KEY.HEDGE].get(KEY.QTY, Decimal('0.0')),
        }
        self.updateStatus(**fields)
        self.putBuffer(fields=fields)

        track_balances_async = threading.Thread(target=self._track_balances)
        track_balances_async.start()

        if self._alert_timestamp is not None:
            if self._alert_timestamp > self._timer.Timestamp():
                self._alert_timestamp = None

        for name, product in self.products.items():
            if not product.oms.isOnline():
                if self._alert_timestamp is None:
                    self.broadcastAlert(message=f'"{name}" exchange is OFFLINE')
                    self._alert_timestamp = self._timer.Timestamp() + ALERT_TIMEOUT


    def _handle_spread(self):
        # Skip if we have no prices for both exchanges yet
        if not all([self._current[KEY.DEFAULT], self._current[KEY.HEDGE]]):
            return

        midpoints = {}

        self._midpoint = sum([x.ask_price + x.bid_price for x in self._current.values()]) / 4

        for side in [KEY.DEFAULT, KEY.HEDGE]:
            midpoints[side] = (self._current[side].ask_price + self._current[side].bid_price) / 2

        self._spread = midpoints[KEY.DEFAULT] - midpoints[KEY.HEDGE]
        self._spread = self._spread / self._midpoint

        self.putBuffer(fields={'spread_arbitrage': self._spread, 'midpoint_arbitrage': self._midpoint})

    def _handle_positions(self):
        # we cant handle spread till we have fresh value
        if self._spread is None:
            return

        if self.state[KEY_BOT_STATE] == BotState.Empty:
            if abs(self._spread) > abs(self._high_threshold):
                self._open()

        elif sign(self._spread) == sign(self.state[KEY_INIT_SPREAD]) and \
                self.state[KEY_BOT_STATE] == BotState.Down and \
                abs(self._spread) > abs(self._high_threshold):
            self._flip()

        elif sign(self._spread) == sign(self.state[KEY_INIT_SPREAD]) and \
                self.state[KEY_BOT_STATE] == BotState.Up and \
                abs(self._spread) < abs(self._low_threshold):
            self._flip()

        elif sign(self._spread) != sign(self.state[KEY_INIT_SPREAD]) and \
                self.state[KEY_BOT_STATE] == BotState.Up:
            self._flip()

    def _get_qty(self) -> Optional[Decimal]:

        # We cant find qty till we have correct midpoint
        if self._midpoint is None:
            return None

        # find qty estimate: without exchange limits
        qty_estimate = self._capital / self._midpoint

        # Use biggest step
        if self.products[KEY.DEFAULT].oms.getMinQty() > self.products[KEY.HEDGE].oms.getMinQty():
            order = self.products[KEY.DEFAULT].oms.applyRules(Order(qty=qty_estimate))
        else:
            order = self.products[KEY.HEDGE].oms.applyRules(Order(qty=qty_estimate))

        return order.qty


    def _open(self):
        """
        When we cross `high_threshold` first time, we have no open positions. So we just have to go
        LONG and SHORT for both exchanges.
        :return:
        """
        self.state[KEY_INIT_SPREAD] = self._spread
        self.state[KEY_BOT_STATE] = BotState.Up
        self._logger.info(f'OPEN first deal', spread=self._spread)

        qty = self._get_qty()

        direction = self._direction * sign(self._spread)

        target_a_qty = qty * direction
        target_b_qty = -1 * target_a_qty

        id_a = self.products[KEY.DEFAULT].oms.Post(Order(qty=target_a_qty))
        id_b = self.products[KEY.HEDGE].oms.Post(Order(qty=target_b_qty))

        self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.PENDING] = target_a_qty
        self.state[KEY.INVENTORY][KEY.HEDGE][KEY.PENDING] = target_b_qty

        self._logger.info(f'Open new round', threshold=self._high_threshold, spread=self._spread,
                          target_a_qty=target_a_qty, target_b_qty=target_b_qty,
                          id_a=id_a, id_b=id_b)
        self.saveState()


    def _flip(self):
        """
        When we have some open positions and cross any threshold we ahve to FLIP positions.
        For LONG we going SHORT 2x qty, vice versa for SHORT

        :return:
        """
        pending_a = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.PENDING, Decimal('0'))
        pending_b = self.state[KEY.INVENTORY][KEY.HEDGE].get(KEY.PENDING, Decimal('0'))

        target_qty = self._get_qty()
        max_pending = target_qty * MAX_PENDING


        if abs(pending_a) > max_pending or abs(pending_b) > max_pending:
            self._logger.warning(f'We should flip positions, but have pending orders. Cant flip',
                                 pending_a=pending_a, pending_b=pending_b, spread=self._spread,
                                 low_threshold=self._low_threshold, high_threshold=self._high_threshold)
            return

        qty_a = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, 0)
        qty_b = self.state[KEY.INVENTORY][KEY.HEDGE].get(KEY.QTY, 0)

        if not(abs(qty_a) > 0 and abs(qty_b)):
            self._logger.warning(f'We should flip positions, actually have no inventory. Cant flip',
                                 qty_a=qty_a, qty_b=qty_b, spread=self._spread,
                                 low_threshold=self._low_threshold, high_threshold=self._high_threshold)
            return

        direction_a = -1 * sign(qty_a)
        direction_b = -1 * direction_a

        flip_qty_a = target_qty + abs(qty_a)
        flip_qty_b = target_qty + abs(qty_b)

        order_qty_a = direction_a * flip_qty_a
        order_qty_b = direction_b * flip_qty_b

        id_a = self.products[KEY.DEFAULT].oms.Post(Order(qty=order_qty_a))
        id_b = self.products[KEY.HEDGE].oms.Post(Order(qty=order_qty_b))

        self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.PENDING] = pending_a + order_qty_a
        self.state[KEY.INVENTORY][KEY.HEDGE][KEY.PENDING] = pending_b + order_qty_b

        self._logger.info(f'Flip Inventory', high_threshold=self._high_threshold, low_threshold=self._low_threshold,
                          spread=self._spread, target_a_qty=order_qty_a, target_b_qty=order_qty_b, id_a=id_a, id_b=id_b)

        self.state[KEY_BOT_STATE] = BotState.Up if self.state[KEY_BOT_STATE] == BotState.Down else BotState.Down

        fields = {
            'entry_a_ask': self._current[KEY.DEFAULT].ask_price,
            'entry_a_bid': self._current[KEY.DEFAULT].bid_price,
            'entry_b_ask': self._current[KEY.HEDGE].ask_price,
            'entry_b_bid': self._current[KEY.HEDGE].bid_price,
            'qty_a': order_qty_a,
            'qty_b': order_qty_b,
        }
        self.putBuffer(fields)

        self.saveState()

    def onAccount(self, price: Decimal, qty: Decimal, symbol: str, exchange: str, timestamp: int, latency: int = 0):
        """
        Will log actual entry price as `entry_a` for DEFAULT exchange and `entry_b` for HEDGE exchange

        :param price:
        :param qty:
        :param symbol:
        :param exchange:
        :param timestamp:
        :param latency:
        :return:
        """
        super().onAccount(price, qty, symbol, exchange, timestamp, latency)

        if (symbol, exchange) == (self.products[KEY.DEFAULT].symbol, self.products[KEY.DEFAULT].exchange):
            self.putBuffer(fields={'entry_a': price})

        if (symbol, exchange) == (self.products[KEY.HEDGE].symbol, self.products[KEY.HEDGE].exchange):
            self.putBuffer(fields={'entry_b': price})



    def onOrderbook(self, askPrice: Decimal, askQty: Decimal, bidPrice: Decimal, bidQty: Decimal,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        # call parent method
        super().onOrderbook(askPrice, askQty, bidPrice, bidQty, symbol, exchange, timestamp, latency)

        # try to determine product using map. If product is not exists --> skip
        target = self.products_map.get((symbol, exchange), None)
        if target is None:
            return

        # save latest ask/bid pair
        self._current[target] = Book(ask_price=askPrice, ask_qty=askQty, bid_price=bidPrice, bid_qty=bidQty)

        self._handle_spread()

        if not self._test_mode_no_trades:
            self._handle_positions()

