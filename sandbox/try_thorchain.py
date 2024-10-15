import os
import sys
from decimal import Decimal
from pprint import pprint

sys.path.append(os.path.abspath('..'))
from bot.iea.thorchain import Thorchain
from lib.constants import KEY
from lib.database.no_db import NoDb
from lib.factory.custom_factory import CustomFactory
from lib.logger.console_logger import ConsoleLogger
from lib.state.memory_state import MemoryState
from lib.supervisor.live_supervisor import LiveSupervisor
from lib.timer.live_timer import LiveTimer
from lib.vault.env_vault import EnvVault

if __name__ == '__main__':
    config = {
        KEY.PRODUCT: 'MATIC',
        KEY.THORCHAIN: {
            KEY.API: 'https://chaosnet-midgard.bepswap.com',
            KEY.ADDRESS: 'bnb123qkzlr0c4s60qs7rlprpz4apd6l2fdyhhaalt',
            KEY.PRIVATE_KEY: '504980ce915cefadb9a301a5a25aeecc7fa445aa9bd4b78e7dce0b799f8acbbf'
        }
    }

    factory = CustomFactory(
        timer=LiveTimer,
        database=NoDb,
        logger=ConsoleLogger,
    )

    timer = factory.Timer()

    supervisor = LiveSupervisor(config, factory, timer)

    bot = Thorchain(config, factory, timer)


    status = bot.Swap('RUNE', 'BNB', Decimal('3'))
    print(f'Status={status}')

    # supervisor.Run(bot)
