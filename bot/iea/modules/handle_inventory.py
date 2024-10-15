import math
from decimal import Decimal
from typing import Tuple

from bot import AbstractBot
from bot.iea.modules.handle_distance import HandleDistance
from bot.iea.modules.handle_exchange import HandleExchange
from bot.iea.modules.handle_positions import HandlePositions
from bot.iea.modules.handle_state import HandleState
from lib.async_ejector import FieldsAsyncEjector
from lib.constants import KEY, ORDER_TAG
from lib.database import AbstractDatabase
from lib.defaults import DEFAULT
from lib.exchange import Order
from lib.factory import AbstractFactory
from lib.helpers import sign
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer


class HandleInventory(
    HandlePositions,
    HandleState,
    HandleDistance,
    HandleExchange,
    AbstractBot
):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        ###########################
        # Create utility objects
        ###########################
        self._logger: AbstractLogger = factory.Logger(config, factory, timer)
        self._database: AbstractDatabase = factory.Database(config, factory, timer)

        ###########################
        # Load internal
        ###########################
        self._first_liquidation = config.get(KEY.FIRST_LIQUIDATION, DEFAULT.FIRST_LIQUIDATION)
        self._first_liquidation = Decimal(str(self._first_liquidation))

        self._second_liquidation = config.get(KEY.SECOND_LIQUIDATION, DEFAULT.SECOND_LIQUIDATION)
        self._second_liquidation = Decimal(str(self._second_liquidation))

        self._trailing_profit = config.get(KEY.TRAILING_PROFIT, DEFAULT.TRAILING_PROFIT)
        self._trailing_profit = Decimal(str(self._trailing_profit))

        self._stoploss_trailing_profit = config.get(KEY.STOPLOSS_TRAILING_PROFIT, DEFAULT.STOPLOSS_TRAILING_PROFIT)
        self._stoploss_trailing_profit = Decimal(str(self._stoploss_trailing_profit))


    def onOrderbook(self, askPrice: Decimal, askQty: Decimal, bidPrice: Decimal, bidQty: Decimal,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        super().onOrderbook(askPrice, askQty, bidPrice, bidQty, symbol, exchange, timestamp, latency)
        self.handle_inventory_dynamic_partial(askPrice, bidPrice)

    ########################################################################################################
    # Private Methods
    ########################################################################################################

    def _get_stoploss_price(self, entry_price: Decimal, qty: Decimal, current_price: Decimal,
                            offset: Decimal, state) -> Tuple[Decimal, Decimal]:

        if state == KEY.STATE_FIRST_HIT:
            _trailing_profit = self._stoploss_trailing_profit
            _entry_price = offset
            _fee = 0
            _distance = self.distance * Decimal('0.25')

        elif state == KEY.STATE_SECOND_HIT:
            _trailing_profit = self._stoploss_trailing_profit
            _entry_price = offset
            _fee = 0
            _distance = self.distance * Decimal('0.25')

        else:
            _trailing_profit = self._trailing_profit
            _entry_price = entry_price
            _fee = self._fee
            _distance = self.distance

        zero = self.getZeroPrice(qty, _entry_price)

        adjusted_zero = zero * (1 + sign(qty) * _trailing_profit)

        if sign(qty) * (current_price - adjusted_zero) <= 0:
            distance = _distance
            break_price = adjusted_zero
        else:
            distance = _trailing_profit
            break_price = None

        stoploss = current_price * (1 - sign(qty) * distance)

        return (break_price, self.priceUp(stoploss) if qty > 0 else self.priceDown(stoploss))

    def _estimate(self, qty: Decimal, entry: Decimal, price: Decimal) -> Decimal:
        return qty * (price - entry - self._fee * entry - self._fee * price)

    def _update_state(self, qty: Decimal, entry: Decimal, current: Decimal, stoploss: Decimal, break_price: Decimal):
        estimatePnl = self._estimate(qty, entry, stoploss)
        distance_tick = abs(stoploss - current) / self.tick_size
        self._logger.warning('Got new Stoploss Price', event='STOPLOSS',
                             qty=qty, stoploss=stoploss, entry=entry, current=current,
                             estimatePnl=estimatePnl, distance_tick=distance_tick)
        self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.STOPLOSS] = stoploss
        self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.ESTIMATE_PNL] = estimatePnl
        self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.DISTANCE] = distance_tick
        self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.BREAK_PRICE] = break_price
        if self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.STATE, None) is None:
            self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.STATE] = KEY.STATE_NORMAL

        self.saveState()

        FieldsAsyncEjector(self._database, self._timer, stoploss=stoploss, entry=entry, break_price=break_price).start()

    def handle_inventory_dynamic_partial(self, ask: Decimal, bid: Decimal):

        # Get current portfolio, qty and pending from State
        qty = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, 0)
        offset = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.OFFSET, 0)
        entry = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.PRICE, 0)
        pending = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.PENDING, 0)
        state = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.STATE, KEY.STATE_NORMAL)

        # Basically we should not call this fn when Qty == 0 or we have no Entry price,
        # but if it happens --> handle correct: do nothing
        if abs(qty) < KEY.ED or entry is None \
                or self.distance is None:
            return

        # Get previous Stoploss price from State. None means we have no Stoploss price --> will set new
        current_stoploss = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.STOPLOSS, None)

        # We will use Bid price for Long positions to liquidate, Ask for Short
        price = bid if qty > 0 else ask

        break_price, stoploss = self._get_stoploss_price(entry, qty, price, offset, state)

        # For Long positions we move Stoploss only UP, for Short -- only Down
        fn = max if qty > 0 else min
        new_stoploss = fn(current_stoploss or stoploss, stoploss)

        if new_stoploss != current_stoploss:
            self._update_state(qty, entry, price, new_stoploss, break_price)

        # We have Stoploss Event --> prepare MARKET order, take "pending" into account
        if sign(qty) * (price - new_stoploss) <= 0:
            if self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.BREAK_PRICE] is None:
                new_qty = -1 * sign(qty) * max(0, abs(qty) - abs(pending))
                if abs(new_qty) > KEY.ED:
                    # Change pending. In general we r able to increase it.
                    self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.PENDING] = pending + new_qty
                    self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.STATE] = KEY.STATE_NORMAL
                    self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.STOPLOSS] = None

                    id = self.default_oms.Post(Order(qty=new_qty, tag=ORDER_TAG.TAKE_PROFIT, liquidation=True))

                    self._logger.warning(f'Liquidate with profit. Send MARKET order',
                                         event='STOPLOSS', orderId=id, current=price, stoploss=new_stoploss,
                                         pending=self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.PENDING],
                                         break_price=break_price)

                    # We r update Pending --> have to save State
                    self.saveState()

            elif self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.STATE] == KEY.STATE_NORMAL:
                self._quoting = False
                self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.STATE] = KEY.STATE_FIRST_HIT
                self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.OFFSET] = new_stoploss
                qty_for_liquidation = math.ceil(
                    self._first_liquidation * abs(qty) / self.min_qty_size) * self.min_qty_size
                new_qty = -1 * sign(qty) * max(0, abs(qty_for_liquidation) - abs(pending))
                if abs(new_qty) > KEY.ED:
                    # Change pending. In general we r able to increase it.
                    self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.PENDING] = pending + new_qty
                    self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.STOPLOSS] = None

                    id = self.default_oms.Post(Order(qty=new_qty, tag=ORDER_TAG.STOP_LOSSES_1, liquidation=True))

                    self._logger.warning(
                        f'Hit FIRST Stoploss. Send MARKET order for {self._first_liquidation * 100}% of inventory',
                        event='STOPLOSS', orderId=id, current=price, stoploss=new_stoploss,
                        pending=self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.PENDING],
                        break_price=break_price)

                    # We r update Pending --> have to save State
                    self.saveState()

            elif self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.STATE] == KEY.STATE_FIRST_HIT:
                self._quoting = False
                self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.STATE] = KEY.STATE_SECOND_HIT
                self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.OFFSET] = new_stoploss
                qty_for_liquidation = math.ceil(
                    self._second_liquidation * abs(qty) / self.min_qty_size) * self.min_qty_size
                new_qty = -1 * sign(qty) * max(0, abs(qty_for_liquidation) - abs(pending))
                if abs(new_qty) > KEY.ED:
                    # Change pending. In general we r able to increase it.
                    self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.PENDING] = pending + new_qty
                    self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.STOPLOSS] = None

                    id = self.default_oms.Post(Order(qty=new_qty, tag=ORDER_TAG.STOP_LOSSES_2, liquidation=True))

                    self._logger.warning(
                        f'Hit SECOND Stoploss. Send MARKET order for {self._second_liquidation * 100}% of inventory',
                        event='STOPLOSS', orderId=id, current=price, stoploss=new_stoploss,
                        pending=self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.PENDING],
                        break_price=break_price)

                    # We r update Pending --> have to save State
                    self.saveState()

            elif self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.STATE] == KEY.STATE_SECOND_HIT:
                self._quoting = False
                self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.STATE] = KEY.STATE_STOP_QUOTING
                new_qty = -1 * sign(qty) * max(0, abs(qty) - abs(pending))
                if abs(new_qty) > KEY.ED:
                    # Change pending. In general we r able to increase it.
                    self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.PENDING] = pending + new_qty
                    self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.STOPLOSS] = None

                    id = self.default_oms.Post(Order(qty=new_qty, tag=ORDER_TAG.STOP_LOSSES_3, liquidation=True))

                    self._logger.warning(f'Liquidate Rest. Send MARKET order and STOP',
                                         event='STOPLOSS', orderId=id, current=price, stoploss=new_stoploss,
                                         pending=self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.PENDING],
                                         break_price=break_price)

                    # We r update Pending --> have to save State
                    self.saveState()
