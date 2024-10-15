import json

from lib.async_ejector import FieldsAsyncEjector
from lib.constants import DB
from lib.database import AbstractDatabase
from lib.factory import AbstractFactory
from lib.helpers import custom_dump
from lib.state import AbstractState
from lib.timer import AbstractTimer


class DbState(AbstractState):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, factory, timer)

        self._database: AbstractDatabase = factory.Database(config, factory, timer)

    def Push(self, state: dict):
        message = json.dumps(state, default=custom_dump).replace('"', '\\"')
        FieldsAsyncEjector(self._database, self._timer,
                           **{DB.STATE: message}).start()

    def Pop(self) -> dict:
        return self._database.readLast(field=DB.STATE)