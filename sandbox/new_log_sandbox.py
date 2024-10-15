import os; import sys; sys.path.append(os.path.abspath('..'))

import time

from lib.constants import KEY
from lib.database.influx_db import InfluxDb
from lib.factory.custom_factory import CustomFactory
from lib.factory.sandbox_factory import SandboxFactory
from lib.logger.console_logger import ConsoleLogger
from lib.logger.db_logger import DbLogger
from lib.timer.virtual_timer import VirtualTimer

if __name__ == '__main__':
    config = {
        KEY.PROJECT: 'sandbox',
        KEY.SYMBOL: 'ETHUSDT',
        KEY.EXCHANGE: KEY.EXHANGE_BINANCE_FUTURES,
        KEY.INFLUX_DB: {
            KEY.HOST: 'essowyn.ddns.net',   # 10.0.0.1
            KEY.DATABASE: 'logs',
        }
    }

    # Simple logger that write only to stdout. Dont need any factory
    logger = ConsoleLogger()
    logger.info('Message One', key='key', value=123)

    ############################################################################################

    # For more complex logging we have to Factory: LiveTimer, no Databases
    factory = SandboxFactory()

    # Database version that writes to database. Requires Factory
    logger = DbLogger(config, factory=factory)
    logger.info('Message One', key='key', value=123)

    ############################################################################################

    # Lets write to database with Virtual Timer
    factory = CustomFactory(database=InfluxDb, timer=VirtualTimer)

    timer = factory.Timer()
    timer.setTimestamp(time.time_ns() - 5 * KEY.ONE_MINUTE)

    logger = DbLogger(config, factory=factory, timer=timer)
    logger.info('Message History', key='key', value=123)

