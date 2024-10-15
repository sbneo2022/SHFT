import os
import sys
from decimal import Decimal

sys.path.append(os.path.abspath('..'))
from bot.clp.helpers.solve_stoploss import get_stoploss_price
from lib.constants import KEY
from lib.database.no_db import NoDb
from lib.exchange import BinanceFuturesExchange
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

    qty = Decimal('-1')

    price = Decimal('5.0')

    distance = Decimal('1') * KEY.PERCENTD

    stoploss_price = get_stoploss_price(exchange, qty, price, distance)

    print(f'price={price} {("LONG" if qty > 0 else "SHORT")} distance={distance} --> stoploss={stoploss_price}')