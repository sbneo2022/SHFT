from decimal import Decimal
from pprint import pprint

from bot.clp.conditions.actions import ACTIONS_MAP
from bot.helpers.solve_multilevels import get_buy_sell_multilevels, mix_qty
from lib.async_ejector import FieldsAsyncEjector
from lib.constants import KEY
from lib.exchange import Book, AbstractExchange


def handle_level(self, level_name: str, ask: Decimal, bid: Decimal, latency: int):
    exchange: AbstractExchange = self._exchange

    # Point to current Level in config
    level = self._config[KEY.SPREAD][level_name]

    threshold = KEY.FORCE if self._inside_holding_period(level) else KEY.HYSTERESIS

    if all([level[KEY.BUY], level[KEY.SELL]]):
        distance_pct = {
            KEY.BUY: (bid - level[KEY.BUY]) / level[KEY.DISTANCE][KEY.BUY],
            KEY.SELL: (level[KEY.SELL] - ask) / level[KEY.DISTANCE][KEY.SELL],
        }
        if distance_pct[KEY.BUY] > (1 - level.get(threshold, 0)) and distance_pct[KEY.SELL] > (1 - level.get(threshold, 0)):
            return

    ###############################################################
    # Okay, now we should replace orders
    ###############################################################

    if KEY.MAX_PCT in self._optional.keys():

        for key in [KEY.RATIO + KEY.BUY, KEY.QTY + KEY.BUY]:
            if key not in self._optional.keys():
                return

        buy_max_qty = level[KEY.MAX_QTY] * self._optional[KEY.RATIO + KEY.BUY]
        buy_orderbook = self._optional[KEY.QTY + KEY.BUY]
        buy_orderbook_available = buy_orderbook * self._optional[KEY.MAX_PCT] * self._optional[KEY.RATIO + KEY.BUY]
        buy_orderbook_available = min([buy_orderbook_available, buy_max_qty])

        sell_max_qty = level[KEY.MAX_QTY] * self._optional[KEY.RATIO + KEY.SELL]
        sell_orderbook = self._optional[KEY.QTY + KEY.SELL]
        sell_orderbook_available = sell_orderbook * self._optional[KEY.MAX_PCT] * self._optional[KEY.RATIO + KEY.SELL]
        sell_orderbook_available = min([sell_orderbook_available, sell_max_qty])

        # TODO: delete debug output
        # print(f'BUY side: max_qty:{buy_max_qty} buy_orderbook:{buy_orderbook} available:{buy_orderbook_available}')
        # print(f'SELL side: max_qty:{sell_max_qty} buy_orderbook:{sell_orderbook} available:{sell_orderbook_available}')

    elif (KEY.RATIO + KEY.BUY) in self._optional.keys():
        buy_orderbook_available = level[KEY.MAX_QTY] * self._optional[KEY.RATIO + KEY.BUY]
        sell_orderbook_available = level[KEY.MAX_QTY]

    elif (KEY.RATIO + KEY.SELL) in self._optional.keys():
        buy_orderbook_available = level[KEY.MAX_QTY]
        sell_orderbook_available = level[KEY.MAX_QTY] * self._optional[KEY.RATIO + KEY.SELL]

    else:
        buy_orderbook_available = level[KEY.MAX_QTY]
        sell_orderbook_available = level[KEY.MAX_QTY]

    print(f'Max Buy={buy_orderbook_available}, Max Sell={sell_orderbook_available}')

    buys = self.getMultilevelPrices(level_name=level_name, side=KEY.BUY, max_qty=buy_orderbook_available)
    sells = self.getMultilevelPrices(level_name=level_name, side=KEY.SELL, max_qty=sell_orderbook_available)

    holding_time = self._timer.Timestamp() - (level[KEY.WAS_UPDATE] or 0)

    if threshold == KEY.HYSTERESIS:
        # Replace quotes
        ids_buy = exchange.batchPost(buys)
        ids_sell = exchange.batchPost(sells)
        self._exchange.Cancel(level[KEY.ORDER_ID])

        # Save ids
        level[KEY.ORDER_ID] = [*ids_buy, *ids_sell]

        # Update new Level prices (inner)
        level[KEY.BUY], level[KEY.SELL] = buys[0].price, sells[0].price

        for price, side in [(bid, KEY.BUY), (ask, KEY.SELL)]:
            level[KEY.DISTANCE][side] = abs(level[side] - price)

        self._logger.success(f'Post NEW level "{level_name}"', event='REPLACE',
                             inner_buy_tick=level[KEY.BUY], inner_sell_tick=level[KEY.SELL], holding_time=holding_time * 1e-9)

        # Write outer values to db
        fields = {
                   f'{level_name}_buy': float(buys[-1].price),
                   f'{level_name}_sell': float(sells[-1].price),
                   'quoting': 1 if self._stop_quoting is None else 0,
                 }

        if level[KEY.WAS_UPDATE] is not None:
            fields[f'{level_name}_holding_time'] = holding_time

        level[KEY.WAS_UPDATE] = self._timer.Timestamp()

        FieldsAsyncEjector(self._database, self._timer, **fields).start()

        # Every time we set new levels --> we have to mix Qty
        if KEY.QTY in level.keys():
            level[KEY.QTY] = mix_qty(self.spread[level_name][KEY.QTY], self._min_qty_size)

        elif KEY.PCT in level.keys():
            level[KEY.PCT] = mix_qty(self.spread[level_name][KEY.PCT], Decimal(0.01))

    else:
        self._exchange.Cancel(level[KEY.ORDER_ID])

        level[KEY.ORDER_ID]= []

        self._logger.warning(f'Force Order replace for level "{level_name}": Cancel all')

        level[KEY.BUY], level[KEY.SELL] = None, None
        level[KEY.WAS_UPDATE] = None


