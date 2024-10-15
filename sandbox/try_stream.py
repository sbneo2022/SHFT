import os; import sys

from lib.database.no_db import NoDb
from lib.vault.config_vault import ConfigVault

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
        KEY.SYMBOL: 'RUNEUSD',
        KEY.EXCHANGE: KEY.EXHANGE_FTX_PERP,
        KEY.EXHANGE_FTX_PERP: {
            KEY.KEY: 'IkyfFiD3QPEEUdeXG_JDMuvDhj_0mCb44PIsm6Q0',
            KEY.SECRET: 'hYgYQgPvH1tFine_HxX5uqCIRICbxfzFEZB2vjQK'
        }
    }

    factory = CustomFactory(timer=LiveTimer, database=NoDb, logger=ConsoleLogger, vault=ConfigVault)
    timer = factory.Timer()

    supervisor = LiveSupervisor(config, factory, timer)

    stream = get_stream(config)(config, supervisor, factory=factory, timer=timer)

    stream.Run()