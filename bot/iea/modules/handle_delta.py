from decimal import Decimal
from typing import Optional

from bot import AbstractBot
from bot.iea.modules.handle_buffer import HandleBuffer
from lib.constants import KEY
from lib.factory import AbstractFactory
from lib.timer import AbstractTimer


class HandleDelta(
    HandleBuffer,
    AbstractBot,
):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        # to make code general --> get target products independently
        self._target_symbol = config[KEY.SYMBOL]
        self._target_exchange = config[KEY.EXCHANGE]

        self._delta_symbol = config[KEY.DELTA][KEY.SYMBOL]
        self._delta_exchange = config[KEY.DELTA][KEY.EXCHANGE]


        ################################################################
        # Load parameter from config
        ################################################################
        self._formula: str = config.get(KEY.FORMULA, 'ask')
        self._ask_bid = 'ASK' in self._formula.upper()


        ################################################################
        # Internal variables to handle orderbook data
        ################################################################
        self._target_ask: Optional[Decimal] = None
        self._target_bid: Optional[Decimal] = None
        self._target_midpoint: Optional[Decimal] = None

        self._delta_ask: Optional[Decimal] = None
        self._delta_bid: Optional[Decimal] = None
        self._delta_midpoint: Optional[Decimal] = None

        self._target_funding_rate: Optional[Decimal] = None
        self._delta_funding_rate: Optional[Decimal] = None

        ################################################################
        # Public variables
        ################################################################
        self.delta: Optional[Decimal] = None


    def onMessage(self, message: dict,
                  timestamp: int, latency: int = 0):
        super().onMessage(message, timestamp, latency)

        if message[KEY.TYPE] == KEY.FUNDING_RATE \
            and message[KEY.SYMBOL] == self._target_symbol \
            and message[KEY.EXCHANGE] == self._target_exchange:

            self._target_funding_rate = Decimal(message[KEY.FUNDING_RATE])

        elif message[KEY.TYPE] == KEY.FUNDING_RATE \
            and message[KEY.SYMBOL] == self._delta_symbol \
            and message[KEY.EXCHANGE] == self._delta_exchange:

            self._delta_funding_rate = Decimal(message[KEY.FUNDING_RATE])

        else:
            return

    def onOrderbook(self, askPrice: Decimal, askQty: Decimal, bidPrice: Decimal, bidQty: Decimal,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):

        super().onOrderbook(askPrice, askQty, bidPrice, bidQty, symbol, exchange, timestamp, latency)

        if (symbol, exchange) == (self._target_symbol, self._target_exchange):
            new = self._update_target_bbo(askPrice, bidPrice)

        elif (symbol, exchange) == (self._delta_symbol, self._delta_exchange):
            new = self._update_delta_bbo(askPrice, bidPrice)

        else:
            return

        if new:
            self.delta = self._find_delta()
            self.putBuffer(fields={KEY.DELTA: self.delta})

    def _update_target_bbo(self, askPrice: Decimal, bidPrice: Decimal) -> bool:
        if self._target_ask != askPrice or self._target_bid != bidPrice:
            self._target_ask, self._target_bid = askPrice, bidPrice
            self._target_midpoint = (askPrice + bidPrice) / 2
            self._target_last_update_timestamp = self._timer.Timestamp()
            return True
        else:
            return False

    def _update_delta_bbo(self, askPrice: Decimal, bidPrice: Decimal) -> bool:
        if self._delta_ask != askPrice or self._delta_bid != bidPrice:
            self._delta_ask, self._delta_bid = askPrice, bidPrice
            self._delta_midpoint = (askPrice + bidPrice) / 2
            self._delta_last_update_timestamp = self._timer.Timestamp()
            return True
        else:
            return False

    def _find_delta(self) -> Optional[Decimal]:
        if not all([
            self._target_funding_rate,
            self._target_ask,
            self._target_bid,

            self._delta_funding_rate,
            self._delta_ask,
            self._delta_bid,
        ]):
            return

        if self._ask_bid:
            a = self._delta_bid / (1 + self._delta_funding_rate)
            b = self._target_ask / (1 + self._target_funding_rate)
        else:
            a = self._delta_ask / (1 + self._delta_funding_rate)
            b = self._target_bid / (1 + self._target_funding_rate)

        midpoint = sum([self._target_ask, self._target_bid, self._delta_ask, self._delta_bid]) / 4

        return Decimal(1e4) * (a - b) / midpoint
