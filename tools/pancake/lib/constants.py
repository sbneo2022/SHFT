class CASE_1:
    STEP_1 = "Dex swap from base to product"
    STEP_2 = "Transfer product from DEX to CEX"
    STEP_3 = "Sell product for base on CEX"
    STEP_4 = "Transfer product from CEX to DEX"

    EXPECTED_STEP_1 = "1. we_got_base"
    EXPECTED_STEP_2 = "2. we_received_on_bidask"
    EXPECTED_STEP_3 = "3. we_got_quote"
    EXPECTED_STEP_4 = "4. output"


class CASE_2:
    STEP_1 = "Sell base for product on CEX"
    STEP_2 = "Transfer product from CEX to DEX"
    STEP_3 = "Dex swap from product to base"
    STEP_4 = "Transfer product from DEX to CEX"

    EXPECTED_STEP_1 = "1. we_got_base"
    EXPECTED_STEP_2 = "2. we_received_on_xyk"
    EXPECTED_STEP_3 = "3. we_got_quote"
    EXPECTED_STEP_4 = "4. output"


class CONSTANTS:
    TIMEOUT_MINUTES = 5
    RETRY = 10
    TIME_DELAY = 5

    SLIPPAGE_MAX = 5

    GAS_LIMIT = 3_000_000
    GAS_PRICE = 10

    DECIMAL_BNB = 1e-18
    PRECISION = 15

    MIN_LIQUIDITY = 10_000

    STABLE_COINS = ["USDT", "BUSD", "USDC"]
    MIN_ROC_EXECUTION = 2e-4


class KEY:
    PAIR_LOCKED = "pair_locked"
    STEPS = "steps"
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
    SLIPPAGE_MAX = "slippage_max"
    GAS_LIMIT = "gas_limit"
    GAS_PRICE = "gas_price"

    QUOTE_PRECISION = "quotePrecision"
    BASE_PRECISION = "baseAssetPrecision"

    DEX_EXCHANGE = "dex_exchange"
    BAKERYSWAP = "bakery"
    PANCAKESWAP = "pancake"
    MIN_LIQUIDITY = "min_liquidity"
    MIN_ROC_EXECUTION = "min_roc_execution"


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
    STEP_ID = None
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
            f"Executed step {self.STEP_ID} '{self.STEP_NAME}': "
            + f"{round(self.EXECUTED_QTY,4)} {self.SYMBOL} in {round(self.TIME_S,2)} "
            + "seconds"
            + expected_string
        )
