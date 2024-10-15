from decimal import Decimal
from typing import List

from bot.clp.mode.handle_multilevels import get_buy_sell_multilevels
from lib.async_ejector import FieldsAsyncEjector
from lib.constants import KEY

from lib.exchange import Order


def get_qwap(self, orders: List[Order]) -> Decimal:
    pq = sum(x.price * x.qty for x in orders)

    qty_sum = sum(x.qty for x in orders)

    price = pq / qty_sum

    return round(price / self._tick_size) * self._tick_size


def handle_event(self, qty: list, trigger: Decimal, current: Decimal, side: str) -> bool:
    if side == KEY.BUY and current < trigger:
        return False

    if side == KEY.SELL and current > trigger:
        return False

    qty = abs(self._qty_coeff * sum(qty))
    qty = round(qty / self._min_qty_size) * self._min_qty_size
    qty = qty if side == KEY.BUY else -1 * qty

    id = self._exchange.Post(qty)
    self._logger.warning(f'Hit momentum level. Send MARKET order.', event='MOMENTUM',
                         orderId=id, current=current, trigger=trigger, qty=qty)

    return True

def replace_levels(self, level_name: str, ask: Decimal, bid: Decimal, latency: int):
    # Point to current Level in config
    level = self._config[KEY.SPREAD][level_name]

    buys, sells = get_buy_sell_multilevels(
        min_qty_size=self._min_qty_size,
        tick_size=self._tick_size,
        ask_price=ask,
        bid_price=bid,
        spread_value=level[KEY.VALUE],
        ask_qtys=level[KEY.QTY],
        bid_qtys=level[KEY.QTY],
        gap=level[KEY.GAP],
        min=level[KEY.MIN]
    )

    buy_level = get_qwap(self, sells)
    sell_level = get_qwap(self, buys)

    holding_time = self._timer.Timestamp() - (level[KEY.WAS_UPDATE] or 0)

    # Update new Level prices (inner)
    level[KEY.BUY], level[KEY.SELL] = buys[-1].price, sells[-1].price

    for price, side in [(bid, KEY.BUY), (ask, KEY.SELL)]:
        level[KEY.DISTANCE][side] = abs(level[side] - price)

    self._logger.success(f'Set NEW level "{level_name}"', event='REPLACE',
                         buy_price=level[KEY.BUY], sell_price=level[KEY.SELL], holding_time=holding_time * 1e-9)

    # Write outer values to db
    fields = {
               f'{level_name}_buy': float(buy_level),
               f'{level_name}_sell': float(sell_level),
               'quoting': 1 if self._stop_quoting is None else 0,
             }

    for idx, order in enumerate(buys):
        fields[f'{level_name}_quote_buy_{idx}'] = float(order.price)

    for idx, order in enumerate(sells):
        fields[f'{level_name}_quote_sell_{idx}'] = float(order.price)

    if level[KEY.WAS_UPDATE] is not None:
        fields[f'{level_name}_holding_time'] = holding_time

    FieldsAsyncEjector(self._database, self._timer, **fields).start()

    level[KEY.WAS_UPDATE] = self._timer.Timestamp()


def handle_level(self, level_name: str, ask: Decimal, bid: Decimal, latency: int):
    # Point to current Level in config
    level = self._config[KEY.SPREAD][level_name]

    hit_buy, hit_sell = False, False
    if all([level[KEY.BUY], level[KEY.SELL]]):
        hit_sell = handle_event(self, qty=level[KEY.QTY], trigger=level[KEY.BUY], current=ask, side=KEY.SELL)
        hit_buy = handle_event(self, qty=level[KEY.QTY], trigger=level[KEY.SELL], current=bid, side=KEY.BUY)

    if any([hit_buy, hit_sell]):
        replace_levels(self, level_name, ask, bid, latency)
    else:
        # Lets check are we inside target holding period or not
        if self._inside_holding_period(level):
            # If we are inside and not "force" key --> no replace till the end
            if KEY.FORCE not in level:
                return
            threshold = KEY.FORCE
        else:
            threshold = KEY.HYSTERESIS

        if all([level[KEY.BUY], level[KEY.SELL]]) and not any([hit_buy, hit_sell]):
            distance_pct = {
                KEY.BUY: (bid - level[KEY.BUY]) / level[KEY.DISTANCE][KEY.BUY],
                KEY.SELL: (level[KEY.SELL] - ask) / level[KEY.DISTANCE][KEY.SELL],
            }
            if distance_pct[KEY.BUY] > (1 - level.get(threshold, 0)) and distance_pct[KEY.SELL] > (1 - level.get(threshold, 0)):
                return
        replace_levels(self, level_name, ask, bid, latency)


def check_conditions(self, ask, bid, latency):
    if isinstance(self._stop_quoting, int) and self._timer.Timestamp() < self._stop_quoting:
        return False

    ok_latency = latency < self._max_latency

    ok_allocation = abs(self._state.get(KEY.QTY, 0)) < self._max_available_allocation

    ok_exchange = self._exchange.isOnline()

    if not all([ok_allocation, ok_exchange, ok_latency]):
        penalty = 0

        if not ok_latency:
            penalty = self._high_latency_pause
            self._logger.error(f'Stop quoting because of HIGH LATENCY and block for {self._high_latency_pause // KEY.ONE_SECOND}s',
                               event='STOP', latency=latency)

        if not ok_allocation:
            penalty = self._high_allocation_pause
            self._logger.error(f'Stop quoting because HIGH ALLOCATION for {self._high_allocation_pause // KEY.ONE_SECOND}s',
                               event='STOP', allocation=self._state[KEY.QTY])

        if not ok_exchange:
            penalty = self._high_api_pause
            self._logger.error(f'Stop quoting because EXCHANGE error: API limits? Block for {self._high_api_pause // KEY.ONE_SECOND}s',
                               event='STOP')

        self._stop_quoting = self._timer.Timestamp() + penalty

        return False

    else:
        if isinstance(self._stop_quoting, int):
            self._logger.warning(f'Continue quoting', latency=latency)

        self._stop_quoting = None
        return True

def handle_momentum(self, ask: Decimal, bid: Decimal, latency: int):
    # Check various conditions and skip event if we should skip
    if not check_conditions(self, ask, bid, latency):
        return

    # Will not quote till we have right distance (could be based on additional data)
    if self._distance is None:
        return

    order = self._event.Get()

    if order is not None:
        self._stop_quoting = self._timer.Timestamp() + 1 * KEY.ONE_SECOND
        id = self._exchange.Post(order.qty)
        self._logger.warning(f'Hit momentum level. Send MARKET order.', event='MOMENTUM',
                             orderId=id, ask=ask, bid=bid, qty=order.qty)