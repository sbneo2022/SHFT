from bot import AbstractBot
from lib.constants import KEY, QUEUE
from lib.factory.backtest_factory import BacktestFactory
from lib.helpers import create_subscriptions, get_class_by_filename
from lib.init import init_service
from lib.supervisor.backtest_supervisor import BacktestSupervisor
from lib.timer.virtual_timer import VirtualTimer

if __name__ == '__main__':
    config = init_service()

    config[KEY.MODE] = KEY.SIMULATION
    config[QUEUE.QUEUE] = []

    config = create_subscriptions(config)

    factory, timer = BacktestFactory(), VirtualTimer()

    supervisor = BacktestSupervisor(config, factory, timer)

    # Create bot
    bot = get_class_by_filename(config[KEY.BOT], AbstractBot)(config, factory, timer)
    factory.Logger(config, factory, timer).success(f'Running bot class {bot.__class__.__name__}')

    supervisor.Run(bot)

