import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional, Any, List
import string
import random
from datetime import datetime


FORMAT = "%Y-%m-%dT%H:%M:%S.%f%z"
import requests


def id_generator(size=6, chars=string.ascii_uppercase + string.digits) -> str:
    """
    Create a random id.
    Random string generation with upper case letters and digits

    Args:
        size (int, optional): [description]. Defaults to 6.
        chars (str, optional): The characters to use. Defaults to 
            string.ascii_uppercase+string.digits.

    Returns:
        str: The id created
    """
    random.seed(datetime.now())
    return "".join(random.choice(chars) for _ in range(size))


def gasPrice(transaction_speed="standard"):
    """
    Transaction_speed should be ["slow", "fast", "standard"]
    """
    assert transaction_speed in ["slow", "fast", "standard"]
    return requests.get("https://gasnow.sparkpool.com/api/v3/gas/price").json()["data"][
        transaction_speed
    ]


def load_json_data(abi: str) -> Optional[dict]:
    folder = Path(__file__).absolute().parent.parent / Path("data")
    filename = folder / Path(f"{abi}.json")

    try:
        with filename.open("r") as fp:
            return json.load(fp)
    except:
        return {}


def load_parameters(config: dict, section: str, keys: List[str]) -> List[Optional[str]]:
    source = config.get(section, config)

    return_me = []
    for key in keys:
        return_me.append(str(source[key]) if key in source else None)

    return return_me


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


class DecimalDecoder(json.JSONDecoder):
    def __init__(self):
        super().__init__(object_hook=self._object_hook)

    def _load_list(self, l: list) -> list:
        result = []
        for item in l:
            if isinstance(item, str):
                try:
                    result.append(Decimal(item))
                except:
                    result.append(item)
            elif isinstance(item, list):
                result.append(self._load_list(item))
        return result

    def _object_hook(self, o: Any) -> Any:
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
                    o[key] = self._load_list(value)
        return o


class DecimalEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, datetime):
            return o.strftime(FORMAT)
        elif isinstance(o, Decimal):
            return f"{str(o)}"
        elif isinstance(o, dict):
            return self.default(o)
        return o
