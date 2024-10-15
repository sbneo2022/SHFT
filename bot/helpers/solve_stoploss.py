import math
from decimal import Decimal
from typing import Union

from lib.exchange import AbstractExchange
from lib.helpers import sign


def get_stoploss_price(
        exchange: AbstractExchange,  # Exchange object --> we need `tick_size` only, but using AbstractExchange for future improvenets
        qty: Decimal,  # Position to solve Stoploss --> actually we r using sign only
        price: Decimal,  # Reference price to Stoploss --> could Entry price, or current Orderbook price (midpoint?)
        distance: Union[Decimal, int], # Target stoploss distance, like 0.002 --> 0.2% below
    ) -> Decimal:

    price_in_ticks = int(price / exchange.getTick())

    distance_in_ticks = int(price * distance / exchange.getTick())

    stoploss_in_ticks = price_in_ticks - sign(qty) * distance_in_ticks

    return stoploss_in_ticks * exchange.getTick()


def get_zero_price(
        exchange: AbstractExchange,  # Used for `tick_size`
        qty: Decimal, #  Order Qty --> used for `sign`
        entry: Decimal, # Entry price (Average Entry Price)
        fee: Union[Decimal, int], # Fee for one transaction (Post) --> will be doubled
    ) -> Decimal:

    entry_in_ticks = int(entry / exchange.getTick())  # Entry price in ticks

    fee_in_ticks = math.ceil(2 * fee * entry)  #

    zero_price_in_ticks = entry_in_ticks + sign(qty) * fee_in_ticks

    return zero_price_in_ticks * exchange.getTick()

def is_profit(
        qty: Decimal,  # Order Qty --> used for `sign`
        price: Decimal, #
        zero_price: Decimal,
    ) -> bool:
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