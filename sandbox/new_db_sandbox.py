import os; import sys; sys.path.append(os.path.abspath('..'))

import json
from pprint import pprint

from lib.constants import KEY, DB
from lib.database.influx_db import InfluxDb
from lib.factory.custom_factory import CustomFactory
from lib.logger.console_logger import ConsoleLogger
from lib.timer.live_timer import LiveTimer

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

    factory = CustomFactory(database=InfluxDb, logger=ConsoleLogger, timer=LiveTimer)

    timer = factory.Timer()

    database = factory.Database(config, factory, timer)

    payload = dict(key='key', value=123)

    item = database.Encode(fields={DB.MESSAGE: json.dumps(payload)}, timestamp=timer.Timestamp())

    print(item)

    database.writeEncoded([item])

    item = database.readLast(field=DB.MESSAGE)

    pprint(item)