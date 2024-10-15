import os
import time
from datetime import datetime, timedelta

import influxdb
import pandas as pd
import tqdm
from lib.init import init_service
from loguru import logger

LOCAL_BASE_PATH = "app/lp_simulator/data"
REMOTE_BASE_PATH = "s3://dex-aggregator/data-dump/"


def read_sql(query, client, on_no_rows="raise"):
    """
    Read table from select statement into pandas dataframe.

    Args:
        query (str): valid SQL select statement
        client (InfluxDB.DataFrameClient): the InfluxDB client
        on_no_rows (str): Either raise or ignore
    Returns:
        (pd.DataFrame): the dataframe
    """
    dataframes = client.query(query)

    if on_no_rows == "raise":
        assert dataframes, f"No data returned by query. {query}"
        return dataframes[list(dataframes.keys())[0]].reset_index()
    else:
        try:
            return dataframes[list(dataframes.keys())[0]].reset_index()
        except Exception as e:

            return pd.DataFrame()


class ETL:
    def __init__(self, config):
        """
        Initialize the connection to the influx database.

        Args:
            config (dict): Configuratio file
        """

        host = config["influxql"]["host"]
        username = config["influxql"]["username"]
        password = config["influxql"]["password"]

        self.base_dir = (
            LOCAL_BASE_PATH
            if config.get("target", "live") == "local"
            else REMOTE_BASE_PATH
        )

        self.influx_client = influxdb.DataFrameClient(
            host, 8086, username, password, "reports"
        )

        self.dates = config.get(
            "run_dates",
            [
                str(datetime.utcnow().date()),
                str((datetime.utcnow().date() - timedelta(days=1))),
            ],
        )

    def run(self):
        """
        Run all extractions
        """

        for date in tqdm.tqdm(self.dates):
            try:
                year, month, day = date.split("-")
                self.current_path = f"year={year}/month={month}/day={day}/"
                self.extract_transactions(date)
                self.extract_pool_prices(date)
            except Exception as e:
                logger.error(e)

    def extract_transactions(self, date) -> None:
        """
        Extract the information about pool transactions from influx and dump them to
        local or s3 folder.

        Args:
            days (str): THe day to run the analysis for.
        """

        sql_query = f"""
            SELECT 
                base_asset, 
                quote_asset, 
                quote_asset_commission, 
                quote_asset_volume, 
                base_asset_commission, 
                base_asset_volume 
            FROM pancake_fee_reader_v5 
            WHERE 
                time >= '{date} 00:00:00' and 
                time <= '{date} 23:59:59'
        """

        data = read_sql(sql_query, self.influx_client)
        data = data.rename(columns={"base_asset": "base", "quote_asset": "quote"})

        data.groupby(
            [data["index"].round("min"), "base", "quote"]
        ).sum().reset_index().to_csv(
            os.path.join(self.base_dir, self.current_path, "pools_transactions.csv"),
            index=False,
        )

    def extract_pool_prices(self, date) -> None:
        """
        Extract the information about pool prices
        """
        sql_query = f"""
            SELECT 
                base, 
                quote, 
                capital, 
                price, 
                case_1, 
                case_2,
                reserve_base,
                reserve_quote
            FROM pancake_websocket_4 
            WHERE
                time >= '{date} 00:00:00' and 
                time <= '{date} 23:59:59'
        """

        data = read_sql(sql_query, self.influx_client)

        data = data.rename(
            columns={"reserve_base": "base_reserve", "reserve_quote": "quote_reserve"}
        )

        if "base_reserve" not in data.columns:
            data["base_reserve"] = 0
            data["quote_reserve"] = 0

        data.groupby([data["index"].round("min"), "base", "quote", "capital"]).agg(
            price=pd.NamedAgg("price", lambda x: x.iloc[-1]),
            base_reserve=pd.NamedAgg("base_reserve", lambda x: x.iloc[-1]),
            quote_reserve=pd.NamedAgg("quote_reserve", lambda x: x.iloc[-1]),
            case_1=pd.NamedAgg("case_1", lambda x: max(0, x.max())),
            case_2=pd.NamedAgg("case_2", lambda x: max(0, x.max())),
        ).reset_index().to_csv(
            os.path.join(self.base_dir, self.current_path, "pool_arbs.csv"), index=False
        )


def main():
    """
    Run the ETL process.
    """
    config = init_service()

    config["run_dates"] = [
        "2021-11-28",
        "2021-11-29",
        "2021-11-30",
        "2021-12-01",
        "2021-12-02",
        "2021-12-03",
        "2021-12-04",
        "2021-12-05",
        "2021-12-06"
    ]
    etl = ETL(config)

    etl.run()

    exit()
    while True:
        try:
            etl = ETL(config)
            etl.run()
        except Exception as e:
            logger.erorr(e)

        time.sleep(60 * 60)


if __name__ == "__main__":
    main()
