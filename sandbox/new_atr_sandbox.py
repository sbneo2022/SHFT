import os; import sys; sys.path.append(os.path.abspath('..'))

from datetime import datetime, timezone

from bot.clp.clp_atr import CLPATR, ATR_CANDLES, CANDLES_DEPTH
from lib.constants import KEY
from lib.database.no_db import NoDb
from lib.factory.custom_factory import CustomFactory
from lib.logger.console_logger import ConsoleLogger
from lib.state.memory_state import MemoryState
from lib.timer.live_timer import LiveTimer
from lib.vault.env_vault import EnvVault

if __name__ == '__main__':
    # General config parameters: symbol/exchange
    config = {KEY.SYMBOL: 'RUNEUSDT', KEY.EXCHANGE: KEY.EXHANGE_BINANCE_FUTURES}

    # Bot-specific config parameters. Only required
    config[KEY.HOLD] = 2.1
    config[KEY.SPREAD] = {'innner': {KEY.VALUE: 0.01}}

    # Create Factory with given modules
    factory = CustomFactory(database=NoDb, logger=ConsoleLogger, vault=EnvVault, state=MemoryState)

    # Create LiveTimer because we want to operate with Live Date
    timer = LiveTimer()

    # Create CLP-ATR bot object
    bot = CLPATR(config, factory, timer)

    # NOTE:
    # Some parameters are hardcoded now because WIP
    # and we decide with config later
    #

    # This is how many candles we are loading into deque
    # We can change that constant in clp_atr.py
    print(CANDLES_DEPTH // KEY.ONE_MINUTE)

    # This is ATR depths we are using. Can change in a same file
    print(ATR_CANDLES)

    # Call "onCandle" event. Because it first call, it will preload history candles from
    # Binance Exchange (bases on Exchange name) and update ATRs from "timestamp" and older
    # We are using None for OHLCV because "finished" set as False -> we loading history data only
    bot.onCandle(None, None, None, None, None, timestamp=timer.Timestamp(), finished=False)

    # We can see all candles data for "Close" field
    # NOTE: A lot of data!
    # NOTE: Latest one -- last one [-1]
    print(bot._candles[KEY.CLOSE])

    # We can check latest datetime
    # NOTE: Binance use OPEN time for candles like a time marker
    print(datetime.fromtimestamp(bot._candles[KEY.TIMESTAMP][-1] / KEY.ONE_SECOND, tz=timezone.utc))

    # we can repeat ATRs calculations with same candles and
    # set breakpoints/additional output
    bot._update_atr()
