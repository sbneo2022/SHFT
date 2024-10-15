import json
import math
import traceback
from collections import deque
from decimal import Decimal
from pathlib import Path
from pprint import pprint
from typing import Optional, Dict, List, Union

import requests
from eth_typing import Address
from web3 import Web3, HTTPProvider
from web3.contract import Contract

from lib.constants import KEY, DB, SIDE, ORDER_TYPE, TIF, MONTH_MAP
from lib.database import AbstractDatabase
from lib.defaults import DEFAULT
from lib.exchange import AbstractExchange, Order, Book, Balance
from lib.factory import AbstractFactory
from lib.helpers import custom_dump, sign
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer
from lib.vault import AbstractVault, VAULT

DEFAULT_NODE_URL = 'http://127.0.0.1:8545'

META_URL = 'https://metadata.perp.exchange/production.json'

ABI_AMM = Path(__file__).parent.parent / Path('data/abi') / Path('amm.json')
ABI_AMM_READER = Path(__file__).parent.parent / Path('data/abi') / Path('amm_reader.json')
ABI_CLEARING_HOUSE = Path(__file__).parent.parent / Path('data/abi') / Path('clearing_house.json')
ABI_CLEARING_HOUSE_VIEWER = Path(__file__).parent.parent / Path('data/abi') / Path('clearing_house_viewer.json')
ABI_COIN = Path(__file__).parent.parent / Path('data/abi') / Path('coin.json')

USDC_COEFF = 1_000_000
COIN_COEFF = int(1e18)
MIN_QTY = Decimal('1') / COIN_COEFF
USDC_TICK = Decimal('0.000001')
CHAIN_ID = 0x64
MIN_NOTIONAL = Decimal('1')
DEFAULT_LEVERAGE = 2
DEFAULT_GAS_MAX = 5_000_000
DEFAULT_GAS_PRICE_GWEI = 1

FAILED_RESET_TIMEOUT = 10 * KEY.ONE_SECOND

