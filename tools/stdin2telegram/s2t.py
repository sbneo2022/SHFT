import argparse
import sys

from notifiers import get_notifier


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--token", type=str, help="Telegram Token", required=True)
    parser.add_argument("-u", "--user", type=str, help="User Id", required=True)
    args = parser.parse_args()

    telegram = get_notifier('telegram')

    message = sys.stdin.read()

    telegram.notify(message=message, token=args.token, chat_id=args.user, parse_mode='markdown')
