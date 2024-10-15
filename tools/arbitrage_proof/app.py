import atexit
import os
import sys


sys.path.append(os.path.abspath("../.."))
from lib.chain_config import load_chain_config
from lib.worker import Worker
from lib.lock import Lock, handle_lock

if __name__ == "__main__":
    config = load_chain_config()

    # handle_lock(config)

    worker = Worker(config)

    prefix = config.get("coin", None)
    prefix = [config["method"]] if prefix is None else [config["method"], prefix]
    # atexit.register(worker.save, prefix="_".join(prefix))

    getattr(worker, config["method"])()
