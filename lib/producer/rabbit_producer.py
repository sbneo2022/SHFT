import json

import pika
from pika.exchange_type import ExchangeType

from lib.constants import KEY
from lib.consumer.rabbit_consumer import DEFAULT
from lib.factory import AbstractFactory
from lib.helpers import custom_dump
from lib.logger import AbstractLogger
from lib.producer import AbstractProducer
from lib.timer import AbstractTimer


class RabbitProducer(AbstractProducer):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, factory, timer)

        self._logger: AbstractLogger = factory.Logger(config, factory=factory, timer=timer)

        self._symbol = self._config[KEY.SYMBOL]
        self._exchage = self._config[KEY.EXCHANGE]

        self._channel = None

        if KEY.RABBIT_MQ in self._config:

            host = self._config[KEY.RABBIT_MQ][KEY.HOST]

            username = self._config[KEY.RABBIT_MQ].get(KEY.USERNAME, None) or DEFAULT.USERNAME

            password = self._config[KEY.RABBIT_MQ].get(KEY.PASSWORD, None) or DEFAULT.PASSWORD

            parameters = (
                pika.ConnectionParameters(
                    host=host,
                    credentials=pika.PlainCredentials(
                        username=username,
                        password=password,
                    )
                )
            )

            try:
                connection = pika.BlockingConnection(parameters=parameters)
                self._channel = connection.channel()
                self._channel.exchange_declare(
                    exchange=self._symbol,
                    exchange_type=ExchangeType.fanout,
                    passive=False,
                    durable=True,
                    auto_delete=False)

                self._logger.success(f'Connected to RabbitMQ', exchange=self._symbol, host=host)
            except Exception as e:
                self._logger.error(f'Error MQ connection: {e}. No MQ messages')

    def Send(self, message: dict, channel=KEY.PRODUCT):
        self._logger.info(f'New broadcasting message', event='MESSAGE', payload=message)
        if self._channel is not None:
            payload = json.dumps(message, default=custom_dump)
            self._channel.basic_publish(
                self._symbol, 'standard_key', payload,
                pika.BasicProperties(content_type='text/plain', delivery_mode=1))