from bot.iea.modules.handle_atr import HandleATR
from bot.iea.modules.handle_distance import HandleDistance
from bot.iea.modules.handle_exchange import HandleExchange
from bot.iea.modules.handle_state import HandleState
from lib.async_ejector import FieldsAsyncEjector
from lib.constants import KEY, ORDER_TAG
from lib.database import AbstractDatabase
from lib.exchange import Order
from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer


class HandleCleanStoploss(HandleExchange, HandleState, HandleDistance):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        # Create utility objects
        self._logger: AbstractLogger = factory.Logger(config, factory, timer)
        self._database: AbstractDatabase = factory.Database(config, factory, timer)


    def Clean(self):
        self.State[KEY.MODE] = KEY.MODE_HALT

        self._logger.warning(f'Cleaning all open orders')

        # Cancel ALL open orders
        self.Exchange.Cancel(wait=True)

        # Get list of current positions (we cant trust websocket data because
        # reason of this cleaning could be websocket connection error
        # Also we r quering current ask/bid
        positions = self.Exchange.getPosition()
        book = self.Exchange.getBook()

        if abs(positions.qty) > KEY.ED:
            self._logger.warning(f'Inventory found: keep STOPLOSS order', event='INVENTORY')

            midpoint = (book.ask_price + book.bid_price) / 2
            zero_price = self.GetZeroPrice(positions.qty, positions.price)
            if self.IsProfit(positions.qty, midpoint, zero_price):
                distance = self._trailing_profit  # Static "take_profit" distance from config
            else:
                distance = self.Distance  # ATR-based stoploss distance

            worst_stoploss_price = self.GetStoplossPrice(positions.qty, midpoint, distance)

            stoploss_price = self.State.get(KEY.STOPLOSS, None)

            if stoploss_price is None or \
                positions.qty > 0 and stoploss_price < worst_stoploss_price or \
                positions.qty < 0 and stoploss_price > worst_stoploss_price:
                stoploss_price = worst_stoploss_price

            liquidation_order = Order(qty=-1 * positions.qty, price=stoploss_price,
                                      stopmarket=True,  tag=ORDER_TAG.CONDITIONAL, liquidation=True)

            self.Exchange.Post(order=liquidation_order, wait=True)

        FieldsAsyncEjector(self._database, self._timer, quoting=-1).start()
        self._timer.Sleep(1)
