import json
import random
import time

import pandas as pd
import requests

from lib.constants import KEY
from lib.database.influx_db import InfluxDb
from lib.logger.console_logger import ConsoleLogger
from tools.pancake.lib.chain_config import load_chain_config
from tqdm import tqdm
from web3 import HTTPProvider, Web3
from web3.exceptions import BlockNotFound, TransactionNotFound
from web3.middleware import geth_poa_middleware
from web3.types import BlockIdentifier

ROUTER_CONTRACT_ADDRESS = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
PANCAKE_COMMISSION = 0.0017
BINANCE_TICKER_API = "https://api.binance.com/api/v3/ticker/price"
MAX_TRIES = 60


def read_json(filename):
    """
    Reads a JSON file and returns a dictionary

    Args:
        filename (str): path of the json file.

    Returns:
        dict: The output dictionary
    """
    with open(filename, "r") as f:
        return json.load(f)


def load_pancake_pools() -> pd.DataFrame:
    """
    Load the pancake referecne file to get the pools we care about

    Returns:
        pd.DataFrame: Reference file loaded in.
    """

    pancake_pools = pd.DataFrame(
        columns=[
            "base_asset",
            "quote_asset",
            "pool_inverted",
            "pool",
            "base_address",
            "quote_address",
            "base_decimals",
            "quote_decimals",
            "symbol",
        ]
    )

    for _, item in read_json("tools/pancake/data/pancake/reference.json").items():
        pancake_pools.loc[len(pancake_pools)] = [
            item[column] for column in pancake_pools.columns
        ]
    return pancake_pools


