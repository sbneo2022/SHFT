import math
from collections import deque
from decimal import Decimal
from typing import Optional, Union

from bot import AbstractBot
from bot.iea.modules.handle_buffer import HandleBuffer
from bot.iea.modules.handle_exchange import HandleExchange
from bot.iea.modules.handle_inventory import HandleInventory
from bot.iea.modules.handle_positions import HandlePositions
from bot.iea.modules.handle_state import HandleState
from bot.iea.modules.handle_top_imbalance import HandleTopImbalance
from lib.constants import KEY
from lib.defaults import DEFAULT
from lib.exchange import Order
from lib.factory import AbstractFactory
from lib.helpers import sign
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer


TOPIC = KEY.MARKET

class HandleQtyMarket(
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

        self._impact_market = load_with_prefix(KEY.IMPACT, default=0.05)
        self._pause_market = load_with_prefix(KEY.PAUSE, default=1) * KEY.ONE_SECOND

        ################################################################
        # Internal variables
        ################################################################
        if TOPIC not in self.state:
            self.state[TOPIC] = []

        self._next_handle_market: Optional[int] = None


        ################################################################
        # Public variables
        ################################################################

    def _delete_last_task(self):
        if self.state[TOPIC]:
            print(f'delete first item from {self.state[TOPIC]}')
            _ = self.state[TOPIC].pop(0)

    def _handle_next_market_step(self, force=False):
        print(self.state[TOPIC])
        # Handle delay
        if self._next_handle_market is not None \
                and self._timer.Timestamp() < self._next_handle_market \
                and not force:
            return
        else:
            self._next_handle_market = self._timer.Timestamp() + self._pause_market

        # Return if no liquidation tasks
        if not self.state[TOPIC]:
            return

        target = self.state[TOPIC][0][KEY.EXCHANGE]

        if not(all([self.top_imbalance[target].ask_average_sum, self.top_imbalance[target].bid_average_sum])):
            return

        pending = self.state[KEY.INVENTORY][target].get(KEY.PENDING, 0)
        inventory = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, 0)

        # We handle _next_ step only when _current_ is done
        if abs(pending) > 0:
            return

        if self.state[TOPIC][0].get(KEY.DELTA, None) is None:

            target_qty = self.state[TOPIC][0][KEY.QTY]

            delta = target_qty - inventory

            if abs(delta) >= self.min_qty_size:

                if (target_qty * inventory) >= 0 and abs(target_qty) < abs(inventory):
                    liquidation = True
                else:
                    liquidation = False

                self.state[TOPIC][0][KEY.DELTA] = delta
                self.state[TOPIC][0][KEY.LIQUIDATION] = liquidation

                self._logger.warning(f'Total delta for "{target}" = {delta}', delta=delta, liquidation=liquidation)
            else:
                print('delta less min_qty - post task')
                self._delete_last_task()
                return

        elif abs(self.state[TOPIC][0][KEY.DELTA]) < self.products[target].oms.getMinQty():
            print('delta less min_qty')
            self._delete_last_task()
            return

        task_qty = self.state[TOPIC][0][KEY.DELTA]

        # Because we change Inventory (not liquidate) we cant use order less than notional
        # We will use some trick: if order qty after rules applied is zero --> stop changing inventory
        if not self.state[TOPIC][0][KEY.LIQUIDATION]:
            test_order = self.products[target].oms.applyRules(Order(qty=task_qty))
            if abs(test_order.qty) < KEY.ED:
                self._logger.warning(f'Probably order size for {self.state[TOPIC][0]} less than possible '
                                     f'and that is not LIQUIDATION task. Stop and delete')
                self._delete_last_task()
                return

        used_top_book = self.top_imbalance[target].bid_average_sum if task_qty > 0 \
            else self.top_imbalance[target].ask_average_sum

        impact = self.state[TOPIC][0][KEY.IMPACT]
        step_qty = min(abs(task_qty), impact * used_top_book)

        print(f'HANDLE_NEXT_STEP :: used_top_book: {used_top_book} task_qty={task_qty}  step_qty={step_qty}')

        order = Order(qty=sign(task_qty) * step_qty, liquidation=self.state[TOPIC][0][KEY.LIQUIDATION])
        order = self.products[target].oms.applyRules(order)

        if self.state[TOPIC][0][KEY.LIQUIDATION]:
            if abs(order.qty) > abs(inventory):
                new_qty = abs(order.qty) - self.products[target].oms.getMinQty()
                new_qty = sign(order.qty) * new_qty
                order = Order(qty=new_qty, price=order.price, liquidation=order.liquidation)

        print('state', self.state)
        print('>>>>>', order)
        id = self.products[target].oms.Post(order)
        print('<<<<<', order)

        self.state[KEY.INVENTORY][target][KEY.PENDING] = order.qty
        self.state[TOPIC][0][KEY.DELTA] -= order.qty

        self._logger.warning(f'POST MARKET {order.qty} with id={id}')

    def onTime(self, timestamp: int):
        super().onTime(timestamp)
        self._handle_next_market_step()

    def clear_market_queue(self):
        self.state[TOPIC].clear()

    def get_market_queue_length(self):
        return len(self.state[TOPIC])

    def make_qty_market(self, qty: Union[int, Decimal], target: str = KEY.DEFAULT, impact: Optional[Decimal] = None):
        impact = impact or self._impact_market

        self._logger.warning(f'Receive {TOPIC.upper()} task make {qty} on "{target}"',
                             qty=qty, target=target, impact=impact)

        self.state[TOPIC].append({
            KEY.QTY: qty,
            KEY.EXCHANGE: target,
            KEY.IMPACT: impact
        })

        self._handle_next_market_step(force=True)