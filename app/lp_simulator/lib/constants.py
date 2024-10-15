import datetime
from datetime import timedelta
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Union

import pandas as pd


@dataclass(unsafe_hash=True)
class StreamlitInputParameters:
    """
    Define base parameters for the streamlit inputs
    """

    label: str
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    value: Optional[Union[int, float]] = None
    step: Optional[Union[int, float]] = None
    format: Optional[str] = None
    key: Optional[Union[str, int]] = None
    help: Optional[str] = None
    on_change: Optional[Callable] = None

    def items(self) -> dict:
        """
        Return only defined parameters

        Returns:
            dict: Dictionnary of parameters
        """
        return {key: value for key, value in self.__dict__.items() if value is not None}


@dataclass(unsafe_hash=True)
class DataInput:
    """
    Define input and path for data files
    """

    path: str


class KEY:

    LP_SHARE = StreamlitInputParameters(
        label="LP/Arbitrage distribution",
        min_value=0,
        max_value=100,
        value=85,
        step=1,
    )

    CAPITAL = StreamlitInputParameters(
        label="Capital added to pool",
        min_value=0,
        max_value=30_000_000,
        value=2_000_000,
        step=10_000,
    )

    START_DATE = StreamlitInputParameters(
        label="Start date", value=datetime.date(2021, 1, 1)
    )
    END_DATE = StreamlitInputParameters(
        label="End date", value=datetime.datetime.utcnow().date() + timedelta(days=1)
    )

    BASE_ASSET = StreamlitInputParameters(
        label="Base asset of the pool",
    )
    QUOTE_ASSET = StreamlitInputParameters(
        label="Quote asset of the pool",
    )

    POOLS_TRANSACTIONS = "s3://dex-aggregator/data-dump/pools_transactions.csv"
    POOLS_PRICE = "s3://dex-aggregator/data-dump/pool_arbs.csv"

    # POOLS_TRANSACTIONS = "app/lp_simulator/data/pools_transactions.csv"
    # POOLS_PRICE = "app/lp_simulator/data/pool_arbs.csv"
