import sys
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

from eth_typing import Address
from web3 import Web3, HTTPProvider


sys.path.append(Path(__file__).absolute().parent.parent.parent.parent.parent.as_posix())
from tools.pancake.lib.venue.base.xyk import Xyk
from tools.pancake.lib.venue.base import Pair, OperationResult
from tools.pancake.lib.helpers import load_json_data

NULL_ADDRESS = Address("0x0000000000000000000000000000000000000000")

PANCAKE_FACTORY = Address("0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73")

PANCAKE_ROUTER = Address("0x10ED43C718714eb63d5aA57B78B54704E256024E")

E18 = Decimal("1e18")

POOL_FEE = Decimal("0.0020")


class Pancake(Xyk):
    def __init__(self, config: dict):
        super().__init__(config)

        self._node = self._config["pancake"]["node"]

        self._w3 = Web3(HTTPProvider(self._node))

        # Load contract's ABI
        pancake_factory_abi = load_json_data("pancake/factory")
        pancake_router_abi = load_json_data("pancake/router")
        self._pancake_pair_abi = load_json_data("pancake/pair")
        self._bsc_token_abi = load_json_data("bsc_token")

        self._pancake_factory = self._w3.eth.contract(
            address=PANCAKE_FACTORY, abi=pancake_factory_abi
        )
        self._pancake_router = self._w3.eth.contract(
            address=PANCAKE_ROUTER, abi=pancake_router_abi
        )

    def loadReference(self) -> Dict[Pair, dict]:
        reference = load_json_data("pancake/reference")
        return {
            Pair(base=x.split("-")[0], quote=x.split("-")[1]): y
            for x, y in reference.items()
        }

    def updateReserves(self, pairs: List[Pair]):
        def _fn(pair: Pair):
            if pair in self._reference:
                address = self._reference[pair]["pool"]
                inverted = self._reference[pair]["pool_inverted"]
            else:
                return

            contract = self._w3.eth.contract(address, abi=self._pancake_pair_abi)

            reserve0, reserve1, _ = contract.functions.getReserves().call()
            reserve0, reserve1 = Decimal(str(reserve0)), Decimal(str(reserve1))

            self._reserves[pair] = (
                {
                    "reserve0": reserve1,
                    "reserve1": reserve0,
                    "price": reserve0 / reserve1,
                }
                if inverted
                else {
                    "reserve0": reserve0,
                    "reserve1": reserve1,
                    "price": reserve1 / reserve0,
                }
            )

        with ThreadPoolExecutor(max_workers=16) as executor:
            for pair in pairs:
                executor.submit(_fn, pair)

    def swapBase(
        self, pair: Pair, base: Decimal, live: bool = False
    ) -> OperationResult:
        fee = base * POOL_FEE
        quote = self._calc_swap_base(pair, qty=base - fee)
        return OperationResult(value=quote)

    def swapQuote(
        self, pair: Pair, quote: Decimal, live: bool = False
    ) -> OperationResult:
        fee = quote * POOL_FEE
        base = self._calc_swap_quote(pair, qty=quote - fee)
        return OperationResult(value=base)

    def transferQuote(
        self, bidask, pair: Pair, quote: Decimal, live: bool = False
    ) -> OperationResult:
        return OperationResult(value=quote)

    def transferBase(
        self, bidask, pair: Pair, base: Decimal, live: bool = False
    ) -> OperationResult:
        return OperationResult(value=base)
