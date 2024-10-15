from typing import Optional

from lib.constants import KEY


def max_latency(self, params: dict) -> Optional[dict]:
    condition = self._latency > params[KEY.MAX_LATENCY] * KEY.ONE_SECOND

    if condition:
        return {
            KEY.MESSAGE: 'HIGH LATENCY event',
            KEY.EVENT: 'CONDITION',
            KEY.TAG: 'ML',
            'latency': self._latency,
        }
