from typing import Optional

from lib.constants import KEY


def max_spread(self, params: dict) -> Optional[dict]:
    spread = 2 * (self._ask - self._bid) / (self._ask + self._bid)

    condition = spread > params[KEY.MAX_ABS_SPREAD]

    if condition:
        if condition:
            return {
                KEY.MESSAGE: 'HIGH SPREAD event',
                KEY.EVENT: 'CONDITION',
                KEY.TAG: 'MS',
                'spread': spread,
            }
