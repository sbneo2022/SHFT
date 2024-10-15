import os
import sys
from decimal import Decimal
from pprint import pprint
from typing import Optional, Tuple, Dict, List

import requests

sys.path.append(os.path.abspath("../../.."))
from tools.arbitrage_proof.lib.swap_busd import SwapBusd, BNB, BUSD

SECTION = "thorswap"


class ThorswapBusd(SwapBusd):
    def __init__(self, config: dict):
        super().__init__(config)
        self._pool = config[SECTION]["pool"]

        self.rune_commission = Decimal("0.06")

    def getProducts(self) -> Tuple[Optional[list], Optional[str]]:
        address, err = self._get_swap_address()
        if err is None:
            self.address = address
        else:
            return (None, err)

        pools = self._request("GET", endpoint="/thorchain/pools")

        if isinstance(pools, str):
            return (None, pools)
        else:
            return_me = []
            for item in pools:
                asset = item["asset"]
                network, product = asset.split(".")
                if network == "BNB" and item["status"] == "Available":
                    symbol = product.split("-")[0]
                    return_me.append(asset)
                    self.reference[symbol] = asset
            return (return_me, None)

    def _get_swap_address(self) -> Tuple[Optional[str], Optional[str]]:
        r = self._request("GET", endpoint="/thorchain/vaults/asgard")
        if isinstance(r, str):
            return (None, r)

        for item in r:
            for chain in item["addresses"]:
                if chain["chain"] == "BNB":
                    return (chain["address"], None)

    def getReport(
        self,
        capital: Decimal,
        pool_depths: Dict[str, Dict[str, int]],
        exchange_prices: Dict[str, Dict[str, Decimal]],
        market=True,  #  Use MARKET or LIMIT order
        capital_fitting=True,  # Try or not to find most profitable capital
        only_one=True,  # Return best capital for product or all
        all_cases=False,
    ) -> List[dict]:
        report = super().getReport(
            capital, pool_depths, exchange_prices, market, capital_fitting, only_one
        )
        if all_cases:
            return report

        return_me = []

        for item in report:
            if "RUNE" not in item["exchange_product"]:
                return_me.append(item)

        return return_me

    def getDepths(
        self, products: List[str]
    ) -> Tuple[Optional[Dict[str, Dict[str, int]]], Optional[str]]:
        if BUSD not in products:
            products.append(BUSD)

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
