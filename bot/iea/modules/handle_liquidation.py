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


class HandleLiquidation(
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

        self._orderbook_impact = Decimal(0.05)

        ################################################################
        # Internal variables
        ################################################################
        if KEY.LIQUIDATION not in self.state:
            self.state[KEY.LIQUIDATION] = []

        ################################################################
        # Public variables
        ################################################################

    def _delete_last_task(self):
        if self.state[KEY.LIQUIDATION]:
            print(f'delete first item from {self.state[KEY.LIQUIDATION]}')
            _ = self.state[KEY.LIQUIDATION].pop()

    def _handle_next_step(self):
        if not(all([self.ask_average_sum, self.bid_average_sum])):
            return

        # Return if no liquidation tasks
        if not self.state[KEY.LIQUIDATION]:
            return

        pending = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.PENDING, 0)
        # We handle _next_ step only when _current_ is done
        if abs(pending) > 0:
            return

        if self.state[KEY.LIQUIDATION][0].get(KEY.QTY, None) is None:
            inventory = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, 0)

            if abs(inventory) >= self.min_qty_size:
                pct = self.state[KEY.LIQUIDATION][0][KEY.PCT]

                qty = math.ceil(inventory * pct / self.min_qty_size) * self.min_qty_size

                self.state[KEY.LIQUIDATION][0][KEY.QTY] = qty

                self._logger.warning(f'Total liquidation amount will be: {qty}')
            else:
                self._delete_last_task()
                return

        elif abs(self.state[KEY.LIQUIDATION][0][KEY.QTY]) < KEY.ED:
            self._delete_last_task()
            return

        qty_to_liquidate = self.state[KEY.LIQUIDATION][0][KEY.QTY]

        used_top_book = self.bid_average_sum if qty_to_liquidate > 0 else self.ask_average_sum

        print(f'used_top_book: {used_top_book}')

        liquidation_qty = min(abs(qty_to_liquidate), self._orderbook_impact * used_top_book)

        print(f'qty_to_liquidate: {liquidation_qty}')

        order = Order(qty=-1 * sign(qty_to_liquidate) * liquidation_qty, liquidation=True)
        order = self.products[KEY.DEFAULT].oms.applyRules(order)

        print('state', self.state)
        print('>>>>>', order)
        id = self.products[KEY.DEFAULT].oms.Post(order)
        print('<<<<<', order)

        self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.PENDING] = order.qty
        self.state[KEY.LIQUIDATION][0][KEY.QTY] += order.qty

        self._logger.warning(f'POST MARKET {order.qty} with id={id}')


    def onTime(self, timestamp: int):
        super().onTime(timestamp)
        self._handle_next_step()

    def liquidate(self, pct: Union[int, Decimal] = 1):
        if abs(self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, 0)) > 0:
            self._logger.warning(f'Receive LIQUIDATION task for {(100 * pct):0.2f}%')

            # Add liquidation task to queue
            self.state[KEY.LIQUIDATION].append({
                KEY.PCT: pct
            })

            self._handle_next_step()
        else:
            self._logger.info(f'Receive LIQUIDATION task for {(100 * pct):0.2f}% but no inventory found')

