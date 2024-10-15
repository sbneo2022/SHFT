from decimal import Decimal

from bot import AbstractBot
from bot.iea.modules.handle_exchange import HandleExchange
from bot.iea.modules.handle_state import HandleState
from lib.constants import KEY
from lib.factory import AbstractFactory
from lib.helpers import sign
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer


class HandlePositions(HandleState, HandleExchange, AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        # Create utility objects
        self._logger: AbstractLogger = factory.Logger(config, factory, timer)

        # Create state section for inventory with multiply products
        if KEY.INVENTORY not in self.state.keys():
            self.state[KEY.INVENTORY] = {}

    def onAccount(self, price: Decimal, qty: Decimal, symbol: str, exchange: str, timestamp: int, latency: int = 0):
        super().onAccount(price, qty, symbol, exchange, timestamp, latency)

        # We well handle only registered products
        product_pair = (symbol, exchange)

        if product_pair not in self.products_map.keys():
            return

        product = self.products_map[product_pair]

        if product not in self.state[KEY.INVENTORY].keys():
            self.state[KEY.INVENTORY][product] = {}

        pending = self.state[KEY.INVENTORY][product].get(KEY.PENDING, 0)
        inventory = self.state[KEY.INVENTORY][product].get(KEY.QTY, 0)

        self._logger.warning(f'NEW INVENTORY for {product}: {qty}', qty=qty, pending=pending)

        delta = qty - inventory
        self.state[KEY.INVENTORY][product][KEY.QTY] = qty
        if sign(delta) == sign(pending):
            _new_pending = max(0, abs(pending) - abs(delta))
            self.state[KEY.INVENTORY][product][KEY.PENDING] = sign(pending) * _new_pending

        if abs(inventory) < KEY.ED:
            if abs(qty) > KEY.ED:
                self._logger.warning(f'Change MODE: EMPTY->INVENTORY', entry=price, qty=qty)
                self.state[KEY.INVENTORY][product][KEY.PRICE] = price
                self.state[KEY.INVENTORY][product][KEY.STOPLOSS] = None

        elif abs(qty) < KEY.ED:
            self._logger.warning(f'FORCE change MODE: INVENTORY->EMPTY', entry=price, qty=qty)
            self.state[KEY.INVENTORY][product] = {}

        else:
            self._logger.warning(f'Inventory change; Reset Stoploss price', entry=price, qty=qty)
            self.state[KEY.INVENTORY][product][KEY.PRICE] = price
            self.state[KEY.INVENTORY][product][KEY.STOPLOSS] = None

        self.saveState()
