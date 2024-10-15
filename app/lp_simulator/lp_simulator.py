import json
from datetime import date, datetime
from typing import Iterable, Optional
import numpy as np
import pandas as pd
import pytz
import requests
import seaborn as sns
import streamlit as st
from app.lp_simulator.lib.helpers import pretty_date, list_s3_dir, bp_print
from app.lp_simulator.lib.constants import KEY
from attr import s
from loguru import logger
from matplotlib import pyplot as plt

from app.lp_simulator.scripts.update_reference_file_with_tags import load_reference_file

ARB_BLACKOUT_DATE = ["2021-12-03"]
FEE_READER_DASHBOARD = (
    "http://dashboard.credencelimited.com/d/_JK7ADp7z/fee-reader?orgId=2&"
    "from={ts_from}&to={ts_to}&var-base={base}&var-quote={quote}"
)
ARB_DASHBOARD = (
    "http://dashboard.credencelimited.com/d/079oa2K7k/pancakeswap-v2?orgId=2&"
    "var-base={base}&var-quote={quote}&from={ts_from}&to={ts_to}"
)

BINANCE_TICKER_API = "https://api.binance.com/api/v3/ticker/price"
SECONDS_IN_DAY = 60 * 60 * 24


@st.cache()
def load_prices() -> dict:
    """
    Load the prices in USDT from binance.

    Returns:
        dict: The price for each assets pair.
    """
    prices = json.loads(requests.get(BINANCE_TICKER_API).content)
    output_prices = {"USDT": 1.0}

    for price in prices:
        if price["symbol"][-4:] == "USDT":
            output_prices[price["symbol"].replace("USDT", "")] = float(price["price"])

    return output_prices


def iloss_simulate(price_evolution: float) -> float:
    """Calculate simulated impermanent loss from an initial value invested,
    Args:
        price_evolution (float): Evolution of the price of the asset in percentage

    Returns:
        tuple (value_f, iloss): Decimal impermanent loss
    """

    return 2 * (price_evolution ** 0.5 / (1 + price_evolution)) - 1


@st.cache(allow_output_mutation=True)
def load_data() -> Iterable[pd.DataFrame]:
    """
    Read the data from local csv files and output the results

    """
    files = list_s3_dir("dex-aggregator", "data-dump")
    transaction_files = [
        f for f in files if f.endswith("pools_transactions.csv") and "year" in f
    ]
    prices_files = [f for f in files if f.endswith("pool_arbs.csv") and "year" in f]

    pool_transaction = pd.concat(
        [pd.read_csv(f, parse_dates=["index"]) for f in transaction_files], axis=0
    )
    pool_prices = pd.concat(
        [pd.read_csv(f, parse_dates=["index"]) for f in prices_files], axis=0
    )

    return {KEY.POOLS_TRANSACTIONS: pool_transaction, KEY.POOLS_PRICE: pool_prices}


