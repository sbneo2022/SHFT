import sys
from datetime import datetime
from pathlib import Path

from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler

sys.path.append(Path(__file__).absolute().parent.parent.parent.as_posix())
from tools.pancake.lib.chain_config import load_chain_config
from tools.pancake.lib.worker import Worker

DEFAULT_INTERVAL = 15

if __name__ == "__main__":
    config = load_chain_config(
        Path(__file__).absolute().parent / Path("yaml/default.yaml")
    )

    worker = Worker(config)

    scheduler = BlockingScheduler()

    start_date = datetime.now().replace(second=0, microsecond=0)

    interval = config.get("interval", DEFAULT_INTERVAL)

    scheduler.add_job(
        worker.run, "interval", seconds=interval, max_instances=3, start_date=start_date
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt):
        logger.info("Got SIGTERM! Terminating...")
