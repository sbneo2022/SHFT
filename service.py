import multiprocessing
import threading

from deepmerge import Merger

from bot import AbstractBot
from lib.constants import KEY
from lib.factory.live_factory import LiveFactory
from lib.helpers import get_class_by_filename, create_subscriptions
from lib.init import init_service
from lib.stream import get_stream
from lib.supervisor.live_supervisor import LiveSupervisor
from lib.timer.live_timer import LiveTimer
from lib.watchdog import Watchdog

if __name__ == "__main__":
    multiprocessing.set_start_method(method="spawn")

    config = init_service()

    config = create_subscriptions(config)

    factory, timer = LiveFactory(), LiveTimer()

    supervisor = LiveSupervisor(config, factory, timer)

    # Create bot
    bot = get_class_by_filename(config[KEY.BOT], AbstractBot)(config, factory, timer)
    factory.Logger(config, factory, timer).success(
        f"Running bot class {bot.__class__.__name__}"
    )

    # Create and run Messages datasource
    messages = factory.Consumer(config, supervisor, factory, timer)
    threading.Thread(target=messages.Run, daemon=True).start()

    # Create and fill Watchdog
    watchdog = Watchdog(config, factory, timer)
    watchdog.addHandler(bot.Clean)
    watchdog.addHandler(messages.Close)

    merger = Merger([(list, "override"), (dict, "merge")], ["override"], ["override"])
    for exchange, symbols in config[KEY.SUBSCRIPTION].items():
        # Create and run websocket datasource

        stream = get_stream(config, exchange=exchange)(
            config=merger.merge(
                config,
                {KEY.SYMBOL: symbols[0], KEY.SYMBOLS: symbols, KEY.EXCHANGE: exchange},
            ),
            supervisor=supervisor,
            factory=factory,
            timer=timer,
        )

        if stream.__class__.__name__ == "PerpetualProtocolWebsocketStream":
            threading.Thread(target=stream.Run, daemon=True).start()
        else:
            multiprocessing.Process(target=stream.Run, daemon=True).start()

    # Run bot
    supervisor.Run(bot, watchdog)
