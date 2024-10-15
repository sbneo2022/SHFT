from decimal import Decimal
from typing import Dict, Union

from bot import AbstractBot
from bot.iea.modules.handle_exchange import HandleExchange
from lib.constants import KEY
from lib.exchange import get_exchange, Order
from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.state import AbstractState
from lib.timer import AbstractTimer


class HandleState(HandleExchange, AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        self._logger: AbstractLogger = factory.Logger(config, factory, timer)
        self._state_repository: AbstractState = factory.State(config, factory, timer)

        ################################################################
        # Clear Open Orders for all exchanges and load actual positions
        ################################################################
        positions: Dict[str, Order] = dict()

        for target, product in self.products.items():
            product.oms.Cancel()
            positions[target] = product.oms.getPosition()

        ################################################################
        # Public variables
        ################################################################
        self.state = self._build_state_from_positions(positions)

        ################################################################
        # Save State to State Repository
        ################################################################
        self.saveState()


    def saveState(self):
        self._state_repository.Push(self.state)

    def _build_state_from_positions(self, position: Dict[str, Order]) -> Dict[str, Union[Decimal, int, Dict]]:
        state = self._state_repository.Pop() or {}

        if KEY.INVENTORY not in state:
            state[KEY.INVENTORY] = {}

        for target, order in position.items():
            if abs(order.qty) < KEY.ED:
                self._logger.warning(f'"{target.upper()}" portfolio is empty')
                state[KEY.INVENTORY][target] = {}
            else:
                self._logger.warning(f'Current portfolio for '
                                     f'{self.products[target].symbol}@{self.products[target].exchange}: '
                                     f'{order.qty}@{order.price}')

                if state[KEY.INVENTORY].get(target, {}).get(KEY.QTY, None) == order.qty:
                    state[KEY.INVENTORY][target][KEY.PENDING] = 0
                    self._logger.warning(f'Continue with State', state=state[KEY.INVENTORY][target])
                else:
                    if target not in state[KEY.INVENTORY].keys():
                        state[KEY.INVENTORY][target] = {}

                    state[KEY.INVENTORY][target][KEY.QTY] = order.qty
                    state[KEY.INVENTORY][target][KEY.PRICE] = order.price
                    self._logger.warning(f'Qty not equal to Repository State.'
                                         f' Continue with current inventory', state=state[KEY.INVENTORY][target])

        return state