class FeeReader(InfluxDb):
    def __init__(self, config: dict):
        """
        Fee reader reads transactions block from BSC and find transactions that uses
        one of the pancakeswap pools we used for arbitrage.

        We compute from them the final commission.
        """
        config[KEY.PROJECT] = "pancake_fee_reader_v5"
        super().__init__(config, None, None)

        self._logger = ConsoleLogger()

        self.web3s = [
            Web3(HTTPProvider("https://bsc-dataseed.binance.org/")),
            Web3(HTTPProvider("https://bsc-dataseed1.defibit.io/")),
            Web3(HTTPProvider("https://bsc-dataseed1.ninicoin.io/")),
        ]

        for web3 in self.web3s:
            web3.middleware_onion.inject(geth_poa_middleware, layer=0)

        self.router_contract = web3.eth.contract(
            address=ROUTER_CONTRACT_ADDRESS,
            abi=read_json("tools/pancake/data/pancake/router.json"),
        )

        self.pancake_pools = load_pancake_pools()
        self.block_ran = {}

        # scheduler = BackgroundScheduler()
        # scheduler.add_job(self.update_price_and_reserve, "interval", seconds=60)
        # scheduler.start()

    def find_pool(self, a, b):
        """
        Given a pair of addresses, find the pool associated with them and the decimal of
        the amount in given.

        Args:
            a (str): The path from
            b (str): The path to

        Returns:
            tuple: Pool address and decimal of the input value
        """
        filter_1 = (self.pancake_pools.base_address == a) & (
            self.pancake_pools.quote_address == b
        )

        if any(filter_1):
            return (
                self.pancake_pools.loc[filter_1, ["pool", "base_decimals"]]
                .iloc[0]
                .tolist()
            )

        filter_2 = (self.pancake_pools.base_address == b) & (
            self.pancake_pools.quote_address == a
        )

        if any(filter_2):
            return (
                self.pancake_pools.loc[filter_2, ["pool", "quote_decimals"]]
                .iloc[0]
                .tolist()
            )

        return None

    def read_blocks(self, block_from: int, block_to: int):
        """
        Loop through blocks and search for transactions

        Args:
            block_from (int): Initial block number
            block_to (int): Final block number
        """
        for block_number in tqdm(range(block_from, block_to)):
            self.read_block(block_number)

    def get_block(self, block: BlockIdentifier, web3: Web3):
        while True:
            try:
                block = dict(
                    web3.eth.get_block(block_identifier=block, full_transactions=True)
                )
                if block["number"] is None:
                    raise BlockNotFound
                else:
                    return block

            except BlockNotFound:
                self._logger.error(f"... Waiting on block {block} to be done")
                time.sleep(1)

            except (requests.exceptions.HTTPError, ValueError):
                self._logger.error(f"... Web3 error, likely throttling by node")
                time.sleep(1)

    def read_block(self, block: BlockIdentifier, identifier: int = None):
        if isinstance(block, int):
            web3 = self.web3s[block % len(self.web3s)]

        elif isinstance(block, str) and identifier is not None:
            web3 = self.web3s[identifier % len(self.web3s)]

        else:
            raise ValueError("Invalid input.")

        block = dict(self.get_block(block, web3))

        if block["number"] in self.block_ran.keys():
            return block["number"]

        transactions = block["transactions"]
        transactions = pd.DataFrame(dict(block)["transactions"])

        if not transactions.empty:

            transactions[["blockHash", "hash", "r", "s"]] = transactions[
                ["blockHash", "hash", "r", "s"]
            ].applymap(lambda x: x.hex())

            # Filter transactions with pancake router
            transactions = transactions[transactions["to"] == ROUTER_CONTRACT_ADDRESS]

            # Decode input from transaction
            transactions = pd.concat(
                [
                    transactions.reset_index(drop=True),
                    pd.DataFrame(
                        transactions["input"]
                        .apply(self.decode_transaction_input)
                        .apply(list)
                        .tolist(),
                        columns=["function", "input_decoded"],
                    ),
                ],
                axis=1,
            ).copy()

            potential_transactions = self.find_transaction_with_valid_pools(
                transactions
            )

            pool_transaction = self.check_confirmation_from_transactions(
                potential_transactions, block, web3
            )

            pool_transaction = self.enhance_data(pool_transaction)

            if not pool_transaction.empty:
                eject_messages = [
                    self.Encode(
                        data,
                        tags=["pool", "symbol", "base_asset", "quote_asset"],
                        timestamp=block["timestamp"] * KEY.ONE_SECOND,
                    )
                    for data in pool_transaction.to_dict(orient="records")
                ]
                status = self.writeEncoded(eject_messages)

                if status is not None and not status["ok"]:
                    raise Exception(str(status))

        return block["number"]

    def enhance_data(self, pool_transaction: pd.DataFrame) -> pd.DataFrame:
        """
        Update the pool dataframe with the information from the pools and distribute the
        commission in the base asset ommission or quote asset commission column.

        Args:
            pool_transaction (pd.DataFrame): The dataframe with the transactions

        Returns:
            pd.DataFrame: Updated dataframe
        """
        pool_transaction = pool_transaction.merge(
            self.pancake_pools[
                [
                    "pool",
                    "symbol",
                    "base_asset",
                    "quote_asset",
                    "base_address",
                    "quote_address",
                ]
            ],
            on="pool",
        )

        pool_transaction["base_asset_commission"] = 0.0
        pool_transaction["quote_asset_commission"] = 0.0

        pool_transaction["base_asset_volume"] = 0.0
        pool_transaction["quote_asset_volume"] = 0.0

        base_used = pool_transaction.token == pool_transaction.base_address
        quote_used = pool_transaction.token == pool_transaction.quote_address

        pool_transaction.loc[
            base_used, "base_asset_commission"
        ] = pool_transaction.commission
        pool_transaction.loc[base_used, "base_asset_volume"] = pool_transaction.volume

        pool_transaction.loc[
            quote_used, "quote_asset_commission"
        ] = pool_transaction.commission
        pool_transaction.loc[quote_used, "quote_asset_volume"] = pool_transaction.volume

        return pool_transaction

    def decode_transaction_input(self, input_string):
        try:
            return self.router_contract.decode_function_input(input_string)
        except:
            return [None, []]

    def get_transaction(self, transaction: str, web3: Web3):
        """
        Get the transaction detail from the blockchain.

        Args:
            transaction (str): [description]
            web3 (Web3): [description]
        """
        tries = 0
        while True:
            try:
                return web3.eth.getTransactionReceipt(transaction)
            except (TransactionNotFound, ValueError, requests.exceptions.HTTPError):
                tries += 1

                if tries >= MAX_TRIES:
                    self._logger.error(f"\t\t ... Timeout on transaction {transaction}")
                    return {"logs": []}

                self._logger.info(f"\t ... Waiting for transaction {transaction}")
                time.sleep(1)

    def check_confirmation_from_transactions(
        self, potential_transactions: dict, block: dict, web3: Web3
    ) -> None:
        """
        Poll the nodes for transactions status. For transactions with valid status,
        search the logs for the executed transferred amount in each of the pools.
        We compute the commission as being 0.0017 of the value.

        Args:
            potential_transactions (dict): The list of potential transactions
            block (dict): The current block
            web3 (Web3): Web3 client to poll from
        """
        pool_transaction = pd.DataFrame(
            columns=["pool", "block", "token", "volume", "commission", "transaction",]
        )
        for transaction, pools in potential_transactions.items():
            status = self.get_transaction(transaction, web3)
            for pool in pools:
                for log in status["logs"]:
                    try:
                        if (log["topics"][0].hex() == TRANSFER_TOPIC) and (
                            Web3.toChecksumAddress(
                                log["topics"][2]
                                .hex()
                                .replace("000000000000000000000000", "")
                            )
                            == pool["pool"]
                        ):
                            volume = int(log["data"], 16) * 10 ** (-pool["decimals"])

                            commission = volume * PANCAKE_COMMISSION
                            pool_transaction.loc[len(pool_transaction)] = [
                                pool["pool"],
                                block["number"],
                                pool["token_from"],
                                volume,
                                commission,
                                transaction,
                            ]

                    except Exception as e:
                        self._logger.error(
                            f"Failed to check the output of the transaction {e}"
                        )
                        pass

        return pool_transaction

    def find_transaction_with_valid_pools(self, transactions: pd.DataFrame) -> dict:
        """
        Loop through transactions input and search for jump through pool listed in
        pancakeswap reference file. If we find a match, save the pool path, transaction
        hash and token path in a dictionary

        Args:
            transactions (pd.DataFrame): The list of transactions from the block

        Returns:
            dict: The list of transactions we need to investigate further.
        """
        potential_transactions = {}
        for i, transaction in transactions.iterrows():
            row = transaction["input_decoded"]

            if "path" in row:
                for i, path in enumerate(row["path"]):
                    if i > 0:
                        result = self.find_pool(path, previous_path)

                        if result is not None:
                            if transaction["hash"] not in potential_transactions:

                                potential_transactions[transaction["hash"]] = [
                                    {
                                        "pool": result[0],
                                        "decimals": result[1],
                                        "token_from": previous_path,
                                        "token_to": path,
                                    }
                                ]
                            else:
                                potential_transactions[transaction["hash"]].append(
                                    {
                                        "pool": result[0],
                                        "decimals": result[1],
                                        "token_from": previous_path,
                                        "token_to": path,
                                    }
                                )

                    previous_path = path

        return potential_transactions

    def run_forever(self):
        """
        Run the scrapper forever
        """
        block_number = 0
        i = 0

        while True:
            time.sleep(1)
            if i == 0:
                block = "latest"
            else:
                block = block_number + 1

            block_number = fee_reader.read_block(block=block, identifier=i)
            self.block_ran[block_number] = "ok"
            self._logger.info(f"Done for block {block_number}")
            i += 1

    def run_from_to(self, block_from, block_to):
        """
        Run the scrapper from a block to another specific block
        """

        for block in tqdm(
            range(
                block_from,
                block_to,
            )
        ):
            self.read_block(block=block)


if __name__ == "__main__":
    CONFIG = load_chain_config()

    fee_reader = FeeReader(CONFIG)
    # while True:
    #    time.sleep(1)
    fee_reader.run_forever()
    # fee_reader.update_price_and_reserve(fee_reader.web3s[0])
    # fee_reader.read_block(32815226, 1)
    # fee_reader.read_blocks(12815226, 12815226 + 10)
