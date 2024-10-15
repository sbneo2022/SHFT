import json
import os
import sys
import time
from datetime import datetime
from pprint import pprint
from typing import Any, Dict, Tuple, List

from loguru import logger

sys.path.append(os.path.abspath('../../..'))
from tools.perpetual_protocol.bot import Bot
from tools.perpetual_protocol.bot.basis import Basis
from tools.perpetual_protocol.lib.binance import Binance, BINANCE_BASE
from tools.perpetual_protocol.lib.binance_spot import BinanceSpot
from tools.perpetual_protocol.lib.constants import KEY, EXCHANGE, Product
from tools.perpetual_protocol.lib.db import Db
from tools.perpetual_protocol.lib.dydx import DyDx, DYDX_BASE
from tools.perpetual_protocol.lib.ftx import Ftx, FTX_BASE
from tools.perpetual_protocol.lib.message import Message, MessageDepth, MessageBestBook
from tools.perpetual_protocol.lib.perpetual_protocol import PerpetualProtocol, PP_BASE


class Worker:
    def __init__(self, config: dict):
        self._config = config

        self._pp = PerpetualProtocol(self._config)
        self._ftx = Ftx(self._config)
        self._binance = Binance(self._config)
        self._binance_spot = BinanceSpot(self._config)
        self._dydx = DyDx(self._config)

        self._db = Db(self._config)

        ########################################################################################################
        # Create bots
        ########################################################################################################
        self._bots = self._create_bots()

        logger.success(f'{len(self._bots)} bots are created')

    def _get_exchange_tuple_from_list(self, pair: List[str]) -> Tuple[EXCHANGE, EXCHANGE]:
        return_me = []
        for item in pair:
            if item.upper() in EXCHANGE._member_map_.keys():
                return_me.append(EXCHANGE._member_map_[item.upper()])
        return (return_me[0], return_me[1])

    def _get_exchange_pairs(self, config) -> Dict[Tuple[EXCHANGE, EXCHANGE], dict]:
        return_me = {}
        for item in config['pairs']:
            if isinstance(item, list):
                pair = self._get_exchange_tuple_from_list(item)
                return_me[pair] = {}
            else:
                pair = self._get_exchange_tuple_from_list(item['pair'])
                custom = {
                    key: value for key, value in item.items() if key != 'pair'
                }
                return_me[pair] = custom

        return return_me

    def _create_bots(self) -> List[Bot]:
        return_me: List[Bot] = []

        exchange_pairs = self._get_exchange_pairs(self._config)

        for base in self._config['products']:
            for exchange_pair, custom in exchange_pairs.items():
                a, b = exchange_pair
                custom_config = self._config.copy()
                for key, value in custom.items():
                    custom_config[key] = value

                return_me.append(
                    Basis({
                        **custom_config,
                        'a': a,
                        'b': b,
                        KEY.BASE: base
                    })
                )

        return return_me

    def _load_all_prices(self) -> Tuple[dict, dict, dict, dict, dict]:
        pp_prices = self._pp.getProductsData()
        ftx_prices = self._ftx.getProductsData()
        binance_prices = self._binance.getProductsData()
        binance_spot_prices = self._binance_spot.getProductsData()
        dydx_prices = self._dydx.getProductsData()

        return (pp_prices, ftx_prices, binance_prices, binance_spot_prices, dydx_prices)

    def _get_basis(self, futures_prices, spot_prices) -> dict:
        return_me = {}
        for key, value in futures_prices.items():
            if key in spot_prices:
                futures_midpoint = (value[KEY.ASK_PRICE] + value[KEY.BID_PRICE]) / 2
                spot_midpoint = (spot_prices[key][KEY.ASK_PRICE] + spot_prices[key][KEY.BID_PRICE]) / 2
                basis_midpoint = (futures_midpoint + spot_midpoint) / 2
                return_me[key] = (futures_midpoint - spot_midpoint) / basis_midpoint

        return return_me

    def _save_basis_to_database(self, basis: dict, _time: datetime):
        for tag, value in basis.items():
            base, quote = tag.split('-')
            _tag = base + '-' + PP_BASE
            self._db.addPoint(fields={'basis': value}, tags=dict(product=_tag), time=_time)


    def _get_mix_data(self, pp_prices, ftx_prices, binance_prices, dydx_prices) -> dict:
        mix = dict()

        for product, data in pp_prices.items():
            base, quote = product.split('-')
            maybe_ftx = base + '-' + FTX_BASE
            maybe_binance = base + '-' + BINANCE_BASE
            maybe_dydx = base + '-' + DYDX_BASE
            if maybe_ftx in ftx_prices and \
               maybe_binance in binance_prices and \
               maybe_dydx in dydx_prices:

                pool_price = data[KEY.POOL_PRICE]
                ftx_ask_price = ftx_prices[maybe_ftx][KEY.ASK_PRICE]
                ftx_bid_price = ftx_prices[maybe_ftx][KEY.BID_PRICE]

                binance_ask_price = binance_prices[maybe_binance][KEY.ASK_PRICE]
                binance_bid_price = binance_prices[maybe_binance][KEY.BID_PRICE]

                dydx_ask_price = dydx_prices[maybe_dydx][KEY.ASK_PRICE]
                dydx_bid_price = dydx_prices[maybe_dydx][KEY.BID_PRICE]

                ftx_midpoint = (ftx_ask_price + ftx_bid_price) / 2
                binance_midpoint = (binance_ask_price + binance_bid_price) / 2
                dydx_midpoint = (dydx_ask_price + dydx_bid_price) / 2

                general_midpoint = (pool_price + ftx_midpoint + binance_midpoint + dydx_midpoint) / 4

                pool_ftx_spread = pool_price - ftx_midpoint
                pool_binance_spread = pool_price - binance_midpoint
                pool_dydx_spread = pool_price - dydx_midpoint
                ftx_binance_spread = ftx_midpoint - binance_midpoint
                ftx_dydx_spread = ftx_midpoint - dydx_midpoint
                binance_dydx_spread = binance_midpoint - dydx_midpoint

                pool_ftx_spread = pool_ftx_spread / general_midpoint
                pool_binance_spread = pool_binance_spread / general_midpoint
                pool_dydx_spread = pool_dydx_spread / general_midpoint
                ftx_binance_spread = ftx_binance_spread / general_midpoint
                ftx_dydx_spread = ftx_dydx_spread / general_midpoint
                binance_dydx_spread = binance_dydx_spread / general_midpoint

                mix[product] = {
                    'poolPrice': pool_price,
                    'askPrice': ftx_ask_price,
                    'bidPrice': ftx_bid_price,
                    'spread': pool_ftx_spread,
                    'binance_askPrice': binance_ask_price,
                    'binance_bidPrice': binance_bid_price,
                    'dydx_askPrice': dydx_ask_price,
                    'dydx_bidPrice': dydx_bid_price,
                    'pool_binance_spread': pool_binance_spread,
                    'pool_dydx_spread': pool_dydx_spread,
                    'ftx_binance_spread': ftx_binance_spread,
                    'ftx_dydx_spread':  ftx_dydx_spread,
                    'binance_dydx_spread':  binance_dydx_spread,
                }

        return mix

    def _save_mix_to_database(self, mix: dict, _time: datetime):
        for tag, fields in mix.items():
            self._db.addPoint(fields, tags=dict(product=tag), time=_time)

    def _save_funding_rate(self, mix: dict, _time: datetime):
        ftx_funding_rates = self._ftx.getFundingRates()
        binance_funding_rates = self._binance.getFundingRates()

        for product in mix.keys():
            quote, base = product.split('-')
            self._db.addPoint({
                'ftx_funding_rate': ftx_funding_rates[quote + '-' + FTX_BASE]['fundingRate'],
                'binance_funding_rate': binance_funding_rates[quote + '-' + BINANCE_BASE]['fundingRate'],
            }, tags=dict(product=product), time=_time)


    def run(self) -> Dict[str, Any]:
        now = datetime.utcnow().replace(microsecond=0)
        t0 = time.time()

        ###########################################################################################
        # Load prices and depth data from all sources. TODO: make parallel
        ###########################################################################################
        pp_prices, ftx_prices, binance_prices, binance_spot_prices, dydx_prices = self._load_all_prices()

        ###########################################################################################
        # Create normalized fields for common products
        ###########################################################################################
        mix = self._get_mix_data(pp_prices, ftx_prices, binance_prices, dydx_prices)

        ###########################################################################################
        # Save "how many seconds we need to load data"
        ###########################################################################################
        duration = time.time() - t0
        self._db.addPoint(dict(duration=float(duration)), time=now)

        ###########################################################################################
        # Save mix of products to database
        ###########################################################################################
        self._save_mix_to_database(mix, now)

        ###########################################################################################
        # Handle Basis data (Binance Futures vs Spot)
        ###########################################################################################
        basis = self._get_basis(binance_prices, binance_spot_prices)
        self._save_basis_to_database(basis, now)

        ###########################################################################################
        # Load and save funding rates
        ###########################################################################################
        self._save_funding_rate(mix, now)

        ###########################################################################################
        # Final message
        ###########################################################################################
        logger.info(f'{len(mix)} products are loaded in {duration} seconds')
        t0 = time.time()
        logger.info(f'Running {len(self._bots)} bots')

        messages = []
        bases = [x.split('-')[0] for x in mix.keys()]
        for symbol, item in pp_prices.items():
            base = symbol.split('-')[0]
            if base in bases:
                messages.append(MessageDepth(
                    product=Product(symbol=symbol, exchange=EXCHANGE.PERPETUAL_PROTOCOL),
                    pool_price=item[KEY.POOL_PRICE],
                    base_depth=item[KEY.BASE_DEPTH],
                    quote_depth=item[KEY.QUOTE_DEPTH],
                    time=now,
                ))

        for symbol, item in binance_prices.items():
            base = symbol.split('-')[0]
            if base in bases:
                messages.append(MessageBestBook(
                    product=Product(symbol=symbol, exchange=EXCHANGE.BINANCE),
                    best_ask=item[KEY.ASK_PRICE],
                    best_bid=item[KEY.BID_PRICE],
                    time=now,
                ))

        for symbol, item in ftx_prices.items():
            base = symbol.split('-')[0]
            if base in bases and FTX_BASE in symbol:
                messages.append(MessageBestBook(
                    product=Product(symbol=symbol, exchange=EXCHANGE.FTX),
                    best_ask=item[KEY.ASK_PRICE],
                    best_bid=item[KEY.BID_PRICE],
                    time=now,
                ))

        for symbol, item in dydx_prices.items():
            base = symbol.split('-')[0]
            if base in bases:
                messages.append(MessageBestBook(
                    product=Product(symbol=symbol, exchange=EXCHANGE.DYDX),
                    best_ask=item[KEY.ASK_PRICE],
                    best_bid=item[KEY.BID_PRICE],
                    time=now,
                ))

        for bot in self._bots:
            bot.on_message(messages)

        logger.info(f'Done in {time.time() - t0} seconds')

        ###########################################################################################
        # Return Base Data
        ###########################################################################################
        return mix