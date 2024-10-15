import os
import sys
from decimal import Decimal
from pprint import pprint
from typing import Optional, Tuple, Dict, List

import requests

sys.path.append(os.path.abspath("../../.."))
from lib.swap import Swap, BNB

SECTION = "delphidigital"


class Delphidigital(Swap):
    def __init__(self, config: dict):
        super().__init__(config)
        self._pool = config[SECTION]["pool"]

        self.rune_commission = Decimal("1.0")

    def getProducts(self) -> Tuple[Optional[list], Optional[str]]:
        pools = self._request("GET", endpoint="/thorchain/pools")

        address, err = self._get_swap_address()
        if err is None:
            self.address = address
        else:
            return (None, err)

        if isinstance(pools, str):
            return (None, pools)
        else:
            return_me = []
            for item in pools:
                asset = item["asset"]
                network, product = asset.split(".")
                if network == "BNB":
                    symbol = product.split("-")[0]
                    return_me.append(asset)
                    self.reference[symbol] = asset
            return (return_me, None)

    def _get_swap_address(self) -> Tuple[Optional[str], Optional[str]]:
        r = self._request("GET", endpoint="/thorchain/pool_addresses")

        if isinstance(r, str):
            return (None, r)

        for item in r["current"]:
            if not item["halted"] and item["chain"] == "BNB":
                return (item["address"], None)

    def getDepths(
        self, products: List[str]
    ) -> Tuple[Optional[Dict[str, Dict[str, int]]], Optional[str]]:
        if BNB not in products:
            products.append(BNB)

        pools = self._request("GET", endpoint="/thorchain/pools")
        if isinstance(pools, str):
            return (None, pools)
        else:
            return_me = {}
            for item in pools:
                asset = item["asset"]
                if asset in products:
                    return_me[asset] = {
                        "assetDepth": int(item["balance_asset"]),
                        "runeDepth": int(item["balance_rune"]),
                    }
            return (return_me, None)