def clear_quotes(self):
    # Cancel all open orders synchronously
    self._exchange.Cancel(wait=True)

    for level_name, level in self._config[KEY.SPREAD].items():
        # First we should cancel all open orders
        self._logger.warning(f'Cancel open orders and reset Buy/Sell for level "{level_name}"')
        # self._exchange.Cancel(level[KEY.ORDER_ID])
        level[KEY.BUY], level[KEY.SELL] = None, None
        level[KEY.WAS_UPDATE] = None

    # Cancel another one time because we could have new from async
    self._exchange.Cancel(wait=True)

    # Log "No Quoting" to database
    FieldsAsyncEjector(self._database, self._timer, quoting=0).start()


def check_conditions(self, ask: Decimal, bid: Decimal, latency: int) -> bool:
    """
    Check several contditions and decide should we Quoting or not

    If Not:
      - set time when we should continue to self._stop_quoting
      - Cancel all open orders
      - Clear last Buy/Sell prices for all levels
      - Log message
    If Yes:
      - make self._stop_quoting=True

    :param self: Bot instance
    :param ask: Decimal Ask price
    :param bid: Decimal Bid price
    :param latency:
    :return: True if all conditions Ok, False if we shouldnt Quoting
    """

    ################################################################
    # Check "Stop Quoting" conditions from external source
    ################################################################
    if not self._quoting and self._stop_quoting is None:
        self._logger.error(f'Pause quoting from external event')
        self._stop_quoting = -1 * self._timer.Timestamp()
        clear_quotes(self)
        return False
    elif not self._quoting:
        return False
    elif self._quoting and self._stop_quoting is not None and self._stop_quoting < 0:
        self._logger.error(f'Continue quoting from external event')
        self._stop_quoting = None

    ################################################################
    # Check spread and Latency conditions
    ################################################################
    spread = 2 * (ask - bid) / (ask + bid)
    mean_spread = sum(self._spread_buffer) / len(self._spread_buffer) if self._spread_buffer else 0
    self._spread_buffer.append(spread)

    if isinstance(self._stop_quoting, int) and self._timer.Timestamp() < self._stop_quoting:
        return False

    if len(self._spread_buffer) == self._max_spread_count:
        ok_spread_peak = spread / mean_spread - 1 < self._max_ratio_spread
    else:
        ok_spread_peak = True


    ok_exchange = self._exchange.isOnline()

    try:
        ok_atr = self._used_atr < self._max_atr
    except:
        ok_atr = True

    ################################################################
    # If something goes wrong: STOP QUOTING for target time
    ################################################################
    if not all([ok_spread_peak, ok_exchange, ok_atr]):
        penalty = 0

        if not ok_spread_peak:
            penalty = self._high_ratio_spread_pause
            self._logger.error(f'Pause quoting because of SPREAD jump up more {self._max_ratio_spread * 100}% '
                               f'than {self._max_spread_count} spread values average',
                               event='STOP', mean=mean_spread, spread=spread)

        if not ok_exchange:
            penalty = self._high_api_pause
            self._logger.error(f'Stop quoting because EXCHANGE error: API limits? Block for {self._high_api_pause // KEY.ONE_SECOND}s',
                               event='STOP')

        if not ok_atr:
            penalty = self._high_atr_pause
            self._logger.error(f'Stop quoting because ATR too high. Block for {self._high_atr_pause // KEY.ONE_SECOND}s',
                               event='STOP')

        if self._stop_quoting is None:
            # Cancel orders and reset Buy/Sell for all levels
            clear_quotes(self)

        self._stop_quoting = self._timer.Timestamp() + penalty

        return False

    else:
        if isinstance(self._stop_quoting, int):
            self._logger.warning(f'Continue quoting', mean=mean_spread, spread=spread, latency=latency)

        self._stop_quoting = None
        return True


def _check_conditions(self):
    any_condition = False
    quoting_now = self._stop_quoting is None

    for item in self._conditions:
        payload = item[KEY.FN](self, item[KEY.PARAMS])

        if isinstance(self._stop_quoting, int) and self._timer.Timestamp() < self._stop_quoting:
            any_condition = True

        elif payload is not None:
            any_condition = True
            actions = item.get(KEY.PARAMS, {}).get(KEY.ACTION, [])
            for action in actions:
                ACTIONS_MAP[action[KEY.ACTION]](
                    self,
                    action[KEY.VALUE],
                    tag=payload.get(KEY.TAG, '')
                )

            self._logger.warning(**payload)

    if quoting_now and self._stop_quoting is not None:
        clear_quotes(self)

    return any_condition


def handle_quote(self, ask: Decimal, bid: Decimal, latency: int):
    # TODO: Make all conditions here
    if _check_conditions(self):
        return

    # Check various conditions and skip event if we should skip
    if not check_conditions(self, ask, bid, latency):
        return

    for level_name, level in self._config[KEY.SPREAD].items():
        # Check (or get) FORCE parameter from Level data
        # With this parameter we can exit from open positions
        # even before holding time
        force = level.get(KEY.FORCE, None)

        # If we have update orders --> skip given Level
        # IF current level have no FORCE parameter
        # With FORCE parameter we check distance constantly

        # inside = self._inside_holding_period(level)
        # if level_name == 'outer':
        #     print(inside, level)

        if self._inside_holding_period(level) and force is None:
            continue

        # Will not quote till we have right distance (could be based on additional data)
        if self._distance is None:
            continue

        # Process given Level
        handle_level(self, level_name, ask, bid, latency)

