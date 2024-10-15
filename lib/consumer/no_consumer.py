import json
import uuid

import pika
from pika.exchange_type import ExchangeType

from lib.constants import KEY, QUEUE
from lib.consumer import AbstractConsumer
from lib.factory import AbstractFactory
from lib.helpers import custom_load
from lib.logger import AbstractLogger
from lib.supervisor import AbstractSupervisor
from lib.timer import AbstractTimer


class NoConsumer(AbstractConsumer):
    def __init__(self, config: dict, supervisor: AbstractSupervisor, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, supervisor, factory, timer)

    def Run(self):
        pass

    def Close(self):
        pass

