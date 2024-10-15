from decimal import Decimal
from typing import Optional

from bot import AbstractBot
from bot.clp.clp_atr import CLPATR
from bot.clp.mode.handle_inventory_dynamic_partial import handle_inventory_dynamic_partial
from bot.clp.mode.handle_quote import handle_quote
from bot.iea.modules.handle_liquidation import HandleLiquidation
from bot.iea.modules.handle_top_imbalance import HandleTopImbalance
from lib.constants import KEY
from lib.factory import AbstractFactory
from lib.timer import AbstractTimer


class CLPATRPartialImbalanceConditions(
    CLPATR,
    HandleLiquidation,
    HandleTopImbalance,
    AbstractBot
):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):

        super().__init__(config, factory, timer)

        self._ratio_reduce_threshold = Decimal(str(self._config['ratio_reduce_threshold']))
        self._ratio_stop_threshold = Decimal(str(self._config['ratio_stop_threshold']))

        self._ratio_reduce_pct = Decimal(str(self._config['ratio_reduce_pct']))

        self._ratio_reduce_pause = self._config['ratio_reduce_pause'] * KEY.ONE_SECOND
        self._ratio_stop_pause = self._config['ratio_stop_pause'] * KEY.ONE_SECOND

        self._ratio_state = KEY.STATE_NORMAL
        self._make_normal_timestamp: Optional[int] = None


    def onSnapshot(self, asks: list, bids: list,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        super().onSnapshot(asks, bids, symbol, exchange, timestamp, latency)

        # We are not handle orderbook imbalance while have no all indicators
        if not all([self.ask_bid_ratio, self.ask_average_sum, self.bid_average_sum]):
            return

        # We are in LOW range of imbalance
        if self._ratio_reduce_threshold < abs(self.ask_bid_ratio) <= self._ratio_stop_threshold:

            # If state already LOW or STOP --> do nothing
            if self._ratio_state in [KEY.LOW, KEY.STOP]:
                return

            # If state == NORMAL --> reduce qty and, state LOW and CANCEL all open orders
            self._ratio_state = KEY.LOW

            if self.ask_bid_ratio > 0:
                self._optional[KEY.RATIO + KEY.BUY] = 1 - self._ratio_reduce_pct
            else:
                self._optional[KEY.RATIO + KEY.SELL] = 1 - self._ratio_reduce_pct

            self._exchange.Cancel(wait=True)

            self._logger.warning(f'Ratio now in LOW state. Reduce one side', optional=self._optional,
                                 ratio=self.ask_bid_ratio)

        # We are in STOP range of imbalance
        elif abs(self.ask_bid_ratio) > self._ratio_stop_threshold:

            # If we are already in STOP state --> do nothing
            if self._ratio_state == KEY.STOP:
                return

            self._ratio_state = KEY.STOP

            if self.ask_bid_ratio > 0:
                self._optional[KEY.RATIO + KEY.BUY] = 0
            else:
                self._optional[KEY.RATIO + KEY.SELL] = 0

            self._exchange.Cancel(wait=True)

            self.liquidate(1)

            self._logger.warning(f'Ratio now in STOP state. Stop one side and liquidate inventory',
                                 optional=self._optional, ratio=self.ask_bid_ratio)

        else:
            if self._ratio_state in [KEY.LOW, KEY.STOP]:
                if self._make_normal_timestamp is None:
                    penalty = self._ratio_reduce_pause if self._ratio_state == KEY.LOW else self._ratio_stop_pause
                    self._make_normal_timestamp = self._timer.Timestamp() + penalty

                    self._logger.warning(f'Ratio now in NORMAL. Add penalty',
                                         ratio=self.ask_bid_ratio, penalty=penalty // KEY.ONE_SECOND)

                elif self._timer.Timestamp() > self._make_normal_timestamp:

                    for key in [KEY.BUY, KEY.SELL]:
                        if (KEY.RATIO + key) in self._optional:
                            del self._optional[KEY.RATIO + key]

                    self._make_normal_timestamp = None
                    self._ratio_state = KEY.STATE_NORMAL

                    self._logger.warning(f'Ratio now in NORMAL. Quotes are normal',
                                         ratio=self.ask_bid_ratio)


    def _handle_new_orderbook_event(self, askPrice, bidPrice, latency):
        if self._state[KEY.MODE] == KEY.MODE_HALT:
            pass

        elif self._state[KEY.MODE] == KEY.MODE_EMPTY:
            if self._handle_quote:
                handle_quote(self, askPrice, bidPrice, latency)

        elif self._state[KEY.MODE] == KEY.MODE_INVENTORY:
            if self._handle_quote:
                handle_quote(self, askPrice, bidPrice, latency)
            if self._handle_inventory:
                handle_inventory_dynamic_partial(self, askPrice, bidPrice)
