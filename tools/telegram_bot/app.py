import os
import sys

sys.path.append(os.path.abspath('../..'))
from tools.telegram_bot.bot.alarm_bot import AlarmBot
from tools.telegram_bot.lib.chain_config import load_chain_config
from tools.telegram_bot.lib.constants import KEY

if __name__ == '__main__':

    config = load_chain_config('config.yaml')

    token = config.get(KEY.TOKEN, None)

    if token is not None:
        bot = AlarmBot(config, token)
        bot.run()

    else:
        print('No token found, stop')
        exit(-1)
