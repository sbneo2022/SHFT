from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass
class Book:
    ask_price: Decimal
    ask_qty: Optional[Decimal]
    bid_price: Decimal
    bid_qty: Optional[Decimal]

class VAULT:
    KEY = 'key'
    SECRET = 'secret'
    PASSPHRASE = 'passphrase'

class KEY:

    ########## Exchange names
    EXHANGE_BINANCE_FUTURES = 'BINANCE.FUTURES'
    EXHANGE_OKEX_PERP = 'OKEX.PERP'
    EXHANGE_HUOBI_SWAP = 'HUOBI.SWAP'
    EXHANGE_BITMEX = 'BITMEX'

    ########## Request Methods
    POST = 'POST'
    GET = 'GET'
    DELETE = 'DELETE'

    ONE_MS = 1_000_000
    ONE_SECOND = ONE_MS * 1_000
    ONE_MINUTE = ONE_SECOND * 60
    ONE_HOUR = ONE_MINUTE * 60
    ONE_DAY = ONE_HOUR * 24
