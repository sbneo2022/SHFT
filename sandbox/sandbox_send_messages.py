import multiprocessing
import os; import sys;
import threading
from decimal import Decimal
from random import random

sys.path.append(os.path.abspath('..'))

from lib.consumer.hazelcast_consumer import HazelcastConsumer
from lib.helpers import sign
from lib.producer.hazelcast_producer import HazelcastProducer
from lib.stream import get_stream
from lib.timer.live_timer import LiveTimer
from lib.vault.env_vault import EnvVault
from lib.watchdog import Watchdog


from lib.consumer.rabbit_consumer import RabbitConsumer
from lib.producer.rabbit_producer import RabbitProducer

from lib.constants import KEY
from lib.database.no_db import NoDb
from lib.factory.custom_factory import CustomFactory
from lib.logger.console_logger import ConsoleLogger
from lib.supervisor.live_supervisor import LiveSupervisor

if __name__ == '__main__':
    config = {
        KEY.SYMBOL: 'RUNEUSDT',
        KEY.EXCHANGE: KEY.EXHANGE_BINANCE_FUTURES,
        KEY.RABBIT_MQ: {
            KEY.HOST: '54.248.124.33',
            KEY.USERNAME: 'admin',
            KEY.PASSWORD: 's5r-26m-nkj'
        },
        KEY.HAZELCAST: {
            KEY.HOST: '10.0.0.1'
        }
    }

    factory = CustomFactory(
        timer=LiveTimer,
        database=NoDb,
        logger=ConsoleLogger,
        producer=HazelcastProducer,
        consumer=HazelcastConsumer,
        vault=EnvVault,
    )

    timer = factory.Timer()

    # supervisor = LiveSupervisor(config, factory, timer)
    #
    producer = factory.Producer(config, factory, timer)
    # consumer = factory.Consumer(config, supervisor, factory, timer)
    # threading.Thread(target=consumer.Run, daemon=True).start()
    #
    # watchdog = Watchdog(config, factory, timer)
    # watchdog.addHandler(consumer.Close)
    #
    # exchange = config[KEY.EXCHANGE]
    # stream = get_stream(exchange)(config, supervisor, factory, timer)
    # multiprocessing.Process(target=stream.Run, daemon=True).start()

    message = {
        KEY.TYPE: KEY.INVENTORY,
        KEY.PROJECT: 'clp_bot_prod',
        KEY.TIMESTAMP: timer.Timestamp(),
        KEY.QTY: Decimal(50),
        KEY.MAX_QTY: Decimal(100)
    }

    producer.Send(message=message)
    print(f'Sending message: {message}')

    exit()

    while True:
        message = {
            KEY.TYPE: KEY.INVENTORY,
            KEY.PROJECT: 'clp_bot_prod',
            KEY.TIMESTAMP: timer.Timestamp(),
            KEY.QTY: Decimal(sign(random() - 0.5) * (30 + int(70 * random()))),
            KEY.MAX_QTY: Decimal(100)
        }

        producer.Send(message=message)
        print(f'Sending message: {message}')
        timer.Sleep(1 + 5 * random())

