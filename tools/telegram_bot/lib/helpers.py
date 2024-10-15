"""
Set of short helpers for various simple tasks
"""

from datetime import datetime
from decimal import Decimal
import importlib.util
from pathlib import Path

FORMAT = '%Y-%m-%dT%H:%M:%S.%f%z'

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
    for item in path.rglob('*.py'):
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
                candidates.append(dict(
                    _class=value,
                    _parents=len(value.__bases__)
                ))
        except:
            pass

    if not candidates:
        raise NameError(f"Valid class not found in {filename}")
    else:
        return sorted(candidates, key=lambda x: x['_parents'], reverse=True)[0]['_class']


"""
Makes custom JSON dump with 

  - datatime as iso string
  
  - Decimal as string
"""
def custom_dump(o):
    if isinstance(o, datetime):
        return o.strftime(FORMAT)
    elif isinstance(o, Decimal):
        return f'{str(o)}'
    return o

"""
Decode dump from previous function to JSON
"""
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
    return o
