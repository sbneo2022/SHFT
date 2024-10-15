import os
import signal
import sys
from typing import Callable

import hazelcast
from hazelcast.proxy.base import TopicMessage
from telegram.bot import RT

sys.path.append(os.path.abspath('../../..'))
from tools.telegram_bot.lib.constants import KEY


class HAZELCAST_STATE:
    STARTING = 'STARTING'
    STARTED = 'STARTED'
    CONNECTED = 'CONNECTED'
    SHUTTING_DOWN = 'SHUTTING_DOWN'
    DISCONNECTED = 'DISCONNECTED'
    SHUTDOWN = 'SHUTDOWN'


class Receiver:
    def __init__(self, config: dict, callback: Callable[[str], None]):
        self._config = config
        self._callback = callback

        self._state = []

        self._client = hazelcast.HazelcastClient(
            cluster_members=[config[KEY.HAZELCAST]],
            lifecycle_listeners=[self._on_lifecycle],
            cluster_connect_timeout=5,
        )

        self._topic = self._client.get_topic(config[KEY.TOPIC]).blocking()

        self._topic.add_listener(self._on_message)

    def _on_message(self, event: TopicMessage):
        self._callback(event.message)

    def _on_lifecycle(self, state):
        self._state.append(state)

        if state == HAZELCAST_STATE.DISCONNECTED:
            os.kill(os.getpid(), signal.SIGKILL)

    def shutdown(self):
        try:
            self._client.shutdown()
        except:
            pass
