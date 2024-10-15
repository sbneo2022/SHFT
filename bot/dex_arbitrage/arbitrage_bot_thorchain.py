from datetime import datetime
from decimal import Decimal

from bot import AbstractBot
from lib.constants import KEY
from lib.database import AbstractDatabase
from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer
from tools.arbitrage_proof.lib.worker import Worker


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
        self._data_buffer = []
        self.second_count = 0

        self.worker = Worker(config)
        self.orderbook = {}

        self._capital = config[KEY.CAPITAL]

        self.bepswap_products = self._load_bepswap_product()

    def _load_bepswap_product(self):
        """
        Load products from bepswap

        Raises:
            Exception: Raise exception on error from the geproduct API.
        """
        bepswap_products, err = self.worker._bepswap.getProducts()

        if bepswap_products is None:
            self._json_log["error"] = err
            self._logger.error(f"Error loading Bepswap products: {err}")
            raise Exception(f"Error loading Bepswap products: {err}")

        return bepswap_products

    def onTime(self, timestamp: int):
        self.second_count += 1

        if self._data_buffer:
            result = self._database.writeEncoded(self._data_buffer)

            if not result["ok"]:
                self._logger.error(result["exception"])

            self._data_buffer = []

        if self.second_count % self.interval == 0:

            bepswap_products, _ = self.worker._bepswap.getExchangeIntersection(
                bepswap=self.bepswap_products, exchange=self.orderbook.keys()
            )
            bepswap_products, _ = self.worker._bepswap.getDepths(bepswap_products)

            reports = self.worker._bepswap.getReport(
                self._capital,
                pool_depths=bepswap_products,
                exchange_prices=self.orderbook,
                only_one=True,
                all_cases=True,
            )

            min_roc = -999
            best_report = None

            for report in reports:
                self._data_buffer.append(
                    self._database.Encode(
                        {
                            "pair": report["exchange_product"],
                            "capital": report["capital_in_base"],
                            "quote": report["product"],
                            "base": report["BASE"],
                            "case": report["case_name"],
                            "revenue": report["revenue"],
                            "roc": report["roc"],
                        },
                        timestamp,
                        tags=["pair", "case", "quote", "base"],
                    )
                )
                if report["roc"] > min_roc:
                    best_report = report
                    min_roc = report["roc"]

            self._logger.info(
                {
                    "best_pair": str(best_report["exchange_product"]),
                    "case": best_report["case_name"],
                    "revenue": round(float(best_report["revenue"]), 4),
                    "roc": round(float(best_report["roc"]) * 1e4, 2),
                    "timestamp": timestamp,
                }
            )

    def onOrderbook(self, symbol: str, askPrice: Decimal, bidPrice: Decimal, **kwargs):
        """
        Update the local orderbook dictionary with the latest data.

        Args:
            symbol (str): The current symbol
            askPrice (Decimal): Asking price
            bidPrice (Decimal): Bid price
        """
        self.orderbook[symbol] = {"ask_price": askPrice, "bid_price": bidPrice}

    def Clean(self):
        self._logger.warning("onClean")

        self._logger.info(
            f"Ending bot at {datetime.utcnow().strftime('%Y/%m/%d, %H:%M:%S')}"
        )
