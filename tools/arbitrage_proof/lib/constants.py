MIDGARD_SWAP_DICTIONARY = {
    "BTC": "BNB.BTCB-1DE",
    "TWT": "BNB.TWT-8C2",
    "ETH": "BNB.ETH-1C9",
    "AVA": "BNB.AVA-645",
    "BUSD": "BUSD-BD1",
    "BNB": "BNB.BNB",
}

MIDGARD_TRANSFER_DICTIONARY = {
    "BTC": "BTCB-1DE",
    "TWT": "TWT-8C2",
    "ETH": "ETH-1C9",
    "AVA": "AVA-645",
    "BUSD": "BUSD-BD1",
}


class KEY:
    CASE = "case"
    CASE_1 = "case_1"
    CASE_2 = "case_2"
    CASE_NAME = "case_name"

    BASE = "BASE"
    PRODUCT = "product"

    BASE_CAPITAL = "capital_in_base"

    COIN = "coin"
    QTY = "qty"
    MIN_QTY = "min_qty"
    MIN_NOTIONAL = "min_notional"

    ASK_PRICE = "ask_price"
    BID_PRICE = "bid_price"

    ADDRESS = "address"
    MEMO = "memo"


class CASE_1:
    STEP_1 = "Dex swap from base to product"
    STEP_2 = "Transfer product from DEX to CEX"
    STEP_3 = "Sell product for base on CEX"
    STEP_4 = "Transfer product from CEX to DEX"

    EXPECTED_STEP_1 = "2. Doubleswap base to product"
    EXPECTED_STEP_3 = "3. We can buy using Market order"


class CASE_2:
    STEP_1 = "Sell base for product on CEX"
    STEP_2 = "Transfer product from CEX to DEX"
    STEP_3 = "Dex swap from product to base"
    STEP_4 = "Transfer product from DEX to CEX"

    EXPECTED_STEP_1 = "1. We can buy using Market order"
    EXPECTED_STEP_3 = "3. Doubleswap product to base"


class CONSTANTS:
    RETRY = 10
    TIME_DELAY = 5


class ExecutionReport:
    """
    Execution report base class that is returned by execution methods.
    """

    SUCCESS = True
    ERROR_STR = None
    EXECUTED_QTY = None
    EXPECTED_QTY = None
    TIME_S = None
    TRANSACTION_ID = None
    SYMBOL = None
    STEP_NAME = ""
    DIFFERENCE_EXPECTED = None

    def __str__(self) -> str:
        if self.SUCCESS and self.EXECUTED_QTY is None:
            return "Execution not finished"

        if not self.SUCCESS:
            return f"Execution failed with error: {self.ERROR_STR}"

        if self.EXPECTED_QTY is not None:
            division = round(
                (float(self.EXECUTED_QTY) / float(self.EXPECTED_QTY) - 1) * 1e4, 2
            )
            sign_of_bp = "+" if division > 0 else "-"
            expected_string = (
                f" . Expected: {round(self.EXPECTED_QTY,4)} "
                + f"({sign_of_bp}{abs(division)} bp)"
            )
            self.DIFFERENCE_EXPECTED = division
        else:
            expected_string = ""

        return (
            f"Executed '{self.STEP_NAME}': "
            + f"{round(self.EXECUTED_QTY,4)} {self.SYMBOL} in {round(self.TIME_S,2)} "
            + "seconds"
            + expected_string
        )
