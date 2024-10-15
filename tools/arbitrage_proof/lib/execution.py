import math
import time
import uuid
from decimal import Decimal

from loguru import logger

from tools.arbitrage_proof.lib.constants import (
    CASE_1,
    CASE_2,
    CONSTANTS,
    KEY,
    MIDGARD_SWAP_DICTIONARY,
    MIDGARD_TRANSFER_DICTIONARY,
    ExecutionReport,
)
from tools.arbitrage_proof.lib.lib import execute_order, timeit


class ExecuteCase:
    def execute(self, report):
        """
        Execute the arbitrage opportunity using the report dictionary.

        Args:
            report (dict): Report with the information about what needs to be executed.
        """

        self.report = report

        if report[KEY.CASE_NAME] == KEY.CASE_1:
            reports = self.execute_case_1()

        elif report[KEY.CASE_NAME] == KEY.CASE_2:
            reports = self.execute_case_2()

        else:
            raise KeyError(f"Invalid case name, got: {report[KEY.CASE_NAME]}")

        roc_executed = (
            float(reports[-1].EXECUTED_QTY) / float(self.report["capital_in_base"]) - 1
        )
        roc_planned = float(self.report["roc"])
        difference = round((float(roc_executed) - roc_planned) * 1e4, 2)
        sign_difference = "+" if difference > 0 else "-"
        revenue = round(
            float(reports[-1].EXECUTED_QTY) - float(self.report["capital_in_base"]), 2
        )

        roc_string = (
            f"Executed ROC is {round(float(roc_executed) * 1e4,2)}bp "
            f"vs {round(roc_planned * 1e4, 2)}bp "
            f" --> {sign_difference}{difference} bp"
        )

        revenue_string = f"Revenue={revenue} {self.report['BASE']}"

        logger.info(roc_string)
        logger.info(revenue_string)
        self._db.addPoint({"_message": roc_string})
        self._db.addPoint({"_message": revenue_string})

        self._db_log["total_time"] = sum([report.TIME_S for report in reports])
        self._db_log["revenue"] = revenue
        self._db_log["revenue_expected"] = float(self.report["revenue"])

    def handle_report(self, report, step_id, expected_qty=None, step_name=""):
        if not report.SUCCESS:
            raise RuntimeError(str(report))

        if expected_qty is not None:
            report.EXPECTED_QTY = expected_qty

        report.STEP_NAME = step_name

        self.reports.append(report)

        logger.info(str(report))

        self._db.addPoint({"_message": str(report)})
        self._db_log[f"time_step_{step_id}"] = report.TIME_S

        if report.DIFFERENCE_EXPECTED is not None:
            self._db_log[f"difference_expected_{step_id}"] = report.DIFFERENCE_EXPECTED

    def execute_case_1(self):
        """
        Execute the case 1 strategy.

        This strategy starts with a swap of the the base asset to the product on bepswap
        before sending this product to the CEX and selling it with a market order.
        The resulting base is then sent too the wallet.
        """

        base = self.report[KEY.BASE]
        product = self.report[KEY.PRODUCT]
        base_capital = self.report[KEY.BASE_CAPITAL]

        self.reports = []

        # Dex swap from base to product
        coin_from = MIDGARD_SWAP_DICTIONARY.get(base, base)
        self.handle_report(
            self.dex_swap(coin_from=coin_from, coin_to=product, quantity=base_capital),
            expected_qty=self.report[KEY.CASE][CASE_1.EXPECTED_STEP_1],
            step_name=CASE_1.STEP_1,
            step_id=1,
        )

        # Transfer product from DEX to CEX.
        self.handle_report(
            self.dex_transfer(
                coin=self.reports[0].SYMBOL, quantity=self.reports[0].EXECUTED_QTY,
            ),
            step_name=CASE_1.STEP_2,
            step_id=2,
        )

        # Sell product for base on CEX.
        self.handle_report(
            self.cex_market_order(
                coin_from=product, coin_to=base, quantity=self.reports[1].EXECUTED_QTY,
            ),
            expected_qty=self.report[KEY.CASE][CASE_1.EXPECTED_STEP_3],
            step_name=CASE_1.STEP_3,
            step_id=3,
        )

        # Transfer product from CEX to DEX.
        self.handle_report(
            self.cex_transfer(coin=base, quantity=self.reports[2].EXECUTED_QTY),
            step_name=CASE_1.STEP_4,
            step_id=4,
        )

        return self.reports

    def execute_case_2(self):
        """
        Execute the case 2 strategy.

        This strategy starts with buying some asset (product) on Exchange, transfer
        those to the DEX, swap it for the base on the CEX, and then transfer it back to
        the CEX.
        """

        base = self.report[KEY.BASE]
        product = self.report[KEY.PRODUCT]
        base_capital = Decimal(self.report[KEY.BASE_CAPITAL]) / Decimal(
            self.report[KEY.ASK_PRICE]
        )

        self.reports = []

        # 1. Buy product for base on CEX.
        self.handle_report(
            self.cex_market_order(
                coin_from=base, coin_to=product, quantity=base_capital,
            ),
            expected_qty=self.report[KEY.CASE][CASE_2.EXPECTED_STEP_1],
            step_id=1,
            step_name=CASE_2.STEP_1,
        )

        # 2. Transfer product from CEX to DEX.
        self.handle_report(
            self.cex_transfer(coin=product, quantity=self.reports[0].EXECUTED_QTY),
            step_id=2,
            step_name=CASE_2.STEP_2,
        )

        # 3. Dex swap from product to base
        self.handle_report(
            self.dex_swap(
                coin_from=product, coin_to=base, quantity=self.reports[1].EXECUTED_QTY,
            ),
            expected_qty=self.report[KEY.CASE][CASE_2.EXPECTED_STEP_3],
            step_id=3,
            step_name=CASE_2.STEP_3,
        )

        # 4. Transfer base from DEX to CEX.
        self.handle_report(
            self.dex_transfer(
                coin=self.reports[2].SYMBOL, quantity=self.reports[2].EXECUTED_QTY,
            ),
            step_id=4,
            step_name=CASE_2.STEP_4,
        )

        return self.reports

    @timeit
    def dex_swap(
        self, coin_from: str, coin_to: str, quantity: Decimal, confirmation=True
    ) -> ExecutionReport:
        """
        Swap the coin_from for the coin_to on the DEX. The function return

        Args:
            coin_from (str): The name of the coin_from
            coin_to (str): The name of the coin_to
            quantity (Decimal): The amount of coin_from to swap for the coin_to

        Returns:
            (ExecutionReport) The report about the run of the execution
        """

        coin_to = MIDGARD_SWAP_DICTIONARY.get(coin_to, coin_to)

        memo = f"SWAP:{coin_to}"
        address = self._bepswap.address

        method = self._dex.Transfer
        arguments = {
            KEY.COIN: coin_from,
            KEY.QTY: quantity,
            KEY.ADDRESS: address,
            KEY.MEMO: memo,
        }

        report = execute_order(method, arguments)
        report.SYMBOL = coin_to
        if not report.SUCCESS or not confirmation:
            return report

        while True:
            time.sleep(CONSTANTS.TIME_DELAY)
            transactions, _ = self._dex.getTransactions()

            print(transactions, report.TRANSACTION_ID)
            if transactions is not None:
                for item in transactions:

                    if item["memo"] == f"OUT:{report.TRANSACTION_ID}":
                        report.EXECUTED_QTY = Decimal(item["value"])
                        report.SYMBOL = item["txAsset"]
                        return report

                    elif item["memo"] == f"REFUND:{report.TRANSACTION_ID}":
                        report.EXECUTED_QTY = Decimal(0)
                        report.SUCCESS = False
                        report.ERROR_STR = (
                            "Transaction failed, funds have been returned to DEX."
                        )
                        return report

    @timeit
    def dex_transfer(self, coin: str, quantity: Decimal) -> ExecutionReport:
        """
        Transfer the coin from the DEX to the CEX

        Args:
            coin (str): The name of the coin
            quantity (Decimal): The amount of coin_from to swap for the coin_to

        Returns:
            (ExecutionReport) The report about the run of the execution
        """
        coin = MIDGARD_TRANSFER_DICTIONARY.get(coin, coin)

        address, memo = (
            self._cex.address,
            self._cex.memo,
        )

        method = self._dex.Transfer
        arguments = {
            # TODO: Fix coin_from denomination in CEX
            KEY.COIN: coin,
            KEY.QTY: quantity,
            KEY.ADDRESS: address,
            KEY.MEMO: memo,
        }

        report = execute_order(method, arguments)
        report.SYMBOL = coin
        if not report.SUCCESS:
            return report

        while True:
            time.sleep(CONSTANTS.TIME_DELAY)
            transactions, _ = self._cex.getTransactions()

            if transactions is not None:
                for item in transactions:
                    if report.TRANSACTION_ID == item["txId"]:
                        product = coin.split("-")[0]
                        original_qty = self._json_log["wallets"]["before"]["cex"][
                            product
                        ]
                        while True:
                            new_qty, _ = self._cex_accounts.getWallet()
                            if new_qty[product] != original_qty:
                                report.EXECUTED_QTY = quantity
                                return report
                            time.sleep(CONSTANTS.TIME_DELAY / 2)

    @timeit
    def cex_market_order(
        self, coin_from: str, coin_to: str, quantity: Decimal
    ) -> ExecutionReport:
        """
        Search for the market pair and execute a sell/buy order to get the coin to from
        the coin from.

        Args:
            coin_from (str): The name of the coin_from
            coin_to (str): The name of the coin_to
            quantity (Decimal): The amount of coin_from to swap for the coin_to

        Returns:
            (ExecutionReport) The report about the run of the execution
        """

        if coin_from + coin_to in self._cex.reference:
            market_pair = coin_from + coin_to
            min_qty = self._cex.reference[market_pair][KEY.MIN_QTY]
            min_notional = self._cex.reference[market_pair][KEY.MIN_QTY]

            quantity *= -1

        elif coin_to + coin_from in self._cex.reference:
            market_pair = coin_to + coin_from
            min_qty = self._cex.reference[market_pair][KEY.MIN_QTY]
            min_notional = self._cex.reference[market_pair][KEY.MIN_NOTIONAL]

        report = ExecutionReport()
        report.SYMBOL = coin_to
        qty = math.floor(quantity / min_qty) * min_qty

        if False:  # abs(qty) < min_notional:
            report.SUCCESS = False
            report.ERROR_STR = (
                f"Market order for {qty} {market_pair} but min notional is "
                f"{self._cex.reference[market_pair][KEY.MIN_NOTIONAL]}"
            )
            return report

        order_id, error = self._cex.Post(symbol=market_pair, qty=qty)

        if error is not None:
            report.SUCCESS = False
            report.ERROR_STR = (
                f"Error when posting the order for {round(quantity,2)} "
                f"of {coin_from} {error}"
            )
            return report

        while True:
            status, _ = self._cex.getStatus(order_id)
            if status is not None and status["status"] == "FILLED":

                original_qty = self._json_log["wallets"]["before"]["cex"][coin_to]

                while True:
                    new_qty, _ = self._cex_accounts.getWallet()
                    if new_qty is not None and new_qty[coin_to] != original_qty:
                        executed_qty = new_qty[coin_to] - original_qty
                        report.EXECUTED_QTY = executed_qty
                        return report

                    time.sleep(CONSTANTS.TIME_DELAY / 2)

            time.sleep(CONSTANTS.TIME_DELAY / 2)

    @timeit
    def cex_transfer(self, coin: str, quantity: Decimal) -> ExecutionReport:
        """
        Transfer the coin from the CEX to the DEX

        Args:
            coin (str): The name of the coin
            quantity (Decimal): The amount of coin_from to swap for the coin_to

        Returns:
            (ExecutionReport) The report about the run of the execution
        """

        address = self._config["dex"]["address"]
        memo = uuid.uuid4().__str__().split("-")[0]

        transaction_id, err = self._cex.Transfer(
            coin, quantity, address=address, memo=memo
        )

        report = ExecutionReport()
        report.SYMBOL = coin

        if err is not None:
            report.SUCCESS = False
            report.ERROR_STR = f"Failed transfer with error: {err}"

            return report

        while True:
            time.sleep(CONSTANTS.TIME_DELAY)
            transactions, err = self._dex.getTransactions()

            if err is None:
                for item in transactions:
                    if item["memo"] == memo:
                        report.EXECUTED_QTY = Decimal(item["value"])
                        return report
