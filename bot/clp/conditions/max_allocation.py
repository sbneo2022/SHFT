from decimal import Decimal
from typing import Optional

from lib.constants import KEY, ORDER_TAG


def max_allocation(self, params: dict) -> Optional[dict]:
    qty = self._state.get(KEY.QTY, 0)
    pending: Decimal = self._state.get(KEY.PENDING, 0)
    qty = abs(qty + pending)

    if self._max_allocation_coeff is None:
        self._max_allocation_coeff = Decimal(params[KEY.MAX_ALLOCATION_COEFF])

    condition = qty >= self._max_allocation_coeff * self._all_levels_qty

    if condition:
        return {
            KEY.MESSAGE: 'HIGH ALLOCATION event',
            KEY.EVENT:'CONDITION',
            KEY.TAG: ORDER_TAG.MARKET + 'A',
            'allocation': qty,
        }

