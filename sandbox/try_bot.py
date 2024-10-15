import os
import sys
import multiprocessing

sys.path.append(os.path.abspath('..'))
from bot.sandbox_bot.sandbox_bot import SandboxBot
from lib.constants import KEY
from lib.database.no_db import NoDb
from lib.factory.custom_factory import CustomFactory
from lib.logger.console_logger import ConsoleLogger
from lib.stream.binance_futures_websocket_stream import BinanceFuturesWebsocketStream
from lib.supervisor.live_supervisor import LiveSupervisor
from lib.timer.live_timer import LiveTimer
from lib.vault.env_vault import EnvVault

if __name__ == '__main__':
    config = {KEY.SYMBOL: 'RUNEUSDT', KEY.EXCHANGE: KEY.EXHANGE_BINANCE_FUTURES}

    factory = CustomFactory(timer=LiveTimer, database=NoDb, logger=ConsoleLogger, vault=EnvVault)

    timer = factory.Timer()

    supervisor = LiveSupervisor(config, factory, timer)

    stream = BinanceFuturesWebsocketStream(config, supervisor, factory=factory, timer=timer)
    multiprocessing.Process(target=stream.Run, daemon=True).start()

    bot = SandboxBot(config, factory, timer)

    supervisor.Run(bot)
