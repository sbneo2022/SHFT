from datetime import datetime
from decimal import Decimal

from bot import AbstractBot
from lib.constants import KEY
from lib.database import AbstractDatabase
from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer
from tools.pancake.lib.arbitrage import Case
from tools.pancake.lib.execution import Execution
from tools.pancake.lib.helpers import id_generator
from tools.pancake.lib.venue.binance_spot import COMMISSION, TRANSFER_COMMISSION
from tools.pancake.lib.worker import Worker


MAX_TIMEOUT = KEY.ONE_SECOND


class SandboxBot(AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, factory, timer)

        self._logger: AbstractLogger = factory.Logger(config, factory, timer)
        self._database: AbstractDatabase = factory.Database(config, factory, timer)

        self._orderbooks = {}
        self._logger.info(
            f"Starting bot at {datetime.utcnow().strftime('%Y/%m/%d, %H:%M:%S')}"
        )

        self.worker = Worker(config)
        self.interval = config.get(KEY.INTERVAL, 15)
        self.live = config.get(KEY.LIVE, False)
        self.min_roc = Decimal(config.get(KEY.MIN_ROC, 1e8))

        self._data_buffer = []

        self.second_count = 0

    def onTime(self, timestamp: int):
        self.second_count += 1

        if self._data_buffer:

            result = self._database.writeEncoded(self._data_buffer)

            if not result["ok"]:
                self._logger.error(result["exception"])

            self._data_buffer = []

        # Remove outdated price
        remove_pair = []
        for pair in self.worker._bidask._orderbooks.keys():
            if (
                self.worker._bidask._orderbooks[pair]["timestamp"] - timestamp
                >= MAX_TIMEOUT
            ):
                remove_pair.append(pair)
                self._logger.error(f"removing pair {pair}")

        [self.worker._bidask._orderbooks.pop(key) for key in remove_pair]

        if self.second_count % self.interval == 0:

            self.worker.update_dex_reserves()
            all_pairs = []

            for pair in self.worker._bidask._orderbooks.keys():
                for capital in self.worker._get_quote_capitals(pair):

                    top_ask, _ = self.worker._bidask._orderbooks[pair]["asks"][0]
                    top_bid, _ = self.worker._bidask._orderbooks[pair]["bids"][0]

                    case_1 = (
                        self.worker._xyk.swapQuote(pair, capital).value
                        * top_bid
                        * (1 - COMMISSION)
                    ) * (1 - TRANSFER_COMMISSION) - capital

                    report_case_1 = {
                        "capital": Decimal(capital),
                        "pair": str(pair),
                        "case": Case.ONE,
                        "steps": {
                            "1. we_got_base": self.worker._xyk.swapQuote(
                                pair, capital
                            ).value,
                            "2. we_received_on_bidask": self.worker._xyk.swapQuote(
                                pair, capital
                            ).value
                            * top_bid
                            * (1 - COMMISSION),
                            "3. we_got_quote": (
                                self.worker._xyk.swapQuote(pair, capital).value
                                * top_bid
                                * (1 - COMMISSION)
                            ),
                            "4. output": (
                                self.worker._xyk.swapQuote(pair, capital).value
                                * top_bid
                                * (1 - COMMISSION)
                            )
                            * (1 - TRANSFER_COMMISSION),
                        },
                        "roc": Decimal(case_1) / Decimal(capital),
                    }

                    case_2 = (
                        self.worker._xyk.swapBase(
                            pair,
                            (capital * (1 - COMMISSION) / top_ask)
                            * (1 - TRANSFER_COMMISSION),
                        ).value
                        - capital
                    )

                    report_case_2 = {
                        "capital": Decimal(capital),
                        "pair": str(pair),
                        "case": Case.TWO,
                        "steps": {
                            "1. we_got_base": (capital * (1 - COMMISSION) / top_ask),
                            "2. we_received_on_xyk": (
                                capital * (1 - COMMISSION) / top_ask
                            )
                            * (1 - TRANSFER_COMMISSION),
                            "3. we_got_quote": self.worker._xyk.swapBase(
                                pair,
                                (capital * (1 - COMMISSION) / top_ask)
                                * (1 - TRANSFER_COMMISSION),
                            ).value,
                            "4. output": self.worker._xyk.swapBase(
                                pair,
                                (capital * (1 - COMMISSION) / top_ask)
                                * (1 - TRANSFER_COMMISSION),
                            ).value,
                        },
                        "roc": Decimal(case_2) / Decimal(capital),
                    }

                    base, quote = pair.base, pair.quote

                    if pair in self.worker._between_10_000_and_100k:
                        pool_type = "Between_10000_and_100k"
                    elif pair in self.worker._between_100k_and_1M:
                        pool_type = "Between_100k_and_1M"
                    elif pair in self.worker._more_than_1M:
                        pool_type = "More_than_1M"
                    else:
                        print(pair)
                        raise

                    data = {
                        "pair": pair,
                        "pool_type": pool_type,
                        "base": base,
                        "quote": quote,
                        "capital": capital,
                        "case_1": case_1,
                        "roc_1": case_1 / capital,
                        "case_2": case_2,
                        "roc_2": case_2 / capital,
                        "report_case_1": report_case_1,
                        "report_case_2": report_case_2,
                        "bid": top_bid,
                        "ask": top_ask,
                        "price": self.worker._xyk._reserves[pair]["price"],
                        "reserve_base": self.worker._xyk._reserves[pair]["reserve0"],
                        "reserve_quote": self.worker._xyk._reserves[pair]["reserve1"],
                    }

                    all_pairs.append(data)

                    self._data_buffer.append(
                        self._database.Encode(
                            data,
                            timestamp,
                            tags=["pair", "capital", "pool_type", "base", "quote"],
                        )
                    )

            min_roc = -999
            best_pair = None
            best_case = None

            for pair in all_pairs:
                if pair["roc_1"] > min_roc:
                    best_case = "1"
                    best_pair = pair
                    min_roc = pair["roc_1"]
                if pair["roc_2"] > min_roc:
                    best_case = "2"
                    best_pair = pair
                    min_roc = pair["roc_2"]

            self._logger.info(
                {
                    "best_pair": str(best_pair["pair"]),
                    "case": best_case,
                    "capital": best_pair["capital"],
                    "revenue": round(float(best_pair[f"case_{best_case}"]), 4),
                    "roc": round(float(best_pair[f"roc_{best_case}"]) * 1e4, 2),
                    "timestamp": timestamp,
                }
            )

            if self.live:
                if Decimal(best_pair[f"roc_{best_case}"]) * Decimal(1e4) > self.min_roc:
                    self._logger.info("Starting execution")
                    execute = Execution(id_generator(), self._config)
                    results = execute.execute(best_pair[f"report_case_{best_case}"])

                    results["case"] = best_case
                    results["capital"] = best_pair["capital"]
                    results["pair"] = str(best_pair["pair"])

                    self._data_buffer.append(
                        self._database.Encode(results, tags=["pair", "capital", "case"])
                    )

    def onOrderbook(
        self,
        symbol: str,
        askPrice: Decimal,
        bidPrice: Decimal,
        timestamp: int,
        **kwargs,
    ):
        """
        Update the local orderbook dictionary with the latest data.

        Args:
            symbol (str): The current symbol
            askPrice (Decimal): Asking price
            bidPrice (Decimal): Bid price
        """
        self.worker.update_cex_reserves(symbol, askPrice, bidPrice, timestamp)

    def Clean(self):
        self._logger.warning("onClean")

        self._logger.info(
            f"Ending bot at {datetime.utcnow().strftime('%Y/%m/%d, %H:%M:%S')}"
        )
