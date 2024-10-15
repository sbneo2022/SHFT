"""
Set of short helpers for various simple tasks
"""
import importlib.util
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from pprint import pprint
from typing import Any, List, Optional
import json

from lib.constants import KEY

FORMAT = "%Y-%m-%dT%H:%M:%S.%f%z"

"""
Simpe Sign function to avoid numpy
"""


def sign(a) -> int:
    if a > 0:
        return +1
    elif a < 0:
        return -1
    else:
        return 0


"""
This function returns CLASS by its name from "path" directory
"""


def get_class_by_classname(classname: str, path: Path):
    for item in path.rglob("*.py"):
        try:
            spec = importlib.util.spec_from_file_location(classname.lower(), item)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.__dict__[classname]
        except:
            pass
    return None


def get_class_by_filename(filename, base: object):
    path = Path(filename).parent
    spec = importlib.util.spec_from_file_location(path.stem, filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    candidates = []
    for key, value in module.__dict__.items():
        try:
            if base in value.__bases__ and value.__module__ == path.stem:
                candidates.append(dict(_class=value, _parents=len(value.__bases__)))
        except:
            pass

    if not candidates:
        raise NameError(f"Valid class not found in {filename}")
    else:
        return sorted(candidates, key=lambda x: x["_parents"], reverse=True)[0][
            "_class"
        ]


"""
Makes custom JSON dump with 

  - datatime as iso string
  
  - Decimal as string
"""


def custom_dump(o):
    if isinstance(o, datetime):
        return o.strftime(FORMAT)
    elif isinstance(o, Decimal):
        return f"{str(o)}"
    return o


"""
Decode dump from previous function to JSON
"""


def load_list(l: list) -> list:
    result = []
    for item in l:
        if isinstance(item, str):
            try:
                result.append(Decimal(item))
            except:
                result.append(item)
        elif isinstance(item, list):
            result.append(load_list(item))
    return result


def custom_load(o):
    for key, value in o.items():
        try:
            o[key] = datetime.strptime(value, FORMAT)
        except:
            if isinstance(value, str):
                try:
                    o[key] = Decimal(value)
                except:
                    o[key] = value
            elif isinstance(value, list):
                o[key] = load_list(value)
    return o


def create_subscriptions(config: dict) -> dict:
    """
    Create a subscription in the config file for the specified excahnge and symbol

    Args:
        config (dict): The config dict

    Returns:
        dict: The updated config dict
    """

    if KEY.SUBSCRIPTION not in config.keys():
        if not any([key in config for key in [KEY.SYMBOL, KEY.SYMBOLS]]):
            raise KeyError("Symbol, symbols or subscriptions missing in config file")

        config[KEY.SUBSCRIPTION] = {
            config[KEY.EXCHANGE]: [config.get(KEY.SYMBOLS, [config.get(KEY.SYMBOL)])]
        }

    for key, value in config.items():
        if isinstance(value, dict):
            symbol, exchange = (
                value.get(KEY.SYMBOL, None),
                value.get(KEY.EXCHANGE, None),
            )
            if all([symbol, exchange]):
                config[KEY.SUBSCRIPTION].append(
                    {KEY.SYMBOL: symbol, KEY.EXCHANGE: exchange}
                )

    return config


def load_parameters(config: dict, section: str, keys: List[str]) -> List[Optional[str]]:
    source = config.get(section, config)

    return_me = []
    for key in keys:
        return_me.append(str(source[key]) if key in source else None)

    return return_me
