import json
from datetime import datetime
from decimal import Decimal
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from bot import AbstractBot
from lib.constants import KEY, QUEUE
from lib.defaults import DEFAULT
from lib.factory import AbstractFactory
from lib.helpers import custom_load
from lib.stream.virtual_stream import VirtualStream
from lib.supervisor import AbstractSupervisor
from lib.timer import AbstractTimer
from lib.watchdog import Watchdog


class BacktestSupervisor(AbstractSupervisor):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, factory, timer)

        self._stream = VirtualStream(config, self, factory, timer)

        self._start_timestamp = int(config[KEY.START_TIME].timestamp()) * KEY.ONE_SECOND
        self._end_timestamp = int(config[KEY.END_TIME].timestamp()) * KEY.ONE_SECOND

        self._timer.setTimestamp(self._start_timestamp)

    def Run(self, bot: AbstractBot):
        for item in self._stream.Run(self._start_timestamp, self._end_timestamp):
            if item[QUEUE.QUEUE] == QUEUE.ORDERBOOK:
                bot.onOrderbook(
                    askPrice=Decimal(item[KEY.ASK_PRICE]),
                    askQty=Decimal(item[KEY.ASK_QTY]),
                    bidPrice=Decimal(item[KEY.BID_PRICE]),
                    bidQty=Decimal(item[KEY.BID_QTY]),
                    symbol=item[KEY.SYMBOL],
                    exchange=item[KEY.EXCHANGE],
                    latency=item[KEY.LATENCY],
                    timestamp=item[KEY.TIMESTAMP]
                )

            elif item[QUEUE.QUEUE] == QUEUE.TRADES:
                bot.onTrade(
                    price=Decimal(item[KEY.PRICE]),
                    qty=Decimal(item[KEY.QTY]),
                    side=item[KEY.SIDE],
                    symbol=item[KEY.SYMBOL],
                    exchange=item[KEY.EXCHANGE],
                    latency=item[KEY.LATENCY],
                    timestamp=item[KEY.TIMESTAMP]
                )

            elif item[QUEUE.QUEUE] == QUEUE.CANDLES:
                bot.onCandle(
                    open=Decimal(item[KEY.OPEN]),
                    high=Decimal(item[KEY.HIGH]),
                    low=Decimal(item[KEY.LOW]),
                    close=Decimal(item[KEY.CLOSE]),
                    volume=Decimal(item[KEY.VOLUME]),
                    symbol=item[KEY.SYMBOL],
                    exchange=item[KEY.EXCHANGE],
                    finished=True,
                    timestamp=item[KEY.TIMESTAMP]
                )

            elif item[QUEUE.QUEUE] == QUEUE.ACCOUNT:
                bot.onAccount(
                    price=Decimal(item[KEY.PRICE]),
                    qty=Decimal(item[KEY.QTY]),
                    symbol=item[KEY.SYMBOL],
                    exchange=item[KEY.EXCHANGE],
                    timestamp=self._timer.Timestamp(),
                )

            elif item[QUEUE.QUEUE] == QUEUE.MESSAGE:
                try:
                    payload = json.loads(item[KEY.PAYLOAD], object_hook=custom_load)
                    bot.onMessage(
                        message=payload,
                        timestamp=item[KEY.TIMESTAMP],
                        latency=item[KEY.LATENCY],
                    )
                except:
                    pass

