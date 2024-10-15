from collections import deque, defaultdict
from decimal import Decimal
from pprint import pprint
from typing import Optional, Union, Dict

from bot import AbstractBot
from bot.iea.modules.handle_buffer import HandleBuffer
from bot.iea.modules.handle_exchange import HandleExchange
from bot.iea.modules.handle_positions import HandlePositions
from bot.iea.modules.handle_state import HandleState
from bot.iea.modules.handle_top_imbalance import HandleTopImbalance
from lib.constants import KEY
from lib.exchange import Order, Book
from lib.factory import AbstractFactory
from lib.helpers import sign
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer

TOPIC = KEY.LIMIT

class HandleQtyLimit(
    HandlePositions,
    HandleState,
    HandleTopImbalance,
    HandleExchange,
    HandleBuffer,
    AbstractBot,
):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        self._logger: AbstractLogger = factory.Logger(config, factory, timer)

        ################################################################
        # Load parameter from config
        ################################################################
        def load_with_prefix(tag: str, default=None) -> Decimal:
            _tag = '.'.join([TOPIC, tag])
            value = self._config.get(_tag, default)
            self._logger.info(f'{TOPIC.upper()} :: {tag} = {value}')
            return Decimal(str(value)) if value is not None else None

        self._tick_limit = int(load_with_prefix(KEY.TICK, default=0))
        self._impact_limit = load_with_prefix(KEY.IMPACT, default=0.05)
        self._hold_limit = load_with_prefix(KEY.HOLD, default=10) * KEY.ONE_SECOND

        ################################################################
        # Internal variables
        ################################################################
        if TOPIC not in self.state:
            self.state[TOPIC] = {}

        if not isinstance(self.state[TOPIC], dict):
            self.state[TOPIC] = {}

        self._next_handle_limit: Optional[int] = None

        self._top_book: Dict[str, Book] = defaultdict(lambda: Book())

        self._lock_state = defaultdict(lambda: False)

        self._current_order_id: Dict[str, Optional[str]] = defaultdict(lambda: None)
        self._next_timestamp: Dict[str, Optional[int]] = defaultdict(lambda: None)
        self._current_order: Dict[str, Optional[Order]] = defaultdict(lambda: None)

        ################################################################
        # Public variables
        ################################################################

    def _delete_last_limit_task(self, target: str):
        if self.state[TOPIC].get(target, []):
            print(f'delete first item from {self.state[TOPIC][target]}')
            _ = self.state[TOPIC][target].pop(0)

    def _handle_next_limit_step(self, target: str):
        # Return if no liquidation tasks
        if not self.state[TOPIC].get(target, []):
            return

        # Read current LOCK parameter
        lock = self.state[TOPIC][target][0][KEY.LOCK]

        # We will handle next step if "no locks" parameter or not in lock state
        if lock and self._lock_state[target]:
            return

        # Get target exchange for current task
        target_qty = self.state[TOPIC][target][0][KEY.QTY]
        target_tick = self.state[TOPIC][target][0][KEY.TICK]

        # We cant process task without ask/bid top book qty
        if not(all([self.top_imbalance[target].ask_average_sum, self.top_imbalance[target].bid_average_sum])):
            return

        # Get current qty for target exchange
        current_qty = self.state[KEY.INVENTORY][target].get(KEY.QTY, 0)
        delta = target_qty - current_qty

        # If current qty equal to target qty of latest task --> delete latest task
        if abs(delta) < KEY.ED:
            self.products[target].oms.Cancel(self._current_order_id[target])
            self._current_order_id[target], self._next_timestamp[target] = None, None

            self._logger.warning(f'Task {self.state[TOPIC][target][0]} is done. Delete it')
            self._delete_last_limit_task(target)
            return

        if self._next_timestamp[target] is not None:

            # If we have some open orders and holding time is gone --> CANCEL them
            if self._timer.Timestamp() > self._next_timestamp[target]:
                self.products[target].oms.Cancel(self._current_order_id[target])
                self._current_order_id[target], self._next_timestamp[target] = None, None
                print('cancel open orders because of out of time')

            # If holding time not pass --> keep holding (return from function)
            else:
                print('keep holding open orders')
                return

        # Ok, now we have to post new LIMIT order
        base_price = self._top_book[target].bid_price if delta > 0 else self._top_book[target].ask_price

        _coeff = +1 if delta < 0 else -1

        price = base_price + _coeff * target_tick * self.products[target].oms.getTick()

        liquidation = True if (target_qty * current_qty) >= 0 and abs(target_qty) < abs(current_qty) else False

        order = Order(qty=delta, price=price, liquidation=liquidation)
        order = self.products[target].oms.applyRules(order)

        if liquidation:
            if abs(order.qty) > abs(current_qty):
                new_qty = abs(order.qty) - self.products[target].oms.getMinQty()
                new_qty = sign(order.qty) * new_qty
                order = Order(qty=new_qty, price=order.price, liquidation=order.liquidation)

        if abs(order.qty) < KEY.ED:
            self._logger.warning(f'Target qty ({order}) is 0. Delete task')
            self._delete_last_limit_task(target)
            return

        used_top_book = self.top_imbalance[target].bid_average_sum if order.qty > 0 \
            else self.top_imbalance[target].ask_average_sum

        orderbook_based_qty = min(abs(order.qty), self._impact_limit * used_top_book)

        order = Order(qty=orderbook_based_qty * sign(order.qty), price=price, liquidation=liquidation)
        order = self.products[target].oms.applyRules(order)

        if abs(order.qty) < KEY.ED:
            self._logger.warning(f'Orderbook based qty ({order}) is 0. SKIP step')
            return

        self._current_order_id[target] = self.products[target].oms.Post(order)

        self._logger.warning(f'POST limit order {order} with id={self._current_order_id[target]}')

        self._next_timestamp[target] = self._timer.Timestamp() + self._hold_limit


    def onTime(self, timestamp: int):
        super().onTime(timestamp)
        for target in self.state[TOPIC].keys():
            self._handle_next_limit_step(target)

    def onOrderbook(self, askPrice: Decimal, askQty: Decimal, bidPrice: Decimal, bidQty: Decimal,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        super().onOrderbook(askPrice, askQty, bidPrice, bidQty, symbol, exchange, timestamp, latency)

        target = self.products_map[symbol, exchange]
        self._top_book[target].ask_price = askPrice
        self._top_book[target].bid_price = bidPrice

    def clear_limit_queue(self, target: str):
        if target in self.state[TOPIC]:
            self.state[TOPIC][target].clear()

    def lock_qty_limit(self, target: str):
        if not self._lock_state[target]:
            print('LOCK QTY LIMIT')
        self._lock_state[target] = True

    def unlock_qty_limit(self, target: str):
        if self._lock_state[target]:
            print('UNLOCK QTY LIMIT')
        self._lock_state[target] = False

    def get_limit_queue_length(self, target: str):
        return len(self.state[TOPIC].get(target, []))

    def make_qty_limit(self, qty: Union[int, Decimal], target: str = KEY.DEFAULT,
                       tick: Optional[int] = None, lock: bool = False):
        tick = tick or self._tick_limit

        self._logger.warning(f'Receive {TOPIC.upper()} task make {qty} on "{target}"',
                             qty=qty, target=target, tick=tick)

        if target not in self.state[TOPIC]:
            self.state[TOPIC][target] = []

        self.state[TOPIC][target].append({
            KEY.QTY: qty,
            KEY.TICK: tick,
            KEY.LOCK: lock,
        })

        print(self.state[TOPIC])
        self._handle_next_limit_step(target)