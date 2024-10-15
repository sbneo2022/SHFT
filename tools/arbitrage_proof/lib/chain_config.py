import argparse
import os
from typing import Optional

import yaml
from deepmerge import Merger


def load_chain_config(default_config_path: Optional[str] = None) -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-a",
        "--add",
        type=str,
        help="Additional YAML config or JSON item",
        action="append",
    )
    args = parser.parse_args()

    config = (
        get_config(default_config_path) if default_config_path is not None else dict()
    )

    if args.add is not None:
        merger = Merger(
            [(list, "override"), (dict, "merge")], ["override"], ["override"]
        )
        for add in args.add:
            config = merger.merge(config, get_config(add))

    return config


def get_config(filename: str) -> dict:
    if os.path.isfile(filename):
        with open(filename, "r") as fp:
            config = yaml.load(fp, Loader=yaml.Loader) or dict()
    else:
        try:
            config = yaml.load(filename, Loader=yaml.Loader)
        except:
            config = dict()

    return config
