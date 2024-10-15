import json
from datetime import datetime
from decimal import Decimal
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from bot import AbstractBot
from lib.constants import KEY, QUEUE
from lib.defaults import DEFAULT
from lib.helpers import custom_load
from lib.supervisor import AbstractSupervisor
from lib.watchdog import Watchdog


class LiveSupervisor(AbstractSupervisor):
    def Run(self, bot: AbstractBot, watchdog: Optional[Watchdog] = None):
        self._watchdog = watchdog

        ###############################################################
        # Setup "onTime" engine
        ###############################################################
        scheduler = BackgroundScheduler()

        self._disable_on_time = False

        def onTime():
            if self._watchdog is not None:
                if self._watchdog.shutdown_in_progress:
                    self._disable_on_time = True

            if not self._disable_on_time:
                bot.onTime(self._timer.Timestamp())

        start_date = datetime.now().replace(second=0, microsecond=0)
        scheduler.add_job(
            onTime,
            "interval",
            seconds=DEFAULT.ONTIME_INTERVAL_SECONDS,
            start_date=start_date,
            max_instances=1,
        )
        scheduler.start()

        ###############################################################
        # Run message loop
        ###############################################################
        while True:
            """
            NOTE: onTime message not available now: 
            
                  Reason: to decrease CPU load
                  
                  Solution: May be change to "onSecond" behaviour and send them every second. TBD/
            """
            item = self.Queue.get()

            if self._watchdog is not None:
                if self._watchdog.shutdown_in_progress:
                    break

            if item[QUEUE.QUEUE] == QUEUE.ORDERBOOK:
                bot.onOrderbook(
                    askPrice=Decimal(item[KEY.ASK_PRICE]),
                    askQty=Decimal(item[KEY.ASK_QTY]),
                    bidPrice=Decimal(item[KEY.BID_PRICE]),
                    bidQty=Decimal(item[KEY.BID_QTY]),
                    symbol=item[KEY.SYMBOL],
                    exchange=item[KEY.EXCHANGE],
                    latency=item[KEY.LATENCY],
                    timestamp=item[KEY.TIMESTAMP],
                )

            elif item[QUEUE.QUEUE] == QUEUE.TRADES:
                bot.onTrade(
                    price=Decimal(item[KEY.PRICE]),
                    qty=Decimal(item[KEY.QTY]),
                    side=item[KEY.SIDE],
                    symbol=item[KEY.SYMBOL],
                    exchange=item[KEY.EXCHANGE],
                    latency=item[KEY.LATENCY],
                    timestamp=item[KEY.TIMESTAMP],
                )

            elif item[QUEUE.QUEUE] == QUEUE.ACCOUNT:
                bot.onAccount(
                    price=Decimal(item[KEY.PRICE]),
                    qty=Decimal(item[KEY.QTY]),
                    symbol=item[KEY.SYMBOL],
                    exchange=item[KEY.EXCHANGE],
                    timestamp=self._timer.Timestamp(),
                )

            elif item[QUEUE.QUEUE] == QUEUE.STATUS:
                bot.onStatus(
                    orderId=item[KEY.ORDER_ID],
                    status=item[KEY.STATUS],
                    price=Decimal(item[KEY.PRICE]),
                    qty=Decimal(item[KEY.QTY]),
                    pct=Decimal(item[KEY.PCT]),
                    symbol=item[KEY.SYMBOL],
                    exchange=item[KEY.EXCHANGE],
                    timestamp=self._timer.Timestamp(),
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
                    finished=item[KEY.FINISHED],
                    timestamp=item[KEY.TIMESTAMP],
                )

            elif item[QUEUE.QUEUE] == QUEUE.LEVEL:
                payload = json.loads(item[KEY.PAYLOAD], object_hook=custom_load)
                bot.onSnapshot(
                    asks=payload[KEY.ASKS],
                    bids=payload[KEY.BIDS],
                    symbol=item[KEY.SYMBOL],
                    exchange=item[KEY.EXCHANGE],
                    timestamp=item[KEY.TIMESTAMP],
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
