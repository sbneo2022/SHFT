from typing import Type

from lib.consumer import AbstractConsumer
from lib.consumer.hazelcast_consumer import HazelcastConsumer
from lib.consumer.no_consumer import NoConsumer
from lib.database import AbstractDatabase
from lib.database.influx_db import InfluxDb
from lib.factory import AbstractFactory
from lib.history import AbstractHistory
from lib.history.influxdb_history import InfluxDbHistory
from lib.logger import AbstractLogger
from lib.logger.db_logger import DbLogger
from lib.producer import AbstractProducer
from lib.producer.fake_producer import FakeProducer
from lib.producer.hazelcast_producer import HazelcastProducer
from lib.state import AbstractState
from lib.state.db_state import DbState
from lib.state.memory_state import MemoryState
from lib.timer import AbstractTimer
from lib.timer.live_timer import LiveTimer
from lib.timer.virtual_timer import VirtualTimer
from lib.vault import AbstractVault
from lib.vault.config_vault import ConfigVault


class BacktestFactory(AbstractFactory):
    @property
    def Vault(self) -> Type[AbstractVault]:
        return ConfigVault

    @property
    def Database(self) -> Type[AbstractDatabase]:
        return InfluxDb

    @property
    def Timer(self) -> Type[AbstractTimer]:
        return VirtualTimer

    @property
    def Logger(self) -> Type[AbstractLogger]:
        return DbLogger

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
