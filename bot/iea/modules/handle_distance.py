import math
from decimal import Decimal
from typing import Optional, Union

from bot import AbstractBot
from bot.iea.modules.handle_atr import HandleATR
from bot.iea.modules.handle_exchange import HandleExchange
from lib.constants import KEY
from lib.defaults import DEFAULT
from lib.factory import AbstractFactory
from lib.helpers import sign
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer


class HandleDistance(HandleATR, HandleExchange, AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        self._logger: AbstractLogger = factory.Logger(config, factory, timer)

        self._fee = config.get(KEY.FEE, Decimal(0))
        self._fee = Decimal(str(self._fee))
        self._logger.info(f'Used exchange fee = {(10_000 * self._fee):.1f}bps ({self._fee})', fee=self._fee)

        # Load and print stoploss_coeff (function from ATR)
        self._stoploss_coeff = config.get(KEY.STOPLOSS_COEFF, DEFAULT.STOPLOSS_COEFF)
        self._stoploss_coeff = Decimal(str(self._stoploss_coeff))
        self._logger.info(f'Used ATR/Stoploss Coeff = {self._stoploss_coeff}', stoploss_coeff=self._stoploss_coeff)

        ################################################################
        # Public variables
        ################################################################
        self.distance: Optional[Decimal] = None


    def onCandle(self, open: Decimal, high: Decimal, low: Decimal, close: Decimal, volume: Decimal,
                 symbol: str, exchange: str,
                 timestamp: int, latency: int = 0, finished: bool = True):

        super().onCandle(open, high, low, close, volume, symbol, exchange, timestamp, latency, finished)

        # Skip other than target products
        if (symbol, exchange) != (self._config[KEY.SYMBOL], self._config[KEY.EXCHANGE]):
            return

        # Skip if ATR are not calculated yet
        if self.atr is None:
            return

        # Update Distance
        if self.distance is None or finished:
            self.distance = self._stoploss_coeff * self.atr

            self._logger.warning(f'Set new stoploss Distance={self.distance}', event='STOPLOSS',
                                 distance=self.distance, atr=self.atr)

    def getStoplossPrice(self,
                         qty: Decimal,  # Position to solve Stoploss --> actually we r using sign only
                         price: Decimal,  # Reference price to Stoploss --> could Entry price, or current Orderbook price (midpoint?)
                         distance: Union[Decimal, int],  # Target stoploss distance, like 0.002 --> 0.2% below
                         ) -> Decimal:
        price_in_ticks = int(price / self.tick_size)

        distance_in_ticks = int(price * distance / self.tick_size)

        stoploss_in_ticks = price_in_ticks - sign(qty) * distance_in_ticks

        return stoploss_in_ticks * self.tick_size

    def getZeroPrice(self,
                     qty: Decimal,  #  Order Qty --> used for `sign`
                     entry: Decimal,  # Entry price (Average Entry Price)
                     ) -> Decimal:

        entry_in_ticks = int(entry / self.tick_size)  # Entry price in ticks

        fee_in_ticks = math.ceil(2 * self._fee * entry)  #

        zero_price_in_ticks = entry_in_ticks + sign(qty) * fee_in_ticks

        return zero_price_in_ticks * self.tick_size

    @staticmethod
    def isProfit(qty: Decimal, price: Decimal, zero_price: Decimal) -> bool:
        """

        :param qty: Position Qty
        :param price: Current Price
        :param zero_price: Zero Price from `get_zero_price` fn --> price when we became positive
        :return: True --> price > zero_price for LONG or price < zero_price for SHORT
        """
        if qty > 0:
            return price >= zero_price
        else:
            return price <= zero_price
