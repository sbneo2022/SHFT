import argparse
import binascii
import os
from typing import Optional

import yaml
from deepmerge import Merger
from loguru import logger

from lib.constants import KEY


def error(config: dict) -> Optional[str]:
    """
    Check are any errors in config dictionary.

    If NO error (all correct) --> return None

    If YES (some errors found) --> return error text message
    """
    message = []
    for key in KEY.REQUIRED:
        if key not in config:
            message.append(f'key "{key}" should be in config')
    if not message:
        return None
    else:
        return 'Error: ' + ','.join(message)


def get_config(filename: str) -> dict:
    if os.path.isfile(filename):
        with open(filename, 'r') as fp:
            config = yaml.load(fp, Loader=yaml.Loader)
    else:
        try:
            config = yaml.load(filename, Loader=yaml.Loader)
        except:
            config = dict()

    return config if isinstance(config, dict) else dict()

def get_project_name(config: dict) -> str:
    """
    Return Project Name from configuration data
    As simple implementation return Table name fron Influx configuration
    """

    return config.get(KEY.PROJECT, 'Untitled')

def get_project_id(config: dict) -> str:
    symbol = config[KEY.SYMBOL]

    id = get_project_name(config) + symbol

    crc32 = (binascii.crc32(id.encode()) & 0xFFFFFFFF)

    return f'{crc32:0x}'


def init_service() -> dict:
    # Handle command line
    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--add", type=str, help="Additional YAML config", action='append')
    parser.add_argument("-m", "--minutes", type=int, help="Amount of minutes to run")
    args = parser.parse_args()

    # Handle base and additional config file
    config_filename = os.getenv(KEY.CONFIG_ENV, default=KEY.CONFIG_FILENAME)
    logger.info(f'Load "{config_filename}" as base configuration')
    config = get_config(config_filename)
    if args.add is not None:
        merger = Merger([(list, "override"),(dict, "merge")], ["override"],["override"])
        for add in args.add:
            logger.info(f'Add "{add}" as additional configuration')
            config = merger.merge(config, get_config(add))

    config[KEY.STOP_AFTER] = args.minutes
    return config

