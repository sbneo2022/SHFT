from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Dict, Type, List, Union

from lib.constants import KEY, STATUS
from lib.factory import AbstractFactory
from lib.init import get_project_id
from lib.timer import AbstractTimer

@dataclass
class Order:
    qty: Union[int, Decimal] = Decimal(0)
    price: Optional[Decimal] = None
    stopmarket: bool = False
    tag: Optional[str] = None
    liquidation: bool = False

    def as_market_order(self):
        return Order(self.qty, None, self.stopmarket, self.tag, self.liquidation)

    def __str__(self):
        direction = 'LONG ' if self.qty > 0 else 'SHORT '
        direction = '' if self.qty == Decimal(0) else direction
        direction = f'LIQUIDATION {direction}' if self.liquidation else direction
        return f'{direction}{abs(self.qty)}@{self.price} {(self.tag or "")}'

    __repr__ = __str__

@dataclass
class Book:
    ask_price: Optional[Union[int, Decimal]] = None
    ask_qty: Optional[Union[int, Decimal]] = None
    bid_price: Optional[Union[int, Decimal]] = None
    bid_qty: Optional[Union[int, Decimal]] = None


@dataclass
class Balance:
    balance: Decimal = Decimal('0.0')
    unrealized_pnl: Optional[Union[int, Decimal]] = None
    available: Optional[Union[int, Decimal]] = None
    gas: Optional[Union[int, Decimal]] = None


class AbstractExchange(ABC):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, symbol: Optional[str] = None):
        self._config = config.copy()
        self._factory = factory
        self._timer = timer

        # Override symbol if `symbol` is not None
        self._config[KEY.SYMBOL] = symbol or self._config[KEY.SYMBOL]

        self._id = get_project_id(config)

        self._top_book: Optional[Book] = None
        self._order_state: Dict[str, dict] = dict()
        self._portfolio:  Union[int, Decimal] = 0

    @abstractmethod
    def isOnline(self) -> bool:
        pass

    @abstractmethod
    def applyRules(self, order: Order, rule: Optional[str] = None) -> Order:
        pass

    @abstractmethod
    def getBook(self) -> Book:
        pass

    @abstractmethod
    def getBalance(self) -> Balance:
        pass

    @abstractmethod
    def getTick(self) -> Decimal:
        pass

    @abstractmethod
    def getMinQty(self) -> Decimal:
        pass

    @abstractmethod
    def getPosition(self) -> Order:
        pass

    @abstractmethod
    def getCandles(self, start_timestamp: int, end_timestamp: int) -> Dict[str, deque]:
        pass

    @abstractmethod
    def Post(self, order: Order, wait=False) -> str:
        pass

    @abstractmethod
    def batchPost(self, orders: List[Order], wait=False) -> List[str]:
        pass

    @abstractmethod
    def Cancel(self, ids: Optional[Union[str, List]] = None, wait=False):
        pass

    def updateBook(self, top_book: Book):
        self._top_book = top_book

    def updateOrder(self, orderId: str, status: str, price: Decimal, qty: Union[int, Decimal], pct: Union[int, Decimal]):
        if status == STATUS.CANCELED:
            if orderId in self._order_state:
                del self._order_state[orderId]
        elif status == STATUS.OPEN:
            self._order_state[orderId] = {KEY.STATUS: status, KEY.PRICE: price, KEY.QTY: qty, KEY.PCT: 0}
        elif status == STATUS.PARTIALLY_FILLED:
            self._order_state[orderId][KEY.PCT] += pct
            self._portfolio += pct * qty
        elif status == STATUS.FILLED:
            self._portfolio += pct * qty
            if orderId in self._order_state:
                del self._order_state[orderId]

def get_exchange(config: dict, exchange: Optional[str] = None) -> Type[AbstractExchange]:

    from lib.exchange.binance_futures_exchange import BinanceFuturesExchange
    from lib.exchange.binance_spot_exchange import BinanceSpotExchange
    from lib.exchange.okex_perp_exchange import OkexPerpExchange
    from lib.exchange.huobi_swap_exchange import HuobiSwapExchange
    from lib.exchange.ftx_perp_exchange import FtxPerpExchange
    from lib.exchange.perpetual_protocol_exchange import PerpetualProtocolExchange
    from lib.exchange.virtual_exchange import VirtualExchange

    if config.get(KEY.MODE, None) == KEY.SIMULATION:
        return VirtualExchange

    else:
        exchange = exchange or config[KEY.EXCHANGE]
        return {
            KEY.EXCHANGE_BINANCE_FUTURES: BinanceFuturesExchange,
            KEY.EXCHANGE_BINANCE_SPOT: BinanceSpotExchange,
            KEY.EXCHANGE_OKEX_PERP: OkexPerpExchange,
            KEY.EXCHANGE_HUOBI_SWAP: HuobiSwapExchange,
            KEY.EXCHANGE_FTX_PERP: FtxPerpExchange,
            KEY.EXCHANGE_PERPETUAL_PROTOCOL: PerpetualProtocolExchange,
        }[exchange]
