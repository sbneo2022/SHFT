import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.append(os.path.abspath("../../.."))
from lib.worker import DEFAULT_PREFIX
from lib.db import Db

DEFAULT_REPORT_DEPTH = 24


class Report:
    def __init__(self, config: dict):
        self._config = config

        self._prefix = config.get("prefix", DEFAULT_PREFIX)

        self._db = Db(config, prefix=self._prefix)

    def getReport(self, last_hours=DEFAULT_REPORT_DEPTH):
        return_me = ""

        try:
            now = datetime.now(tz=timezone.utc)
            before = now - timedelta(hours=last_hours)

            return_me += f'*{self._config["method"].upper()} PNL Report*\n'
            return_me += f"*{now} UTC*\n\n"

            data = self._db.getPoint(
                now, fields=["bnb_cex_wallet_before", "bnb_dex_wallet_before"]
            )
            cex_wallet, dex_wallet = (
                data["bnb_cex_wallet_before"],
                data["bnb_dex_wallet_before"],
            )
            return_me += f"CEX Wallet NOW: {cex_wallet} BNB\n"
            return_me += f"DEX Wallet NOW: {dex_wallet} BNB\n"
            total_now = cex_wallet + dex_wallet

            data = self._db.getPoint(
                before, fields=["bnb_cex_wallet_before", "bnb_dex_wallet_before"]
            )
            cex_wallet, dex_wallet = (
                data["bnb_cex_wallet_before"],
                data["bnb_dex_wallet_before"],
            )
            return_me += f"CEX Wallet {last_hours}h ago: {cex_wallet} BNB\n"
            return_me += f"DEX Wallet {last_hours}h ago: {dex_wallet} BNB\n"
            total_before = cex_wallet + dex_wallet

            return_me += f"\nTOTAL BALANCE: {total_before} -> {total_now}\n"

            revenue = total_now - total_before
            return_me += f"\n*REVENUE: {revenue} BNB*\n"

            roc = total_now / total_before - 1
            return_me += f"*ROC: {(roc * 100):0.2f}%*"

        except Exception as e:
            return_me += f"\nError while generating report: {e}"

        return return_me
