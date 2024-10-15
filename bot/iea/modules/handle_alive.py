import json

from bot import AbstractBot
from lib.constants import KEY
from lib.factory import AbstractFactory
from lib.helpers import custom_dump
from lib.init import get_project_name
from lib.producer import AbstractProducer
from lib.timer import AbstractTimer


class HandleAlive(AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        self._project_name = get_project_name(config)

        self._producer: AbstractProducer = factory.Producer(config, factory, timer)

        self._status = {}

        self._alert = {}

    def updateStatus(self, **kwargs):
        for key, value in kwargs.items():
            self._status[key] = value

    def broadcastAlert(self, **kwargs):
        for key, value in kwargs.items():
            self._alert[key] = value

    def onTime(self, timestamp: int):
        super().onTime(timestamp)

        alive_message = f'{self._project_name}:{self._config[KEY.SYMBOL]}:{self._config[KEY.EXCHANGE]}'

        status_message = json.dumps(self._status, default=custom_dump)
        alert_message = json.dumps(self._alert, default=custom_dump)
        self._alert = {}

        payload = {KEY.ID: alive_message, 'json': status_message, 'alert': alert_message}

        self._producer.Send(payload, channel=KEY.ALIVE)
