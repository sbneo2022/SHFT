import math
from decimal import Decimal
from pprint import pprint
from typing import Optional

from bot import AbstractBot
from lib.async_ejector import FieldsAsyncEjector
from lib.constants import KEY
from lib.exchange import Order


class PriceEvent:
    def __init__(self, config: dict, bot: AbstractBot):
        self._config = config
        self._bot = bot

        self._ask: Optional[Decimal] = None
        self._bid: Optional[Decimal] = None

        self._buy: Optional[Decimal] = None
        self._sell: Optional[Decimal] = None
        self._distance = {}

        # Scan all "spread" values and get lowest one based on "value" field
        self._level = sorted(
            [x for x in config[KEY.SPREAD].values()],
            key=lambda x: x[KEY.VALUE],
            reverse=False
        )[0]

    def Update(self, ask: Decimal, bid: Decimal):
        self._ask = ask
        self._bid = bid

    def _handle_event(self, trigger: Decimal, current: Decimal,
                      side: str) -> Optional[Order]:
        if side == KEY.BUY and current < trigger:
            return None

        if side == KEY.SELL and current > trigger:
            return None

        qty = abs(self._bot._qty_coeff * sum(self._level[KEY.QTY]))
        qty = round(qty / self._bot._min_qty_size) * self._bot._min_qty_size
        qty = qty if side == KEY.BUY else -1 * qty

        return Order(qty=qty)

    def _replace_levels(self):
        midpoint = (self._ask + self._bid) / 2

        holding_time = self._bot._timer.Timestamp() - (self._level[KEY.WAS_UPDATE] or 0)

        self._sell = midpoint * (1 - self._level[KEY.VALUE] / 2)
        self._sell = math.ceil(self._sell / self._bot._tick_size) * self._bot._tick_size

        self._buy = midpoint * (1 + self._level[KEY.VALUE] / 2)
        self._buy = math.floor(self._buy / self._bot._tick_size) * self._bot._tick_size

        self._distance[KEY.BUY] = abs(self._buy - self._ask)
        self._distance[KEY.SELL] = abs(self._sell - self._bid)

        self._bot._logger.success(f'Set new triggers', event='REPLACE',
                             buy_price=self._buy, sell_price=self._sell, holding_time=holding_time * 1e-9)

        # Write outer values to db
        fields = {
            f'buy': float(self._buy),
            f'sell': float(self._sell),
            'quoting': 1 if self._bot._stop_quoting is None else 0,
        }

        if self._level[KEY.WAS_UPDATE] is not None:
            fields[f'holding_time'] = holding_time

        FieldsAsyncEjector(self._bot._database, self._bot._timer, **fields).start()

        self._level[KEY.WAS_UPDATE] = self._bot._timer.Timestamp()


    def Get(self) -> Optional[Order]:
        # No orders if no "ask" or "bid" price
        if not all([self._ask, self._bid]):
            return

        if all([self._buy, self._sell]):
            order = self._handle_event(trigger=self._buy, current=self._ask, side=KEY.BUY)
            if order is not None:
                self._buy, self._sell = None, None
                return order

            order = self._handle_event(trigger=self._sell, current=self._bid, side=KEY.SELL)
            if order is not None:
                self._buy, self._sell = None, None
                return order


        # Lets check are we inside target holding period or not
        if self._bot._inside_holding_period(self._level):
            # If we are inside and not "force" key --> no replace till the end
            if KEY.FORCE not in self._level:
                return

            if self._level[KEY.FORCE] is None:
                return

            threshold = KEY.FORCE
        else:
            threshold = KEY.HYSTERESIS

        if all([self._buy, self._sell]):
            distance_pct = {
                KEY.BUY: (self._buy - self._ask) / self._distance[KEY.BUY],
                KEY.SELL: (self._bid - self._sell) / self._distance[KEY.SELL],
            }
            if distance_pct[KEY.BUY] > (1 - self._level.get(threshold, 0)) \
                    and distance_pct[KEY.SELL] > (1 - self._level.get(threshold, 0)):
                return

        self._replace_levels()

