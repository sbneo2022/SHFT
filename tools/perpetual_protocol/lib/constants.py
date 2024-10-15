from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

ED = Decimal(1e-12)
E = 1e-12

class KEY(Enum):
    HIGH_THRESHOLD = 'High Threshold'
    LOW_THRESHOLD = 'Low Threshold'
    QTY = 'Qty'
    CAPITAL = 'Capital'
    DIRECTION = 'Direction'

    ASK_PRICE = 'Ask Price'
    BID_PRICE = 'Bid Price'
    POOL_PRICE = 'Pool Price'
    BASE_DEPTH = 'Base Depth'
    QUOTE_DEPTH = 'Quote Depth'

    PRODUCT = 'Product'
    EXCHANGE = 'Exchange'
    BASE = 'Base'
    FEE = 'Fee'
    SLIPPAGE = 'Slippage'

class EXCHANGE(Enum):
    BINANCE = 'Binance Futures'
    PERPETUAL_PROTOCOL = 'Perpetual Protocol'
    DYDX = 'DyDx'
    FTX = 'FTX'

AMM_MODEL = [EXCHANGE.PERPETUAL_PROTOCOL]

class ACTION(Enum):
    BUY = 'Buy'
    SELL = 'Sell'


@dataclass
class Product:
    symbol: str
    exchange: EXCHANGE
