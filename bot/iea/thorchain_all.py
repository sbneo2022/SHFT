from decimal import Decimal
from pprint import pprint
from typing import Optional, Dict, Union

from bot import AbstractBot
from bot.iea.modules.handle_buffer import HandleBuffer
from bot.iea.modules.handle_swap import HandleSwap
from bot.iea.modules.handle_watchdog import HandleWatchdog
from lib.constants import KEY
from lib.exchange import Book
from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer

RUNE_THORCHAIN_SYMBOL = 'BNB.BNB'

RUNE_BNB_SYMBOL = 'RUNEBNB'

RUNE_USD_SYMBOL = 'RUNEBUSD'

DEFAULT_CAPITAL = 10_000

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

        self._logger: AbstractLogger = factory.Logger(config, factory=factory, timer=timer)

        self._capital = self._config.get(KEY.CAPITAL, DEFAULT_CAPITAL)
        self._capital = Decimal(str(self._capital))
        self._logger.info(f'Estimate capital used: {self._capital} USD', capital=self._capital)


        self._dex_latest: Dict[str, Dict[str, Union[int, Decimal]]] = {}


    def onOrderbook(self, askPrice: Decimal, askQty: Decimal, bidPrice: Decimal, bidQty: Decimal,
                    symbol: str, exchange: str,
                    timestamp: int, latency: int = 0):
        super().onOrderbook(askPrice, askQty, bidPrice, bidQty, symbol, exchange, timestamp, latency)

        self._dex_latest[symbol] = {
            KEY.ASK_PRICE: askPrice,
            KEY.BID_PRICE: bidPrice,
        }

        # print(symbol, self._dex_latest[symbol])


    def _get_dex_price(self, base_symbol: str) -> Optional[Dict[str, Union[int, Decimal]]]:

        if base_symbol + 'BNB' in self._dex_latest:
            return self._dex_latest[base_symbol + 'BNB'].copy()

        elif 'BNB' + base_symbol in self._dex_latest:
            return {
                KEY.ASK_PRICE: 1 / self._dex_latest['BNB' + base_symbol][KEY.BID_PRICE],
                KEY.BID_PRICE: 1 / self._dex_latest['BNB' + base_symbol][KEY.ASK_PRICE],
            }

        else:
            return


    def onTime(self, timestamp: int):
        super().onTime(timestamp)
        thorchain_products = self.getThorchainDetails()

        if RUNE_THORCHAIN_SYMBOL not in thorchain_products:
            return

        if RUNE_USD_SYMBOL in self._dex_latest.keys():
            ask_price = self._dex_latest[RUNE_USD_SYMBOL][KEY.ASK_PRICE]
            bid_price = self._dex_latest[RUNE_USD_SYMBOL][KEY.BID_PRICE]
            rune_price_in_usd = (ask_price + bid_price) / 2
            capital_in_rune = self._capital / rune_price_in_usd
        else:
            capital_in_rune = 0

        rune_assetDepth = thorchain_products[RUNE_THORCHAIN_SYMBOL]['assetDepth']
        rune_runeDepth = thorchain_products[RUNE_THORCHAIN_SYMBOL]['runeDepth']

        for product, depths in thorchain_products.items():
            base_symbol = product.split('.')[1].split('-')[0]
            symbol = base_symbol + 'RUNE'

            dex_price = self._get_dex_price(base_symbol)

            assetDepth = depths['assetDepth']
            runeDepth = depths['runeDepth']

            price = runeDepth / assetDepth

            if base_symbol == 'BNB':
                result_in_bnb = self.calc_swap_rune(assetDepth, runeDepth, capital_in_rune - 1)
                capital_ratio = None if not capital_in_rune else result_in_bnb / capital_in_rune
            else:
                capital_in_product = capital_in_rune / price
                result_in_rune = self.calc_swap_asset(assetDepth, runeDepth, capital_in_product)
                result_in_bnb = self.calc_swap_rune(rune_assetDepth, rune_runeDepth, result_in_rune - 1)
                capital_ratio = None if not capital_in_product else result_in_bnb / capital_in_product

            item = {
                'price': price,
                'runeDepth': int(runeDepth),
                'assetDepth': int(assetDepth),
                'dex_ask_asset_bnb': None if dex_price is None else dex_price[KEY.ASK_PRICE],
                'dex_bid_asset_bnb': None if dex_price is None else dex_price[KEY.BID_PRICE],
                'thorchain_asset_bnb': capital_ratio,
            }

            print({**item, KEY.SYMBOL: base_symbol})

            self.putBuffer(item, tags={KEY.SYMBOL: symbol, KEY.EXCHANGE: KEY.EXHANGE_THORCHAIN})
