from datetime import datetime, timezone
from decimal import Decimal
from pprint import pprint
from typing import Optional, Union

from loguru import logger
from influxdb import InfluxDBClient

FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


class Db:
    def __init__(self, config: dict, prefix: Optional[str] = None, dry_mode=False):
        self._config = config
        self._prefix = prefix

        # Handle "Dry Mode": no database operations if no "method" field in database
        if "series" not in self._config:
            logger.warning(
                f'No "series" field in config: no data will be written to database'
            )
            self._dry_mode = True
            return
        else:
            self._dry_mode = dry_mode

        self._measurement = self._config["series"]
        self._measurement = (
            self._measurement
            if self._prefix is None
            else "_".join([self._prefix, self._measurement])
        )

        influx_settings = self._config.get("influx", {})
        self._database = influx_settings["database"]
        self._client = InfluxDBClient(**influx_settings)
        if self._database not in [
            database["name"] for database in self._client.get_list_database()
        ]:
            self._client.create_database(self._database)

    def addPoint(
        self, fields: dict, tags: Optional[dict] = None, time: Optional[datetime] = None
    ) -> Optional[str]:
        if self._dry_mode:
            return

        json_item = {
            "measurement": self._measurement,
            "tags": tags or {},
            "time": (time or datetime.now(tz=timezone.utc)).strftime(FORMAT),
            "fields": {},
        }

        for key, value in fields.items():
            if isinstance(value, Decimal):
                json_item["fields"][key] = float(value)
            elif isinstance(value, int):
                json_item["fields"][key] = value
            elif isinstance(value, float):
                json_item["fields"][key] = value
            elif value is None:
                pass
            else:
                json_item["fields"][key] = str(value)

        try:
            self._client.write_points(
                [json_item], database=self._database, time_precision="u"
            )
        except Exception as e:
            return e.__str__()
