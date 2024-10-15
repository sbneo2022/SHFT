from typing import Optional, Type

from lib.consumer import AbstractConsumer
from lib.database import AbstractDatabase
from lib.exchange import AbstractExchange
from lib.factory import AbstractFactory
from lib.history import AbstractHistory
from lib.logger import AbstractLogger
from lib.producer import AbstractProducer
from lib.state import AbstractState
from lib.timer import AbstractTimer
from lib.vault import AbstractVault

VAULT = 'vault'
DATABASE = 'database'
TIMER = 'timer'
LOGGER = 'logger'
STATE = 'state'
CONSUMER = 'consumer'
PRODUCER = 'producer'
HISTORY = 'history'

class CustomFactory(AbstractFactory):

    def __init__(self, config: Optional[dict] = None,
                 vault: Optional[Type[AbstractVault]] = None,
                 database: Optional[Type[AbstractDatabase]] = None,
                 timer: Optional[Type[AbstractTimer]] = None,
                 logger: Optional[Type[AbstractLogger]] = None,
                 state:  Optional[Type[AbstractState]] = None,
                 consumer:  Optional[Type[AbstractConsumer]] = None,
                 producer:  Optional[Type[AbstractProducer]] = None,
                 history:  Optional[Type[AbstractHistory]] = None,
                 ):
        super().__init__(config)

        self._factory = {
            VAULT: vault,
            DATABASE: database,
            TIMER: timer,
            LOGGER: logger,
            STATE: state,
            CONSUMER: consumer,
            PRODUCER: producer,
            HISTORY: history,
        }

    @property
    def Vault(self) -> Type[AbstractVault]:
        return self._factory[VAULT]

    @property
    def Database(self) -> Type[AbstractDatabase]:
        return self._factory[DATABASE]

    @property
    def Timer(self) -> Type[AbstractTimer]:
        return self._factory[TIMER]

    @property
    def Logger(self) -> Type[AbstractLogger]:
        return self._factory[LOGGER]

    @property
    def State(self) -> Type[AbstractState]:
        return self._factory[STATE]

    @property
    def Consumer(self) -> Type[AbstractConsumer]:
        return self._factory[CONSUMER]

    @property
    def Producer(self) -> Type[AbstractProducer]:
        return self._factory[PRODUCER]

    @property
    def History(self) -> Type[AbstractHistory]:
        return self._factory[HISTORY]