class PerpetualProtocolExchange(AbstractExchange):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, symbol: Optional[str] = None):
        super().__init__(config, factory, timer, symbol)

        # Override exchange name
        self._config[KEY.EXCHANGE] = KEY.EXCHANGE_PERPETUAL_PROTOCOL
        self._symbol, self._exchange = self._config[KEY.SYMBOL], self._config[KEY.EXCHANGE]

        self._database: AbstractDatabase = factory.Database(self._config, factory=factory, timer=timer)
        self._logger: AbstractLogger = factory.Logger(self._config, factory=factory, timer=timer)
        self._vault: AbstractVault = factory.Vault(self._config, factory=factory, timer=timer)

        self._node_url = self._config.get(self._exchange, {}).get(KEY.NODE_URL, None) or DEFAULT_NODE_URL
        self._leverage = self._config.get(self._exchange, {}).get(KEY.LEVERAGE, None) or DEFAULT_LEVERAGE
        self._leverage = Decimal(str(self._leverage))

        self._gas_price = self._config.get(self._exchange, {}).get(KEY.GAS_PRICE_GWEI, None) or DEFAULT_GAS_PRICE_GWEI
        self._gas_price = int(Decimal(str(self._gas_price)) * 1_000_000_000)

        self._gas_max = self._config.get(self._exchange, {}).get(KEY.GAS_MAX, None) or DEFAULT_GAS_MAX
        self._gas_max = int(self._gas_max)

        self._logger.info(f'Node: {self._node_url} | '
                          f'Gas Max: {self._gas_max} | '
                          f'Gas Price (gwei): {self._gas_price / 1_000_000_000}')

        self._private_key = self._vault.Get(VAULT.PRIVATE_KEY)
        self._address = self._vault.Get(VAULT.ADDRESS)

        self._symbol = self._construct_symbol()

        self._dry = self._address is None or self._private_key is None
        if self._dry:
            self._logger.error('Exchange: No ADDRESS/PRIVATE_KEY given. Running in DRY mode')

        meta = self._get_meta()
        self._tick = self._get_tick(meta)
        self._min_qty = self._get_min_qty(meta)
        self._min_notional = self._get_min_notional(meta)

        self._w3 = Web3(HTTPProvider(self._node_url))

        self._amm = self._get_amm(meta)
        self._amm_reader = self._get_amm_reader(meta)
        self._clearing_house = self._get_clearing_house(meta)
        self._clearing_house_viewer = self._get_clearing_house_viewer(meta)
        self._usdc = self._get_usdc(meta)

        self._exchange_error: Optional[int] = None

    ##############################################################################
    #
    # Public Methods
    #
    ##############################################################################

    def isOnline(self) -> bool:
        if self._exchange_error is not None:
            if self._exchange_error > self._timer.Timestamp():
                self._exchange_error = None
        return self._exchange_error is None

    def getTick(self) -> Decimal:
        return self._tick

    def getMinQty(self) -> Decimal:
        return self._min_qty

    def applyRules(self, order: Order, rule: Optional[str] = None) -> Order:
        # Round price UP/DOWN/SIMPLE
        if order.price is not None:
            if rule == KEY.UP:
                order.price = math.ceil(order.price / self._tick) * self._tick
            elif rule == KEY.DOWN:
                order.price = math.floor(order.price / self._tick) * self._tick
            else:
                order.price = round(order.price / self._tick) * self._tick

        order.qty = sign(order.qty) * round(abs(order.qty) / self._min_qty) * self._min_qty

        # If order is not LIQUIDATION --> check "min_notional"
        if not order.liquidation:
            if order.price is None:
                price = self._top_book.ask_price if order.qty > 0 else self._top_book.bid_price
            else:
                price = order.price

            if abs(order.qty * (price or 0)) <= self._min_notional:
                order.qty = Decimal(0)

        return order

    def getBook(self) -> Book:
        try:
            states = self._amm_reader.functions.getAmmStates(self._amm.address).call()
            quoteAssetReserve, baseAssetReserve, *_ = states
            price = Decimal(quoteAssetReserve/ baseAssetReserve)
            return Book(ask_price=price, bid_price=price)
        except:
            self._exchange_error = self._timer.Timestamp() + FAILED_RESET_TIMEOUT
            traceback.print_exc()
            return Book()

    def getFundingRate(self) -> Optional[Decimal]:
        try:
            funding_rate = self._amm.functions.fundingRate().call()
            return Decimal(str(funding_rate)) / COIN_COEFF
        except:
            self._exchange_error = self._timer.Timestamp() + FAILED_RESET_TIMEOUT
            traceback.print_exc()
            return None

    def getBalance(self) -> Balance:
        try:
            gas = self._w3.eth.get_balance(self._address)
            usdc_balance = self._usdc.functions.balanceOf(self._address).call()
            return Balance(
                balance=Decimal(usdc_balance) / USDC_COEFF,
                available=Decimal(usdc_balance) / USDC_COEFF,
                gas=Decimal(gas) / COIN_COEFF
            )
        except:
            self._exchange_error = self._timer.Timestamp() + FAILED_RESET_TIMEOUT
            traceback.print_exc()
            return Balance()

    def getPosition(self) -> Order:
        try:
            data = self._clearing_house_viewer\
                .functions\
                .getPersonalPositionWithFundingPayment(self._amm.address, self._address)\
                .call()

            (position, margin, openNotional, lastUpdatedCumulativePremiumFraction, liquidityHistoryIndex, blockNumber) = data

            position = Decimal(str(position[0])) / COIN_COEFF
            openNotional = Decimal(str(openNotional[0])) / COIN_COEFF
            entry_price = None if abs(position) < KEY.ED else openNotional / position

            return Order(qty=position, price=None if entry_price is None else abs(entry_price))
        except:
            self._exchange_error = self._timer.Timestamp() + FAILED_RESET_TIMEOUT
            traceback.print_exc()
            return Order()


    def getCandles(self, start_timestamp: int, end_timestamp: int) -> Dict[str, deque]:
        return dict()

    def Post(self, order: Order, wait=False) -> str:
        book = self.getBook()
        position = self.getPosition()

        quote_asset_amount = abs(order.qty) * (book.ask_price if order.qty > 0 else book.bid_price) / self._leverage
        quote_asset_amount = int(quote_asset_amount * COIN_COEFF)

        if abs(position.qty + order.qty) < KEY.ED:
            print('CLOSE method')
            tx = self._clearing_house.functions.closePosition(self._amm.address, {'d': 0})
        else:
            print('POST method')
            tx = self._clearing_house.functions.openPosition(
                self._amm.address,
                0 if order.qty > 0 else 1,
                {'d': quote_asset_amount},
                {'d': int(self._leverage * COIN_COEFF)},
                {'d': 0},
            )

        # Get current Nonce estimate from blockchain
        nonce = self._w3.eth.getTransactionCount(self._address)

        tx_id = None

        # Try to send transaction no more than 10 times, increasing Nonce every time
        for idx in range(10):
            builded_transaction = tx.buildTransaction({
                'gas': self._gas_max,
                'gasPrice': self._gas_price,
                'chainId': CHAIN_ID,
                'nonce': nonce + idx
            })

            signed_tx = self._w3.eth.account.signTransaction(builded_transaction, private_key=self._private_key)

            try:
                tx_id = self._w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                break

            except Exception as e:
                if '-32010' in e.__str__():
                    self._logger.warning(f'Wrong `nonce` while making transaction. Increase `nonce` by {idx + 1}')

                else:
                    error = traceback.format_exc()
                    self._logger.error('Error while making transaction', error=error)
                    return None

        if tx_id is None:
            self._logger.error('Error while making transaction after several times increasing `nonce`')
            return None
        else:
            return tx_id.hex()

    def batchPost(self, orders: List[Order], wait=False) -> List[str]:
        return []

    def Cancel(self, ids: Optional[Union[str, List]] = None, wait=False):
        return

    ##############################################################################
    #
    # Private Methods
    #
    ##############################################################################

    def _load_abi(self, filename: Path) -> dict:
        with open(filename, 'r') as fp:
            return json.load(fp)

    def _construct_symbol(self) -> str:
        for _tail in ['USD', 'USDT', 'USDC']:
            if self._symbol.upper().endswith(_tail):
                return f'{self._symbol.upper()[:-len(_tail)]}USDC'

    def _get_meta(self) -> dict:
        meta = requests.get(META_URL).json()
        return meta

    def _get_tick(self, meta: dict) -> Decimal:
        return USDC_TICK

    def _get_min_qty(self, meta: dict) -> Decimal:
        return MIN_QTY

    def _get_min_notional(self, meta: dict) -> Decimal:
        return MIN_NOTIONAL

    def _get_layer(self, meta: dict, network: str = 'xdai') -> dict:
        for item in meta['layers'].values():
            if item['network'] == network:
                return item

    def _get_amm(self, meta: dict) -> Contract:
        abi = self._load_abi(ABI_AMM)
        layer = self._get_layer(meta)
        address = Address(layer['contracts'][self._symbol]['address'])
        return self._w3.eth.contract(address=address, abi=abi)

    def _get_amm_reader(self, meta: dict) -> Contract:
        abi = self._load_abi(ABI_AMM_READER)
        layer = self._get_layer(meta)
        address = Address(layer['contracts']['AmmReader']['address'])
        return self._w3.eth.contract(address=address, abi=abi)

    def _get_clearing_house(self, meta: dict) -> Contract:
        abi = self._load_abi(ABI_CLEARING_HOUSE)
        layer = self._get_layer(meta)
        address = Address(layer['contracts']['ClearingHouse']['address'])
        return self._w3.eth.contract(address=address, abi=abi)

    def _get_clearing_house_viewer(self, meta: dict) -> Contract:
        abi = self._load_abi(ABI_CLEARING_HOUSE_VIEWER)
        layer = self._get_layer(meta)
        address = Address(layer['contracts']['ClearingHouseViewer']['address'])
        return self._w3.eth.contract(address=address, abi=abi)

    def _get_usdc(self, meta: dict) -> Contract:
        abi = self._load_abi(ABI_COIN)
        layer = self._get_layer(meta)
        address = Address(layer['externalContracts']['usdc'])
        return self._w3.eth.contract(address=address, abi=abi)
