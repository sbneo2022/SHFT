from typing import Type

from lib.consumer import AbstractConsumer
from lib.consumer.no_consumer import NoConsumer
from lib.database import AbstractDatabase
from lib.database.fake_db import FakeDb
from lib.factory import AbstractFactory
from lib.history import AbstractHistory
from lib.history.influxdb_history import InfluxDbHistory
from lib.logger import AbstractLogger
from lib.logger.console_logger import ConsoleLogger
from lib.producer import AbstractProducer
from lib.producer.fake_producer import FakeProducer
from lib.state import AbstractState
from lib.state.memory_state import MemoryState
from lib.timer import AbstractTimer
from lib.timer.live_timer import LiveTimer
from lib.vault import AbstractVault
from lib.vault.env_vault import EnvVault


class SandboxFactory(AbstractFactory):
    @property
    def Vault(self) -> Type[AbstractVault]:
        return EnvVault

    @property
    def Database(self) -> Type[AbstractDatabase]:
        return FakeDb

    @property
    def Timer(self) -> Type[AbstractTimer]:
        return LiveTimer

    @property
    def Logger(self) -> Type[AbstractLogger]:
        return ConsoleLogger

    @property
    def State(self) -> Type[AbstractState]:
        return MemoryState

    @property
    def Consumer(self) -> Type[AbstractConsumer]:
        return NoConsumer

    @property
    def Producer(self) -> Type[AbstractProducer]:
        return FakeProducer

    @property
    def History(self) -> Type[AbstractHistory]:
        return InfluxDbHistory
