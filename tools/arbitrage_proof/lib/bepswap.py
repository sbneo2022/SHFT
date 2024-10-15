import os
import sys
import time
from concurrent.futures.thread import ThreadPoolExecutor
from decimal import Decimal
from pprint import pprint
from typing import Optional, Tuple, Dict, List, Union

import requests

sys.path.append(os.path.abspath("../../.."))
from tools.arbitrage_proof.lib.swap import Swap, BNB

SECTION = "bepswap"


class Bepswap(Swap):
    def __init__(self, config: dict):
        super().__init__(config)
        self._pool = config[SECTION]["pool"]

        self.rune_commission = Decimal("1")

    def getProducts(self) -> Tuple[Optional[list], Optional[str]]:
        address, err = self._get_swap_address()
        if err is None:
            self.address = address
        else:
            return (None, err)

        products = self._request("GET", "/v1/pools")
        if isinstance(products, str):
            return (None, products)
        else:
            for item in products:
                product = item.split(".")[1].split("-")[0]
                self.reference[product] = item

        return (products, None)

    def _get_swap_address(self) -> Tuple[Optional[str], Optional[str]]:
        r = requests.get(self._pool + "/v1/thorchain/pool_addresses").json()

        pprint(r)

        try:
            for item in r["current"]:
                if not item["halted"] and item["chain"] == "BNB":
                    return (item["address"], None)
        except Exception as e:
            return (None, e.__str__())

    def getDepths(
        self, products: List[str]
    ) -> Tuple[Optional[Dict[str, Dict[str, int]]], Optional[str]]:
        if BNB not in products:
            products.append(BNB)

        return_me = {}

        def get_depth(product, grid):
            while True:
                try:
                    details = requests.get(
                        self._pool + "/v1/pools/detail",
                        params={"asset": product},
                        timeout=1,
                    )
                    details = details.json()[0]
                    grid[product] = {
                        "assetDepth": int(details["assetDepth"]),
                        "runeDepth": int(details["runeDepth"]),
                    }
                    return
                except Exception as e:
                    time.sleep(0.5)

        with ThreadPoolExecutor(max_workers=8) as executor:
            for item in products:
                executor.submit(get_depth, item, return_me)

        return (return_me, None)
