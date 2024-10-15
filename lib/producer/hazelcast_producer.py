import json
import os
import signal
from typing import List

import hazelcast

from lib.constants import KEY
from lib.factory import AbstractFactory
from lib.helpers import custom_dump
from lib.logger import AbstractLogger
from lib.producer import AbstractProducer
from lib.timer import AbstractTimer


class HAZELCAST_STATE:
    STARTING = 'STARTING'
    STARTED = 'STARTED'
    CONNECTED = 'CONNECTED'
    SHUTTING_DOWN = 'SHUTTING_DOWN'
    DISCONNECTED = 'DISCONNECTED'
    SHUTDOWN = 'SHUTDOWN'

class HAZELCAST_DEFAULT:
    HOST = '127.0.0.1'
    PORT = 5701

class HazelcastProducer(AbstractProducer):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, factory, timer)

        self._logger: AbstractLogger = factory.Logger(config, factory=factory, timer=timer)

        self._symbol = self._config[KEY.SYMBOL]
        self._exchage = self._config[KEY.EXCHANGE]
        self._product = '~'.join([self._symbol, self._exchage])

        self._state: List[str] = []

        self._client = None

        self._topic, self._alive = None, None

        if KEY.HAZELCAST in self._config:

            host = self._config[KEY.HAZELCAST].get(KEY.HOST, HAZELCAST_DEFAULT.HOST)

            port = self._config[KEY.HAZELCAST].get(KEY.PORT, HAZELCAST_DEFAULT.PORT)

            try:
                self._client = hazelcast.HazelcastClient(
                    cluster_members=[f'{host}:{port}'],
                    lifecycle_listeners=[self._on_lifecycle],
                    cluster_connect_timeout=5,
                )

                self._topic = self._client.get_topic(self._product).blocking()
                self._alive = self._client.get_topic(KEY.ALIVE).blocking()

                self._logger.success(f'Producer connected to Hazelcast', product=self._product, host=host)
            except Exception as e:
                self._logger.error(f'Error Hazelcast connection: {e}. No messages')


    def _on_lifecycle(self, state):
        self._state.append(state)

        if state == HAZELCAST_STATE.DISCONNECTED:
            self._logger.error(f'Producer: Hazelcast disconnected. Stop')
            os.kill(os.getpid(), signal.SIGHUP)

    def Send(self, message: dict, channel=KEY.PRODUCT):
        if self._topic is not None:
            try:
                payload = json.dumps(
                    {
                        KEY.TIMESTAMP: self._timer.Timestamp(),
                        KEY.PAYLOAD: message
                    }, default=custom_dump)

                if channel == KEY.PRODUCT:
                    self._topic.publish(payload)
                elif channel == KEY.ALIVE and self._alive is not None:
                    self._alive.publish(payload)

            except:
                pass


