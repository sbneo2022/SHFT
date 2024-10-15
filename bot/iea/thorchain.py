from decimal import Decimal
from pprint import pprint
from typing import Optional

from bot import AbstractBot
from bot.iea.modules.handle_buffer import HandleBuffer
from bot.iea.modules.handle_swap import HandleSwap
from bot.iea.modules.handle_watchdog import HandleWatchdog
from lib.constants import KEY
from lib.exchange import Book
from lib.factory import AbstractFactory
from lib.timer import AbstractTimer


RUNE_BNB_SYMBOL = 'RUNEBNB'

RUNE_MIN_QTY = Decimal('0.1')
BNB_TICK_SIZE = Decimal('0.0000001')

class Thorchain(
    HandleWatchdog,
    HandleBuffer,
    HandleSwap,
    AbstractBot
):

    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        self._symbol: str = self._config[KEY.SYMBOL]

        if self._symbol.endswith('BNB'):
            self._product = self._symbol[:-3]
            self._fn = lambda x: x
        elif self._symbol.startswith('BNB'):
            self._product = self._symbol[3:]
            self._fn = lambda x: 1 / x
        else:
            raise Exception('Wrong product')

        self._product_bnb: Optional[Book] = Book(ask_price=Decimal('1'), bid_price=Decimal('1'))
        self._rune_bnb: Optional[Book] = None

        self._task: Optional[list] = None


    def onOrderbook(self, askPrice: Decimal, askQty: Decimal, bidPrice: Decimal, bidQty: Decimal,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        super().onOrderbook(askPrice, askQty, bidPrice, bidQty, symbol, exchange, timestamp, latency)

        if symbol == self._symbol:
            self._product_bnb = Book(ask_price=askPrice, ask_qty=askQty, bid_price=bidPrice, bid_qty=bidQty)
            print('product_bnb update', self._product_bnb)

        if symbol == RUNE_BNB_SYMBOL:
            self._rune_bnb = Book(ask_price=askPrice, ask_qty=askQty, bid_price=bidPrice, bid_qty=bidQty)
            print('rune_bnb update', self._rune_bnb)


    def onTime(self, timestamp: int):
        super().onTime(timestamp)

        if all([self._rune_bnb, self._product_bnb]):
            thorchain_detail = self._get_thorchain_detail(self.swap_products[self._product]['thor'])[0]
            runeDepth = Decimal(thorchain_detail['runeDepth'])
            assetDepth = Decimal(thorchain_detail['assetDepth'])


            thorchain_price_in_rune = runeDepth / assetDepth


            rune_midpoint = (self._rune_bnb.ask_price + self._rune_bnb.bid_price) / 2
            product_midpoint = (self._product_bnb.ask_price + self._product_bnb.bid_price) / 2

            dex_ask_in_rune = self._fn(self._product_bnb.ask_price) / self._rune_bnb.bid_price
            dex_bid_in_rune = self._fn(self._product_bnb.bid_price) / self._rune_bnb.ask_price
            dex_mid_in_rune = self._fn(product_midpoint) / rune_midpoint

            summary = {
                'assetDepth': int(assetDepth),
                'runeDepth': int(runeDepth),
                'thorchain_price_in_rune': thorchain_price_in_rune,
                'dex_ask_in_rune': dex_ask_in_rune,
                'dex_bid_in_rune': dex_bid_in_rune,
                'dex_mid_in_rune': dex_mid_in_rune,
            }


            if self._symbol == 'BNBBNB':
                max_rune_available_to_buy = self._rune_bnb.ask_qty * Decimal('0.8')
                max_rune_available_to_buy = round(max_rune_available_to_buy / RUNE_MIN_QTY) * RUNE_MIN_QTY

                max_rune_available_to_sell = self._rune_bnb.bid_qty * Decimal('0.8')
                max_rune_available_to_sell = round(max_rune_available_to_sell / RUNE_MIN_QTY) * RUNE_MIN_QTY

                max_bnb_available_to_buy = max_rune_available_to_sell * self._rune_bnb.bid_price

                # Case 1: Send RUNE, receive BNB, convert them to RUNE
                receive = (max_rune_available_to_buy - 1) / (thorchain_price_in_rune * self._rune_bnb.ask_price)
                roc_case_1 = receive / max_rune_available_to_buy - 1
                print(f'------- Case 1 ROC: {roc_case_1}')
                summary['max_rune_we_can_use'] = max_rune_available_to_buy
                summary['max_roc_rbr'] = roc_case_1


                # Case 2: Send BNB, receive RUNE, convert them to BNB
                receive = (max_bnb_available_to_buy * thorchain_price_in_rune - 1) * self._rune_bnb.bid_price
                roc_case_2 = receive / max_bnb_available_to_buy - 1
                print(f'------- Case 2 ROC: {roc_case_2}')
                summary['max_bnb_we_can_use'] = max_bnb_available_to_buy
                summary['max_roc_brb'] = roc_case_2

                if max([roc_case_1, roc_case_2]) > 0:
                    account = {
                        'RUNE': Decimal('2000'),
                        'BNB': Decimal('100'),
                    }
                    # account = self.getDexAccount()
                    print(f'Current account: {account}')

                    if roc_case_1 > roc_case_2:
                        print(f'======== Will try to convert RUNE -> BNB -> RUNE')
                        max_rune = min(max_rune_available_to_buy, account['RUNE'])
                        receive = (max_rune - 1) / (thorchain_price_in_rune * self._rune_bnb.ask_price)
                        roc = receive / max_rune - 1

                        if roc > 0:
                            print(f'Target ROC: {roc}. Try to start conversion')

                            if self._task is None:
                                self._add_rbr_task(max_rune)
                                summary['available_roc'] = roc
                            else:
                                print(f'Task in progress: cant add new task')
                        else:
                            print(f'Target ROC: {roc}. Not enough funds, we need at least {max_rune_available_to_buy} ({account}. Skip event')

                    else:
                        print(f'======== Will try to convert BNB -> RUNE -> BNB')
                        max_bnb = min(account['BNB'], max_bnb_available_to_buy)
                        receive = (max_bnb * thorchain_price_in_rune - 1) * self._rune_bnb.bid_price
                        roc = receive / max_bnb - 1

                        if roc > 0:
                            print(f'Target ROC: {roc}. Try to start conversion')

                            if self._task is None:
                                self._add_rbr_task(max_bnb)
                                summary['available_roc'] = roc
                            else:
                                print(f'Task in progress: cant add new task')
                        else:
                            print(f'Target ROC: {roc}. Not enough funds, we need at least {max_bnb_available_to_buy} ({account}). Skip event')

                # for capital in [10, 100, 1000]:
                #     receive = (capital - 1) / (thorchain_price_in_rune * self._rune_bnb.ask_price)
                #     roc[f'rune_{capital}'] = (receive / capital) - 1
                #
                # for capital in [1, 10, 100]:
                #     receive = (capital * thorchain_price_in_rune - 1) * self._rune_bnb.bid_price
                #     roc[f'bnb_{capital}'] = (receive / capital) - 1
            #
            self.putBuffer(summary)
            pprint(summary)


    def _add_rbr_task(self, capital: Decimal):
        print(f'Add new task RBR with capital {capital}')
        # self._task = [
        #     {
        #         'action': 'rbr',
        #         'capital': capital
        #     }
        # ]

    def _add_brb_task(self, capital: Decimal):
        print(f'Add new task BRB with capital {capital}')
        # self._task = [
        #     {
        #         'action': 'brb',
        #         'capital': capital
        #     }
        # ]