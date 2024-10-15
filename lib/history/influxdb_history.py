from datetime import datetime, timezone
from decimal import Decimal
from pprint import pprint
from typing import Optional, List

import ciso8601
from influxdb import InfluxDBClient
from influxdb.resultset import ResultSet

from lib.constants import KEY
from lib.database.influx_db import DEFAULT_DATABASE
from lib.factory import AbstractFactory
from lib.history import AbstractHistory
from lib.timer import AbstractTimer

TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
CHUNK_SIZE = 10_000


class InfluxDbHistory(AbstractHistory):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, factory, timer)

        self._symbol = self._config[KEY.SYMBOL]
        self._exchange = self._config[KEY.EXCHANGE]

        influx_settings = self._config.get(KEY.HISTORY_DB, {}).copy()
        self._measurement = influx_settings[KEY.MEASUREMENT]
        self._database = influx_settings.get(KEY.DATABASE, DEFAULT_DATABASE)

        # Influx client cant accept any arg
        if KEY.MEASUREMENT in influx_settings:
            del influx_settings[KEY.MEASUREMENT]

        # Open database connection
        self._client = InfluxDBClient(**influx_settings)


    def getHistory(self, start_timestamp: int, end_timestamp: int, fields: Optional[List[str]] = None) -> list:

        # make start/end time in influxdb format
        start_time = datetime.fromtimestamp(start_timestamp / KEY.ONE_SECOND, tz=timezone.utc).strftime(TIME_FORMAT)
        end_time = datetime.fromtimestamp(end_timestamp / KEY.ONE_SECOND, tz=timezone.utc).strftime(TIME_FORMAT)
        fields = '*' if fields is None else ','.join([f'"{x}"' for x in fields])

        query = f'SELECT {fields} FROM "{self._measurement}" WHERE "symbol"=\'{self._symbol}\' AND "exchange"=\'{self._exchange}\' ' \
                f'AND TIME >= \'{start_time}\' AND TIME < \'{end_time}\' '

        reply: ResultSet = self._client.query(query, chunked=True, chunk_size=CHUNK_SIZE)

        payload = []

        for item in reply.get_points():
            item[KEY.TIMESTAMP] = int(
                Decimal(
                    str(
                        ciso8601.parse_datetime(item['time']).timestamp()
                    )
                ) * KEY.ONE_SECOND
            )
            payload.append(item)

        return payload

