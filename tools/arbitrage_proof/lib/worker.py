import json
import math
import os
import sys
import time
import uuid
from datetime import datetime
from decimal import Decimal
from pprint import pprint
from random import random
from typing import List, Tuple, Optional

from loguru import logger

FOLDER = os.path.dirname(__file__)
FOLDER = os.path.join(FOLDER, "../")
FOLDER = os.path.abspath(FOLDER)
FRAMEWORK = os.path.join(FOLDER, "../..")

sys.path.append(os.path.abspath(FRAMEWORK))
from tools.arbitrage_proof.lib.thorswap import Thorswap
from tools.arbitrage_proof.lib.helpers import DecimalEncoder, randomize_value
from tools.arbitrage_proof.lib.bepswap import Bepswap
from tools.arbitrage_proof.lib.thorswap_busd import ThorswapBusd
from tools.arbitrage_proof.lib.sifchain import Sifchain
from tools.arbitrage_proof.lib.cex import Cex
from tools.arbitrage_proof.lib.accounts import CexAccounts
from tools.arbitrage_proof.lib.dex import Dex
from tools.arbitrage_proof.lib.db import Db
from tools.arbitrage_proof.lib.lock import Lock
from tools.arbitrage_proof.lib.swap import BNB, RUNE, CASE_1, CASE_2
from tools.arbitrage_proof.lib.execution import ExecuteCase

TIME_DELAY = 5
ERR_MAX = 10

DEFAULT_PREFIX = "bepswap"
DEFAULT_COIN = "BNB"
BUSD_COIN = "BUSD"
ROWAN_COIN = "ROWAN"


class Worker(ExecuteCase):
    def __init__(self, config):
        self._config = config

        self.live_mode = config.get("live_mode", False)

        # Load parameters from config
        self._capital = Decimal(str(self._config["capital"]))
        self._prefix = self._config.get("prefix", DEFAULT_PREFIX)

        self._coin = self._config.get("coin", DEFAULT_COIN)

        # Create objects that we need
        self._cex_accounts = CexAccounts(config)

        self._cex = self._cex_accounts.getCex()

        self._dex = Dex(config)

        if self._coin == BUSD_COIN:
            self._bepswap = ThorswapBusd(config)
        elif self._coin == ROWAN_COIN:
            self._bepswap = Sifchain(config)
        else:
            self._bepswap = Bepswap(config)

        self._db = Db(config, prefix=self._prefix)

        # We will create different logs for text/json reports and database
        # Database has flat structure and mostly numerical values
        # Json log has human-readable keys and nested dicts
        self._json_log = {}
        self._db_log = {}

    def _track_capitals(self, pool_depths: dict, exchange_prices: dict):
        for value in self._config.get("track_capital", []):
            capital = Decimal(str(value))
            report = self._bepswap.getReport(
                capital,
                pool_depths=pool_depths,
                exchange_prices=exchange_prices,
                capital_fitting=False,
            )
            self._db.addPoint({f"roc_capital_{capital}": report[0]["roc"]})

    def _get_report(self, only_one=True) -> Optional[List[dict]]:
        logger.info(f"Loading list of Bepswap products...")
        bepswap_products, err = self._bepswap.getProducts()

        if bepswap_products is None:
            self._json_log["error"] = err
            logger.error(f"Error loading Bepswap products: {err}")
            return

        cex_products, _ = self._cex.getProducts()

        bepswap_products, _ = self._bepswap.getExchangeIntersection(
            bepswap=bepswap_products, exchange=cex_products.keys()
        )

        logger.info(f"Loading details for {len(bepswap_products)} Bepswap products...")
        bepswap_products, _ = self._bepswap.getDepths(bepswap_products)

        print(bepswap_products.keys())

        report = self._bepswap.getReport(
            self._capital,
            pool_depths=bepswap_products,
            exchange_prices=cex_products,
            only_one=only_one,
        )
        self._track_capitals(bepswap_products, cex_products)
        return report

    def arbitrage(self):
        self._json_log.clear()  # Clear arbitrage report

        if self._cex_accounts.getErrors() is not None:
            self._json_log["error"] = self._cex_accounts.getErrors()
            logger.error(f'ERROR: {self._json_log["error"]}')
            return

        self._json_log["account"] = self._cex.key
        self._db.addPoint({"_message": f'Used account: {self._json_log["account"]}'})

        # Load all data and create Report
        logger.info(f"Start arbitrage iteration")
        report = self._get_report(only_one=True)

        if report is None:
            return

        # Save wallets BEFORE arbitrage
        self._save_wallets("before")

        # Save current estimate for 24 BTC Withdrawal
        self._db_log["24h_withdrawal_btc"] = self._cex_accounts.getWithdrawAmount()
        self._db_log["24h_withdrawal_limit_btc"] = self._cex_accounts.getWithdrawLimit()

        # Filter report with only xxxBNB products
        report = [x for x in report if not x["replace_ask_bid"]]

        # Update DEX porducts and reference
        _ = self._dex.getProducts()

        # Filter report with only products that we have on Dex
        report = [x for x in report if x["product"] in self._dex.reference]

        self._db.addPoint(
            {
                "_message": f"DEBUG: Start Arbitrage iteration with {len(report)} products"
            }
        )

        case = report[0]
        self.case = case
        self._json_log["case"] = case
        self._db_log["best_case_roc"] = case["roc"]
        # self._db_log["second_case_roc"] = report[1]["roc"]

        self._db_log["capital"] = case["capital_in_usd"]
        self._db_log["capital_in_bnb"] = case["capital_in_base"]
        self._db_log["bnb_usd_price"] = case["base_usd_price"]
        self._db_log["case_name"] = case["case_name"]
        self._db_log["product"] = case["product"]

        logger.info(f"Best case:\n{json.dumps(case, indent=2, cls=DecimalEncoder)}")
        self._db.addPoint(
            {"_message": f"Best case: {json.dumps(case, cls=DecimalEncoder)}"}
        )
        threshold = Decimal(str(self._config.get("threshold", 0)))
        if case["roc"] < threshold:
            logger.warning(
                f'Best ROC: {case["roc"]} less than threshold={threshold}. Exit'
            )
            self._db.addPoint(
                {
                    "_message": f'WARNING: Best ROC: {case["roc"]} less than threshold={threshold}. Exit'
                }
            )
            return

        if self.live_mode:
            self.execute(case)

        # Save wallets AFTER arbitrage
        self._save_wallets("after")
