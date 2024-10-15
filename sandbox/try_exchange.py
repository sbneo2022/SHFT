import os
import sys
from decimal import Decimal

sys.path.append(os.path.abspath('..'))
from lib.constants import KEY, ORDER_TAG
from lib.database.no_db import NoDb
from lib.exchange import get_exchange, Order
from lib.factory.custom_factory import CustomFactory
from lib.logger.console_logger import ConsoleLogger
from lib.timer.live_timer import LiveTimer
from lib.vault.env_vault import EnvVault

if __name__ == '__main__':

    # Mininal config for exchange: `symbol` and `exchange`
    config = {
        KEY.SYMBOL: 'FILUSDT.LONG',
        KEY.EXCHANGE: KEY.EXHANGE_OKEX_PERP,
    }

    # Minimal factory:
    #  - timer: LiveTimer --> required for LIVE api
    #  - database: NoDb --> we dont care of DB now, so just skip
    #  - logger: ConsoleLogger --> lets write to stdout only
    #  - vault: EnvVault --> lets get KEY and SECRET from env. Exchange will be in DRY mode without KEY/SECRET
    factory = CustomFactory(timer=LiveTimer, database=NoDb, logger=ConsoleLogger, vault=EnvVault)

    # We have to create single and global timer
    timer = factory.Timer()

    # Lets create Exchange object. Most objects in framework could be created with 'Foo(config, factory, timer)'
    # For exchange we choose right class using Exchange Name
    exchange = get_exchange(config[KEY.EXCHANGE])(config, factory, timer)

    # Get `tick` for given product
    tick = exchange.getTick()
    print(f'{config[KEY.SYMBOL]} :: tick :: {tick}')

    # Get `min_qty` for given product
    min_qty = exchange.getMinQty()
    print(f'{config[KEY.SYMBOL]} :: min_qty :: {min_qty}')

    # Get account balance
    balance = exchange.getBalance()
    print(f'{config[KEY.SYMBOL]} :: balance :: {balance}')

    # Get Best Book
    book = exchange.getBook()
    print(f'{config[KEY.SYMBOL]} :: book :: {book}')

    # Get Positions
    positions = exchange.getPosition()
    print(f'{config[KEY.SYMBOL]} :: positions :: {positions}')

    # Post limit order
    order = Order(qty=Decimal(0.2), price=book.bid_price * Decimal(0.9))
    print(f'{config[KEY.SYMBOL]} :: buy {order.qty} coin -10% from best_bid :: {order}')

    # Apply Exchange rules
    order = exchange.applyRules(order)
    print(f'{config[KEY.SYMBOL]} :: apply rules :: {order}')

    # Send Limit order
    id = exchange.Post(order.as_market_order(), wait=True)
    print(f'{config[KEY.SYMBOL]} :: order_ids :: {id}')


    # Cancel Limit order
    # exchange.Cancel(wait=True)
    # print(f'{config[KEY.SYMBOL]} :: canceled :: {order}')

    # Liquidate market inventory
    order.qty = -1 * order.qty
    id = exchange.Post(order.as_market_order(), wait=True)
    print(f'{config[KEY.SYMBOL]} :: order_ids :: {id}')
