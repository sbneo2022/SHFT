import json
from decimal import Decimal

from loguru import logger
from tools.pancake.lib.arbitrage import Case
from tools.pancake.lib.cex import Cex
from tools.pancake.lib.constants import CASE_1, CASE_2, KEY
from tools.pancake.lib.dex import Dex


class Execution:
    def __init__(self, run_id, config):
        self.cex = Cex(config)
        self.dex = Dex(config)
        self.run_id = run_id

    def handle_report(self, report, step_id, expected_qty=None, step_name=""):
        if not report.SUCCESS:
            logger.error(f"Error on run: {self.run_id}")
            raise RuntimeError(str(report))

        if expected_qty is not None:
            report.EXPECTED_QTY = expected_qty

        report.STEP_NAME = step_name
        report.STEP_ID = step_id

        self.reports.append(report)

        logger.info(f"{self.run_id}: " + str(report))

    def test_report_case_1(self):
        report = {
            "capital": Decimal("0.1"),
            "pair": "BAKE-BNB",
            "case": Case.ONE,
            "steps": {
                "1. we_got_base": Decimal("8.079189438215428449522425809"),
                "2. we_received_on_bidask": Decimal("8.079189438215428449522425809"),
                "3. we_got_quote": Decimal("0.5000746963074014936167046613"),
                "4. output": Decimal("0.5000746963074014936167046613"),
            },
            "roc": Decimal("0.000149392614802987233409323"),
        }

        return self.execute(report)

    def test_report_case_2(self):
        report = {
            "capital": Decimal(".1"),
            "pair": "BAKE-BNB",
            "case": Case.TWO,
            "steps": {
                "1. we_got_base": Decimal("26.20427428871115772912023076"),
                "2. we_received_on_xyk": Decimal("26.20427428871115772912023076"),
                "3. we_got_quote": Decimal("2.002711259120943062560158335"),
                "4. output": Decimal("2.002711259120943062560158335"),
            },
            "roc": Decimal("0.001355629560471531280079168"),
        }
        return self.execute(report)

    def locked(self, pair):
        """
        Check if pair is locked (use in another process)

        Args:
            pair (str): market pair

        Returns:
            bool: wether pair is locked or not
        """
        with open("lock.json", "r") as json_lock_file:
            dictionary = json.load(json_lock_file)[KEY.PAIR_LOCKED]

        return pair in dictionary

    def lock(self, pair):
        """
        Lock the pair

        Args:
            pair (str): The current pair
        """
        with open("lock.json", "r") as json_lock_file:
            dictionary = json.load(json_lock_file)

        dictionary[KEY.PAIR_LOCKED].append(pair)
        with open("lock.json", "w") as json_lock_file:
            json.dump(dictionary, json_lock_file)

    def unlock(self, pair):
        """
        Unlock the pair

        Args:
            pair (str): the current pair
        """
        with open("lock.json", "r") as json_lock_file:
            dictionary = json.load(json_lock_file)

        dictionary[KEY.PAIR_LOCKED].remove(pair)
        with open("lock.json", "w") as json_lock_file:
            json.dump(dictionary, json_lock_file)

    def execute(self, report):
        """
        Execute a report

        Args:
            report ([type]): [description]
        """
        pair = report["pair"]

        # if not self.locked(pair):
        #    self.lock(pair)
        # else:
        #    # logger.error("Locked. Passing on opportunity.")
        #    return {}

        logger.info(f"{self.run_id} - Executing report {report}")

        token_0, token_1 = pair.split("-")

        self.reports = []

        if report["case"] == Case.ONE:
            case_name = "case_ones"
            self.handle_report(
                self.dex.swap(token_1, token_0, report["capital"]),
                expected_qty=report[KEY.STEPS][CASE_1.EXPECTED_STEP_1],
                step_name=CASE_1.STEP_1,
                step_id=1,
            )

            self.handle_report(
                self.dex.transfer(token_0, self.reports[0].EXECUTED_QTY, self.cex),
                expected_qty=report[KEY.STEPS][CASE_1.EXPECTED_STEP_2],
                step_name=CASE_1.STEP_2,
                step_id=2,
            )
            print(self.reports)

            self.handle_report(
                self.cex.market_order(token_0, token_1, self.reports[1].EXECUTED_QTY),
                expected_qty=report[KEY.STEPS][CASE_1.EXPECTED_STEP_3],
                step_name=CASE_1.STEP_3,
                step_id=3,
            )

            self.handle_report(
                self.cex.transfer(token_1, self.reports[2].EXECUTED_QTY, self.dex),
                expected_qty=report[KEY.STEPS][CASE_1.EXPECTED_STEP_4],
                step_name=CASE_1.STEP_4,
                step_id=4,
            )

        elif report["case"] == Case.TWO:
            case_name = "case_two"

            self.handle_report(
                self.cex.market_order(token_1, token_0, report["capital"]),
                expected_qty=report[KEY.STEPS][CASE_2.EXPECTED_STEP_1],
                step_name=CASE_2.STEP_1,
                step_id=0,
            )

            self.handle_report(
                self.cex.transfer(token_0, self.reports[0].EXECUTED_QTY, self.dex),
                expected_qty=report[KEY.STEPS][CASE_2.EXPECTED_STEP_2],
                step_name=CASE_2.STEP_2,
                step_id=1,
            )

            self.handle_report(
                self.dex.swap(token_0, token_1, self.reports[1].EXECUTED_QTY),
                expected_qty=report[KEY.STEPS][CASE_2.EXPECTED_STEP_3],
                step_name=CASE_2.STEP_3,
                step_id=2,
            )

            self.handle_report(
                self.dex.transfer(token_1, self.reports[2].EXECUTED_QTY, self.cex),
                expected_qty=report[KEY.STEPS][CASE_2.EXPECTED_STEP_4],
                step_name=CASE_2.STEP_4,
                step_id=3,
            )

        revenue = Decimal(self.reports[3].EXECUTED_QTY) - report["capital"]
        roc = Decimal(self.reports[3].EXECUTED_QTY) / report["capital"] - 1

        logger.info(f"{self.run_id} Revenue = {revenue} {token_1}")

        result = {}
        for id_report, step_report in enumerate(self.reports):
            result[f"time_{case_name}_{id_report}"] = step_report.TIME_S

        result["revenue"] = revenue
        result["executed_roc"] = roc

        self.unlock(pair)
        return result
