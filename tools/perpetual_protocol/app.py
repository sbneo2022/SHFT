import json
import os
import sys
import time
from datetime import datetime
from pprint import pprint

from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger


sys.path.append(os.path.abspath('../..'))
from tools.perpetual_protocol.lib.db import Db
from tools.perpetual_protocol.lib.chain_config import load_chain_config
from tools.perpetual_protocol.lib.worker import Worker

MESSAGE = 'Press Ctrl-C for EXIT'


def log_config_to_database(config: dict):
    config_as_message = json.dumps(config, indent=2)
    config_as_message = config_as_message.split('\n')

    message = ['', f'--- {datetime.utcnow().isoformat()} ---']
    footer = [f'--- END OF CONFIGURATION ---', '']

    message.extend(config_as_message)
    message.extend(footer)

    for item in message[::-1]:
        Db(config).addPoint(fields={
            '_config': item
        })

if __name__ == '__main__':
    config = load_chain_config()

    log_config_to_database(config)

    worker = Worker(config)

    logger.info(MESSAGE)

    scheduler = BackgroundScheduler()
    start_date = datetime.now().replace(second=0, microsecond=0)
    scheduler.add_job(worker.run, 'interval', seconds=10, start_date=start_date)
    scheduler.start()

    while True:
        time.sleep(2)