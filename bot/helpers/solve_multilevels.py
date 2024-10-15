import math
import random
from decimal import Decimal
from typing import List, Tuple

from lib.constants import ORDER_TAG, KEY
from lib.defaults import DEFAULT
from lib.exchange import Order, AbstractExchange, Book

"""
Simple Qty function: returns original Qty "as is"
"""
def raw_qty(qty, min_qty_size,
            max_deviation=DEFAULT.QTY_DEVIATION_PLUS, min_deviation=DEFAULT.QTY_DEVIATION_MINUS):
    return qty

"""
Rand Qty function: mix qty +/- "max_deviation" for n-1 levels, put rest to n level
"""
def mix_qty(qty, min_qty_size,
            max_deviation=DEFAULT.QTY_DEVIATION_PLUS, min_deviation=DEFAULT.QTY_DEVIATION_MINUS):
    result = []
    last_qty = qty[-1]
    range = max_deviation + min_deviation
    for item in qty[:-1]:
        coeff = 1 - Decimal(random.random()) * range + max_deviation
        new = round(item * coeff / min_qty_size) * min_qty_size
        if new > 0:
            result.append(new)
        last_qty += item - new

    result.append(last_qty)
    return result

def get_buy_sell_multilevels(
        exchange: AbstractExchange,
        book: Book,
        spread_value: Decimal,  # Target spread value like 0.01 for 1%
        ask_qtys: List[Decimal],  # list of qty for each sub-level on ASK side
        bid_qtys: List[Decimal],  # list of qty for each sub-level on BID side
        gap: Decimal,  # "gap" value from config (0 if not set)
        min: Decimal,  # "min" spread value from config (0 if not set)
        level_name: str = '_',  # Level name to generate Order Tag
    ) -> Tuple[List[Order], List[Order]]:  # Tuple of `buy` and `sell` price lists

    tag = f'{ORDER_TAG.LIMIT}{level_name.upper()[0]}'

    midpoint = (book.bid_price + book.ask_price) / 2

    spread = book.ask_price - book.bid_price

    min_gap = gap * midpoint

    high = midpoint * spread_value / 2

    _len = max([len(ask_qtys), len(bid_qtys)])

    if min != 0:
        low = midpoint * min / 2
    else:
        if min_gap > 0:
            low = min_gap + spread / 2
        else:
            low = high - _len + 1

    if _len > 1:
        step = (high - low) / (_len - 1)
    else:
        step = 0

    orders_buy = [
        exchange.applyRules(Order(+1 * qty, midpoint - (high - step * idx), tag=f'{tag}{_len - idx}'), rule=KEY.UP)
        for idx, qty in enumerate(bid_qtys[::-1])
    ]

    orders_sell = [
        exchange.applyRules(Order(-1 * qty, midpoint + (high - step * idx), tag=f'{tag}{_len - idx}'), rule=KEY.DOWN)
        for idx, qty in enumerate(ask_qtys[::-1])
    ]

    return (orders_buy[::-1], orders_sell[::-1])
