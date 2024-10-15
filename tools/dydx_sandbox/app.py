import os
import sys
import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

sys.path.append(os.path.abspath('../..'))
from tools.dydx_sandbox.lib.chain_config import load_chain_config
from tools.dydx_sandbox.lib.worker import Worker

if __name__ == '__main__':
    config = load_chain_config()

    worker = Worker(config)

    scheduler = BackgroundScheduler()
    start_date = datetime.now().replace(second=0, microsecond=0)
    scheduler.add_job(worker.run, 'interval', seconds=10, start_date=start_date)
    scheduler.start()

    while True:
        time.sleep(5)