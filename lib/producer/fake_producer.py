from lib.constants import KEY
from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.producer import AbstractProducer
from lib.timer import AbstractTimer


class FakeProducer(AbstractProducer):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, factory, timer)

        self._logger: AbstractLogger = factory.Logger(config, factory=factory, timer=timer)

    def Send(self, message: dict, channel=KEY.PRODUCT):
        self._logger.info('Send Message!', payload=message, channel=channel)
