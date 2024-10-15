import sys
from pathlib import Path
from pprint import pprint

sys.path.append(Path(__file__).absolute().parent.parent.parent.as_posix())
from tools.pancake.lib.chain_config import load_chain_config
from tools.pancake.lib.worker import Worker

if __name__ == "__main__":
    config = load_chain_config(
        Path(__file__).absolute().parent / Path("yaml/default.yaml")
    )

    worker = Worker(config)

    report = worker.run()

    pprint(report)
