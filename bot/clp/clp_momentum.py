from decimal import Decimal

from bot import AbstractBot
from bot.clp.clp_atr import CLPATR
from bot.clp.mode.handle_inventory_dynamic_partial import handle_inventory_dynamic_partial
from bot.clp.momentum.handle_momentum import handle_momentum
from bot.clp.momentum.price_event import PriceEvent
from lib.constants import KEY
from lib.factory import AbstractFactory
from lib.timer import AbstractTimer


class CLPMomentum(CLPATR, AbstractBot):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer):
        super().__init__(config, factory, timer)

        self._qty_coeff = Decimal(str(config['qty_coeff']))

        self._event = PriceEvent(config, self)

    def _handle_new_orderbook_event(self, askPrice, bidPrice, latency):
        self._event.Update(askPrice, bidPrice)

        if self._state[KEY.MODE] == KEY.MODE_HALT:
            pass

        elif self._state[KEY.MODE] == KEY.MODE_EMPTY:
            handle_momentum(self, askPrice, bidPrice, latency)

        elif self._state[KEY.MODE] == KEY.MODE_INVENTORY:
            if self._handle_inventory:
                handle_inventory_dynamic_partial(self, askPrice, bidPrice)

