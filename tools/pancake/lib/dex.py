import datetime
import time
from decimal import Decimal

from tools.pancake.lib.constants import CONSTANTS, KEY, ExecutionReport
from tools.pancake.lib.helpers import load_json_data
from tools.pancake.lib.lib import timeit
from tools.pancake.lib.venue.pancake import PANCAKE_ROUTER
from tools.pancake.lib.venue.bakery import BAKERY_ROUTER
from web3 import Web3

SECTION = "dex"
CHAIN_ID = 56

COIN = "BNB"


class Dex:
    def __init__(self, config):
        self.web3 = Web3(Web3.HTTPProvider("https://bsc-dataseed.binance.org/"))
        self._address = config[SECTION]["address"]
        self._secret = config[SECTION]["private_key"]

        self._token_abi = load_json_data("bakery/token_abi")

        if config[KEY.DEX_EXCHANGE] == KEY.PANCAKESWAP:
            self.reference = load_json_data("pancake/reference")
            self.router_address = PANCAKE_ROUTER

            self.swap_token_for_coin = "swapExactTokensForETH"
            self.swap_coin_for_token = "swapExactETHForTokens"

            router_abi = load_json_data("pancake/router")

        if config[KEY.DEX_EXCHANGE] == KEY.BAKERYSWAP:
            self.reference = load_json_data("bakery/reference")
            self.router_address = BAKERY_ROUTER

            self.swap_token_for_coin = "swapExactTokensForBNB"
            self.swap_coin_for_token = "swapExactBNBForTokens"

            router_abi = load_json_data("bakery/router_abi")

        self.router = self.web3.eth.contract(
            address=self.router_address, abi=router_abi
        )

        self.slippage_max = config.get(KEY.SLIPPAGE_MAX, CONSTANTS.SLIPPAGE_MAX)
        self.gas_limit = config.get(KEY.GAS_LIMIT, CONSTANTS.GAS_LIMIT)
        self.gas_price = config.get(KEY.GAS_PRICE, CONSTANTS.GAS_PRICE)

    @timeit
    def swap(self, token_from: str, token_to: str, amount: Decimal):
        """
        Swap the coin/token from the coin from to the coin to.

        Args:
            token_from (str): The coin/token from
            token_to (str): The coin/token to
            amount (Decimal): The amount of tokens in 
            timeout_minutes (int, optional): The maximum amount of time to wait 
                before timing out. Defaults to 5.
        """

        if "-".join([token_from, token_to]) in self.reference:
            ref = self.reference["-".join([token_from, token_to])]
            fromToken, toToken = (
                Web3.toChecksumAddress(ref["base_address"]),
                Web3.toChecksumAddress(ref["quote_address"]),
            )

        elif "-".join([token_to, token_from]) in self.reference:
            ref = self.reference["-".join([token_to, token_from])]
            fromToken, toToken = (
                Web3.toChecksumAddress(ref["quote_address"]),
                Web3.toChecksumAddress(ref["base_address"]),
            )

        amount = Decimal(int(float(amount) * 1e9) / 1e9)
        transferAmount = Web3.toWei(amount, "ether")
        amountsOut = self.router.functions.getAmountsOut(
            transferAmount, [fromToken, toToken]
        ).call()

        amountOutMin = amountsOut[1] * (100 - self.slippage_max) / 100
        deadline = datetime.datetime.now(datetime.timezone.utc).timestamp() + (
            CONSTANTS.TIMEOUT_MINUTES * 60
        )

        if token_to == COIN:
            swap_abi = self.router.encodeABI(
                self.swap_token_for_coin,
                args=[
                    int(transferAmount),
                    int(amountOutMin),
                    [fromToken, toToken],
                    self._address,
                    int(deadline),
                ],
            )
        else:  # swap output is a token
            swap_abi = self.router.encodeABI(
                self.swap_coin_for_token,
                args=[
                    int(amountOutMin),
                    [fromToken, toToken],
                    self._address,
                    int(deadline),
                ],
            )

        rawTransaction = {
            "to": self.router_address,
            "from": self._address,
            "value": Web3.toHex(0) if token_to == COIN else Web3.toHex(transferAmount),
            "nonce": self.get_nonce(),
            "gas": Web3.toHex(self.gas_limit),
            "gasPrice": Web3.toHex(int(self.gas_price * 1e9)),
            "data": swap_abi,
            "chainId": hex(CHAIN_ID),
        }

        # get previous states of wallet
        previous_qty = self.check_balance(token_to)

        signedTx = self.web3.eth.account.sign_transaction(rawTransaction, self._secret)
        deploy_txn = self.web3.eth.send_raw_transaction(signedTx.rawTransaction)
        _ = self.web3.eth.wait_for_transaction_receipt(deploy_txn)

        report = ExecutionReport()
        report.SYMBOL = token_to

        while True:
            time.sleep(CONSTANTS.TIME_DELAY)
            new_qty = self.check_balance(token_to)

            if new_qty > previous_qty:
                executed_qty = new_qty - previous_qty
                report.EXECUTED_QTY = executed_qty
                return report

    @timeit
    def transfer(self, token: str, transfer_amount: float, cex):

        transfer_amount = int(transfer_amount * 1e9) / 1e9

        transfer_amount = Web3.toWei(transfer_amount, "ether")

        if token == COIN:
            transaction = {
                "to": self.web3.toChecksumAddress(cex.address),
                "from": self.web3.toChecksumAddress(self._address),
                "value": int(transfer_amount),
                "nonce": self.get_nonce(),
                "gas": Web3.toHex(self.gas_limit),
                "gasPrice": Web3.toHex(int(self.gas_price * 1e9)),
            }

        else:
            token_contract = self.get_token_contract(token)

            transaction = token_contract.functions.transfer(
                self.web3.toChecksumAddress(cex.address), int(transfer_amount),
            ).buildTransaction(
                {"chainId": CHAIN_ID, "gas": self.gas_limit, "nonce": self.get_nonce(),}
            )

        signed_transaction = self.web3.eth.account.signTransaction(
            transaction, self._secret
        )

        report = ExecutionReport()
        report.SYMBOL = token
        original_qty = float(cex.getWallet()[0].get(token, 0))

        report.TRANSACTION_ID = self.web3.eth.sendRawTransaction(
            signed_transaction.rawTransaction
        ).hex()

        while True:
            time.sleep(CONSTANTS.TIME_DELAY)
            transactions, _ = cex.getTransactions()

            if transactions is not None:
                for item in transactions:
                    if report.TRANSACTION_ID == item["txId"]:
                        while True:
                            new_qty, _ = cex.getWallet()
                            if new_qty[token] != original_qty:
                                report.EXECUTED_QTY = (
                                    float(new_qty[token]) - original_qty
                                )
                                return report
                            time.sleep(CONSTANTS.TIME_DELAY / 2)

    def get_token_contract(self, token):
        """
        Load in the token contract for the specified token.

        Args:
            token (str): The token to pull the contract from.

        Returns:
            web3._utils.datatypes.Contract: Contract loaded
        """

        address = ""
        for _, ref in self.reference.items():
            if ref["base_asset"] == token:
                address = ref["base_address"]
            if ref["quote_asset"] == token:
                address = ref["quote_address"]

        if not address:
            return None

        return self.web3.eth.contract(address=address, abi=self._token_abi)

    def check_balance(self, coin: str):
        """
        Check the balance of the dex wlalet for the specified token.

        Args:
            coin (str): The coin/token to check the balance of.
        """
        exact = 0

        if coin == "BNB":
            exact = self.web3.eth.getBalance(self._address) * CONSTANTS.DECIMAL_BNB
        else:
            token_contract = self.get_token_contract(coin)
            decimal = token_contract.functions.decimals().call()

            exact = (
                token_contract.functions.balanceOf(self._address).call()
                * 10 ** -decimal
            )

        return int(float(exact) * 10 ** CONSTANTS.PRECISION) * 10 ** (
            -CONSTANTS.PRECISION
        )

    def get_nonce(self):
        return self.web3.eth.getTransactionCount(self._address)
