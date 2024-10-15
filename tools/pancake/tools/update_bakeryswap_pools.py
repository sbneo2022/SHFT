import copy
import json
import sys
import traceback
from pathlib import Path

import requests
import tqdm
import pandas as pd

sys.path.append(Path(__file__).absolute().parent.parent.parent.parent.as_posix())
from tools.pancake.lib.helpers import DecimalEncoder
from tools.pancake.lib.venue.bakery import Bakery, NULL_ADDRESS
from tools.pancake.lib.venue.base import Pair
from tools.pancake.lib.venue.binance_spot import BinanceSpot

QUOTES = ["BNB", "USDT", "BUSD"]

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {__file__} [binance_key] [binance_secret]")
        exit(-1)

    # 1. Get all Pancake tokens
    url = "https://raw.githubusercontent.com/bscswap/default-token-list/9c601a3b40c30f57a56d39a6e3d42f5b3a92aa30/src/tokens/mainnet.json"
    bakery_tokens = {
        item["symbol"]
        if item["symbol"] != "WBNB"
        else "BNB": {"address": item["address"], "name": item["name"]}
        for item in pd.read_json(url).to_dict(orient="records")
    }

    # Get all Binance products and pairs
    binance = BinanceSpot({"binance": {"key": sys.argv[1], "secret": sys.argv[2]}})
    binance_list = binance._get_products_info()
    binance_pairs = binance.getPairsInfo()

    # Join Pancake and Binance products
    good_products = {}
    for item, data in bakery_tokens.items():
        if item in binance_list.keys() or item == "WBNB":
            binance_item = "BNB" if item == "WBNB" else item
            good_products[binance_item] = copy.deepcopy(binance_list[binance_item])
            good_products[binance_item]["address"] = data["address"]
            good_products[binance_item]["pancake"] = data["name"]

    # Load decimals for tokens
    bakery = Bakery({"bakery": {"node": "https://bsc-dataseed.binance.org/"}})
    iterator = tqdm.tqdm(good_products)
    for symbol in iterator:
        iterator.set_description(f"Load decimals for {symbol:10}")
        contract = bakery._w3.eth.contract(
            good_products[symbol]["address"], abi=bakery._bsc_token_abi
        )
        good_products[symbol]["decimals"] = contract.functions.decimals().call()

    # generate possible pairs with target quotes
    combinations = []
    for base in good_products.keys():
        if base not in QUOTES:
            for quote in QUOTES:
                combinations.append(Pair(base=base, quote=quote))

    target_pairs = {}
    for item in combinations:
        if item in binance_pairs:
            if not binance_pairs[item]["inverted"]:
                target_pairs[item] = copy.deepcopy(binance_pairs[item])
                target_pairs[item]["base_address"] = good_products[item.base]["address"]
                target_pairs[item]["quote_address"] = good_products[item.quote][
                    "address"
                ]
                target_pairs[item]["base_decimals"] = good_products[item.base][
                    "decimals"
                ]
                target_pairs[item]["quote_decimals"] = good_products[item.quote][
                    "decimals"
                ]

    # Load Pancake Pools
    delete_me = []
    iterator = tqdm.tqdm(target_pairs)
    for pair in iterator:
        iterator.set_description(f"Load pool address for {str(pair):10}")
        try:
            token0 = target_pairs[pair]["base_address"]
            token1 = target_pairs[pair]["quote_address"]
            target_pairs[pair]["pool"] = bakery._bakery_factory.functions.getPair(
                token0, token1
            ).call()
            if target_pairs[pair]["pool"] == NULL_ADDRESS:
                delete_me.append(pair)
                continue
            contract = bakery._w3.eth.contract(
                target_pairs[pair]["pool"], abi=bakery._bakery_pair_abi
            )

            token0_reserve, token1_reserve, _ = contract.functions.getReserves().call()

            target_pairs[pair]["token0_reserves"] = token0_reserve
            target_pairs[pair]["token1_reserves"] = token1_reserve

            actual_token0 = contract.functions.token0().call()
            if actual_token0 == token0:
                target_pairs[pair]["pool_inverted"] = True
            else:
                target_pairs[pair]["pool_inverted"] = False
        except Exception as e:
            print(target_pairs[pair])
            traceback.print_exc()
            exit()

    for item in delete_me:
        del target_pairs[item]

    # Save Reference
    filename = (
        Path(__file__).absolute().parent.parent
        / Path("data")
        / Path("bakery")
        / Path("reference.json")
    )
    with filename.open("w") as fp:
        json.dump(
            {str(x): y for x, y in target_pairs.items()},
            fp,
            indent=2,
            cls=DecimalEncoder,
        )

    print(f"Saved to {filename}")
