import time
from tools.pancake.lib.constants import ExecutionReport, CONSTANTS
from random import random


def timeit(method):
    """
    Timeit decorator which allows you to measure the execution time of the
    method/function by just adding the @timeit decorator on the method.
    The resulting time in seconds is returned in the execution report.

    Args:
        method (object): The method to execute and profile. This method must return an
        execution report object.
    """

    def timed(*args, **kw):
        time_start = time.time()
        result: ExecutionReport = method(*args, **kw)
        time_end = time.time()

        result.TIME_S = time_end - time_start

        return result

    return timed


def execute_order(method, args) -> ExecutionReport:
    """
    Execute order (66) and return the report with the error if there's any. This
    allow for retries of the method given.

    Args:
        method (object): The function to execute
        args (dict): The arguments passed to the method

    Returns:
        ExecutionReport: The initial execution report.
    """
    for _ in range(CONSTANTS.RETRY):
        transaction_id, error = method(**args)

        if error is None:
            break
        else:
            time.sleep(3 + 5 * random())

    report = ExecutionReport()
    report.TRANSACTION_ID = transaction_id

    if error is not None:
        report.SUCCESS = False
        report.ERROR_STR = error

    return report
