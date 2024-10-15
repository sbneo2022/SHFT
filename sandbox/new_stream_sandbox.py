import os; import sys

sys.path.append(os.path.abspath('..'))

from lib.stream import get_stream
from lib.constants import KEY
from lib.database.fake_db import FakeDb
from lib.factory.custom_factory import CustomFactory
from lib.logger.console_logger import ConsoleLogger
from lib.supervisor.live_supervisor import LiveSupervisor
from lib.timer.live_timer import LiveTimer
from lib.vault.env_vault import EnvVault

if __name__ == '__main__':
    config = {
        KEY.PROJECT: 'sandbox',
        KEY.SYMBOL: 'TRXUSDT.LONG',
        KEY.EXCHANGE: KEY.EXHANGE_OKEX_PERP,
    }

    factory = CustomFactory(timer=LiveTimer, database=FakeDb, logger=ConsoleLogger, vault=EnvVault)

    timer = factory.Timer()

    supervisor = LiveSupervisor(config, factory, timer)

    stream = get_stream(config[KEY.EXCHANGE])(config, supervisor, factory=factory, timer=timer)

    stream.Run()