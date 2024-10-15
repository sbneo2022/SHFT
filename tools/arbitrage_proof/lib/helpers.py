import json
from datetime import datetime
from decimal import Decimal
from random import random
from typing import Any, List, Optional

FORMAT = "%Y-%m-%dT%H:%M:%S.%f%z"


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
        return o


def randomize_value(value: Decimal, plus: Decimal, minus: Decimal):
    rand = random()
    plus, minus = plus * value, minus * value
    _value = (plus + minus) * Decimal(rand)
    return value - minus + _value


def load_parameters(config: dict, section: str, keys: List[str]) -> List[Optional[str]]:
    source = config.get(section, config)

    return_me = []
    for key in keys:
        return_me.append(str(source[key]) if key in source else None)

    return return_me