class SimulatorApp:
    inputs = {}

    def __init__(self):

        # Cache load of data inputs

        self.reference_file = load_reference_file()
        self.prices = load_prices()

        self.prices_dataframe = (
            pd.Series(self.prices)
            .reset_index()
            .rename(columns={0: "price", "index": "symbol"})
        )

        self.base_data = load_data()

        data = self.base_data.copy()

        self.base_list = np.sort(data[KEY.POOLS_PRICE].base.unique())

        self.data = self.copy_datasets(data)

        self.inputs = self.define_controllers()

        self.base_price = self.prices.get(self.inputs[KEY.BASE_ASSET], None)
        self.quote_price = self.prices.get(self.inputs[KEY.QUOTE_ASSET], None)

        self.filter_data()

        self.data[KEY.POOLS_PRICE].to_csv("tmp/pool_prices.csv", index=False)
        self.data[KEY.POOLS_TRANSACTIONS].to_csv(
            "tmp/pool_transactions.csv", index=False
        )
        self.create_data_view()
        self.create_plots()

        logger.info("Done")

    def create_data_view(self):
        """
        Create view by filtering the data based on the inputs
        """

        pool_prices = self.data[KEY.POOLS_PRICE]
        pool_transactions = self.data[KEY.POOLS_TRANSACTIONS]

        # Add base and quote price to dataframe
        pool_transactions = pool_transactions.merge(
            self.prices_dataframe.rename(
                columns={"price": "base_price", "symbol": "base"}
            ),
            on="base",
            how="left",
        ).merge(
            self.prices_dataframe.rename(
                columns={"price": "quote_price", "symbol": "quote"}
            ),
            on="quote",
            how="left",
        )

        pool_prices = pool_prices.merge(
            self.prices_dataframe.rename(
                columns={"price": "base_price", "symbol": "base"}
            ),
            on="base",
            how="left",
        ).merge(
            self.prices_dataframe.rename(
                columns={"price": "quote_price", "symbol": "quote"}
            ),
            on="quote",
            how="left",
        )

        for asset in ["base", "quote"]:
            for transaction_type in ["commission", "volume"]:
                pool_transactions[f"{asset}_asset_{transaction_type}_usd"] = (
                    pool_transactions[f"{asset}_asset_{transaction_type}"]
                    * pool_transactions[f"{asset}_price"]
                )

        # Compute pool size in usd
        pool_prices["pool_size_usdt"] = (
            pool_prices.base_reserve.astype(float) * 1e-18 * self.base_price
            + pool_prices.quote_reserve.astype(float) * 1e-18 * self.quote_price
        )

        pool_prices["initial_share"] = (
            self.inputs[KEY.CAPITAL]
            * self.inputs[KEY.LP_SHARE]
            / 100
            / pool_prices["pool_size_usdt"]
        ).clip(upper=1)

        pool_prices["capital_usdt"] = pool_prices.capital * pool_prices.quote_price

        self.pool_size = (
            pool_prices.groupby(["base", "quote"])
            .pool_size_usdt.agg("last")
            .reset_index()
        )
        self.pool_size["initial_share"] = (
            self.inputs[KEY.CAPITAL]
            * self.inputs[KEY.LP_SHARE]
            / 100
            / self.pool_size.pool_size_usdt.astype(float)
        ).clip(upper=1)

        pool_transactions = pool_transactions.merge(
            self.pool_size, on=["base", "quote"], how="left"
        ).reset_index(drop=True)

        for column in [
            "quote_asset_commission",
            "quote_asset_volume",
            "quote_asset_commission_usd",
            "base_asset_commission",
            "base_asset_volume",
            "base_asset_commission_usd",
        ]:
            pool_transactions[column] = (
                pool_transactions[column] * pool_transactions.initial_share
            )

        pool_transactions["LP_REVENUE"] = pool_transactions[
            ["quote_asset_commission_usd", "base_asset_commission_usd"]
        ].sum(axis=1)

        pool_transactions["TRANSACTION_VOLUME_USDT"] = pool_transactions[
            ["quote_asset_volume_usd", "base_asset_volume_usd"]
        ].sum(axis=1)

        # Update global table with that
        self.data[KEY.POOLS_PRICE] = pool_prices.copy()
        self.data[KEY.POOLS_TRANSACTIONS] = pool_transactions.copy()

        pool_prices = pool_prices[
            (pool_prices.base == self.inputs[KEY.BASE_ASSET])
            & (pool_prices.quote == self.inputs[KEY.QUOTE_ASSET])
        ].copy()

        pool_transactions = pool_transactions[
            (pool_transactions.base == self.inputs[KEY.BASE_ASSET])
            & (pool_transactions.quote == self.inputs[KEY.QUOTE_ASSET])
        ].copy()

        self.data_start_date = pool_transactions["index"].min()
        self.data_end_date = pool_transactions["index"].max()

        self.seconds_passed = (
            self.data_end_date - self.data_start_date
        ).total_seconds()

        self.total_lp_revenue = (
            pool_transactions.quote_asset_commission_usd.sum()
            + pool_transactions.base_asset_commission_usd.sum()
        )

        # Filter price to remove
        pool_prices = (
            pool_prices[
                pool_prices.capital * self.quote_price
                <= self.inputs[KEY.CAPITAL] * (100 - self.inputs[KEY.LP_SHARE]) / 100
            ]
            .sort_values("index", ascending=True)
            .reset_index(drop=True)
        )

        self.pair_pool_prices = pool_prices.copy()
        self.pair_pool_transactions = pool_transactions.copy()

    def create_plots(self) -> None:
        """
        Create the plots for the simulation.
        """
        st.title("LP-ARB Revenue")
        st.markdown("---")

        self.pool_info()
        st.markdown("---")
        self.lp_revenue()
        st.markdown("---")
        self.arb_revenue()
        st.markdown("---")
        self.iloss()
        st.markdown("---")
        self.general_insights()
        self.create_graph()

        st.markdown("---")
        self.global_view()

    def global_view(self) -> None:

        st.header("All pool ROI")

        capital = self.inputs[KEY.CAPITAL]
        lp_share = self.inputs[KEY.LP_SHARE]

        pool_prices = self.data[KEY.POOLS_PRICE]
        pool_transactions = self.data[KEY.POOLS_TRANSACTIONS]

        arb_capital = capital * (1 - lp_share / 100)
        lp_capital = capital * lp_share / 100

        pool_prices = pool_prices[pool_prices.capital_usdt <= arb_capital]
        arbitrage_revenue = (
            pool_prices.groupby(["base", "quote", "index", "quote_price"])[
                ["case_1", "case_2"]
            ]
            .max()[["case_1", "case_2"]]
            .max(axis=1)
            .groupby(["base", "quote", "quote_price"])
            .sum()
            .rename("arbitrage_revenue")
            .reset_index()
        )

        arbitrage_revenue.arbitrage_revenue *= arbitrage_revenue.quote_price

        dataframe = (
            arbitrage_revenue[["base", "quote", "arbitrage_revenue"]]
            .merge(
                pool_prices.groupby(["base", "quote"])[["pool_size_usdt"]].agg("last"),
                on=["base", "quote"],
                how="left",
            )
            .merge(
                pool_transactions.groupby(["base", "quote"])
                .LP_REVENUE.sum()
                .reset_index(),
                on=["base", "quote"],
                how="left",
            )
            .round(2)
        )

        dataframe["arbitrage_roi"] = dataframe.arbitrage_revenue / arb_capital * 1e4
        dataframe["lp_roi"] = dataframe.LP_REVENUE / lp_capital * 1e4

        dataframe["total_revenue"] = dataframe[["arbitrage_revenue", "LP_REVENUE"]].sum(
            axis=1
        )

        dataframe["total_roi"] = dataframe["total_revenue"] / capital * 1e4

        dataframe = (
            dataframe.sort_values("total_roi", ascending=False)
            .copy()
            .reset_index(drop=True)
        )

        for column in [
            "arbitrage_revenue",
            "pool_size_usdt",
            "LP_REVENUE",
            "total_revenue",
        ]:
            dataframe[column] = (
                dataframe[column].round(0).astype(int)
            )  # apply("${:,.2f}".format)

        # for column in ["total_roi", "arbitrage_roi", "lp_roi"]:
        #    dataframe[column] = dataframe[column].apply("{:,.1f} bp".format)

        st.dataframe(dataframe)

    def create_graph(self) -> None:
        pool_prices = self.pair_pool_prices
        pool_transactions = self.pair_pool_transactions
        capital = self.inputs[KEY.CAPITAL]

        pool_prices = pool_prices[
            pool_prices.capital == pool_prices.capital.iloc[0]
        ].copy()

        pool_transactions["fee_cumsum"] = (
            pool_transactions.LP_REVENUE.cumsum() / capital
        ) * 1e4

        pool_prices["evolution"] = (
            pool_prices.price / pool_prices.price.iloc[0]
        ).apply(iloss_simulate) * 1e4

        pool_prices["arb_revenue"] = (
            ((pool_prices[["case_1", "case_2"]].max(axis=1).cumsum()) / capital)
            * 1e4
            * self.quote_price
        )

        fig = plt.figure(figsize=(12, 10))
        ax = sns.lineplot(
            data=pool_transactions,
            x="index",
            y="fee_cumsum",
            color="b",
            label="LP revenue",
        )
        sns.lineplot(
            data=pool_prices,
            x="index",
            y="evolution",
            color="r",
            label="Impermanent loss",
            ax=ax,
        )
        sns.lineplot(
            data=pool_prices,
            x="index",
            y="arb_revenue",
            color="g",
            label="Arbitrage revenue",
            ax=ax,
        )

        st.pyplot(fig)

        fig.savefig("tmp/tmp.png", dpi=fig.dpi)

    def general_insights(self) -> None:
        st.metric(
            "Final yearly ROI",
            bp_print(self.arb_revenue_roi + self.iloss + self.lp_roi),
        )

    def arb_revenue(self) -> None:
        """

        arb revenue in base
        arb revenue in quote
        total arb revenue in usdt

        """
        pool_info = self.data[KEY.POOLS_PRICE]
        pool_info = pool_info[
            (pool_info.base == self.inputs[KEY.BASE_ASSET])
            & (pool_info.quote == self.inputs[KEY.QUOTE_ASSET])
        ].copy()

        capital = self.inputs[KEY.CAPITAL]
        lp_share = self.inputs[KEY.LP_SHARE]

        arb_capital = capital * (1 - lp_share / 100)

        st.header("Arbitrage revenue")

        st.caption(
            f"""Grafana dasbhoard available here: [link]({ARB_DASHBOARD.format(
                ts_from=int(self.data_start_date.timestamp() * 1000),
                ts_to=int(self.data_end_date.timestamp()* 1000),
                base=self.inputs[KEY.BASE_ASSET],
                quote=self.inputs[KEY.QUOTE_ASSET],
            )})"""
        )

        st1, st2, st3 = st.columns(3)

        st1.write("Total sample")
        st2.write("Monthly")
        st3.write("Yearly")

        timeframes = [
            1,
            SECONDS_IN_DAY * 30 / self.seconds_passed,
            SECONDS_IN_DAY * 365 / self.seconds_passed,
        ]
        sts = [st1, st2, st3]

        for timeframe, current_st in zip(timeframes, sts):
            quote = (
                pool_info.groupby(pool_info["index"])[["case_1", "case_2"]]
                .max()
                .max()
                .sum()
            ) * timeframe

            quote_usdt = quote * self.quote_price

            ROI = quote_usdt / arb_capital

            current_st.metric("Arb revenue in quote", "{:,.2f}".format(quote))
            current_st.metric("Arb revenue in usdt", "${:,.0f}".format(quote_usdt))
            current_st.metric("ROI", str(round(1e4 * ROI, 1)) + "bp")

        self.arb_revenue_roi = ROI

    def iloss(self) -> None:
        st.header("Current impermanent loss")

        pool_info = self.data[KEY.POOLS_PRICE]
        pool_info = pool_info[
            (pool_info.base == self.inputs[KEY.BASE_ASSET])
            & (pool_info.quote == self.inputs[KEY.QUOTE_ASSET])
        ].copy()

        price_t0 = pool_info.price.iloc[0]
        price_t1 = pool_info.price.iloc[-1]
        price_evolution = price_t1 / price_t0 - 1
        iloss = iloss_simulate(1 + price_evolution)

        st1, st2 = st.columns(2)

        st1.metric("Price t0", "${:,.4f}".format(price_t0))
        st1.metric("Price t1", "${:,.4f}".format(price_t1))

        st2.metric("Evolution", "{:.3%}".format(price_evolution))
        st2.metric("Iloss ROI", bp_print(iloss))

        self.iloss = iloss

    def lp_revenue(self) -> None:
        st.header("LP revenue")
        st.caption(
            f"""Grafana dasbhoard available here: [link]({FEE_READER_DASHBOARD.format(
                ts_from=int(self.data_start_date.timestamp() * 1000),
                ts_to=int(self.data_end_date.timestamp()* 1000),
                base=self.inputs[KEY.BASE_ASSET],
                quote=self.inputs[KEY.QUOTE_ASSET],
            )})"""
        )

        st1, st2, st3 = st.columns(3)

        st1.write("Total sample")
        st2.write("Monthly")
        st3.write("Yearly")

        timeframes = [
            1,
            SECONDS_IN_DAY * 30 / self.seconds_passed,
            SECONDS_IN_DAY * 365 / self.seconds_passed,
        ]
        sts = [st1, st2, st3]

        for timeframe, current_st in zip(timeframes, sts):
            current_st.metric(
                "Revenue",
                "${:,.0f}".format(self.total_lp_revenue * timeframe),
            )

            current_st.metric(
                "ROI on LP capital",
                bp_print(
                    self.total_lp_revenue
                    * timeframe
                    / (self.inputs[KEY.CAPITAL] * self.inputs[KEY.LP_SHARE] / 100)
                ),
            )

            ROI = self.total_lp_revenue * timeframe / (self.inputs[KEY.CAPITAL])

            current_st.metric(
                "ROI on total capital",
                bp_print(
                    self.total_lp_revenue * timeframe / (self.inputs[KEY.CAPITAL])
                ),
            )

        self.lp_roi = ROI

    def pool_info(self) -> None:
        st.header("Pool information")
        pool_prices = self.pair_pool_prices
        pool_transactions = self.pair_pool_transactions

        tags = self.reference_file[
            "-".join([self.inputs[KEY.BASE_ASSET], self.inputs[KEY.QUOTE_ASSET]])
        ]["tags"]

        st.markdown(
            "> ###### Tags: \n> "
            + ", ".join([t for t in tags if "portfolio" not in t])
            + "\n"
        )

        st1, st2, st3 = st.columns(3)

        st1.metric(
            "Pool",
            "-".join([self.inputs[KEY.BASE_ASSET], self.inputs[KEY.QUOTE_ASSET]]),
        )
        st1.metric("Observation time", pretty_date(self.seconds_passed))

        st2.metric(
            "Size of the pool in USDT",
            "${:,.0f}".format(pool_prices.pool_size_usdt.iloc[-1]),
        )

        print(pool_prices.initial_share.iloc[-1])
        st2.metric(
            "Share of the pool at the start",
            "{:.2%}".format(
                pool_prices.initial_share.iloc[-1],
            ),
        )

        st3.metric(
            "Transaction volume in USDT",
            "${:,.0f}".format(
                self.pair_pool_transactions.TRANSACTION_VOLUME_USDT.sum()
            ),
        )

        st3.metric(
            "Projected yearly volume in USDT",
            "${:,.0f}".format(
                self.pair_pool_transactions.TRANSACTION_VOLUME_USDT.sum()
                / self.seconds_passed
                * 365
                * (SECONDS_IN_DAY)
            ),
        )

    def filter_data(self):
        """
        Filter based on date, base and quote all dataframe
        """
        pool_prices = self.data[KEY.POOLS_PRICE]
        pool_transactions = self.data[KEY.POOLS_TRANSACTIONS]

        self.inputs[KEY.START_DATE] = datetime.combine(
            self.inputs[KEY.START_DATE], datetime.min.time()
        ).astimezone(pytz.utc)
        self.inputs[KEY.END_DATE] = datetime.combine(
            self.inputs[KEY.END_DATE], datetime.min.time()
        ).astimezone(pytz.utc)

        self.data[KEY.POOLS_PRICE] = pool_prices[
            (
                pool_prices["index"].between(
                    self.inputs[KEY.START_DATE], self.inputs[KEY.END_DATE]
                )
            )
            & (~pool_prices["index"].dt.date.astype(str).isin(ARB_BLACKOUT_DATE))
        ].reset_index(drop=True)

        self.data[KEY.POOLS_TRANSACTIONS] = pool_transactions[
            (
                pool_transactions["index"].between(
                    self.inputs[KEY.START_DATE], self.inputs[KEY.END_DATE]
                )
            )
        ].reset_index(drop=True)

    def copy_datasets(self, data):
        """
        Create copy of the original datasets so they are immutable
        """
        return {key: value.copy() for key, value in data.items()}

    def define_controllers(self) -> dict:
        """
        Define the inputs for the application

        Returns:
            dict: Dictionnary with the inputs
        """

        inputs = {
            KEY.BASE_ASSET: st.sidebar.selectbox(
                **{
                    **KEY.BASE_ASSET.items(),
                    "options": self.base_list,
                }
            )
        }

        quote_available = np.sort(
            self.data[KEY.POOLS_PRICE][
                self.data[KEY.POOLS_PRICE].base == inputs[KEY.BASE_ASSET]
            ].quote.unique()
        )

        inputs[KEY.QUOTE_ASSET] = st.sidebar.selectbox(
            **{
                **KEY.QUOTE_ASSET.items(),
                "options": quote_available,
            }
        )

        return {
            **inputs,
            KEY.CAPITAL: st.sidebar.number_input(**KEY.CAPITAL.items()),
            KEY.LP_SHARE: st.sidebar.number_input(**KEY.LP_SHARE.items()),
            KEY.START_DATE: st.sidebar.date_input(**KEY.START_DATE.items()),
            KEY.END_DATE: st.sidebar.date_input(**KEY.END_DATE.items()),
        }

    def _get_options(self, base: Optional[str] = None) -> Iterable[str]:
        if base is None:
            return []

        return ["USDT"]


def main():
    SimulatorApp()


if __name__ == "__main__":
    main()
