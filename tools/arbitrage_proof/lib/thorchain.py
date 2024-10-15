import time
from concurrent.futures.thread import ThreadPoolExecutor
from decimal import Decimal
from typing import Dict, List, Union

import requests

URL = "https://chaosnet-midgard.bepswap.com"


def get_thorchain_products() -> List[str]:
    r = requests.get(URL + "/v1/pools")
    return r.json()


def load_thorchain_depth(thorchain_products: List[str]) -> Dict[str, Dict[str, int]]:
    return_me = {}

    def get_depth(product: str, grid: Dict[str, Dict[str, int]]):
        while True:
            try:
                details = requests.get(
                    URL + "/v1/pools/detail", params={"asset": product}, timeout=1
                )
                details = details.json()[0]

                symbol = product.split(".")[1].split("-")[0]

                grid[symbol] = {
                    "assetDepth": int(details["assetDepth"]),
                    "runeDepth": int(details["runeDepth"]),
                }
                return
            except Exception as e:
                time.sleep(0.5)

    with ThreadPoolExecutor(max_workers=16) as executor:
        for item in thorchain_products:
            executor.submit(get_depth, item, return_me)

    return return_me
