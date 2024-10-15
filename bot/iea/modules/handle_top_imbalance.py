from collections import deque, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Dict

from bot import AbstractBot
from bot.iea.modules.handle_buffer import HandleBuffer
from bot.iea.modules.handle_exchange import HandleExchange
from lib.constants import KEY
from lib.defaults import DEFAULT
from lib.factory import AbstractFactory
from lib.helpers import sign
from lib.timer import AbstractTimer

@dataclass
class Imbalance:
    ask_bid_ratio: Optional[Decimal] = None
    ask_average_sum: Optional[Decimal] = None
    bid_average_sum: Optional[Decimal] = None

class HandleTopImbalance(
    HandleExchange,
    HandleBuffer,
    AbstractBot,
):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        ################################################################
        # Load parameter from config
        ################################################################
        self._max_deque = int(self._config.get(KEY.DEQUE, DEFAULT.MAX_DEQUE))

        ################################################################
        # Internal variables to handle orderbook data
        ################################################################
        self._ask_pressure: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self._max_deque))
        self._bid_pressure: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self._max_deque))

        ################################################################
        # Public variables
        ################################################################

        self.ask_bid_ratio: Optional[Decimal] = None
        self.ask_average_sum: Optional[Decimal] = None
        self.bid_average_sum: Optional[Decimal] = None
        self.top_imbalance: Dict[str, Imbalance] = defaultdict(lambda: Imbalance())


    def onSnapshot(self, asks: list, bids: list,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        super().onSnapshot(asks, bids, symbol, exchange, timestamp, latency)

        target = self.products_map[(symbol, exchange)]

        ask_qty = sum([x for _, x in asks[:5]])
        bid_qty = sum([x for _, x in bids[:5]])

        self._ask_pressure[target].append(ask_qty)
        self._bid_pressure[target].append(bid_qty)

        if len(self._ask_pressure[target]) == self._max_deque:
            self.top_imbalance[target].ask_average_sum = sum(self._ask_pressure[target]) / self._max_deque
            self.top_imbalance[target].bid_average_sum = sum(self._bid_pressure[target]) / self._max_deque

            _sign = sign(self.top_imbalance[target].ask_average_sum - self.top_imbalance[target].bid_average_sum)

            _max = max(self.top_imbalance[target].ask_average_sum, self.top_imbalance[target].bid_average_sum)
            _min = min(self.top_imbalance[target].ask_average_sum, self.top_imbalance[target].bid_average_sum)

            self.top_imbalance[target].ask_bid_ratio = _sign * _max / _min

            if target == KEY.DEFAULT:
                # Log values to database
                self.putBuffer({
                    'ask_average_sum': self.ask_average_sum,
                    'bid_average_sum': self.bid_average_sum,
                    'ask_bid_ratio': self.ask_bid_ratio,
                })

                self.ask_bid_ratio = self.top_imbalance[KEY.DEFAULT].ask_bid_ratio
                self.ask_average_sum = self.top_imbalance[KEY.DEFAULT].ask_average_sum
                self.bid_average_sum = self.top_imbalance[KEY.DEFAULT].bid_average_sum

