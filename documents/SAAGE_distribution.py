import math

import numpy as np
import pandas as pd
import yaml


MAX_SUPPLY = 1_500_000_000
CONSTANTS = {"total_months": 48}


def main(distribution):
    categories = distribution.keys()

    df = pd.DataFrame(
        columns=categories, index=range(CONSTANTS["total_months"])
    ).fillna(0)
    for month in range(CONSTANTS["total_months"]):
        for category in categories:
            params = distribution[category]

            if month == 0 and "initial_supply" in params:
                df.loc[month, category] = params["initial_supply"]
            else:

                if not params.get("exponential", False):
                    if (
                        params["month_offset"]
                        <= month
                        < params["month_offset"] + params["month_distribution"]
                    ):
                        df.loc[month, category] = (
                            params["weight"] * MAX_SUPPLY
                            - params.get("initial_supply", 0)
                        ) / max(1, params["month_distribution"])
                else:
                    if month > 0:
                        # find period

                        period = 0
                        start_period = 0
                        month_id = -1

                        for i, month_period in enumerate(
                            params["exponential_arg"]["month"]
                        ):

                            if month <= start_period + month_period:

                                month_id = i
                                month_len = params["exponential_arg"]["month"][i]
                                weight = params["exponential_arg"]["weight"][i]
                                break
                            else:
                                start_period += month_period

                        if month_id >= 0:

                            current_scalar = math.exp(-month / 12)
                            scalars = [
                                math.exp(-m / 12)
                                for m in range(
                                    start_period + 1, start_period + month_period + 1
                                )
                            ]

                            distribution_amount = params["weight"] * MAX_SUPPLY * weight

                            df.loc[month, category] = (
                                current_scalar / sum(scalars) * distribution_amount
                            )

    df["total_free_supply"] = df.sum(axis=1).cumsum()

    df["total_free_supply_percent"] = df.total_free_supply / MAX_SUPPLY

    df["max_circulating_supply"] = df.total_free_supply - df.loc[0, "INSURANCE FUND"]

    df

    rates = [90, 70, 50, 30]

    output_yields = pd.DataFrame(columns=["type", "rate", "year", "percent"])

    print("Staking yield\n---------------")
    for rate in rates:
        print(f"Rate {rate}%")
        year_one_rate = df.loc[1:12, "STAKERS"].sum() / (
            df.loc[0, "max_circulating_supply"] * rate / 100
        )
        year_two_rate = df.loc[13:24, "STAKERS"].sum() / (
            df.loc[12, "max_circulating_supply"] * rate / 100
        )
        year_three_rate = df.loc[25:36, "STAKERS"].sum() / (
            df.loc[24, "max_circulating_supply"] * rate / 100
        )

        print("\tYear one rate:", "{:.2%}".format(year_one_rate))
        print("\tYear two rate:", "{:.2%}".format(year_two_rate))
        print("\tYear three rate:", "{:.2%}".format(year_three_rate))

        output_yields.loc[len(output_yields) + 1] = [
            "staking yields",
            rate,
            1,
            year_one_rate,
        ]
        output_yields.loc[len(output_yields) + 1] = [
            "staking yields",
            rate,
            2,
            year_two_rate,
        ]
        output_yields.loc[len(output_yields) + 1] = [
            "staking yields",
            rate,
            3,
            year_three_rate,
        ]

    print("LP yield\n---------------")
    for rate in rates:
        print(f"Rate {rate}%")
        year_one_rate = df.loc[1:12, "LP PROVIDERS"].sum() / (
            df.max_circulating_supply.loc[0] * (1 - rate / 100)
        )
        year_two_rate = df.loc[13:24, "LP PROVIDERS"].sum() / (
            df.max_circulating_supply.loc[12] * (1 - rate / 100)
        )
        year_three_rate = df.loc[25:36, "LP PROVIDERS"].sum() / (
            df.max_circulating_supply.loc[24] * (1 - rate / 100)
        )

        print("\tYear one rate:", "{:.2%}".format(year_one_rate))
        print("\tYear two rate:", "{:.2%}".format(year_two_rate))
        print("\tYear three rate:", "{:.2%}".format(year_three_rate))

        output_yields.loc[len(output_yields) + 1] = [
            "lp yields",
            rate,
            1,
            year_one_rate,
        ]
        output_yields.loc[len(output_yields) + 1] = [
            "lp yields",
            rate,
            2,
            year_two_rate,
        ]
        output_yields.loc[len(output_yields) + 1] = [
            "lp yields",
            rate,
            3,
            year_three_rate,
        ]

    save(df, output_yields)


def save(df, output_yields):
    """
    Save to output excel file

    Args:
        df (pd.DataFrame): The final dataframe with the economics
        output_yields (pd.DataFrame): The yields for staker and lp yield
    """
    path = r"output.xlsx"

    writer = pd.ExcelWriter(path, engine="xlsxwriter")
    df.to_excel(writer, sheet_name="table")
    output_yields.to_excel(writer, sheet_name="yields")
    writer.save()
    writer.close()


if __name__ == "__main__":

    with open("input_saage.yaml", "r") as stream:
        distribution = yaml.safe_load(stream)

    main(distribution)
