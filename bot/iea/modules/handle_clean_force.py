from bot import AbstractBot
from bot.iea.modules.handle_exchange import HandleExchange
from bot.iea.modules.handle_state import HandleState
from lib.async_ejector import FieldsAsyncEjector
from lib.constants import KEY, ORDER_TAG
from lib.database import AbstractDatabase
from lib.exchange import Order
from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer


class HandleCleanForce(HandleState, HandleExchange, AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        # Create utility objects
        self._logger: AbstractLogger = factory.Logger(config, factory, timer)
        self._database: AbstractDatabase = factory.Database(config, factory, timer)

    def Clean(self):
        self.state[KEY.MODE] = KEY.MODE_HALT

        self._logger.warning(f'Cleaning all open orders')

        # Cancel ALL open orders
        self.default_oms.Cancel(wait=True)

        # Get list of current positions (we cant trust websocket data because
        # reason of this cleaning could be websocket connection error
        # Also we r quering current ask/bid
        for product in self.products.values():
            positions = product.oms.getPosition()

            if abs(positions.qty) > KEY.ED:
                self._logger.warning(f'Inventory found: {positions}. Clean', event='INVENTORY')

                liquidation_order = Order(qty=-1 * positions.qty, tag=ORDER_TAG.MARKET, liquidation=True)

                product.oms.Post(order=liquidation_order, wait=True)

        FieldsAsyncEjector(self._database, self._timer, quoting=-1).start()
        self._timer.Sleep(1)
