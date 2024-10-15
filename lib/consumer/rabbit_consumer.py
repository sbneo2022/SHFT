import uuid

import pika
from pika.exchange_type import ExchangeType

from lib.constants import KEY, QUEUE
from lib.consumer import AbstractConsumer
from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.supervisor import AbstractSupervisor
from lib.timer import AbstractTimer


class DEFAULT:
    USERNAME = 'guest'
    PASSWORD = 'guest'


class RabbitConsumer(AbstractConsumer):
    def __init__(self, config: dict, supervisor: AbstractSupervisor, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, supervisor, factory, timer)

        self._logger: AbstractLogger = factory.Logger(config, factory=factory, timer=timer)

        self._symbol = self._config[KEY.SYMBOL]
        self._exchage = self._config[KEY.EXCHANGE]

        self._queue = str(uuid.uuid4())

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
                self._connection = pika.BlockingConnection(parameters=parameters)
                self._channel = self._connection.channel()
                self._channel.exchange_declare(
                    exchange=self._symbol,
                    exchange_type=ExchangeType.fanout,
                    passive=False,
                    durable=True,
                    auto_delete=False,
                    arguments={'x-message-ttl': 1000}
                )

                self._channel.queue_declare(queue=self._queue, auto_delete=True)
                self._channel.queue_bind(
                    queue=self._queue, exchange=self._symbol, routing_key='standard_key')
                self._channel.basic_qos(prefetch_count=1)
                self._channel.basic_consume(self._queue, self._on_message)
                self._logger.success(f'Connected to RabbitMQ', queue=self._queue, exchange=self._symbol)
            except Exception as e:
                self._logger.error(f'Error MQ connection: {e}. No MQ messages')

    def _on_message(self, chan, method_frame, header_frame, body):
        self._supervisor.Queue.put({
            QUEUE.QUEUE: QUEUE.MESSAGE,
            KEY.PAYLOAD: body,
        })
        chan.basic_ack(delivery_tag=method_frame.delivery_tag)


    def Run(self):
        if self._channel is not None:
            try:
                self._channel.start_consuming()
            except:
                pass

    def Close(self):
        try:
            self._channel.stop_consuming()
            self._channel.queue_delete(self._queue)
            self._connection.close()
        except Exception as e:
            print(e)

