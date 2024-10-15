import atexit
import os
import sys

from apscheduler.schedulers.background import BackgroundScheduler

sys.path.append(os.path.abspath("../.."))
from lib.chain_config import load_chain_config
from lib.lock import Lock, handle_lock
from lib.worker import Worker

CONFIG = load_chain_config()
# handle_lock(CONFIG)


def run_report():
    worker = Worker(CONFIG)
    prefix = CONFIG.get("coin", None)
    prefix = [CONFIG["method"]] if prefix is None else [CONFIG["method"], prefix]
    # atexit.register(worker.save, prefix='_'.join(prefix))

    getattr(worker, CONFIG["method"])()
    worker.save(prefix="_".join(prefix))


if __name__ == "__main__":
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_report, "interval", seconds=10, max_instances=40)
    scheduler.start()

    while True:
        pass
