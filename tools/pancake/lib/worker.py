import json
import sys
import traceback
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger
from tools.pancake.lib.constants import CONSTANTS, KEY
from tools.pancake.lib.helpers import id_generator

sys.path.append(Path(__file__).absolute().parent.parent.parent.parent.as_posix())
from tools.pancake.lib.arbitrage import Arbitrage, Case
from tools.pancake.lib.db import Db
from tools.pancake.lib.execution import Execution
from tools.pancake.lib.venue.bakery import Bakery
from tools.pancake.lib.venue.ape import Ape
from tools.pancake.lib.venue.base import OperationResult, Pair
from tools.pancake.lib.venue.binance_spot import BinanceSpot
from tools.pancake.lib.venue.pancake import Pancake


class Worker:
    def __init__(self, config: dict):
        self._config = config

        self._bidask = BinanceSpot(self._config)

        if self._config.get("dex_exchange", "pancake") == "pancake":
            self._xyk = Pancake(self._config)
        elif self._config.get("dex_exchange", "pancake") == "bakery":
            self._xyk = Bakery(self._config)
        elif self._config.get("dex_exchange", "pancake") == "ape":
            self._xyk = Ape(self._config)

        self._arbitrage = Arbitrage(self._config, bidask=self._bidask, xyk=self._xyk)
        self._db = Db(self._config)

        self._quotes = self._config["quotes"]
        self.live_execution = self._config.get("live_execution", False)

        self.min_liquidity = self._config.get(
            KEY.MIN_LIQUIDITY, CONSTANTS.MIN_LIQUIDITY
        )

        self.min_roc_execution = self._config.get(
            KEY.MIN_ROC_EXECUTION, CONSTANTS.MIN_ROC_EXECUTION
        )

        self._between_10_000_and_100k = []
        self._between_100k_and_1M = []
        self._more_than_1M = []

        self._filter_products_min_liquidity()

        print(self._between_10_000_and_100k)
        print(self._between_100k_and_1M)
        print(self._more_than_1M)

        self._products = self._get_products()

        self.product_dict = {
            str(product).replace("-", ""): product for product in self._products
        }

    def _filter_products_min_liquidity(self):
        """
        Remove pools where the total liquidity is below the MIN_LIQUIDITY parameter
        """

        prices = self._bidask.get_prices()

        for key, item in self._xyk._reference.items():

            total_reserve = 0
            if item["pool_inverted"]:
                token_quote = "token0"
                token_base = "token1"

                quote_decimals = "base_decimals"
                base_decimals = "quote_decimals"
            else:
                token_quote = "token1"
                token_base = "token0"

                quote_decimals = "quote_decimals"
                base_decimals = "base_decimals"

            quote_reserves = Decimal(
                item[f"{token_quote}_reserves"] * 10 ** (-item[quote_decimals])
            )
            base_reserves = Decimal(
                item[f"{token_base}_reserves"] * 10 ** (-item[base_decimals])
            )

            if item["quote_asset"] in CONSTANTS.STABLE_COINS:
                total_reserve = quote_reserves * prices[item["symbol"]] + base_reserves

            elif item["base_asset"] in CONSTANTS.STABLE_COINS:
                total_reserve = base_reserves * prices[item["symbol"]] + quote_reserves

            else:
                for stable_coin in CONSTANTS.STABLE_COINS:
                    pair = item["quote_asset"] + stable_coin
                    if pair in prices:
                        total_reserve = (
                            quote_reserves * prices[item["symbol"]] + base_reserves
                        ) * prices[pair]

                        break

            self._xyk._reference[key]["pool_size_usd"] = total_reserve

        for key in list(self._xyk._reference.keys()):
            print(key, self._xyk._reference[key]["pool_size_usd"])

            if self._xyk._reference[key]["pool_size_usd"] < self.min_liquidity:
                self._xyk._reference.pop(key, None)

            elif self._xyk._reference[key]["pool_size_usd"] < 100_000:
                self._between_10_000_and_100k.append(key)
            elif self._xyk._reference[key]["pool_size_usd"] < 1_000_000:
                self._between_100k_and_1M.append(key)
            else:
                self._more_than_1M.append(key)

    def _get_quotes(self) -> List[str]:
        return list({x.quote for x in self._products})

    def _get_products(self) -> List[Pair]:
        quotes = self._quotes.keys()
        return [
            x
            for x in self._xyk._reference
            if x.quote in quotes and x in self._bidask._pairs_info
        ]

    def _get_quote_capitals(self, pair: Pair) -> List[Decimal]:
        capitals = self._quotes[pair.quote]
        capitals = capitals if isinstance(capitals, list) else [capitals]
        return [Decimal(str(x)) for x in capitals]

    def _get_all_opportunities(self) -> List[dict]:
        return_me = []

        for pair in self._bidask._orderbooks.keys():  # self._products:
            for capital in self._get_quote_capitals(pair):
                return_me.extend(self._arbitrage.getReport(pair, capital=capital))
        return return_me

    def _get_best_cases(self, opportunities: List[dict]):
        bests = sorted(opportunities, key=lambda x: x["roc"], reverse=True)
        return bests

    def _get_top_roc_fields(
        self,
        opportunities: List[dict],
        top: int = 5,
        quote: Optional[str] = None,
        capital: Optional[Decimal] = None,
    ) -> Dict[str, float]:
        return_me = {}
        filter = (
            opportunities
            if quote is None
            else [x for x in opportunities if x["pair"].quote == quote]
        )
        filter = (
            filter
            if capital is None
            else [x for x in filter if x["capital"] == capital]
        )
        for idx, case in enumerate(filter[:top]):
            return_me[f"top_{idx}"] = float(case["roc"])
        return return_me

    def update_dex_reserves(self):
        """
        Update the reserves from the dex
        """
        self._xyk.updateReserves(self._products)

    def update_cex_reserves(
        self, symbol: str, ask: Decimal, bid: Decimal, timestamp: int
    ) -> None:
        """
        Update the reserves for the cex
        """
        if symbol in self.product_dict.keys():
            self._bidask._orderbooks[self.product_dict[symbol]] = {
                "asks": [[ask, Decimal(0)]],
                "bids": [[bid, Decimal(0)]],
                "timestamp": timestamp,
            }

    def run(self, orderbook) -> Optional[dict]:
        # We will round time to seconds for more clear database data
        # TODO: Probably we should not round on websocket data
        now = datetime.utcnow().replace(microsecond=0)

        if not self.live_execution:
            logger.info(f"Starting iteration at {now}")
        fields = {}

        # Bruteforce ALL cases
        reports = self._get_all_opportunities()

        # Choose best one (sort first)
        bests = self._get_best_cases(reports)

        best = bests[0]

        # Track BEST case to database
        fields["capital"] = best["capital"]
        fields["target_roc"] = best["roc"]
        # fields["_best"] = json.dumps(clear_decimals(best))

        # Save data to database
        self.fields_output = fields
        self.best_roc_quotes = []

        # Save bests for each quote
        for quote in self._get_quotes():
            for capital in self._quotes[quote]:

                self.best_roc_quotes.append(
                    [
                        quote,
                        capital,
                        self._get_top_roc_fields(bests, quote=quote, capital=capital),
                    ]
                )

        # Make some stdout output
        if not self.live_execution:
            logger.info(f"Best case: {best}")
            logger.info(f'Best ROC: {best["roc"]}')

        elif best["roc"] > self.min_roc_execution:

            try:
                best["pair"] = best["pair"].base + "-" + best["pair"].quote

                executor = Execution(id_generator(), self._config)
                results = executor.execute(best)

                now = datetime.utcnow().replace(microsecond=0)
                self._db.addPoint(results, time=now)

            except Exception:
                logger.error(f"ERROR ON RUN {executor.run_id}")
                logger.error(str(traceback.format_exc()))
                logger.warning(f"Unlocking pair {best['pair']} after failure")
                executor.unlock(best["pair"])

        return (
            self.fields_output,
            self.best_roc_quotes,
            json.dumps(clear_decimals(best)),
        )


# TODO: Rewrite DecimalEncoder to handle dict with decimals inside dict
def clear_decimals(d: dict):
    return_me = {}
    for key, value in d.items():
        if isinstance(value, dict):
            return_me[key] = clear_decimals(value)
        elif isinstance(value, Decimal):
            return_me[key] = float(value)
        elif isinstance(value, Pair):
            return_me[key] = str(value)
        elif isinstance(value, Case):
            return_me[key] = value.value
        elif isinstance(value, OperationResult):
            return_me[key] = value.value
        else:
            return_me[key] = value
    return return_me
