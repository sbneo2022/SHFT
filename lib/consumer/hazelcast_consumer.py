import json
import os
import signal
import time
from typing import List

import hazelcast
from hazelcast.proxy.base import TopicMessage

from lib.constants import KEY, QUEUE
from lib.consumer import AbstractConsumer
from lib.factory import AbstractFactory
from lib.helpers import custom_load, custom_dump
from lib.logger import AbstractLogger
from lib.supervisor import AbstractSupervisor
from lib.timer import AbstractTimer


class HAZELCAST_STATE:
    STARTING = "STARTING"
    STARTED = "STARTED"
    CONNECTED = "CONNECTED"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    DISCONNECTED = "DISCONNECTED"
    SHUTDOWN = "SHUTDOWN"


class HAZELCAST_DEFAULT:
    HOST = "127.0.0.1"
    PORT = 5701


class HazelcastConsumer(AbstractConsumer):
    def __init__(
        self,
        config: dict,
        supervisor: AbstractSupervisor,
        factory: AbstractFactory,
        timer: AbstractTimer,
    ):
        super().__init__(config, supervisor, factory, timer)

        self._logger: AbstractLogger = factory.Logger(
            config, factory=factory, timer=timer
        )
        self._product = self._get_product_name(
            symbol=self._config.get(KEY.SYMBOL, "None"),
            exchange=self._config.get(KEY.EXCHANGE, "None"),
        )

        self._state: List[str] = []

        self._client = None

        if KEY.HAZELCAST in self._config:

            host = self._config[KEY.HAZELCAST].get(KEY.HOST, HAZELCAST_DEFAULT.HOST)

            port = self._config[KEY.HAZELCAST].get(KEY.PORT, HAZELCAST_DEFAULT.PORT)

            try:
                self._client = hazelcast.HazelcastClient(
                    cluster_members=[f"{host}:{port}"],
                    lifecycle_listeners=[self._on_lifecycle],
                    cluster_connect_timeout=5,
                )

                self._topic = self._client.get_topic(self._product).blocking()

                self._topic.add_listener(self._on_message)

                self._logger.success(
                    f"Consumer connected to Hazelcast", product=self._product, host=host
                )
            except Exception as e:
                self._logger.error(f"Error Hazelcast connection: {e}. No messages")

    def _get_product_name(self, symbol: str, exchange: str) -> str:

        if symbol.endswith(KEY.LONG.upper()):
            symbol = symbol.replace(KEY.LONG.upper(), KEY.SHORT.upper())

        elif symbol.endswith(KEY.SHORT.upper()):
            symbol = symbol.replace(KEY.SHORT.upper(), KEY.LONG.upper())

        return "~".join([symbol, exchange])

    def _on_lifecycle(self, state):
        self._state.append(state)

        if state == HAZELCAST_STATE.DISCONNECTED:
            self._logger.error(f"Consumer: Hazelcast disconnected. Stop")
            os.kill(os.getpid(), signal.SIGHUP)

    def _on_message(self, event: TopicMessage):
        try:
            payload = json.loads(event.message, object_hook=custom_load)
            self._supervisor.Queue.put(
                {
                    QUEUE.QUEUE: QUEUE.MESSAGE,
                    KEY.PAYLOAD: json.dumps(payload[KEY.PAYLOAD], default=custom_dump),
                    KEY.TIMESTAMP: payload[KEY.TIMESTAMP],
                    KEY.LATENCY: self._timer.Timestamp() - payload[KEY.TIMESTAMP],
                }
            )
        except Exception as e:
            self._logger.error(
                f"Error receiving message: {event} with exception {e}",
                message=event.message,
                publish_time=event.publish_time,
                name=event.name,
            )

    def Run(self):
        if self._client is not None:
            while HAZELCAST_STATE.DISCONNECTED not in self._state:
                time.sleep(1)
            self.Close()

    def Close(self):
        try:
            self._client.shutdown()
        except Exception as e:
            print(e)

