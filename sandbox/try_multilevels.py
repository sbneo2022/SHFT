import os
import sys
import time
from decimal import Decimal


sys.path.append(os.path.abspath('..'))
from bot.clp.helpers.solve_multilevels import get_buy_sell_multilevels
from lib.constants import KEY
from lib.database.no_db import NoDb
from lib.exchange import BinanceFuturesExchange, Book
from lib.factory.custom_factory import CustomFactory
from lib.logger.console_logger import ConsoleLogger
from lib.timer.live_timer import LiveTimer
from lib.vault.env_vault import EnvVault

if __name__ == '__main__':
    ## Initialization ###########################################################################
    config = { KEY.SYMBOL: 'RUNEUSDT', KEY.EXCHANGE: KEY.EXHANGE_BINANCE_FUTURES }
    factory = CustomFactory(timer=LiveTimer, database=NoDb, logger=ConsoleLogger, vault=EnvVault)
    timer = factory.Timer()
    exchange = BinanceFuturesExchange(config, factory, timer)
    #############################################################################################

    qtys = [1, 5, 20, 50, 200]

    book = Book(
        ask_price=Decimal('1.7407'),
        bid_price=Decimal('1.7394'),
        ask_qty=None, bid_qty=None)

    spread_value = 1 * KEY.PERCENTD
    gap = Decimal('0.1') * KEY.PERCENTD
    min = Decimal('0')

    t0 = time.time_ns()
    buys, sells = get_buy_sell_multilevels(
        exchange=exchange,
        book=book,
        spread_value=spread_value,
        ask_qtys=qtys,
        bid_qtys=qtys,
        gap=gap,
        min=min,
        level_name='outer',
    )

    print(book.bid_price, buys)
    print(book.ask_price, sells)
