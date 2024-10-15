from decimal import Decimal
from typing import List, Dict

import requests

DEX = "https://dex.binance.org"

CEX = "https://api.binance.com"


def get_cex_products() -> List[dict]:
    """
    Get all products with latest ask/bid price/qty from Binance Dex api
    :return:
    """
    r = requests.get(CEX + "/api/v3/ticker/24hr")
    return r.json()


def get_dex_products() -> List[dict]:
    """
    Get all products with latest ask/bid price/qty from Binance Dex api
    :return:
    """
    r = requests.get(DEX + "/api/v1/ticker/24hr")
    return r.json()


def find_and_normalize_cex_products(
    cex_products: List[dict],
) -> Dict[str, Dict[str, Decimal]]:
    return_me = {}

    for item in cex_products:
        symbol: str = item["symbol"]
        if symbol.endswith("BNB"):
            ask_price = Decimal(item["askPrice"])
            ask_qty = Decimal(item["askQty"])
            bid_price = Decimal(item["bidPrice"])
            bid_qty = Decimal(item["bidQty"])

            if ask_price > Decimal(1e-9) and bid_price > Decimal(1e-9):
                return_me[symbol] = {
                    "ask_price": ask_price,
                    "ask_qty": ask_qty * ask_price,
                    "bid_price": bid_price,
                    "bid_qty": bid_qty * bid_price,
                }

    return return_me


def find_and_normalize_dex_products(
    dex_products: List[dict],
) -> Dict[str, Dict[str, Decimal]]:
    """
    Find "BNB" products like asset_BNB or BNB_asset

    For products like asset_BNB:
      - convert ask/bid qty to BNB (price * qty)

    For products like BNB_asset:
      - ask_price = 1 / bid_price
      - ask_qty = bid_qty
      - bid_price = 1 / ask_price
      - bid_qty = ask_qty
      - make name like asset_BNB

    :param dex_products:
    :return:
    """
    return_me = {}

    for item in dex_products:
        symbol = item["symbol"]
        left, right = symbol.split("_")

        ask_price = Decimal(item["askPrice"])
        ask_qty = Decimal(item["askQuantity"])
        bid_price = Decimal(item["bidPrice"])
        bid_qty = Decimal(item["bidQuantity"])

        if ask_price > Decimal(1e-9) and bid_price > Decimal(1e-9):

            if left == "BNB":
                symbol = right.split("-")[0] + left.split("-")[0]
                return_me[symbol] = {
                    "ask_price": 1 / bid_price,
                    "ask_qty": bid_qty,
                    "bid_price": 1 / ask_price,
                    "bid_qty": ask_qty,
                }

            elif right == "BNB":
                symbol = left.split("-")[0] + right.split("-")[0]
                return_me[symbol] = {
                    "ask_price": ask_price,
                    "ask_qty": ask_qty * ask_price,
                    "bid_price": bid_price,
                    "bid_qty": bid_qty * bid_price,
                }

    return return_me
