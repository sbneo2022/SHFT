from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pprint import pprint
from typing import Dict, List, Tuple, Optional, Union

import requests
from binance_chain.environment import BinanceEnvironment
from binance_chain.http import HttpApiClient
from binance_chain.messages import TransferMsg, NewOrderMsg
from binance_chain.wallet import Wallet

from bot import AbstractBot
from lib.constants import KEY
from lib.exchange import Book
from lib.factory import AbstractFactory
from lib.logger import AbstractLogger
from lib.timer import AbstractTimer

DEX = 'https://dex.binance.org'


MAX_TRANSACTION_WAIT_TIME = 5 * KEY.ONE_MINUTE


class HandleDex(
    AbstractBot
):
    def __init__(self, config: dict, factory: AbstractFactory, timer: AbstractTimer, **kwargs):
        super().__init__(config, factory, timer, **kwargs)

        self._logger: AbstractLogger = factory.Logger(config, factory, timer)

        self._section = self._config[KEY.THORCHAIN]
        self._api = self._section[KEY.API]
        self._address = self._section[KEY.ADDRESS]
        self._private_key = self._section[KEY.PRIVATE_KEY]

        self._environment = BinanceEnvironment.get_production_env()
        self._client = HttpApiClient(env=self._environment)
        self._wallet = Wallet(self._private_key, env=self._environment)

        self._pending_transactions = {}

    def getDexAccount(self) -> Dict[str, Decimal]:
        result = {}

        account = self._client.get_account(self._address)

        for item in account['balances']:
            symbol = item['symbol'].split('-')[0]
            result[symbol] = Decimal(item['free'])

        return result


    def getDexProducts(self) -> Dict[str, Book]:
        r = requests.get(DEX + '/api/v1/ticker/24hr').json()

        result = {}

        for item in r:
            ask_price = Decimal(item['askPrice'])
            bid_price = Decimal(item['bidPrice'])

            if ask_price > KEY.ED and bid_price > KEY.ED:
                result[item['symbol']] = Book(
                    ask_price=ask_price,
                    ask_qty=Decimal(item['askQuantity']),
                    bid_price=bid_price,
                    bid_qty=Decimal(item['bidQuantity']),
                )

        return result

    def isDexAvailable(self) -> bool:
        return not self._pending_transactions

    def makeDexOrder(self, token: str, qty: Union[int, Decimal], price: Decimal):

        from binance_chain.constants import TimeInForce
        from binance_chain.constants import OrderType
        from binance_chain.constants import OrderSide
        new_order_msg = NewOrderMsg(
            wallet=self._wallet,
            symbol=token,
            time_in_force=TimeInForce.GOOD_TILL_EXPIRE,
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY if qty > 0 else OrderSide.SELL,
            price=price,
            quantity=abs(qty)
        )

        return self._client.broadcast_msg(new_order_msg, sync=True)

    def makeDexTransaction(self, coin: str, amount: Decimal, memo: str, destination: str):
        message = TransferMsg(
            wallet=self._wallet,
            symbol=coin,
            amount=amount,
            to_address=destination,
            memo=memo,
        )

        self._logger.info(f'Transation ready with MEMO: {memo}', tx_msg=message.to_dict())
        r = self._client.broadcast_msg(message, sync=True)
        self._logger.info(f'Transation SENT', tx=r)
        tx = '' # r[]

        self._pending_transactions[tx] = self._timer.Timestamp()


    def _load_last_transactions(self, limit=None, last_hours=1):
        end_time = int(datetime.now(tz=timezone.utc).timestamp() * 1e3)
        start_time = int((datetime.now(tz=timezone.utc) - timedelta(hours=last_hours)).timestamp() * 1e3)
        return self._client.get_transactions(address=self._address, start_time=start_time, end_time=end_time, limit=limit)

    def onTime(self, timestamp: int):
        super().onTime(timestamp)

        if self._pending_transactions:
            last_transations = self._load_last_transactions()
            pprint(last_transations)

            delete_list = []
            for tx, timestamp in self._pending_transactions.items():
                if self._timer.Timestamp() > (timestamp + MAX_TRANSACTION_WAIT_TIME):
                    delete_list.append(tx)
                    self._logger.error(f'Delete transaction {tx} because of out-of-time')
                else:
                    for item in last_transations.get('tx', []):
                        if ':' in item['memo']:
                            _type, _hash = item['memo'].split(':')
                            if _hash == tx:
                                delete_list.append(tx)
                                self._logger.error(f'Transaction {tx} result: {_type}', transaction=item)

            for item in delete_list:
                del self._pending_transactions[item]

