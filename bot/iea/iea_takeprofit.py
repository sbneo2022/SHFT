import math
from collections import deque
from decimal import Decimal
from pprint import pprint
from typing import Optional, List

from bot import AbstractBot
from bot.iea.modules.handle_alive import HandleAlive
from bot.iea.modules.handle_atr import HandleATR
from bot.iea.modules.handle_buffer import HandleBuffer
from bot.iea.modules.handle_clean_cancel import HandleCleanCancel
from bot.iea.modules.handle_clean_force import HandleCleanForce
from bot.iea.modules.handle_delta import HandleDelta
from bot.iea.modules.handle_distance import HandleDistance
from bot.iea.modules.handle_exchange import HandleExchange
from bot.iea.modules.handle_hedge_exchange import HandleHedgeExchange
from bot.iea.modules.handle_inventory import HandleInventory
from bot.iea.modules.handle_spread import HandleSpread
from bot.iea.modules.handle_state import HandleState
from bot.iea.modules.handle_warming_up import HandleWarmingUp
from bot.iea.modules.handle_watchdog import HandleWatchdog
from lib.constants import KEY
from lib.exchange import Order
from lib.factory import AbstractFactory
from lib.helpers import sign
from lib.timer import AbstractTimer



class IeaTakeprofit(
    HandleWarmingUp,
    HandleWatchdog,
    HandleDistance,
    HandleCleanCancel,
    HandleState,
    HandleAlive,
    HandleBuffer,
    HandleExchange,
    AbstractBot
):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        ###########################################
        # Load REQUIRED config parameters
        ###########################################
        # self._threshold = {
        #     KEY.LONG: self._config[KEY.THRESHOLD][KEY.LONG],
        #     KEY.SHORT: self._config[KEY.THRESHOLD][KEY.SHORT],
        # }

        self._max_pct = self._config.get(KEY.MAX_PCT, 0.1)
        self._max_pct = Decimal(str(self._max_pct))

        self._max_qty = self._config.get(KEY.MAX_QTY, self.min_qty_size)
        self._max_qty = Decimal(str(self._max_qty))

        self._max_inventory = self._config.get(KEY.MAX_INVENTORY, self._max_qty)
        self._max_inventory = Decimal(str(self._max_inventory))

        self._hold = self._config.get(KEY.HOLD, 5) * KEY.ONE_SECOND

        self._take_profit = self._config.get(KEY.TAKE_PROFIT, 0)
        self._take_profit = Decimal(str(self._take_profit * 1e-4))

        self._side = self._config.get(KEY.SIDE)
        self._side = KEY.LONG if self._side > 0 else KEY.SHORT

        ###########################################
        # Load OPTIONAL config parameters
        ###########################################
        self._direction: int = self._config.get(KEY.DIRECTION, +1)

        ###########################################
        # Create internal variables
        ###########################################
        self._ask_qty: Optional[Decimal] = None
        self._bid_qty: Optional[Decimal] = None

        self._ask_price: Optional[Decimal] = None
        self._bid_price: Optional[Decimal] = None
        self._midpoint: Optional[Decimal] = None

        self._ask_pressure = deque(maxlen=10)
        self._bid_pressure = deque(maxlen=10)

        self._avg_ask_pressure: Optional[Decimal] = None
        self._avg_bid_pressure: Optional[Decimal] = None

        self._current_side: Optional[str] = None

        self._open_orders_ids: Optional[List[str]] = []
        self._open_orders_timestamp: Optional[int] = None
        self._close_orders_ids: List[str] = []

        self._stoploss_state = False

        self._recover_close_orders()

    def onTime(self, timestamp: int):
        super().onTime(timestamp)

        if all([self._ask_qty, self._bid_qty, self.distance]):
            if self.state.get(KEY.MODE, None) != KEY.MODE_HALT:
                self.putBuffer(fields={'quoting': 1})


    def onAccount(self, price: Decimal, qty: Decimal, symbol: str, exchange: str, timestamp: int, latency: int = 0):
        super().onAccount(price, qty, symbol, exchange, timestamp, latency)

        if (symbol, exchange) == (self.products[KEY.DEFAULT].symbol, self.products[KEY.DEFAULT].exchange):

            if qty != self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, None):
                self._logger.warning(f'We have got now inventory: {qty} at price {price}')

                if abs(qty) < KEY.ED and self._stoploss_state:
                    self._logger.warning(f'Zero inventory: clear `stoploss` state')
                    self._stoploss_state = False

                self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.QTY] = qty
                self.state[KEY.INVENTORY][KEY.DEFAULT][KEY.PRICE] = price

                self._post_close_orders(price, qty)

                self.saveState()


    def _recover_close_orders(self, wait: bool=False):
        price = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.PRICE, 0)
        qty = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, 0)

        if abs(qty) > KEY.ED:
            self._logger.warning(f'We have inventory: {qty}@{price}. Cancel ALL orders and post Liquidations')
            self.products[KEY.DEFAULT].oms.Cancel(wait=True)
            self._post_close_orders(price, qty, wait=wait)

    def _get_profit_price(self, qty: Decimal, price: Decimal) -> Decimal:
        coeff = +1 if qty > 0 else -1
        profit = round(price * self._take_profit / self.tick_size) * self.tick_size
        return price + coeff * profit

    def _get_stoploss_price(self, qty: Decimal, price: Decimal) -> Optional[Decimal]:
        if self.distance is not None:
            coeff = -1 if qty > 0 else +1
            stoploss = round(price * self.distance / self.tick_size) * self.tick_size
            return price + coeff * stoploss
        else:
            return None


    def _post_close_orders(self, price: Decimal, qty: Decimal, wait: bool=False):
        if abs(qty) > KEY.ED:
            self._cancel_close_orders(reason='Cancel close orders to replace')

            profit_price = self._get_profit_price(qty, price)
            order = Order(qty=-1 * qty, price=profit_price, liquidation=True)

            id = self.products[KEY.DEFAULT].oms.Post(order, wait=wait)

            self._close_orders_ids.append(id)

            self._logger.warning(f'Post liquidation order with BBO: {self._ask_price}/{self._bid_price}', id=id, qty=order.qty, price=order.price)

            if abs(qty) >= self._max_inventory:
                self._cancel_open_orders('Cancel because of max inventory')

    def _post_open_orders(self, side: str, asks: list, bids: list):
        source = bids if side == KEY.LONG else asks
        fn = math.floor if side == KEY.LONG else math.ceil
        avg = self._avg_bid_pressure if side == KEY.LONG else self._avg_ask_pressure
        coeff = +1 if side == KEY.LONG else -1

        # Find price between best and second
        price = (source[0][0] + source[1][0]) / 2
        price = fn(price / self.tick_size) * self.tick_size

        # Find qty to bet as N% of avg Top5 or `max_qty`
        qty = min([avg * self._max_pct, self._max_qty])
        qty = round(qty / self.min_qty_size) * self.min_qty_size

        # Create order with correct side using exchange rules
        order = Order(qty=coeff * qty, price=price)
        order = self.products[KEY.DEFAULT].oms.applyRules(order)

        id = self.products[KEY.DEFAULT].oms.Post(order)

        self._logger.success(f'Post limit order {order} with id={id}', id=id, qty=order.qty, price=order.price)

        self._open_orders_ids.append(id)
        self._open_orders_timestamp = self._timer.Timestamp()

    def _cancel_open_orders(self, reason: Optional[str] = None):
        if self._open_orders_ids:
            self._logger.info(f'Cleaning open orders: {self._open_orders_ids}', reason=reason)
            self.products[KEY.DEFAULT].oms.Cancel(self._open_orders_ids)
            self._open_orders_ids.clear()
            self._open_orders_timestamp = None

    def _cancel_close_orders(self, reason: Optional[str] = None):
        if self._close_orders_ids:
            self._logger.info(f'Cleaning CLOSE orders: {self._close_orders_ids}', reason=reason)
            self.products[KEY.DEFAULT].oms.Cancel(self._close_orders_ids, wait=True)
            self._close_orders_ids.clear()

    def _check_open_order_lifetime(self):
        if self._open_orders_timestamp is not None:
            age = self._timer.Timestamp() - self._open_orders_timestamp
            if age > self._hold:
                self._cancel_open_orders(reason='Max holding time')

    # def _check_threshold(self) -> bool:
    #     if self.delta is None:
    #         return False
    #
    #     # filter by "delta" sign using self._side parameter
    #     if self._side >= 0 and self.delta > self._threshold[KEY.LONG]:
    #         return True
    #
    #     if self._side <= 0 and self.delta < self._threshold[KEY.SHORT]:
    #         return True
    #
    #     return False


    def _update_ask_bid_pressure(self, asks: list, bids: list):
        self._ask_qty = sum([x for _, x in asks[:5]])
        self._bid_qty = sum([x for _, x in bids[:5]])

        self._ask_pressure.append(self._ask_qty)
        self._bid_pressure.append(self._bid_qty)

        self._avg_ask_pressure = sum(self._ask_pressure) / self._ask_pressure.maxlen
        self._avg_bid_pressure = sum(self._bid_pressure) / self._bid_pressure.maxlen

        return (self._avg_ask_pressure - self._avg_bid_pressure) / (self._avg_ask_pressure + self._avg_bid_pressure)

    def onSnapshot(self, asks: list, bids: list,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):

        super().onSnapshot(asks, bids, symbol, exchange, timestamp, latency)

        # Save current/latest top5 ask/bid qty
        if (symbol, exchange) == (self.products[KEY.DEFAULT].symbol, self.products[KEY.DEFAULT].exchange):

            ratio = self._update_ask_bid_pressure(asks, bids)
            new_side = KEY.POSITIVE if ratio > 0 else KEY.NEGATIVE

            # hit_threshold = self._check_threshold()
            #
            # if not self._open_orders_ids:
            #     if hit_threshold:
            #         inventory = [
            #             abs(x.get(KEY.QTY, 0))
            #             for x in self.state.get(KEY.INVENTORY, {}).values()
            #         ]
            #
            #         if not inventory or \
            #                 inventory and max(inventory) <= self._max_qty:
            #
            #             # get side from delta threshold
            #             side = KEY.LONG if self.delta > self._threshold[KEY.LONG] else KEY.SHORT
            #
            #             # replace side id direction < 0
            #             if self._direction < 0:
            #                 side = KEY.SHORT if side == KEY.LONG else KEY.LONG
            #
            #             self._post_open_orders(side, asks, bids)
            # else:
            #     if not hit_threshold:
            #         age = self._timer.Timestamp() - self._open_orders_timestamp
            #         if age > self._hold:
            #             self._cancel_open_orders()

            self._check_open_order_lifetime()

            if new_side != self._current_side:
                self._current_side = new_side

                if (self._side == KEY.LONG and new_side == KEY.NEGATIVE) or \
                        (self._side == KEY.SHORT and new_side == KEY.POSITIVE):

                    if abs(self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, 0)) < self._max_inventory:
                        if self.isWarmedUp() and not self._stoploss_state:
                            self._post_open_orders(self._side, asks, bids)
                    else:
                        print(f'Too much allocation: {self.state}')

                else:
                    self._cancel_open_orders()

    def onOrderbook(self, askPrice: Decimal, askQty: Decimal, bidPrice: Decimal, bidQty: Decimal,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        super().onOrderbook(askPrice, askQty, bidPrice, bidQty, symbol, exchange, timestamp, latency)

        if (symbol, exchange) == (self.products[KEY.DEFAULT].symbol, self.products[KEY.DEFAULT].exchange):
            self._ask_price, self._bid_price = askPrice, bidPrice
            self._midpoint = (self._ask_price + self._bid_price) / 2

            qty = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.QTY, 0)
            price = self.state[KEY.INVENTORY][KEY.DEFAULT].get(KEY.PRICE, 0)

            if abs(qty) > KEY.ED:
                bbo = self._bid_price if qty < 0 else self._ask_price

                unrealized_pnl = qty * (bbo - price)

                stoploss_price = self._get_stoploss_price(qty, price)

                self.putBuffer(fields={KEY.STOPLOSS: stoploss_price})

                print(self._stoploss_state, qty, self._midpoint, stoploss_price, unrealized_pnl, self.state)

                if qty * (self._midpoint - (stoploss_price or self._midpoint)) < 0 and not self._stoploss_state:

                    order = Order(qty= -1 * qty, liquidation=True)

                    id = self.products[KEY.DEFAULT].oms.Post(order)

                    self.products[KEY.DEFAULT].oms.Cancel(wait=True)

                    self._logger.warning(f'Post LIQUIDATION order {order}', qty=order.qty, midpoint=self._midpoint,
                                         stoploss_price=stoploss_price, id=id)

                    self._stoploss_state = True

                    self.saveState()





    def Clean(self):
        super().Clean()
        self._recover_close_orders(wait=True)