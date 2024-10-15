from decimal import Decimal
from typing import Optional, List, Union, Dict

from bot import AbstractBot
from bot.iea.modules.handle_exchange import HandleExchange
from lib.constants import KEY, ORDER_TAG
from lib.exchange import Order
from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer


SPREAD_ADDITIONAL_FIELDS = [KEY.GAP, KEY.VALUE, KEY.MIN]

class HandleSpread(HandleExchange, AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        self._logger: AbstractLogger = factory.Logger(config, factory, timer)

        self._bbo: Dict[str, Dict[str, Optional[Decimal]]] = {}

        ################################################################
        # Public variables
        ################################################################
        self.spread = self._load_spread()

        ################################################################
        # Load global spread coeff and log if it != 1
        ################################################################
        self._scale = self._config.get(KEY.SCALE, 1)
        self._scale = Decimal(str(self._scale))
        if self._scale != 1:
            self._logger.info(f'Qty scale is not 1: scale={self._scale}', scale=self._scale)




    def onOrderbook(self, askPrice: Decimal, askQty: Decimal, bidPrice: Decimal, bidQty: Decimal,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        super().onOrderbook(askPrice, askQty, bidPrice, bidQty, symbol, exchange, timestamp, latency)

        product_pair = (symbol, exchange)

        if product_pair in self.products_map.keys():
            target = self.products_map[product_pair]
            self._bbo[target] = {
                KEY.ASK_PRICE: askPrice,
                KEY.BID_PRICE: bidPrice,
            }

    def getMultilevelPrices(self,
                            level_name: str,
                            side: str,
                            max_qty: Optional[Union[Decimal, int]] = None,
                            target: str = KEY.DEFAULT) -> List[Order]:

        # Return empty list if no ask/bid price received yet
        ask = self._bbo[target].get(KEY.ASK_PRICE, None)
        bid = self._bbo[target].get(KEY.BID_PRICE, None)

        if not all([ask, bid]):
            return []

        tag = f'{ORDER_TAG.LIMIT}{level_name.upper()[0]}'

        midpoint, spread = (ask + bid) / 2, ask - bid

        min_gap = midpoint * (self.spread[level_name][KEY.GAP] or Decimal(0))

        high = midpoint * Decimal(0.5) * self.spread[level_name][KEY.VALUE] or Decimal(0)

        if max_qty is None:
            max_qty = self.spread[level_name][KEY.MAX_QTY] or Decimal(0)

        elif self.spread[level_name][KEY.MAX_QTY] is not None:
            max_qty = min(max_qty, self.spread[level_name][KEY.MAX_QTY])

        # Apply scale to max_qty
        max_qty = max_qty * self._scale

        qtys = [max_qty * x for x in self.spread[level_name][KEY.PCT]]

        items = len(qtys)

        if self.spread[level_name][KEY.MIN] is None:
            if min_gap > 0:
                low = min_gap + spread / 2
            else:
                low = high - items + 1
        else:
            low = midpoint * self.spread[level_name][KEY.MIN] / 2

        step = 0 if items < 2 else (high - low) / (items - 1)

        direction, rule = (+1, KEY.UP) if side in [KEY.BUY, KEY.LONG] else (-1, KEY.DOWN)

        orders = [
            self.products[target].oms.applyRules(
                Order(
                    qty=direction * qty,
                    price=midpoint - direction * (high - step * idx),
                    tag=f'{tag}{items - idx}'
                ),
                rule=rule
            )
            for idx, qty in enumerate(qtys[::-1])
        ]

        return orders[::-1]

    def _load_spread(self):
        payload = {}

        for key, value in self._config.get(KEY.SPREAD, {}).items():
            if not isinstance(value, dict):
                continue

            if KEY.QTY in value.keys() and value[KEY.QTY]:
                qty = value[KEY.QTY]

                if not isinstance(qty, list):
                    qty = [qty]

                max_qty = Decimal(str(sum(qty)))

                if max_qty > 0:
                    pct = [Decimal(str(x)) / max_qty for x in qty]
                else:
                    pct = []

            elif KEY.PCT in value.keys():
                pct = value[KEY.PCT]

                if not isinstance(pct, list):
                    pct = [pct]

                if '-' in pct:
                    given_values = [Decimal(str(x)) for x in pct if not isinstance(x, str)]
                    last_value = max(0, 1 - sum(given_values))
                    pct = [*given_values, last_value]

                if sum(pct) > 0:
                    pct = [Decimal(str(x)) for x in pct if x > 0]
                else:
                    pct = []

                if KEY.MAX_QTY in value.keys():
                    max_qty = Decimal(str(value[KEY.MAX_QTY]))
                else:
                    max_qty = None

            else:
                continue

            if pct:

                payload[key] = {KEY.PCT: pct, KEY.MAX_QTY: max_qty}

                for item in SPREAD_ADDITIONAL_FIELDS:
                    try:
                        payload[key][item] = Decimal(str(value[item]))
                    except:
                        payload[key][item] = None

        return payload



