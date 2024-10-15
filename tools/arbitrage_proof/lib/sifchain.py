import os
import sys
from typing import Dict, Optional, Union, List, Iterable, Tuple
from decimal import Decimal

sys.path.append(os.path.abspath("../../.."))
from tools.arbitrage_proof.lib.swap import Swap

SECTION = "sifchain"
BASES = ["USDC", "USDT", "UST"]


class Sifchain(Swap):
    def __init__(self, config: dict):
        super().__init__(config)
        self._pool = config[SECTION]["pool"]
        self.depths = {}

    def getProducts(self) -> Tuple[Optional[list], Optional[str]]:
        pools = self._request("GET", endpoint="/pool")

        if isinstance(pools, str):
            return (None, pools)
        else:
            return_me = []
            for item in pools:
                asset = item["externalAsset"]["symbol"].upper()

                return_me.append(asset)
                self.reference[asset] = asset
                self.depths[asset] = {
                    "assetDepth": int(item["externalAsset"]["balance"]),
                    "rowanDepth": int(item["nativeAsset"]["balance"]),
                }

            return (return_me, None)

    def getExchangeIntersection(
        self, bepswap: Iterable[str], exchange: Iterable[str]
    ) -> Tuple[Optional[List[str]], Optional[str]]:
        """
        Get interesection of pools and symbols between both exchanges.

        Args:
            bepswap (Iterable[str]): The list of assets for the dex
            exchange (Iterable[str]): The list of assets for the cex

        Returns:
            Tuple[Optional[List[str]], Optional[str]]: List of asset for the dex
                filtered.
        """
        return_me = []
        for item in bepswap:
            for base in BASES:
                if item + base in exchange:
                    return_me.append(item)
                    break

        return (return_me, None)

    def _get_swap_address(self) -> Tuple[Optional[str], Optional[str]]:
        raise NotImplementedError()

    def getDepths(
        self, products: List[str]
    ) -> Tuple[Optional[Dict[str, Dict[str, int]]], Optional[str]]:

        if not self.depths:
            return (None, None)
        else:
            return_me = {}
            for asset, item in self.depths.items():
                if asset in products:
                    return_me[asset] = {
                        "assetDepth": item["assetDepth"],
                        "rowanDepth": item["rowanDepth"],
                    }

            return (return_me, None)

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

        # Save asset/rune Depth for RUNE<->BNB Swap: It will be used for DoubleSwap calculations
        rune_assetDepth = pool_depths[BUSD]["assetDepth"]
        rune_runeDepth = pool_depths[BUSD]["runeDepth"]

        # First we will save results to product-bases dictionary
        # Then we will choose best capital for each one and will create final list
        return_me = defaultdict(lambda: [])

        # We need exchange dictionary to normalize products names
        exchange_dictionary = {}

        # Also we need to find and save current BNB<->USD rate (estimate)
        base_usd_price: Optional[Decimal] = None

        for key, value in exchange_prices.items():
            if "_" in key:
                left, right = key.split("_")
                product = left.split("-")[0] + right.split("-")[0]
            else:
                product = key
            exchange_dictionary[product] = key

            base_usd_price = Decimal("1")

            # if key in BNB_USD and base_usd_price is None:
            #     ask_price, bid_price = value['ask_price'], value['bid_price']
            #     base_usd_price = (ask_price + bid_price) / 2

        capitals = (
            self._get_capitals(capital)
            if capital_fitting
            else [randomize_value(capital, self._scattering, self._scattering)]
        )

        # Now we are bruteforce all capitals for best product
        for capital_item in capitals:

            capital_in_base = capital_item / base_usd_price

            for name, item in pool_depths.items():
                payload = {
                    "base_usd_price": base_usd_price,
                    "capital_in_base": capital_in_base,
                    "capital_in_usd": capital_item,
                }

                assetDepth, runeDepth = item["assetDepth"], item["runeDepth"]
                payload["assetDepth"], payload["runeDepth"] = assetDepth, runeDepth

                product = name.split(".")[1].split("-")[0]
                payload["product"] = product

                if name == BUSD:
                    exchange_product = exchange_dictionary["RUNE" + BASE]
                    replace_ask_bid = False

                elif (product + BASE) in exchange_dictionary:
                    exchange_product = exchange_dictionary[product + BASE]
                    replace_ask_bid = False

                elif (BASE + product) in exchange_dictionary:
                    exchange_product = exchange_dictionary[BASE + product]
                    replace_ask_bid = True

                else:
                    continue

                payload["exchange_product"] = exchange_product
                payload["bepswap_product"] = name
                payload["replace_ask_bid"] = replace_ask_bid
                payload["BASE"] = BASE

                if replace_ask_bid:
                    ask_price, bid_price = (
                        1 / exchange_prices[exchange_product]["bid_price"],
                        1 / exchange_prices[exchange_product]["ask_price"],
                    )
                else:
                    ask_price, bid_price = (
                        exchange_prices[exchange_product]["ask_price"],
                        exchange_prices[exchange_product]["bid_price"],
                    )

                payload["ask_price"], payload["bid_price"] = ask_price, bid_price

                if name == BUSD:
                    payload["case"], payload["case_name"] = {}, CASE_1

                    # Case 1: Swap BNB -> asset on Bepswap, then buy BNB on exchange:
                    rune_we_swap = (
                        self._calc_swap_asset(assetDepth, runeDepth, capital_in_base)
                        - self.rune_commission
                    )
                    payload["case"][
                        f"1. Swap {BASE} to RUNE and get (RUNE)"
                    ] = rune_we_swap

                    bnb_we_get = rune_we_swap * (bid_price if market else ask_price)
                    payload["case"][
                        f"2. We can buy using Market order ({BASE})"
                    ] = bnb_we_get

                    roc = bnb_we_get / capital_in_base - 1
                    payload["roc"] = roc
                    payload["revenue"] = roc * capital_item

                    # Add case to cases list
                    return_me[product].append(payload.copy())

                    ###############################################################################################

                    payload["case"], payload["case_name"] = {}, CASE_2

                    # Case 2: Buy Asset on Exchange, then Swap to BNB on Bepswap:
                    rune_we_get = capital_in_base / (ask_price if market else bid_price)
                    payload["case"][
                        f"1. We can buy using Market order (RUNE)"
                    ] = rune_we_get

                    bnb_we_get = self._calc_swap_rune(
                        assetDepth, runeDepth, rune_we_get - self.rune_commission
                    )
                    payload["case"][
                        f"2. Swap RUNE to {BASE} and get ({BASE})"
                    ] = rune_we_get

                    roc = bnb_we_get / capital_in_base - 1
                    payload["roc"] = roc
                    payload["revenue"] = roc * capital_item

                    # Add case to cases list
                    return_me[product].append(payload.copy())
                else:
                    payload["case"], payload["case_name"] = {}, CASE_1

                    # Case 1: Swap BNB -> asset on Bepswap, then buy BNB on exchange:
                    rune_we_swap = (
                        self._calc_swap_asset(
                            rune_assetDepth, rune_runeDepth, capital_in_base
                        )
                        - self.rune_commission
                    )
                    payload["case"][
                        f"1. Doubleswap (1) {BASE} to {product} and get (RUNE)"
                    ] = rune_we_swap

                    asset_we_get = self._calc_swap_rune(
                        assetDepth, runeDepth, rune_we_swap
                    )
                    payload["case"][f"2. Doubleswap base to product"] = asset_we_get

                    bnb_we_get = asset_we_get * (bid_price if market else ask_price)

                    payload["case"][f"3. We can buy using Market order"] = bnb_we_get

                    roc = bnb_we_get / capital_in_base - 1
                    payload["roc"] = roc
                    payload["revenue"] = roc * capital_item

                    # Add case to cases list
                    return_me[product].append(payload.copy())

                    ###############################################################################################

                    payload["case"], payload["case_name"] = {}, CASE_2

                    # Case 2: Buy Asset on Exchange, then Swap to BNB on Bepswap:
                    asset_we_get = capital_in_base / (
                        ask_price if market else bid_price
                    )
                    payload["case"][f"1. We can buy using Market order"] = asset_we_get

                    rune_we_swap = (
                        self._calc_swap_asset(assetDepth, runeDepth, asset_we_get)
                        - self.rune_commission
                    )
                    payload["case"][
                        f"2. Doubleswap (1) {product} to {BASE} and get (RUNE)"
                    ] = rune_we_swap

                    bnb_we_get = self._calc_swap_rune(
                        rune_assetDepth, rune_runeDepth, rune_we_swap
                    )
                    payload["case"][f"3. Doubleswap product to base"] = bnb_we_get

                    roc = bnb_we_get / capital_in_base - 1
                    payload["roc"] = roc
                    payload["revenue"] = roc * capital_item

                    # Add case to cases list
                    return_me[product].append(payload.copy())

        if all_cases:
            return return_me
        # For each product we are choosing capital, that gives us best ROC
        best_cases = []
        for product, cases in return_me.items():
            best_capital = sorted(cases, key=lambda x: x["roc"], reverse=True)
            if only_one:
                best_cases.append(best_capital[0])
            else:
                best_cases.extend(cases)

        return sorted(best_cases, key=lambda x: x["roc"], reverse=True)
