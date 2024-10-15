import os
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pprint import pprint
from typing import Optional, Dict, Union, List

from loguru import logger

sys.path.append(os.path.abspath('../../..'))
from tools.perpetual_protocol.bot import Bot, sign
from tools.perpetual_protocol.lib.constants import KEY, ACTION, EXCHANGE, AMM_MODEL, ED
from tools.perpetual_protocol.lib.db import Db
from tools.perpetual_protocol.lib.message import Message, MessageDepth, MessageBestBook


class STATE(Enum):
    UP = 'Up'
    DOWN = 'Down'


class Basis(Bot):
    def __init__(self, config: dict):
        super().__init__(config)

        self._db = Db(self._config)

        ####################################################################################
        # Load parameters from config
        ####################################################################################

        self._base = self._config[KEY.BASE]

        self._a_exchange: EXCHANGE = self._config['a']
        self._b_exchange: EXCHANGE = self._config['b']

        self._capital = self._load_as_decimal(KEY.CAPITAL)
        self._fee = self._load_as_decimal(KEY.FEE)
        self._slippage = self._load_as_decimal(KEY.SLIPPAGE)
        self._direction = self._load_as_decimal(KEY.DIRECTION)

        self._high_threshold = self._load_as_decimal(KEY.HIGH_THRESHOLD)
        self._low_threhold = self._load_as_decimal(KEY.LOW_THRESHOLD)

        ####################################################################################
        # Create internal variables
        ####################################################################################

        self._a_data: Dict[KEY, Optional[Decimal]] = defaultdict(lambda: None)
        self._b_data: Dict[KEY, Optional[Decimal]] = defaultdict(lambda: None)

        self._a_portfolio: Optional[Union[Decimal, int]] = 0
        self._b_portfolio: Optional[Union[Decimal, int]] = 0

        self._spread: Optional[Decimal] = None

        self._now: Optional[datetime] = None

        self._init_spread: Optional[Decimal] = None

        self._current_state: Optional[STATE] = None

        self._prefix = f'{self._base}:{self._a_exchange.name}-{self._b_exchange.name}:'

        logger.info(f'{self._prefix} Create Basis Bot')


    def _get_a_midpoint(self) -> Optional[Decimal]:
        if all([self._a_data[KEY.ASK_PRICE], self._a_data[KEY.BID_PRICE]]):
            return (self._a_data[KEY.ASK_PRICE] + self._a_data[KEY.BID_PRICE]) / 2
        else:
            return None

    def _get_b_midpoint(self) -> Optional[Decimal]:
        if all([self._b_data[KEY.ASK_PRICE], self._b_data[KEY.BID_PRICE]]):
            return (self._b_data[KEY.ASK_PRICE] + self._b_data[KEY.BID_PRICE]) / 2
        else:
            return None


    def _get_midpoint(self) -> Optional[Decimal]:
        a_midpoint = self._get_a_midpoint()
        b_midpoint = self._get_b_midpoint()

        if all([a_midpoint, b_midpoint]):
            return (a_midpoint + b_midpoint) / 2
        else:
            return None

    # def _get_midpoint(self) -> Optional[Decimal]:
    #     """
    #     1. Get `pool_price` as midpoint if exchange model is AMM
    #     2. Else try to use ask/bid price and get average of them
    #     3. Make that price for both exchange
    #     4. If both price exists -> return average of them
    #     5. If any of price absent -> return None
    #     :return:
    #     """
    #     if self._a_exchange in AMM_MODEL:
    #         a_midpoint = self._a_data[KEY.POOL_PRICE]
    #     elif self._a_data[KEY.ASK_PRICE] is None:
    #         a_midpoint = None
    #     else:
    #         a_midpoint = (self._a_data[KEY.ASK_PRICE] + self._a_data[KEY.BID_PRICE]) / 2
    #
    #     if self._b_exchange in AMM_MODEL:
    #         b_midpoint = self._b_data[KEY.POOL_PRICE]
    #     elif self._b_data[KEY.ASK_PRICE] is None:
    #         b_midpoint = None
    #     else:
    #         b_midpoint = (self._b_data[KEY.ASK_PRICE] + self._b_data[KEY.BID_PRICE]) / 2
    #
    #     if all([a_midpoint, b_midpoint]):
    #         return (a_midpoint + b_midpoint) / 2
    #     else:
    #         return None

    def _get_a_price(self, qty: Union[Decimal, int]) -> Optional[Decimal]:
        if qty > 0:
            return self._a_data[KEY.ASK_PRICE]
        else:
            return self._a_data[KEY.BID_PRICE]


    def _get_b_price(self, qty: Union[Decimal, int]) -> Decimal:
        if qty > 0:
            return self._b_data[KEY.ASK_PRICE]
        else:
            return self._b_data[KEY.BID_PRICE]

    def _get_spread(self) -> Optional[Decimal]:
        midpoint = self._get_midpoint()

        if midpoint is None:
            return None
        else:
            a_midpoint = self._get_a_midpoint()
            b_midpoint = self._get_b_midpoint()
            spread = a_midpoint - b_midpoint
            return spread / midpoint


    def _set_a_data(self, message: Union[Message, MessageBestBook, MessageDepth]):
        if message.product.exchange in AMM_MODEL:
            self._a_data[KEY.ASK_PRICE] = message.pool_price * (1 + self._slippage)
            self._a_data[KEY.BID_PRICE] = message.pool_price * (1 - self._slippage)
        else:
            self._a_data[KEY.ASK_PRICE] = message.best_ask
            self._a_data[KEY.BID_PRICE] = message.best_bid

    def _set_b_data(self, message: Union[Message, MessageBestBook, MessageDepth]):
        if message.product.exchange in AMM_MODEL:
            self._b_data[KEY.ASK_PRICE] = message.pool_price * (1 + self._slippage)
            self._b_data[KEY.BID_PRICE] = message.pool_price * (1 - self._slippage)
        else:
            self._b_data[KEY.ASK_PRICE] = message.best_ask
            self._b_data[KEY.BID_PRICE] = message.best_bid

    def _close(self):
        a_price = self._get_a_price(-self._a_portfolio)
        b_price = self._get_b_price(-self._b_portfolio)

        a_pnl = self._a_portfolio * (a_price - self._a_data['entry_price'])
        b_pnl = self._b_portfolio * (b_price - self._b_data['entry_price'])

        commission = self._capital * self._fee * 2

        if self._a_exchange not in AMM_MODEL:
            a_pnl -= commission

        if self._b_exchange not in AMM_MODEL:
            b_pnl -= commission

        pnl = a_pnl + b_pnl

        self._a_portfolio, self._b_portfolio = 0, 0

        message = f'Close position: a/b pnl={a_pnl}/{b_pnl}, net={pnl} ' \
                  f'Exit price: {a_price}/{b_price} Current ask/bid: ' \
                  f'a:{self._a_data[KEY.ASK_PRICE]}/{self._a_data[KEY.BID_PRICE]} ' \
                  f'b:{self._b_data[KEY.ASK_PRICE]}/{self._b_data[KEY.BID_PRICE]} '

        self._db.addPoint(
            fields={
                '_message': message,
                'a_exit_price': a_price,
                'b_exit_price': b_price,
                'a_pnl': a_pnl,
                'b_pnl': b_pnl,
                'pnl': pnl
            },
            tags={
                'base': self._base,
                'pair': f'{self._a_exchange.name}-{self._b_exchange.name}',
                '_event': 'close',
            },
            time=self._now,
        )
        logger.debug(f'{self._prefix} {message} ')

    def _flip(self):
        a_direction = sign(self._a_portfolio)
        b_direction = sign(self._b_portfolio)
        self._close()
        self._current_state = STATE.UP if self._current_state == STATE.DOWN else STATE.DOWN
        self._open(-a_direction, -b_direction)

    def _start(self, spread):
        direction = sign(spread) * self._direction
        self._init_spread = spread
        self._current_state = STATE.UP
        self._open(direction, -direction)

    def _open(self, a_direction, b_direction):
        a_price, b_price = self._get_a_price(a_direction), self._get_b_price(b_direction)

        self._a_data['entry_price'], self._b_data['entry_price'] = a_price, b_price

        self._a_portfolio = a_direction * self._capital / a_price
        self._b_portfolio = b_direction * self._capital / b_price

        message = f'Open position: a/b = {self._a_portfolio}/{self._b_portfolio}' \
                  f'Entry price: {a_price}/{b_price} Current ask/bid: ' \
                  f'a:{self._a_data[KEY.ASK_PRICE]}/{self._a_data[KEY.BID_PRICE]} ' \
                  f'b:{self._b_data[KEY.ASK_PRICE]}/{self._b_data[KEY.BID_PRICE]} '
        self._db.addPoint(
            fields={
                '_message': message,
                'a_entry_price': a_price,
                'b_entry_price': b_price,
            },
            tags={
                'base': self._base,
                'pair': f'{self._a_exchange.name}-{self._b_exchange.name}',
                '_event': 'open',
        },
            time=self._now,
        )

        logger.debug(f'{self._prefix} {message} a_entry:{a_price} b_entry:{b_price}')

    def _handle_spread(self, spread: Decimal):
        # case 1: if no portfolio --> we open when abs(spread) > entry_threshold
        if abs(self._a_portfolio) < ED and abs(self._b_portfolio) < ED:
            if abs(spread) > abs(self._high_threshold):
                self._start(spread)

        elif sign(spread) == sign(self._init_spread) and self._current_state == STATE.DOWN and abs(spread) > abs(self._high_threshold):
            self._flip()

        elif sign(spread) == sign(self._init_spread) and self._current_state == STATE.UP and abs(spread) < abs(self._low_threhold):
            self._flip()

        elif sign(spread) != sign(self._init_spread) and self._current_state == STATE.UP:
            self._flip()

    def _save_porftolio(self):
        self._db.addPoint(
            fields={
                'a_ask': self._a_data[KEY.ASK_PRICE],
                'a_bid': self._a_data[KEY.BID_PRICE],
                'b_ask': self._b_data[KEY.ASK_PRICE],
                'b_bid': self._b_data[KEY.BID_PRICE],
                'spread': self._spread,
                'a_portfolio': float(self._a_portfolio),
                'b_portfolio': float(self._b_portfolio),
            },
            tags={
                'base': self._base,
                'pair': f'{self._a_exchange.name}-{self._b_exchange.name}'
            },
            time=self._now,
        )

    def on_message(self, messages: List[Message]):
        super().on_message(messages)

        for message in messages:
            # Skip products with wrong base
            base, _ = message.product.symbol.split('-')
            if base == self._base:
                if message.product.exchange == self._a_exchange:
                    self._set_a_data(message)
                if message.product.exchange == self._b_exchange:
                    self._set_b_data(message)
            self._now = message.time

        spread = self._get_spread()

        self._handle_spread(spread)

        self._spread = spread

        self._save_porftolio()