import json
import traceback
from decimal import Decimal
from typing import Mapping, Optional

from influxdb import InfluxDBClient
from lib.constants import KEY
from lib.database import AbstractDatabase
from lib.factory import AbstractFactory
from lib.helpers import custom_load
from lib.timer import AbstractTimer

DEFAULT_TABLE = "DEFAULT_SERVICE"
DEFAULT_DATABASE = "DEFAULT_DATABASE"
DEFAULT_SYMBOL = "DEFAULT_SYMBOL"
DEFAULT_EXCHANGE = "DEFAULT_EXCHANGE"


class InfluxDb(AbstractDatabase):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, factory, timer)

        # Get Symbol/Exchange from global config
        self._symbol = self._config.get(KEY.SYMBOL, DEFAULT_SYMBOL)
        self._exchange = self._config.get(KEY.EXCHANGE, DEFAULT_EXCHANGE)

        # Note: Currently Table(Measurement) name eq. to Project from config
        self._table = self._config.get(KEY.PROJECT, DEFAULT_TABLE)

        # Get section with InfluxDb settings and load some settings
        influx_settings = self._config.get(KEY.INFLUX_DB, {})
        self._database = influx_settings.get(KEY.DATABASE, DEFAULT_DATABASE)

        # Pre-create header to speed-up operations
        self._header = f"{self._table},exchange={self._exchange},symbol={self._symbol}"

        # Open database connection
        self._client = InfluxDBClient(**influx_settings)
        if self._database not in [
            database["name"] for database in self._client.get_list_database()
        ]:

            self._client.create_database(self._database)

    def _create_header(self, tags: Mapping[str, any]) -> str:
        tags_as_str = ",".join([f"{key}={value}" for key, value in tags.items()])
        return f"{self._table},{tags_as_str}"

    # NOTE: Code is pretty UNSAFE in order to speed-uo
    def Encode(self, fields: Mapping[str, any], timestamp: int, tags: list = []):

        fields = fields.copy()

        def fn(value):
            if isinstance(value, bool):
                return value
            elif isinstance(value, int):
                return f"{value}"
            elif isinstance(value, Decimal):
                return float(value)
            elif isinstance(value, float):
                return value
            else:
                return f'"{str(value)}"'

        header = f"{self._table}"
        if "exchange" not in tags:
            header += f",exchange={self._exchange}"
        if "symbol" not in tags:
            header += f",symbol={self._symbol}"

        for tag in tags:
            header += f",{tag}={fields[tag]}"
            fields.pop(tag)

        body = ",".join(
            [f"{key}={fn(value)}" for key, value in fields.items() if value is not None]
        )

        return f"{header} {body} {int(timestamp)}"

    def writeEncoded(self, data: list):
        try:
            self._client.write(data, params=dict(db=self._database), protocol="line")
            return {
                "ok": True,
            }
        except Exception as e:
            return {
                "ok": False,
                "exception": e,
                "traceback": traceback.format_exc(),
            }

    def readLast(self, field: str):
        query = (
            f'select {field} from "{self._table}" '
            f"where \"symbol\"='{self._symbol}' AND \"exchange\"='{self._exchange}' "
            f"order by time desc limit 1"
        )

        reply = self._client.query(query)

        for item in reply.get_points():
            data = item[field]
            try:
                return json.loads(data, object_hook=custom_load)
            except:
                return data
